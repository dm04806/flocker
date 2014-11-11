# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
Tests for running and managing PostgreSQL with Flocker.
"""
from twisted.python.filepath import FilePath
from twisted.trial.unittest import TestCase

from flocker.node._docker import BASE_NAMESPACE, PortMap, Unit, Volume

from .testtools import (assert_expected_deployment, flocker_deploy, get_nodes,
                        require_flocker_cli)

# TODO relative imports and add to setup.py and require_posgres etc like mongo
# I had to do brew install postgresql first
# add to the licensing google doc
import psycopg2

internal_port = 5432
external_port = 5432

POSTGRES_APPLICATION = u"postgres-volume-example"
POSTGRES_IMAGE = u"postgres"
POSTGRES_VOLUME_MOUNTPOINT = u'/var/lib/postgresql/data'

POSTGRES_UNIT = Unit(
    name=POSTGRES_APPLICATION,
    container_name=BASE_NAMESPACE + POSTGRES_APPLICATION,
    activation_state=u'active',
    container_image=POSTGRES_IMAGE + u':latest',
    ports=frozenset([
        PortMap(internal_port=internal_port,
                external_port=external_port)
        ]),
    volumes=frozenset([
        Volume(node_path=FilePath(b'/tmp'),
               container_path=FilePath(POSTGRES_VOLUME_MOUNTPOINT)),
        ]),
)


class PostgresTests(TestCase):
    """
    Tests for running and managing PostgreSQL with Flocker.

    Similar to:
    http://doc-dev.clusterhq.com/gettingstarted/examples/postgres.html

    # TODO Link to this file from postgres.rst
    """
    @require_flocker_cli
    def setUp(self):
        getting_nodes = get_nodes(num_nodes=2)

        def deploy(node_ips):
            self.node_1, self.node_2 = node_ips

            postgres_deployment = {
                u"version": 1,
                u"nodes": {
                    self.node_1: [POSTGRES_APPLICATION],
                    self.node_2: [],
                },
            }

            self.postgres_application = {
                u"version": 1,
                u"applications": {
                    POSTGRES_APPLICATION: {
                        u"image": POSTGRES_IMAGE,
                        u"ports": [{
                            u"internal": internal_port,
                            u"external": external_port,
                    }],
                    "volume": {
                        # The location within the container where the data
                        # volume will be mounted; see:
                        # https://github.com/docker-library/postgres/blob/
                        # docker/Dockerfile.template
                        "mountpoint": POSTGRES_VOLUME_MOUNTPOINT,
                      },
                    },
                },
            }

            flocker_deploy(self, postgres_deployment, self.postgres_application)

        getting_nodes.addCallback(deploy)
        return getting_nodes

    def test_deploy(self):
        # TODO docstrings
        d = assert_expected_deployment(self, {
            self.node_1: set([POSTGRES_UNIT]),
            self.node_2: set([]),
        })

        return d

    def test_postgres(self):
        """
        PostgreSQL and its data can be deployed and moved with Flocker.
        """
        from time import sleep
        # TODO get rid of this sleep
        sleep(5)

        # TODO bytes or unicode (for this and filepaths?)
        conn = psycopg2.connect(host=self.node_1, user=u'postgres', port=external_port)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("CREATE DATABASE flockertest;")
        cur.close()
        conn.close()


        conn = psycopg2.connect(host=self.node_1, user=u'postgres',
                                port=external_port, database='flockertest')
        cur = conn.cursor()
        # TODO use named arguments
        cur.execute("CREATE TABLE testtable (testcolumn int);")
        cur.execute("INSERT INTO testtable (testcolumn) VALUES (3);")
        cur.execute("SELECT * FROM testtable;")
        conn.commit()
        self.assertEqual(cur.fetchone(), (3,))

        # TODO Use context managers instead?
        # http://initd.org/psycopg/docs/usage.html#with-statement
        cur.close()
        conn.close()

        postgres_deployment_moved = {
            u"version": 1,
            u"nodes": {
                self.node_1: [],
                self.node_2: [u"postgres-volume-example"],
            },
        }

        flocker_deploy(self, postgres_deployment_moved, self.postgres_application)

        verifying_deployment = assert_expected_deployment(self, {
            self.node_1: set([]),
            self.node_2: set([POSTGRES_UNIT]),
        })

        def verify_data_moves(client_1):
            # TODO assert that postgres moves nodes
            # TODO call this conn_2 or similar
            # TODO get rid of this sleep
            sleep(5)
            conn = psycopg2.connect(host=self.node_2, user=u'postgres', port=external_port, database='flockertest')
            cur = conn.cursor()
            cur.execute("SELECT * FROM testtable;")
            # conn.commit()
            self.assertEqual(cur.fetchone(), (3,))
            cur.close()
            conn.close()

        verifying = verifying_deployment.addCallback(verify_data_moves)
        return verifying
