"""macOS Cribl Edge -> Cribl Cloud -> Splunk freshness gate.

Verifies the macbook-m4 Cribl Edge node continues to emit events through
Cribl Cloud and into Splunk. Catches silent chain breakage at any layer
(Mac offline, pack misconfigured, Cribl Cloud rejecting enrollment,
Stream pipeline broken, Splunk indexer down).

Complements the Splunk silence-detector saved search in ansible-splunk —
the saved search alerts an on-call human; this pytest test fails the
scheduled E2E run so CI catches the same condition.

Design note: this is a freshness gate, not a sentinel injection. The Mac
pack continuously emits events (system_metrics every 60s,
apple_unified_logs streaming), so any 5-minute window of silence is a
real failure. Sentinel injection from a Linux runner to a Mac at a
remote site would require either runner-to-Mac SSH or a publicly-reachable
HEC endpoint on the Mac — both add deployment complexity without
materially improving the failure detection signal.
"""

from datetime import datetime, timezone

from .helpers import query_splunk


MACOS_INDEX_FILTER = "(index=os OR index=mac_perf)"
MACOS_SOURCETYPE_FILTER = "sourcetype=macos:*"
MACOS_NATIVE_FILTER = (
    "(sourcetype=macos:unified_log OR sourcetype=macos:system:*)"
)


def _format_epoch(epoch):
    """Return an ISO-8601 UTC timestamp for a Splunk epoch value."""
    if epoch in (None, ""):
        return "unknown"
    try:
        return (
            datetime.fromtimestamp(float(epoch), tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (TypeError, ValueError):
        return str(epoch)


def _format_sourcetype_rows(rows):
    """Format compact sourcetype freshness diagnostics."""
    if not rows:
        return "none"

    formatted = []
    for row in rows[:8]:
        sourcetype = row.get("sourcetype") or "(missing sourcetype)"
        index = row.get("index")
        label = f"{index}/{sourcetype}" if index else sourcetype
        last_seen = _format_epoch(row.get("last_seen"))
        seconds_ago = row.get("seconds_ago")
        count = row.get("count")
        parts = [f"{label}: last_seen={last_seen}"]
        if seconds_ago not in (None, ""):
            parts.append(f"seconds_ago={seconds_ago}")
        if count not in (None, ""):
            parts.append(f"count={count}")
        formatted.append(" ".join(parts))
    return "; ".join(formatted)


def _macos_history_context(mgmt_url, user, password):
    """Return recent historical macOS sourcetype activity for failure messages."""
    search_str = (
        "| tstats latest(_time) as last_seen count WHERE earliest=-30d "
        f"{MACOS_INDEX_FILTER} {MACOS_SOURCETYPE_FILTER} BY sourcetype "
        "| eval seconds_ago=round(now() - last_seen, 0) "
        "| sort 0 -last_seen"
    )
    rows = query_splunk(
        mgmt_url, user, password, search_str, earliest=None, timeout=30
    )
    return _format_sourcetype_rows(rows)


def _macos_any_index_context(mgmt_url, user, password):
    """Return recent macOS sourcetype activity across all indexes."""
    search_str = (
        "| tstats latest(_time) as last_seen count WHERE earliest=-30d "
        f"index=* {MACOS_SOURCETYPE_FILTER} BY index sourcetype "
        "| eval seconds_ago=round(now() - last_seen, 0) "
        "| sort 0 -last_seen"
    )
    rows = query_splunk(
        mgmt_url, user, password, search_str, earliest=None, timeout=30
    )
    return _format_sourcetype_rows(rows)


class TestMacOSPipelineFreshness:
    """Verify the macOS Cribl Edge -> Splunk chain produces fresh data."""

    def test_macos_pack_events_arrive(self, splunk_creds):
        """Assert at least one macOS pack event landed in Splunk in the
        last 5 minutes.

        Searches both indexes the pack routes to (``os`` for log events,
        ``mac_perf`` for metric snapshots) and matches any ``macos:*``
        sourcetype set by the pack's main pipeline.
        """
        mgmt_url, user, password = splunk_creds
        search_str = (
            f"{MACOS_INDEX_FILTER} {MACOS_SOURCETYPE_FILTER} | head 5"
        )
        results = query_splunk(
            mgmt_url, user, password, search_str, earliest="-5m", timeout=30
        )
        assert results, (
            "macbook-m4 Cribl Edge -> Cloud -> Splunk chain appears broken: "
            "no events with sourcetype=macos:* in (os OR mac_perf) within "
            "the last 5 minutes. Investigate: Cribl Edge daemon on macbook-m4, "
            "Cribl Cloud enrollment status, Cribl Stream pipelines, and "
            "Splunk HEC ingestion. Latest macOS history in last 30d: "
            f"{_macos_history_context(mgmt_url, user, password)}. "
            "Any-index macOS history in last 30d: "
            f"{_macos_any_index_context(mgmt_url, user, password)}"
        )

    def test_macos_native_sources_emitting(self, splunk_creds):
        """Assert both 4.18 native Source types are emitting data.

        Verifies the pack's apple_unified_logs and system_metrics sources
        are actually producing events, not just any macOS sourcetype.
        Catches the case where one native source is enabled but stuck.

        Uses tstats on the indexed sourcetype field so the search is cheap
        even over a multi-hour window.
        """
        mgmt_url, user, password = splunk_creds
        # Splunk's IN(...) operator does not support wildcards — its
        # arguments are matched literally. Use OR'd sourcetype clauses so
        # `macos:system:*` expands as a glob on the indexed sourcetype.
        search_str = (
            "| tstats count WHERE "
            f"{MACOS_INDEX_FILTER} earliest=-15m "
            f"{MACOS_NATIVE_FILTER} "
            "BY sourcetype"
        )
        results = query_splunk(
            mgmt_url, user, password, search_str, timeout=30
        )
        sourcetypes_seen = {row.get("sourcetype") for row in results}
        seen_context = ", ".join(sorted(filter(None, sourcetypes_seen))) or "none"

        assert any(
            st == "macos:unified_log" for st in sourcetypes_seen
        ), (
            "apple_unified_logs source not emitting: no events with "
            "sourcetype=macos:unified_log in last 15m. The native Cribl 4.18 "
            "apple_unified_logs Source on macbook-m4 may be misconfigured "
            "or the daemon predicate is filtering everything out. Native "
            f"sourcetypes seen in last 15m: {seen_context}. Latest macOS "
            "history in last 30d: "
            f"{_macos_history_context(mgmt_url, user, password)}. "
            "Any-index macOS history in last 30d: "
            f"{_macos_any_index_context(mgmt_url, user, password)}"
        )
        assert any(
            (st or "").startswith("macos:system:") for st in sourcetypes_seen
        ), (
            "system_metrics source not emitting: no events with "
            "sourcetype=macos:system:* in last 15m. The native Cribl 4.18 "
            "system_metrics Source on macbook-m4 may be misconfigured. Native "
            f"sourcetypes seen in last 15m: {seen_context}. Latest macOS "
            "history in last 30d: "
            f"{_macos_history_context(mgmt_url, user, password)}. "
            "Any-index macOS history in last 30d: "
            f"{_macos_any_index_context(mgmt_url, user, password)}"
        )

    def test_macos_pack_recently_active(self, splunk_creds):
        """Latest event timestamp on the chain is within the last 5 minutes.

        Stricter than ``test_macos_pack_events_arrive``: instead of "any
        event in 5m", asserts the freshest event is recent. Catches
        backed-up pipelines where old events keep arriving long after
        the source went silent.
        """
        mgmt_url, user, password = splunk_creds
        # `tstats latest(...) WHERE ...` without a BY clause always emits
        # a single row even when no events match (the aggregate is null),
        # so the row count alone is not a freshness signal. Filter out the
        # null case with `where isnotnull(last_seen)` so the assertion below
        # actually detects a never-indexed pack vs. a stalled one.
        search_str = (
            "| tstats latest(_time) as last_seen WHERE "
            f"{MACOS_INDEX_FILTER} {MACOS_SOURCETYPE_FILTER} "
            "| where isnotnull(last_seen) "
            "| eval seconds_ago = now() - last_seen | head 1"
        )
        results = query_splunk(
            mgmt_url, user, password, search_str, timeout=30
        )
        assert results, (
            "no macOS pack events ever indexed in (index=os OR index=mac_perf): "
            "the pack may have never emitted data, or the indexes do not "
            "exist yet. Latest macOS history in last 30d: "
            f"{_macos_history_context(mgmt_url, user, password)}. "
            "Any-index macOS history in last 30d: "
            f"{_macos_any_index_context(mgmt_url, user, password)}"
        )

        # tstats can emit null/missing aggregates even after the filter when
        # the underlying index has no data — coerce defensively.
        raw_seconds_ago = results[0].get("seconds_ago")
        assert raw_seconds_ago not in (None, ""), (
            f"tstats returned a row but seconds_ago is empty "
            f"({raw_seconds_ago!r}) — pack may have never emitted data"
        )
        seconds_ago = float(raw_seconds_ago)
        assert seconds_ago < 300, (
            f"newest macbook-m4 pack event is {seconds_ago:.0f}s old "
            f"(threshold: 300s). Chain appears to have backed up or "
            f"stalled between Edge and Splunk."
        )
