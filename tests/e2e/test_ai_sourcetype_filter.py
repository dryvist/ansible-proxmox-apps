"""Unit tests for the AI matrix sourcetype filter, with no live Splunk.

Splunk is replaced by a fake that honours the sourcetype clause wait_for_event
adds to its search, so a hit carrying the wrong sourcetype does not satisfy the
AI matrix check.
"""

import json
import re

import pytest

from . import helpers, test_family_matrix

MACSTUDIO_ENTRY = {"port": 10322, "index": "llm", "sourcetype": "caddy:access"}
LLAMAINDEX_ENTRY = {"port": 10353, "index": "llm", "sourcetype": "llamaindex:app"}


class FakeSplunk:
    """Holds ingested events as sentinel -> sourcetype and answers searches."""

    def __init__(self):
        self.events = {}

    def query(self, mgmt_url, user, password, search_str, **kwargs):
        end = search_str.rfind('"')
        start = search_str.rfind('"', 0, end)
        sentinel = search_str[start + 1 : end]
        stored = self.events.get(sentinel)
        if stored is None:
            return []
        clause = re.search(r'sourcetype="([^"]*)"', search_str)
        if clause is not None and clause.group(1) != stored:
            return []
        return [{"_raw": sentinel, "sourcetype": stored}]


def _run_matrix_check(monkeypatch, key, entry, ingested_sourcetype):
    """Run the AI matrix body; the fake pipeline indexes the sent event."""
    fake = FakeSplunk()

    def fake_send(host, port, message, timeout=5):
        sentinel = json.loads(message)["_raw"].removeprefix("e2e matrix sentinel ")
        fake.events[sentinel] = ingested_sourcetype

    monkeypatch.setattr(test_family_matrix, "send_tcp_syslog", fake_send)
    monkeypatch.setattr(helpers, "query_splunk", fake.query)

    test_family_matrix.TestAiFamilyMatrix.test_ai_sentinel_lands_in_index(
        self=None,
        haproxy_host="test-host",
        splunk_creds=("https://unused", "u", "p"),
        key=key,
        entry=entry,
        # Zero would allow no query at all; a small window still makes one attempt.
        pipeline_poll_timeout=1,
        pipeline_poll_interval=0,
    )


def test_matrix_passes_when_family_sourcetype_is_indexed(monkeypatch):
    _run_matrix_check(monkeypatch, "macstudio_gate", MACSTUDIO_ENTRY, "caddy:access")


def test_matrix_times_out_on_wrong_sourcetype_hit(monkeypatch):
    with pytest.raises(TimeoutError):
        _run_matrix_check(
            monkeypatch, "macstudio_gate", MACSTUDIO_ENTRY, "llamaindex:app"
        )


def test_llamaindex_times_out_on_caddy_access_hit(monkeypatch):
    with pytest.raises(TimeoutError):
        _run_matrix_check(monkeypatch, "llamaindex", LLAMAINDEX_ENTRY, "caddy:access")
