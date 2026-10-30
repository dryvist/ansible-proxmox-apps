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
        payload = payload or {}
        if path.startswith("tickets/search?"):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)["query"][0]
            repeat = self.bridge.ntfy_zammad_repeat
            return [
                {
                    "id": ticket["id"],
                    "number": ticket["number"],
                    "title": ticket["title"],
                    "state": ticket["state"],
                    "close_at": ticket.get("close_at"),
                }
                for ticket in self.tickets.values()
                if ticket["state"] in repeat.ACTIVE_STATES + repeat.CLOSED_STATES
                and query == repeat.build_search_query(ticket["key"], (
                    repeat.CLOSED_STATES if ticket["state"] == "closed" else repeat.ACTIVE_STATES
                ))
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
                "close_at": None,
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
                if "article" in payload:
                    ticket["articles"].append(payload["article"])
                if "state" in payload:
                    ticket["state"] = payload["state"]
                    ticket["close_at"] = (
                        self.bridge.time.time() if payload["state"] == "closed" else None
                    )
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

    def test_names_that_differ_by_an_identifier_stay_distinct(self):
        for first, other in (
            ("Disk 1 failed — smart error", "Disk 2 failed — smart error"),
            ("Service deadbeef down — probe", "Service cafe1234 down — probe"),
            ("Backup job failed — x", "Backup job succeeded — x"),
        ):
            self.assertNotEqual(
                self.nz.ntfy_zammad_repeat.correlation_key("status", first),
                self.nz.ntfy_zammad_repeat.correlation_key("status", other),
            )

    def test_stable_alert_key_ignores_the_detail_after_the_separator(self):
        first = "Gatus: API slow — 12 checks failed run-456"
        repeat = "Gatus: API slow — 19 checks failed run_id=789"
        self.assertEqual(
            self.nz.ntfy_zammad_repeat.correlation_key("status", first),
            self.nz.ntfy_zammad_repeat.correlation_key("status", repeat),
        )
        self.send(dict(self.msg, title=first), at=1000)
        self.send(dict(self.msg, title=repeat), at=5000)
        self.assertEqual(len(self.client.tickets), 1)
        self.assertEqual(len(self.open_ticket()["articles"]), 2)

    def test_different_alert_name_does_not_match(self):
        self.send(dict(self.msg, title="Gatus: API slow — 3 checks failed"), at=1000)
        self.send(dict(self.msg, title="Gatus: Database down — connection refused"), at=1001)
        self.assertEqual(len(self.client.tickets), 2)
        self.assertNotEqual(
            self.client.tickets[1]["key"], self.client.tickets[2]["key"]
        )

    def test_repeat_within_interval_is_suppressed_and_persisted(self):
        self.send(at=1000)
        self.send(at=1200)
        self.assertEqual(len(self.open_ticket()["articles"]), 1)
        with open(self.nz.ntfy_zammad_repeat.repeat_state_path(self.state.name)) as f:
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
        key = self.nz.ntfy_zammad_repeat.correlation_key(self.msg["topic"], self.msg["title"])
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

    def test_recent_closed_managed_ticket_reopens_with_one_internal_note(self):
        self.send(at=1000)
        recovered = dict(self.msg, message="worker recovered", tags=["resolved"])
        self.send(recovered, at=1100)
        self.send(dict(self.msg, message="worker failed again"), at=1200)

        ticket = self.open_ticket()
        self.assertEqual(len(self.client.tickets), 1)
        self.assertEqual(ticket["state"], "reopened")
        self.assertEqual(ticket["close_at"], None)
        self.assertEqual(len(ticket["articles"]), 3)
        self.assertIn("worker failed again", ticket["articles"][-1]["body"])
        self.assertEqual(ticket["articles"][-1]["type"], "note")
        self.assertTrue(ticket["articles"][-1]["internal"])
        reopen_payloads = [
            payload
            for method, path, payload in self.client.calls
            if method == "PUT" and path == "tickets/1" and payload.get("state") == "reopened"
        ]
        self.assertEqual(len(reopen_payloads), 1)
        self.assertEqual(set(reopen_payloads[0]), {"state", "article"})

    def test_firing_after_25_hour_closure_creates_new_ticket(self):
        self.send(at=1000)
        recovered = dict(self.msg, message="worker recovered", tags=["resolved"])
        self.send(recovered, at=1100)
        self.send(dict(self.msg, message="worker failed again"), at=1100 + 25 * 60 * 60)

        self.assertEqual(len(self.client.tickets), 2)
        self.assertEqual(self.client.tickets[1]["state"], "closed")
        self.assertEqual(self.client.tickets[2]["state"], "new")

    def test_recovery_does_not_close_ticket_without_bridge_marker(self):
        key = self.nz.ntfy_zammad_repeat.correlation_key(self.msg["topic"], self.msg["title"])
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
