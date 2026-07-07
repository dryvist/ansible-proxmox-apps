"""Proxy syslog family (traefik/haproxy program routes) pipeline tests.

The proxy family carries two senders on one port: guests running Traefik or
HAProxy split those programs' logs off the rsyslog catch-all with
``syslog_forwarder_program_routes`` and ship them to the family's standard
frontend. The Cribl Edge syslog pipeline then refines the sourcetype from the
syslog-header program name (traefik -> traefik:syslog, haproxy ->
haproxy:syslog); anything else keeps the family sourcetype.

Skips when the inventory has no ``proxy`` entry in ``syslog_port_map``.
"""

import time
import uuid

import pytest

from .fixtures import SYSLOG_SOURCES
from .helpers import make_syslog_message, send_tcp_syslog, wait_for_event


PROXY_SOURCES = [s for s in SYSLOG_SOURCES if s.key == "proxy"]

# program name -> the sourcetype the Edge pipeline stamps for it.
PROGRAM_SOURCETYPES = [
    ("traefik", "traefik:syslog"),
    ("haproxy", "haproxy:syslog"),
]
PROGRAM_IDS = [program for program, _ in PROGRAM_SOURCETYPES]


def _proxy_source():
    if not PROXY_SOURCES:
        pytest.skip("No proxy family in constants.syslog_port_map")
    return PROXY_SOURCES[0]


class TestProxyFamilyViaHAProxy:
    """Validate the proxy family program-name sourcetype split."""

    @pytest.mark.parametrize(
        ("program", "expected_sourcetype"), PROGRAM_SOURCETYPES, ids=PROGRAM_IDS
    )
    def test_program_line_gets_program_sourcetype(
        self,
        haproxy_host,
        splunk_creds,
        program,
        expected_sourcetype,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        """A <program> syslog line lands in index=proxy with its sourcetype."""
        source = _proxy_source()
        mgmt_url, user, password = splunk_creds
        sentinel = f"e2e-proxy-{program}-{uuid.uuid4().hex[:10]}-{int(time.time())}"

        send_tcp_syslog(
            haproxy_host,
            source.standard_port,
            make_syslog_message(sentinel, program),
        )
        results = wait_for_event(
            mgmt_url,
            user,
            password,
            sentinel,
            index=source.expected_index,
            sourcetype=expected_sourcetype,
            timeout=pipeline_poll_timeout,
            poll_interval=pipeline_poll_interval,
        )
        assert results, (
            f"Proxy family sentinel {sentinel} (program={program}) did not "
            f"reach Splunk with index={source.expected_index} "
            f"sourcetype={expected_sourcetype}"
        )

    def test_unknown_program_keeps_family_sourcetype(
        self,
        haproxy_host,
        splunk_creds,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        """Negative control: other programs keep the family sourcetype."""
        source = _proxy_source()
        mgmt_url, user, password = splunk_creds
        sentinel = f"e2e-proxy-other-{uuid.uuid4().hex[:10]}-{int(time.time())}"

        send_tcp_syslog(
            haproxy_host,
            source.standard_port,
            make_syslog_message(sentinel, "e2e-other-program"),
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
            f"Proxy family sentinel {sentinel} did not keep the family "
            f"sourcetype {source.expected_sourcetype} in "
            f"index={source.expected_index}"
        )
