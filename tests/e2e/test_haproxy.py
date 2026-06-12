"""HAProxy component tests for the syslog pipeline."""

import pytest

from .fixtures import SYSLOG_SOURCES, SYSLOG_SOURCE_IDS
from .helpers import check_port_tcp, check_port_udp


class TestHAProxyComponent:
    """Validate HAProxy/Nginx frontends independently of Splunk searches."""

    def test_stats_port_is_open(self, haproxy_host, constants):
        """Verify HAProxy stats is reachable."""
        port = constants["service_ports"]["haproxy_stats"]
        assert check_port_tcp(haproxy_host, port), (
            f"HAProxy stats port {port} is not accepting connections on {haproxy_host}"
        )

    @pytest.mark.parametrize("source", SYSLOG_SOURCES, ids=SYSLOG_SOURCE_IDS)
    def test_tcp_standard_frontend_is_open(self, haproxy_host, source):
        """Verify the app-facing TCP syslog frontend exists."""
        assert check_port_tcp(haproxy_host, source.standard_port), (
            f"HAProxy TCP standard frontend {source.standard_port} "
            f"for {source.label} is not open"
        )

    @pytest.mark.parametrize("source", SYSLOG_SOURCES, ids=SYSLOG_SOURCE_IDS)
    def test_tcp_high_frontend_is_open(self, haproxy_host, constants, source):
        """Verify the backward-compatible TCP syslog frontend exists."""
        port = constants["syslog_ports"][source.key]
        assert check_port_tcp(haproxy_host, port), (
            f"HAProxy TCP high frontend {port} for {source.label} is not open"
        )

    @pytest.mark.parametrize("source", SYSLOG_SOURCES, ids=SYSLOG_SOURCE_IDS)
    def test_udp_standard_frontend_is_reachable(self, haproxy_host, source):
        """Verify the app-facing UDP syslog frontend is reachable."""
        assert check_port_udp(haproxy_host, source.standard_port), (
            f"HAProxy UDP standard frontend {source.standard_port} "
            f"for {source.label} is not reachable"
        )

    @pytest.mark.parametrize("source", SYSLOG_SOURCES, ids=SYSLOG_SOURCE_IDS)
    def test_udp_high_frontend_is_reachable(self, haproxy_host, constants, source):
        """Verify the backward-compatible UDP syslog frontend is reachable."""
        port = constants["syslog_ports"][source.key]
        assert check_port_udp(haproxy_host, port), (
            f"HAProxy UDP high frontend {port} for {source.label} is not reachable"
        )
