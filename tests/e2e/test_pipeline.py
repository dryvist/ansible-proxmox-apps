"""Full syslog source-family pipeline tests."""

import time
import uuid

import pytest

from .fixtures import SYSLOG_SOURCES, SYSLOG_SOURCE_IDS
from .helpers import (
    make_syslog_message,
    send_tcp_syslog,
    send_udp_syslog,
    wait_for_event,
)


class TestSyslogViaHAProxy:
    """Validate every app-facing syslog source path through HAProxy."""

    @pytest.mark.parametrize("source", SYSLOG_SOURCES, ids=SYSLOG_SOURCE_IDS)
    def test_udp_syslog_via_haproxy_standard_port(
        self,
        haproxy_host,
        splunk_creds,
        source,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        """Send UDP syslog via HAProxy and verify Splunk routing."""
        mgmt_url, user, password = splunk_creds
        sentinel = f"e2e-haproxy-udp-{source.key}-{uuid.uuid4().hex[:10]}-{int(time.time())}"

        send_udp_syslog(
            haproxy_host,
            source.standard_port,
            make_syslog_message(sentinel, f"e2e-{source.key}-udp"),
        )
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
            f"UDP {source.label} sentinel {sentinel} did not reach Splunk "
            f"with index={source.expected_index} sourcetype={source.expected_sourcetype}"
        )

    @pytest.mark.parametrize("source", SYSLOG_SOURCES, ids=SYSLOG_SOURCE_IDS)
    def test_tcp_syslog_via_haproxy_standard_port(
        self,
        haproxy_host,
        splunk_creds,
        source,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        """Send TCP syslog via HAProxy and verify Splunk routing."""
        mgmt_url, user, password = splunk_creds
        sentinel = f"e2e-haproxy-tcp-{source.key}-{uuid.uuid4().hex[:10]}-{int(time.time())}"

        send_tcp_syslog(
            haproxy_host,
            source.standard_port,
            make_syslog_message(sentinel, f"e2e-{source.key}-tcp"),
        )
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
            f"TCP {source.label} sentinel {sentinel} did not reach Splunk "
            f"with index={source.expected_index} sourcetype={source.expected_sourcetype}"
        )

    @pytest.mark.parametrize("source", SYSLOG_SOURCES, ids=SYSLOG_SOURCE_IDS)
    def test_udp_syslog_via_haproxy_high_port(
        self,
        haproxy_host,
        constants,
        splunk_creds,
        source,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        """Verify backward-compatible high UDP ports still route correctly."""
        mgmt_url, user, password = splunk_creds
        port = constants["syslog_ports"][source.key]
        sentinel = f"e2e-haproxy-high-{source.key}-{uuid.uuid4().hex[:10]}-{int(time.time())}"

        send_udp_syslog(
            haproxy_host,
            port,
            make_syslog_message(sentinel, f"e2e-{source.key}-high"),
        )

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
            f"High-port UDP {source.label} sentinel {sentinel} did not reach Splunk "
            f"with index={source.expected_index} sourcetype={source.expected_sourcetype}"
        )
