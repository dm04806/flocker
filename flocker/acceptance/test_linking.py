# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
Tests for linking containers.
"""
from socket import error
from telnetlib import Telnet

# TODO add this to setup.py, do the whole @require Elasticsearch
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import TransportError

from twisted.python.filepath import FilePath
from twisted.trial.unittest import TestCase

from flocker.node._docker import BASE_NAMESPACE, PortMap, Unit, Volume
from flocker.testtools import loop_until

from .testtools import (assert_expected_deployment, flocker_deploy, get_nodes,
                        require_flocker_cli)

ELASTICSEARCH_INTERNAL_PORT = 9200
ELASTICSEARCH_EXTERNAL_PORT = 9200

ELASTICSEARCH_APPLICATION = u"elasticsearch"
ELASTICSEARCH_IMAGE = u"clusterhq/elasticsearch"
ELASTICSEARCH_VOLUME_MOUNTPOINT = u'/var/lib/elasticsearch'

ELASTICSEARCH_UNIT = Unit(
    name=ELASTICSEARCH_APPLICATION,
    container_name=BASE_NAMESPACE + ELASTICSEARCH_APPLICATION,
    activation_state=u'active',
    container_image=ELASTICSEARCH_IMAGE + u':latest',
    ports=frozenset([
        PortMap(internal_port=ELASTICSEARCH_INTERNAL_PORT,
                external_port=ELASTICSEARCH_EXTERNAL_PORT),
        ]),
    volumes=frozenset([
        Volume(node_path=FilePath(b'/tmp'),
               container_path=FilePath(ELASTICSEARCH_VOLUME_MOUNTPOINT)),
        ]),
)

LOGSTASH_INTERNAL_PORT = 5000
LOGSTASH_EXTERNAL_PORT = 5000

LOGSTASH_LOCAL_PORT = 9200
LOGSTASH_REMOTE_PORT = 9200

LOGSTASH_APPLICATION = u"logstash"
LOGSTASH_IMAGE = u"clusterhq/logstash"

LOGSTASH_UNIT = Unit(
    name=LOGSTASH_APPLICATION,
    container_name=BASE_NAMESPACE + LOGSTASH_APPLICATION,
    activation_state=u'active',
    container_image=LOGSTASH_IMAGE + u':latest',
    ports=frozenset([
        PortMap(internal_port=LOGSTASH_INTERNAL_PORT,
                external_port=LOGSTASH_INTERNAL_PORT),
        ]),
    volumes=frozenset([]),
)

KIBANA_INTERNAL_PORT = 8080
KIBANA_EXTERNAL_PORT = 80

KIBANA_APPLICATION = u"kibana"
KIBANA_IMAGE = u"clusterhq/kibana"

KIBANA_UNIT = Unit(
    name=KIBANA_APPLICATION,
    container_name=BASE_NAMESPACE + KIBANA_APPLICATION,
    activation_state=u'active',
    container_image=KIBANA_IMAGE + u':latest',
    ports=frozenset([
        PortMap(internal_port=KIBANA_INTERNAL_PORT,
                external_port=KIBANA_EXTERNAL_PORT),
        ]),
    volumes=frozenset([]),
)

MESSAGES = set([
    str({"firstname": "Joe", "lastname": "Bloggs"}),
    str({"firstname": "Fred", "lastname": "Bloggs"}),
])


class LinkingTests(TestCase):
    """
    Tests for linking containers with Flocker. In particular, tests for linking
    Logstash and Elasticsearch containers and what happens when the
    Elasticsearch container is moved.

    Similar to:
    http://doc-dev.clusterhq.com/gettingstarted/examples/linking.html

    # TODO remove the loopuntil changes
    # TODO Link to this file from linking.rst

    # TODO This has the flaw of not actually testing Kibana. It does connect
    # the linking feature - between elasticsearch and logstash, and the kibana
    # thing needs to be set up right (this test verifies that it is running)
    # We could e.g. use selenium and check that there is no error saying that
    # kibana is not connected

    # TODO this script avoids so many race conditions. Try manually running the
    # tutorial as fast as possible and see if there are places where that
    # should be warned against.
    """
    @require_flocker_cli
    def setUp(self):
        """
        Deploy Elasticsearch, logstash and Kibana to one of two nodes.
        """
        getting_nodes = get_nodes(num_nodes=2)

        def deploy_elk(node_ips):
            self.node_1, self.node_2 = node_ips

            elk_deployment = {
                u"version": 1,
                u"nodes": {
                    self.node_1: [
                        ELASTICSEARCH_APPLICATION, LOGSTASH_APPLICATION,
                        KIBANA_APPLICATION,
                    ],
                    self.node_2: [],
                },
            }

            self.elk_deployment_moved = {
                u"version": 1,
                u"nodes": {
                    self.node_1: [LOGSTASH_APPLICATION, KIBANA_APPLICATION],
                    self.node_2: [ELASTICSEARCH_APPLICATION],
                },
            }

            self.elk_application = {
                u"version": 1,
                u"applications": {
                    ELASTICSEARCH_APPLICATION: {
                        u"image": ELASTICSEARCH_IMAGE,
                        u"ports": [{
                            u"internal": ELASTICSEARCH_INTERNAL_PORT,
                            u"external": ELASTICSEARCH_EXTERNAL_PORT,
                        }],
                        u"volume": {
                            u"mountpoint": ELASTICSEARCH_VOLUME_MOUNTPOINT,
                        },
                    },
                    LOGSTASH_APPLICATION: {
                        u"image": LOGSTASH_IMAGE,
                        u"ports": [{
                            u"internal": LOGSTASH_INTERNAL_PORT,
                            u"external": LOGSTASH_EXTERNAL_PORT,
                        }],
                        u"links": [{
                            u"local_port": LOGSTASH_LOCAL_PORT,
                            u"remote_port": LOGSTASH_REMOTE_PORT,
                            u"alias": u"es",
                        }],
                    },
                    KIBANA_APPLICATION: {
                        u"image": KIBANA_IMAGE,
                        u"ports": [{
                            u"internal": KIBANA_INTERNAL_PORT,
                            u"external": KIBANA_EXTERNAL_PORT,
                        }],
                    },
                },
            }

            flocker_deploy(self, elk_deployment, self.elk_application)

        deploying_elk = getting_nodes.addCallback(deploy_elk)
        return deploying_elk

    def test_deploy(self):
        """
        The test setUp deploys Elasticsearch, logstash and Kibana to the same
        node.
        """
        d = assert_expected_deployment(self, {
            self.node_1: set([ELASTICSEARCH_UNIT, LOGSTASH_UNIT, KIBANA_UNIT]),
            self.node_2: set([]),
        })

        return d

    def test_elasticsearch_empty(self):
        """
        By default there are no log messages in Elasticsearch.
        """
        checking_no_messages = self._assert_expected_log_messages(
            ignored=None,
            node=self.node_1,
            expected_messages=set([]),
        )

        return checking_no_messages

    def test_moving_just_elasticsearch(self):
        """
        It is possible to move just Elasticsearch to a new node, keeping
        logstash and Kibana in place.
        """
        flocker_deploy(self, self.elk_deployment_moved, self.elk_application)

        asserting_es_moved = assert_expected_deployment(self, {
            self.node_1: set([LOGSTASH_UNIT, KIBANA_UNIT]),
            self.node_2: set([ELASTICSEARCH_UNIT]),
        })

        return asserting_es_moved

    def test_logstash_messages_in_elasticsearch(self):
        """
        After sending messages to logstash, those messages can be found by
        searching Elasticsearch.
        """
        sending_messages = self._send_messages_to_logstash(
            node=self.node_1,
            messages=MESSAGES,
        )

        checking_messages = sending_messages.addCallback(
            self._assert_expected_log_messages,
            node=self.node_1,
            expected_messages=MESSAGES,
        )

        return checking_messages

    def test_moving_data(self):
        """
        After sending messages to logstash and then moving Elasticsearch to
        another node, those messages can still be found in Elasticsearch.
        """
        sending_messages = self._send_messages_to_logstash(
            node=self.node_1,
            messages=MESSAGES,
        )

        checking_messages = sending_messages.addCallback(
            self._assert_expected_log_messages,
            node=self.node_1,
            expected_messages=MESSAGES,
        )

        moving_elasticsearch = checking_messages.addCallback(
            lambda _: flocker_deploy(self, self.elk_deployment_moved,
                                     self.elk_application),
        )

        asserting_messages_moved = moving_elasticsearch.addCallback(
            self._assert_expected_log_messages,
            node=self.node_2,
            expected_messages=MESSAGES,
        )

        return asserting_messages_moved

    def _get_elasticsearch(self, node):
        """
        Get an Elasticsearch instance on a node once one is available.

        :param node: The node hosting, or soon-to-be hosting, an Elasticsearch
            instance.
        :return: A running ``Elasticsearch`` instance.
        """
        elasticsearch = Elasticsearch(
            hosts=[{"host": node, "port": ELASTICSEARCH_EXTERNAL_PORT}],
        )

        def wait_for_ping():
            if elasticsearch.ping():
                return elasticsearch
            else:
                return False

        waiting_for_ping = loop_until(wait_for_ping)
        return waiting_for_ping

    def _assert_expected_log_messages(self, ignored, node, expected_messages):
        """
        Check that expected messages can eventually be found by
        Elasticsearch.

        After sending two messages to logstash, checking elasticsearch will
        at first show that there are zero messages, then later one, then later
        two. Therefore this waits for the expected number of search results
        before making an assertion that the search results have the expected
        contents.

        :param node: The node hosting, or soon-to-be hosting, an Elasticsearch
            instance.
        :param set expected_messages: A set of strings expected to be found as
            messages on Elasticsearch.
        """
        getting_elasticsearch = self._get_elasticsearch(node=node)

        def wait_for_hits(elasticsearch):
            def get_hits():
                try:
                    num_hits = elasticsearch.search()[u'hits'][u'total']
                except TransportError:
                    return False

                if num_hits == len(expected_messages):
                    return elasticsearch

            waiting_for_hits = loop_until(get_hits)
            return waiting_for_hits

        waiting_for_messages = getting_elasticsearch.addCallback(wait_for_hits)

        def check_messages(elasticsearch):
            hits = elasticsearch.search()[u'hits'][u'hits']
            messages = set([hit[u'_source'][u'message'] for hit in hits])
            self.assertEqual(messages, expected_messages)

        checking_messages = waiting_for_messages.addCallback(check_messages)
        return checking_messages

    def _send_messages_to_logstash(self, node, messages):
        """
        Wait for logstash to start up and then send messages to it using
        Telnet.

        :param node: The node hosting, or soon-to-be hosting, a logstash
            instance.
        :param set expected_messages: A set of strings to send to logstash.
        """
        def get_telnet_connection_to_logstash():
            try:
                return Telnet(host=node, port=LOGSTASH_EXTERNAL_PORT)
            except error:
                return False

        waiting_for_logstash = loop_until(get_telnet_connection_to_logstash)

        def send_messages(telnet):
            for message in messages:
                telnet.write(message + "\n")

        sending_messages = waiting_for_logstash.addCallback(send_messages)
        return sending_messages
