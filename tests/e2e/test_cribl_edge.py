"""Cribl Edge component tests for the syslog pipeline."""

import time
import uuid

import pytest

from .fixtures import SYSLOG_SOURCES, SYSLOG_SOURCE_IDS
from .helpers import (
    check_port_tcp,
    check_port_udp,
    make_syslog_message,
    send_udp_syslog,
    wait_for_event,
)


class TestCriblEdgeComponent:
    """Validate Cribl Edge listeners and direct routing.

    Tests taking ``edge_ip`` are parametrized per Edge LXC (see
    conftest.pytest_generate_tests) so each Edge passes or fails
    independently.
    """

    def test_api_port_is_open(self, edge_ip, constants):
        """Verify the Cribl Edge API port is open on this Edge."""
        port = constants["service_ports"]["cribl_edge_api"]
        assert check_port_tcp(edge_ip, port), (
            f"Cribl Edge API port {port} is not open on {edge_ip}"
        )

    @pytest.mark.parametrize("source", SYSLOG_SOURCES, ids=SYSLOG_SOURCE_IDS)
    def test_syslog_listener_is_reachable(self, edge_ip, constants, source):
        """Verify this Cribl Edge listens on each syslog source-family port."""
        port = constants["syslog_ports"][source.key]
        assert check_port_udp(edge_ip, port), (
            f"Cribl Edge UDP syslog port {port} for {source.label} "
            f"is not reachable on {edge_ip}"
        )

    def test_each_edge_can_forward_direct_syslog(
        self,
        edge_ip,
        constants,
        splunk_creds,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        """Send directly to this Edge LXC and verify Splunk receives it."""
        mgmt_url, user, password = splunk_creds
        source = SYSLOG_SOURCES[0]
        port = constants["syslog_ports"][source.key]

        sentinel = f"e2e-edge-{edge_ip.replace('.', '-')}-{uuid.uuid4().hex[:10]}-{int(time.time())}"
        send_udp_syslog(edge_ip, port, make_syslog_message(sentinel, "e2e-edge-direct"))
        results = wait_for_event(
            mgmt_url,
            user,
            password,
            sentinel,
            index=source.expected_index,
            sourcetype=source.expected_sourcetype,
            timeout=pipeline_poll_timeout,
            poll_interval=pipeline_poll_interval,
        )
        assert results, f"Direct Cribl Edge sentinel {sentinel} from {edge_ip} was not searchable"

    @pytest.mark.parametrize("source", SYSLOG_SOURCES, ids=SYSLOG_SOURCE_IDS)
    def test_first_edge_routes_each_source_family(
        self,
        cribl_edge_ips,
        constants,
        splunk_creds,
        source,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        """Verify Cribl Edge sets expected index and sourcetype by syslog port."""
        mgmt_url, user, password = splunk_creds
        edge_ip = cribl_edge_ips[0]
        port = constants["syslog_ports"][source.key]
        sentinel = f"e2e-edge-route-{source.key}-{uuid.uuid4().hex[:10]}-{int(time.time())}"

        send_udp_syslog(edge_ip, port, make_syslog_message(sentinel, f"e2e-{source.key}"))
        results = wait_for_event(
            mgmt_url,
            user,
            password,
            sentinel,
            index=source.expected_index,
            sourcetype=source.expected_sourcetype,
            timeout=pipeline_poll_timeout,
            poll_interval=pipeline_poll_interval,
        )
        assert results, (
            f"Cribl Edge did not route {source.label} sentinel {sentinel} "
            f"to index={source.expected_index} sourcetype={source.expected_sourcetype}"
        )
