"""macOS UDP syslog relay pipeline test.

The Macs ship RFC3164 datagrams to the macos syslog family's standard UDP
port on the HAProxy/Nginx LB; Nginx relays to the Cribl Edge high port, where
the syslog pipeline stamps the family's index/sourcetype (index=os,
sourcetype=syslog:macos with the current tofu constants).

Skips when the inventory has no ``macos`` entry in ``syslog_port_map`` —
without the family entry the Edge pipeline has no branch for the port and
routing cannot be asserted.
"""

import time
import uuid

import pytest

from .fixtures import SYSLOG_SOURCES
from .helpers import send_udp_syslog, wait_for_event


MACOS_SOURCES = [s for s in SYSLOG_SOURCES if s.key == "macos"]


def _macos_source():
    if not MACOS_SOURCES:
        pytest.skip("No macos family in constants.syslog_port_map")
    return MACOS_SOURCES[0]


def _make_rfc3164_message(sentinel):
    """A classic BSD-syslog (RFC3164) line, as macOS syslogd emits."""
    timestamp = time.strftime("%b %d %H:%M:%S", time.gmtime())
    return f"<14>{timestamp} macbook-e2e e2e-macos[123]: {sentinel}"


class TestMacosUdpRelay:
    """Validate the macOS UDP relay path through the LB to Splunk."""

    def test_rfc3164_udp_routes_to_os_index(
        self,
        haproxy_host,
        splunk_creds,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        """An RFC3164 datagram on the macos standard port reaches index=os."""
        source = _macos_source()
        mgmt_url, user, password = splunk_creds
        sentinel = f"e2e-macos-udp-{uuid.uuid4().hex[:10]}-{int(time.time())}"

        send_udp_syslog(
            haproxy_host, source.standard_port, _make_rfc3164_message(sentinel)
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
            f"macOS UDP sentinel {sentinel} did not reach Splunk with "
            f"index={source.expected_index} "
            f"sourcetype={source.expected_sourcetype}"
        )
