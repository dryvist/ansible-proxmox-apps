"""Fake-backed private triage contracts."""

import json
import sys
from pathlib import Path

import pytest

WORKER = Path(__file__).resolve().parents[1] / "roles/hatchet_docker/files/gpu_fill_worker"
sys.path.insert(0, str(WORKER))

from zammadtriage import run, validate_reply  # noqa: E402
from zammadtriage.client import Zammad, validate_url  # noqa: E402


class FakeZammad:
    def __init__(self):
        self.rows = [{"id": i, "title": title} for i, title in (
            (1, "Disk FULL!"), (2, "disk full"), (3, "disk full"),
        )]
        self.notes = {i: [{"id": i, "body": f"fingerprint: {fp}"}] for i, fp in (
            (1, "abc"), (2, "abc"), (3, "xyz"),
        )}
        self.writes = []
        self.reads = 0

    def tickets(self):
        return self.rows

    def articles(self, ticket_id):
        self.reads += 1
        return list(self.notes[ticket_id])

    def link(self, ticket_id, original):
        self.writes.append(("link", ticket_id, original))

    def tag(self, ticket_id, tag):
        self.writes.append(("tag", ticket_id, tag))

    def note(self, ticket_id, body):
        self.notes[ticket_id].append({
            "id": 100 + len(self.notes[ticket_id]), "body": body, "type": "note", "internal": True,
        })
        self.writes.append(("note", ticket_id, body))


def good_chat(config, role, content):
    if role == "small":
        return {"severity": "high", "category": "capacity"}
    return {"summary": "Disk full", "suspected_cause": "Possibly logs", "next_checks": "Check usage"}


def test_no_llm_discovery_duplicates_and_idempotence():
    api = FakeZammad()
    calls = []

    def chat(config, role, content):
        assert api.reads >= 3
        calls.append(role)
        return good_chat(config, role, content)

    assert run({}, api, chat) == {"scanned": 3, "noted": 3}
    assert calls == ["small", "medium"] * 3
    assert [write for write in api.writes if write[0] == "link"] == [("link", 2, 1)]
    writes = list(api.writes)
    assert run({}, api, chat)["noted"] == 0
    assert api.writes == writes
    api.notes[1][0]["body"] += "\nNew evidence"
    assert run({}, api, chat)["noted"] == 1


@pytest.mark.parametrize("bad", [None, [], {"severity": "urgent", "category": "capacity"},
                                  {"severity": "high", "category": "capacity", "close": True}])
def test_bad_classification_has_no_writes(bad):
    api = FakeZammad()
    with pytest.raises(ValueError):
        run({}, api, lambda *args: bad)
    assert not api.writes


def test_bad_summary_has_no_writes():
    api = FakeZammad()
    with pytest.raises(ValueError):
        run({}, api, lambda config, role, content: good_chat(config, role, content) if role == "small" else {})
    assert not api.writes
    with pytest.raises(ValueError):
        validate_reply({"summary": "", "suspected_cause": "x", "next_checks": "x"}, "medium")


@pytest.mark.parametrize("url", ["https://8.8.8.8/v1", "https://example.invalid/v1", "http://0.0.0.0/v1"])
def test_public_inference_rejected(url):
    with pytest.raises(ValueError):
        validate_url(url, local=True)


def test_rest_pagination_and_write_surface(monkeypatch):
    monkeypatch.setenv("ZAMMAD_API_TOKEN", "fake")
    api = Zammad({"base_url": "https://192.0.2.1/api/v1", "auth_env": "ZAMMAD_API_TOKEN"})
    calls = []

    def call(path, payload=None):
        calls.append((path, payload))
        if path.startswith("tickets/search"):
            return [{"id": i} for i in range(100)] if "page=1" in path else []
        if path.startswith("links?"):
            return {"links": []}
        return True

    api.call = call
    assert len(api.tickets()) == 100
    assert len(calls) == 4
    api.link(2, 1)
    api.tag(2, "triage:duplicate")
    api.note(2, "summary")
    assert calls[-1][1]["internal"] is True
    assert calls[-1][1]["type"] == "note"
    assert all("state" not in (payload or {}) for _, payload in calls)
