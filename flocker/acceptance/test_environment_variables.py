# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
Tests for environment variables.
"""
from pymysql import connect
from pymysql.err import OperationalError

from twisted.python.filepath import FilePath
from twisted.trial.unittest import TestCase

from flocker.node._model import Application, DockerImage, AttachedVolume, Port
from flocker.testtools import loop_until

from .testtools import (assert_expected_deployment, flocker_deploy, get_nodes,
                        require_flocker_cli)

MYSQL_INTERNAL_PORT = 3306
MYSQL_EXTERNAL_PORT = 3306

MYSQL_PASSWORD = u"clusterhq"
MYSQL_APPLICATION_NAME = u"mysql-volume-example"
MYSQL_IMAGE = u"mysql:5.6.17"
MYSQL_ENVIRONMENT = {"MYSQL_ROOT_PASSWORD": MYSQL_PASSWORD}
MYSQL_VOLUME_MOUNTPOINT = u'/var/lib/mysql'

MYSQL_APPLICATION = Application(
    name=MYSQL_APPLICATION_NAME,
    image=DockerImage.from_string(MYSQL_IMAGE),
    ports=frozenset([
        Port(internal_port=MYSQL_INTERNAL_PORT,
             external_port=MYSQL_EXTERNAL_PORT),
    ]),
    volume=AttachedVolume(
        name=MYSQL_APPLICATION_NAME,
        mountpoint=FilePath(MYSQL_VOLUME_MOUNTPOINT),
    ),
)


class EnvironmentVariableTests(TestCase):
    """
    Tests for passing environment variables to containers, in particular
    passing a root password to MySQL.

    Similar to:
    http://doc-dev.clusterhq.com/gettingstarted/examples/environment.html

    # TODO (Note for submission)
    # If this is suitable, I will add the new dependencies (currently just the
    # latest https://pypi.python.org/pypi/PyMySQL) to setup.py, and
    # create a @skipUnless decorator for each of the dependencies, similar to
    # require_mongo in testtools.py. Each dependency must also go in the
    # internal documentation for packages used.
    #
    # However, I understand that https://pypi.python.org/pypi/MySQL-python/ may
    # be a more suitable option. I chose PyMySQL because it is pure Python, so
    # on OS X for example it does not require ``brew install mysql``.
    """
    @require_flocker_cli
    def setUp(self):
        """
        Deploy MySQL to one of two nodes.
        """
        getting_nodes = get_nodes(self, num_nodes=2)

        def deploy_mysql(node_ips):
            self.node_1, self.node_2 = node_ips

            mysql_deployment = {
                u"version": 1,
                u"nodes": {
                    self.node_1: [MYSQL_APPLICATION_NAME],
                    self.node_2: [],
                },
            }

            self.mysql_deployment_moved = {
                u"version": 1,
                u"nodes": {
                    self.node_1: [],
                    self.node_2: [MYSQL_APPLICATION_NAME],
                },
            }

            self.mysql_application = {
                u"version": 1,
                u"applications": {
                    MYSQL_APPLICATION_NAME: {
                        u"image": MYSQL_IMAGE,
                        u"environment": MYSQL_ENVIRONMENT,
                        u"ports": [{
                            u"internal": MYSQL_INTERNAL_PORT,
                            u"external": MYSQL_EXTERNAL_PORT,
                        }],
                        u"volume": {
                            u"mountpoint": MYSQL_VOLUME_MOUNTPOINT,
                        },
                    },
                },
            }

            flocker_deploy(self, mysql_deployment, self.mysql_application)

        deploying_mysql = getting_nodes.addCallback(deploy_mysql)
        return deploying_mysql

    def test_deploy(self):
        """
        The test setUp deploys MySQL.
        """
        d = assert_expected_deployment(self, {
            self.node_1: set([MYSQL_APPLICATION]),
            self.node_2: set([]),
        })

        return d

    def test_moving_mysql(self):
        """
        It is possible to move MySQL to a new node.
        """
        flocker_deploy(self, self.mysql_deployment_moved,
                       self.mysql_application)

        asserting_mysql_moved = assert_expected_deployment(self, {
            self.node_1: set([]),
            self.node_2: set([MYSQL_APPLICATION]),
        })

        return asserting_mysql_moved

    def _get_mysql_connection(self, host, port, user, passwd, db=None):
        """
        Returns a ``Deferred`` which fires with a PyMySQL connection when one
        has been created.

        Parameters are passed directly to PyMySQL:
        https://github.com/PyMySQL/PyMySQL
        """
        def connect_to_mysql():
            try:
                return connect(
                    host=host,
                    port=MYSQL_EXTERNAL_PORT,
                    user=user,
                    passwd=passwd,
                    db=db,
                )
            except OperationalError:
                return False

        d = loop_until(connect_to_mysql)
        return d

    def test_moving_data(self):
        """
        After adding data to MySQL and then moving it to another node, the data
        added is available on the second node. The database can be accessed
        using the root password passed in as an environment variable.
        """
        user = b'root'
        data = b'flocker test'
        database = b'example'
        table = b'testtable'

        getting_mysql = self._get_mysql_connection(
            host=self.node_1,
            port=MYSQL_EXTERNAL_PORT,
            user=user,
            passwd=MYSQL_PASSWORD,
        )

        def add_data_node_1(connection):
            cursor = connection.cursor()
            cursor.execute("CREATE DATABASE {database};".format(
                database=database))
            cursor.execute("USE {database};".format(database=database))
            cursor.execute(
                "CREATE TABLE `{table}` ".format(table=table) +
                "(`id` INT NOT NULL AUTO_INCREMENT,`name` VARCHAR(45) " +
                "NULL,PRIMARY KEY (`id`)) ENGINE = MyISAM;",
            )

            cursor.execute("INSERT INTO `{table}` VALUES('','{data}');".format(
                table=table, data=data))
            cursor.close()
            connection.close()

        getting_mysql.addCallback(add_data_node_1)

        def get_mysql_node_2(ignored):
            """
            Move MySQL to ``node_2`` and return a ``Deferred`` which fires
            with a connection to the previously created database on ``node_2``.
            """
            flocker_deploy(self, self.mysql_deployment_moved,
                           self.mysql_application)

            getting_mysql = self._get_mysql_connection(
                host=self.node_2,
                port=MYSQL_EXTERNAL_PORT,
                user=user,
                passwd=MYSQL_PASSWORD,
                db=database,
            )

            return getting_mysql

        getting_mysql_2 = getting_mysql.addCallback(get_mysql_node_2)

        def verify_data_moves(connection_2):
            cursor_2 = connection_2.cursor()
            cursor_2.execute("SELECT * FROM `{table}`;".format(table=table))
            self.addCleanup(cursor_2.close)
            self.addCleanup(connection_2.close)
            self.assertEqual(cursor_2.fetchall(), ((1, data),))

        verifying_data_moves = getting_mysql_2.addCallback(verify_data_moves)
        return verifying_data_moves
