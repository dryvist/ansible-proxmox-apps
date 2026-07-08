"""macOS Cribl Edge -> Cribl Stream -> Splunk freshness gate.

Verifies the Mac hosts' standalone Cribl Edge nodes continue to emit
events through Cribl Stream (shared S2S port) into Splunk. Catches silent
chain breakage at any layer (Mac offline, Edge daemon down, Stream
pipeline broken, Splunk indexer down).

Architecture note (2026-07): the old Cribl-Cloud "mac pack" that routed
``macos:unified_log`` / ``macos:system:*`` into ``os`` / ``mac_perf`` is
retired, as is the BSD-syslogd remote forward (RFC3164 is never skew-safe
from a local-time workstation). The live Mac Edge sources are:

- ``in_system_metrics`` -> ``index=llm sourcetype=mlx:metrics`` — emits
  every 60s from every inference Mac; this is the continuous freshness
  signal for the whole Edge -> Stream -> Splunk chain.
- ``in_firewall_logs`` -> ``index=firewall sourcetype=macos:firewall`` —
  the firewall unified-log tail (nix-darwin modules/darwin/logging.nix).
  Event volume is intrinsically bursty (a marker line per daemon start
  plus whatever the OS firewall logs), so it gets an existence gate over
  a longer window, not a per-5-minute freshness gate.

Complements the Splunk silence-detector saved searches in ansible-splunk —
those alert an on-call human; these tests fail the scheduled E2E run so CI
catches the same condition.
"""

from .helpers import query_splunk


# Continuous per-minute emitter from every inference Mac's Edge.
MACOS_CHAIN_FILTER = "index=llm sourcetype=mlx:metrics"
# Firewall unified-log tail; bursty by nature.
MACOS_FIREWALL_FILTER = "index=firewall sourcetype=macos:firewall"

# Number of Mac hosts expected to be emitting (MacBook + Mac Studio).
EXPECTED_MAC_HOSTS = 2


class TestMacOSPipelineFreshness:
    """Verify the macOS Cribl Edge -> Splunk chain produces fresh data."""

    def test_macos_edge_chain_fresh(self, splunk_creds):
        """The continuous system-metrics stream from every Mac Edge is fresh.

        ``in_system_metrics`` emits every 60s, so any 5-minute window of
        silence from a host is a real failure of that host's chain.
        """
        mgmt_url, user, password = splunk_creds
        search_str = (
            "| tstats latest(_time) as last_seen WHERE "
            f"{MACOS_CHAIN_FILTER} earliest=-5m BY host "
            "| eval seconds_ago=round(now() - last_seen, 0)"
        )
        results = query_splunk(mgmt_url, user, password, search_str, timeout=30)
        hosts_seen = sorted(
            row.get("host") for row in results if row.get("host")
        )
        assert len(hosts_seen) >= EXPECTED_MAC_HOSTS, (
            "Mac Cribl Edge -> Stream -> Splunk chain appears broken for at "
            f"least one host: expected metrics from >= {EXPECTED_MAC_HOSTS} "
            f"Mac hosts in the last 5 minutes, saw {hosts_seen or 'none'}. "
            "Investigate: cribl-edge daemon on the missing Mac, the shared "
            "S2S ingest on Cribl Stream, and Splunk HEC ingestion."
        )

    def test_macos_firewall_log_indexed(self, splunk_creds):
        """The firewall unified-log tail has landed events recently.

        The shipping daemon writes a marker line on every start (boot,
        rebuild, restart), so a 7-day window with zero events means the
        pipeline is broken, not merely quiet.
        """
        mgmt_url, user, password = splunk_creds
        search_str = (
            "| tstats latest(_time) as last_seen count WHERE "
            f"{MACOS_FIREWALL_FILTER} earliest=-7d BY host "
            "| eval seconds_ago=round(now() - last_seen, 0)"
        )
        results = query_splunk(mgmt_url, user, password, search_str, timeout=30)
        assert results, (
            "no macOS firewall unified-log events in the last 7 days: the "
            "firewall-log-shipping launch daemon or the Edge in_firewall_logs "
            "file input is broken on every Mac (each daemon start writes a "
            "marker line, so a healthy host cannot be silent for a week)."
        )
