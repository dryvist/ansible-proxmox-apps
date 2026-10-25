#!/usr/bin/env python3
"""Repeat suppression, state transitions, and recovery closure for ntfy-zammad."""

import importlib.util
import json
import os
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / "roles" / "ntfy_docker" / "files" / "ntfy-zammad.py"


def _load():
    spec = importlib.util.spec_from_file_location("ntfy_zammad_dedupe", SCRIPT)
    assert spec is not None and spec.loader is not None, SCRIPT
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeZammad:
    def __init__(self, bridge):
        self.bridge = bridge
        self.tickets = {}
        self.calls = []
        self.next_number = "1000100"

    def call(self, _base, _token, path, payload=None, method=None):
        self.calls.append((method, path, payload))
        if path.startswith("tickets/search?"):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)["query"][0]
            return [
                {"id": ticket["id"], "number": ticket["number"], "title": ticket["title"]}
                for ticket in self.tickets.values()
                if ticket["state"] in self.bridge.OPEN_STATES
                and query == self.bridge.build_search_query(ticket["key"])
            ]
        if path == "users/me":
            return {"id": 1}
        if method == "POST" and path == "tickets":
            ticket_id = max(self.tickets, default=0) + 1
            title = payload["title"]
            key = title.split(" — ", 1)[0]
            self.tickets[ticket_id] = {
                "id": ticket_id,
                "number": self.next_number,
                "title": title,
                "key": key,
                "state": payload["state"],
                "articles": [payload["article"]],
                "tags": [],
            }
            self.next_number = str(int(self.next_number) + 1)
            return {"id": ticket_id, "number": self.tickets[ticket_id]["number"]}
        if method == "POST" and path == "tags/add":
            ticket = self.tickets[int(payload["o_id"])]
            if payload["item"] not in ticket["tags"]:
                ticket["tags"].append(payload["item"])
            return True
        if path.startswith("tags?"):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
            ticket = self.tickets[int(params["o_id"][0])]
            return {"tags": list(ticket["tags"])}
        if path.startswith("tickets/"):
            ticket_id = int(path.split("/", 1)[1])
            ticket = self.tickets[ticket_id]
            if method == "PUT":
                ticket["articles"].append(payload["article"])
                ticket["state"] = payload.get("state", ticket["state"])
                return {"id": ticket_id}
            return {"id": ticket_id, "number": ticket["number"]}
        raise AssertionError("unexpected Zammad call: %s %s" % (method, path))


class NtfyZammadDedupe(unittest.TestCase):
    def setUp(self):
        self.nz = _load()
        self.state = tempfile.TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        self.client = FakeZammad(self.nz)
        patch_env = mock.patch.dict(os.environ, {
            "ZAMMAD_API_URL": "base",
            "ZAMMAD_API_TOKEN": "fake",
            "NTFY_ZAMMAD_STATE_DIR": self.state.name,
            "NTFY_ZAMMAD_REPEAT_INTERVAL_SECONDS": "3600",
            "NTFY_ZAMMAD_CLOSE_DENYLIST": '["1000854"]',
        })
        patch_env.start()
        self.addCleanup(patch_env.stop)
        patch_call = mock.patch.object(self.nz, "zammad_call", self.client.call)
        patch_call.start()
        self.addCleanup(patch_call.stop)
        self.msg = {
            "topic": "observability",
            "title": "worker unavailable",
            "message": "worker probe failed",
            "tags": ["warning"],
            "priority": "4",
        }

    def send(self, message=None, at=1000):
        with mock.patch.object(self.nz.time, "time", return_value=at):
            self.nz.handle(message or self.msg)

    def open_ticket(self):
        return next(iter(self.client.tickets.values()))

    def test_first_fire_creates_ticket_and_marks_it_bridge_owned(self):
        self.send()
        ticket = self.open_ticket()
        self.assertEqual(len(ticket["articles"]), 1)
        self.assertIn(self.nz.MANAGED_TAG, ticket["tags"])
        self.assertIn("worker probe failed", ticket["articles"][0]["body"])
        self.assertIn("Priority: 4", ticket["articles"][0]["body"])

    def test_repeat_within_interval_is_suppressed_and_persisted(self):
        self.send(at=1000)
        self.send(at=1200)
        self.assertEqual(len(self.open_ticket()["articles"]), 1)
        with open(self.nz.repeat_state_path(self.state.name)) as f:
            state = json.load(f)
        record = next(iter(state.values()))
        self.assertEqual(record["suppressed_count"], 1)
        self.assertEqual(record["suppressed_since"], 1200)

    def test_repeat_after_interval_appends_with_suppressed_count(self):
        self.send(at=1000)
        self.send(at=1200)
        self.send(at=1300)
        self.send(at=5001)
        articles = self.open_ticket()["articles"]
        self.assertEqual(len(articles), 2)
        self.assertIn(
            "2 repeats suppressed since 1970-01-01 00:20:00 UTC",
            articles[-1]["body"],
        )

    def test_priority_change_appends_immediately(self):
        self.send(at=1000)
        changed = dict(self.msg, priority="5", tags=["critical"])
        self.send(changed, at=1001)
        articles = self.open_ticket()["articles"]
        self.assertEqual(len(articles), 2)
        self.assertIn("Priority: 5", articles[-1]["body"])

    def test_resolved_to_firing_appends_immediately_on_an_open_ticket(self):
        key = self.nz.correlation_key(self.msg["topic"], self.msg["title"])
        self.client.tickets[1] = {
            "id": 1, "number": "1000200", "title": key, "key": key,
            "state": "open", "articles": [{"body": "human opened"}], "tags": [],
        }
        self.send(dict(self.msg, message="worker recovered", tags=["resolved"]), at=1000)
        self.send(dict(self.msg, message="worker failed again"), at=1001)
        articles = self.client.tickets[1]["articles"]
        self.assertEqual(len(articles), 3)
        self.assertIn("worker failed again", articles[-1]["body"])

    def test_repeat_state_survives_bridge_reload(self):
        self.send(at=1000)
        self.nz = _load()
        self.client.bridge = self.nz
        patch_call = mock.patch.object(self.nz, "zammad_call", self.client.call)
        patch_call.start()
        self.addCleanup(patch_call.stop)
        self.send(at=1200)
        self.assertEqual(len(self.open_ticket()["articles"]), 1)

    def test_recovery_appends_and_closes_a_bridge_opened_ticket(self):
        self.send(at=1000)
        recovered = dict(self.msg, message="worker recovered", tags=["white_check_mark"])
        self.send(recovered, at=1001)
        ticket = self.open_ticket()
        self.assertEqual(ticket["state"], "closed")
        self.assertEqual(len(ticket["articles"]), 2)
        self.assertIn("worker recovered", ticket["articles"][-1]["body"])

    def test_recovery_does_not_close_ticket_without_bridge_marker(self):
        key = self.nz.correlation_key(self.msg["topic"], self.msg["title"])
        self.client.tickets[1] = {
            "id": 1, "number": "1000200", "title": key, "key": key,
            "state": "open", "articles": [{"body": "human opened"}], "tags": [],
        }
        recovered = dict(self.msg, tags=["resolved"])
        self.send(recovered, at=1001)
        self.assertEqual(self.client.tickets[1]["state"], "open")
        self.assertEqual(len(self.client.tickets[1]["articles"]), 2)

    def test_ticket_1000854_is_never_closed(self):
        self.client.next_number = "1000854"
        self.send(at=1000)
        recovered = dict(self.msg, tags=["resolved"])
        self.send(recovered, at=1001)
        ticket = self.open_ticket()
        self.assertIn(self.nz.MANAGED_TAG, ticket["tags"])
        self.assertEqual(ticket["number"], "1000854")
        self.assertEqual(ticket["state"], "new")
        self.assertEqual(len(ticket["articles"]), 2)


if __name__ == "__main__":
    unittest.main()
