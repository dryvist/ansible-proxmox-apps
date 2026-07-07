"""UniFi firewall/IPS split tests.

The Cribl Edge syslog pipeline re-routes UniFi gateway firewall/IPS lines
(raw content matching ``cribl_edge_unifi_fw_match``) arriving on the unifi
syslog family port to ``index=firewall sourcetype=ubiquiti:firewall``, while
everything else on the port keeps the plain unifi routing. This suite drives
both sides of that split through HAProxy.

Skips when the inventory has no ``unifi`` entry in ``syslog_port_map``.
"""

import time
import uuid

import pytest

from .fixtures import SYSLOG_SOURCES
from .helpers import send_tcp_syslog, wait_for_event


UNIFI_SOURCES = [s for s in SYSLOG_SOURCES if s.key == "unifi"]

pytestmark = pytest.mark.skipif(
    not UNIFI_SOURCES,
    reason="No unifi family in constants.syslog_port_map"
)


def _unifi_source():
    return UNIFI_SOURCES[0]


def _get_syslog_timestamp():
    """Generate an RFC 3164 compliant English syslog timestamp."""
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    t = time.gmtime()
    return f"{months[t.tm_mon - 1]} {t.tm_mday:2d} {time.strftime('%H:%M:%S', t)}"


def _make_fw_message(sentinel):
    """A UniFi kernel iptables rule-hit line (matches the fw split regex)."""
    timestamp = _get_syslog_timestamp()
    return (
        f"<4>{timestamp} usg kernel: [WAN_LOCAL-4001-D] "
        f"IN=eth8 OUT= MAC=aa:bb:cc:dd:ee:ff SRC=203.0.113.9 DST=192.0.2.1 "
        f"PROTO=TCP SPT=51515 DPT=22 {sentinel}"
    )


def _make_admin_message(sentinel):
    """A UniFi management-plane line (must NOT match the fw split regex)."""
    timestamp = _get_syslog_timestamp()
    return (
        f"<14>{timestamp} usg mcad: mgmt.admin login accepted "
        f"for administrator {sentinel}"
    )


class TestUnifiFirewallSplit:
    """Validate the unifi -> firewall/IPS index split at the Edge pipeline."""

    def test_firewall_line_routes_to_firewall_index(
        self,
        haproxy_host,
        splunk_creds,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        """A kernel firewall rule-hit line lands in index=firewall."""
        source = _unifi_source()
        mgmt_url, user, password = splunk_creds
        sentinel = f"e2e-unifi-fw-{uuid.uuid4().hex[:10]}-{int(time.time())}"

        send_tcp_syslog(haproxy_host, source.standard_port, _make_fw_message(sentinel))
        results = wait_for_event(
            mgmt_url,
            user,
            password,
            sentinel,
            index="firewall",
            sourcetype="ubiquiti:firewall",
            timeout=pipeline_poll_timeout,
            poll_interval=pipeline_poll_interval,
        )
        assert results, (
            f"UniFi firewall sentinel {sentinel} did not reach Splunk with "
            f"index=firewall sourcetype=ubiquiti:firewall"
        )

    def test_admin_line_stays_in_unifi_index(
        self,
        haproxy_host,
        splunk_creds,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        """Negative control: a management-plane line keeps the unifi routing."""
        source = _unifi_source()
        mgmt_url, user, password = splunk_creds
        sentinel = f"e2e-unifi-admin-{uuid.uuid4().hex[:10]}-{int(time.time())}"

        send_tcp_syslog(
            haproxy_host, source.standard_port, _make_admin_message(sentinel)
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
            f"UniFi admin sentinel {sentinel} did not reach Splunk with "
            f"index={source.expected_index} "
            f"sourcetype={source.expected_sourcetype} — the firewall split "
            f"regex may be over-matching"
        )
