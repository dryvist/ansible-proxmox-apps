"""Tier 1: service health smoke tests."""

import pytest

from .fixtures import SYSLOG_SOURCES, SYSLOG_SOURCE_IDS
from .helpers import check_port_tcp, check_port_udp, splunk_hec_health


class TestHAProxy:
    """HAProxy load balancer port checks."""

    @pytest.mark.parametrize(
        "source",
        SYSLOG_SOURCES,
        ids=SYSLOG_SOURCE_IDS,
    )
    def test_haproxy_udp_syslog_high_ports(self, haproxy_host, constants, source):
        """Verify HAProxy/Nginx is accepting UDP syslog on each high port."""
        port = constants["syslog_ports"][source.key]
        assert check_port_udp(haproxy_host, port), (
            f"HAProxy UDP syslog port {port} ({source.key}) is not reachable "
            f"on {haproxy_host}"
        )

    @pytest.mark.parametrize(
        "source",
        SYSLOG_SOURCES,
        ids=SYSLOG_SOURCE_IDS,
    )
    def test_haproxy_udp_syslog_standard_ports(self, haproxy_host, source):
        """Verify HAProxy/Nginx is accepting UDP syslog on each app-facing port."""
        assert check_port_udp(haproxy_host, source.standard_port), (
            f"HAProxy UDP syslog port {source.standard_port} "
            f"({source.key}) is not reachable on {haproxy_host}"
        )

    @pytest.mark.parametrize(
        "source",
        SYSLOG_SOURCES,
        ids=SYSLOG_SOURCE_IDS,
    )
    def test_haproxy_tcp_syslog_standard_ports(self, haproxy_host, source):
        """Verify HAProxy is accepting TCP syslog on each app-facing port."""
        assert check_port_tcp(haproxy_host, source.standard_port), (
            f"HAProxy TCP syslog port {source.standard_port} "
            f"({source.key}) is not accepting connections on {haproxy_host}"
        )

    @pytest.mark.parametrize(
        "source",
        SYSLOG_SOURCES,
        ids=SYSLOG_SOURCE_IDS,
    )
    def test_haproxy_tcp_syslog_high_ports(self, haproxy_host, constants, source):
        """Verify HAProxy is accepting TCP syslog on each high port."""
        port = constants["syslog_ports"][source.key]
        assert check_port_tcp(haproxy_host, port), (
            f"HAProxy TCP syslog port {port} ({source.key}) is not accepting connections "
            f"on {haproxy_host}"
        )

    def test_haproxy_stats(self, haproxy_host, constants):
        """Verify HAProxy stats page port is listening."""
        port = constants["service_ports"]["haproxy_stats"]
        assert check_port_tcp(haproxy_host, port), (
            f"HAProxy stats port {port} is not accepting "
            f"connections on {haproxy_host}"
        )


class TestCriblEdgeLXC:
    """Cribl Edge LXC container port checks (syslog processing)."""

    @pytest.mark.parametrize(
        "source",
        SYSLOG_SOURCES,
        ids=SYSLOG_SOURCE_IDS,
    )
    def test_cribl_edge_syslog_ports(
        self, cribl_edge_ips, constants, source
    ):
        """Verify each Cribl Edge LXC is accepting syslog on each UDP port."""
        port = constants["syslog_ports"][source.key]
        for edge_ip in cribl_edge_ips:
            assert check_port_udp(edge_ip, port), (
                f"Cribl Edge syslog port {port} ({source.key}) is not "
                f"reachable on {edge_ip}"
            )

    def test_cribl_edge_api(self, cribl_edge_ips, constants):
        """Verify Cribl Edge API port is accepting TCP connections."""
        port = constants["service_ports"]["cribl_edge_api"]
        for edge_ip in cribl_edge_ips:
            assert check_port_tcp(edge_ip, port), (
                f"Cribl Edge API port {port} is not accepting "
                f"connections on {edge_ip}"
            )


class TestCriblStreamLXC:
    """Cribl Stream LXC container port checks (netflow/IPFIX processing)."""

    def test_cribl_stream_netflow(self, cribl_stream_ips, constants):
        """Verify each Cribl Stream LXC is accepting NetFlow UDP traffic."""
        port = constants["netflow_ports"]["unifi"]
        for stream_ip in cribl_stream_ips:
            assert check_port_udp(stream_ip, port), (
                f"Cribl Stream NetFlow port {port} is not "
                f"reachable on {stream_ip}"
            )

    def test_cribl_stream_api(self, cribl_stream_ips, constants):
        """Verify Cribl Stream API port is accepting TCP connections."""
        port = constants["service_ports"]["cribl_stream_api"]
        for stream_ip in cribl_stream_ips:
            assert check_port_tcp(stream_ip, port), (
                f"Cribl Stream API port {port} is not accepting "
                f"connections on {stream_ip}"
            )


class TestSplunk:
    """Splunk service port checks."""

    def test_splunk_web(self, splunk_host, constants):
        """Verify Splunk Web UI port is listening."""
        port = constants["service_ports"]["splunk_web"]
        assert check_port_tcp(splunk_host, port), (
            f"Splunk Web port {port} is not accepting "
            f"connections on {splunk_host}"
        )

    def test_splunk_hec(self, splunk_host, constants):
        """Verify Splunk HEC port is listening."""
        port = constants["service_ports"]["splunk_hec"]
        assert check_port_tcp(splunk_host, port), (
            f"Splunk HEC port {port} is not accepting "
            f"connections on {splunk_host}"
        )

    def test_splunk_hec_health(self, splunk_hec_url):
        """Verify Splunk HEC health endpoint returns HTTP 200.

        The HEC health endpoint at /services/collector/health/1.0 responds
        with 200 when HEC is enabled and accepting events.
        """
        status, body = splunk_hec_health(splunk_hec_url)
        assert status == 200, (
            f"Splunk HEC health endpoint returned {status}, expected 200: {body}"
        )
