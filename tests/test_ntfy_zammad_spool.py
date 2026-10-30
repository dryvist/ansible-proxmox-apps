#!/usr/bin/env python3
"""ntfy-zammad spool: a failed post spools, then an immediate duplicate replay
is suppressed on the existing ticket. Loads the deployed script itself and
fakes only the Zammad API call."""

import email.message
import importlib.util
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / "roles" / "ntfy_docker" / "files" / "ntfy-zammad.py"


def _load():
    spec = importlib.util.spec_from_file_location("ntfy_zammad", SCRIPT)
    assert spec is not None and spec.loader is not None, SCRIPT
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_json(path):
    with open(path) as f:
        return json.load(f)


class NtfyZammadSpool(unittest.TestCase):
    def setUp(self):
        self.nz = _load()
        self.tickets, self.calls, self.zammad = {}, [], {"down": True}
        env = mock.patch.dict(os.environ, {"ZAMMAD_API_URL": "http://zammad.test/api/v1", "ZAMMAD_API_TOKEN": "t"})
        env.start()
        self.addCleanup(env.stop)
        call = mock.patch.object(self.nz, "zammad_call", self._fake_call)
        call.start()
        self.addCleanup(call.stop)
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.state_dir = state.name
        os.environ["NTFY_ZAMMAD_STATE_DIR"] = self.state_dir
        self.msg = {"topic": "network", "title": "WAN down", "message": "m", "tags": ["high"]}

    def _fake_call(self, base, token, path, payload=None, method=None):
        if self.zammad["down"]:
            raise urllib.error.URLError("no available server")
        self.calls.append((method, path))
        if path.startswith("tickets/search"):
            want = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)["query"][0]
            repeat = self.nz.ntfy_zammad_repeat
            return [
                {
                    "id": i,
                    "title": "%s — summary" % key,
                    "state": "open",
                    "close_at": None,
                }
                for i, key in self.tickets.items()
                if want == repeat.build_search_query(key, repeat.ACTIVE_STATES)
            ]
        if path == "users/me":
            return {"id": 1}
        if method == "POST" and path == "tickets":
            self.tickets[len(self.tickets) + 1] = (payload or {})["title"].split(" — ")[0]
        return {}

    def _spooled(self):
        return sorted(os.listdir(self.nz.ntfy_zammad_spool.spool_dir(self.state_dir)))

    def test_failed_post_spools_and_replays_once_up(self):
        nz = self.nz
        with self.assertRaises(urllib.error.URLError):
            nz.handle(self.msg)
        nz.ntfy_zammad_spool.spool_message(self.state_dir, self.msg)
        spooled = self._spooled()
        self.assertEqual(len(spooled), 1)
        path = os.path.join(nz.ntfy_zammad_spool.spool_dir(self.state_dir), spooled[0])
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertNotIn("t", _read_json(path).values())

        # Still down: replay fails and keeps the file.
        with self.assertRaises(urllib.error.URLError):
            nz.ntfy_zammad_spool.replay_spool(self.state_dir, nz.handle)
        self.assertEqual(len(self._spooled()), 1)

        self.zammad["down"] = False
        nz.ntfy_zammad_spool.replay_spool(self.state_dir, nz.handle)
        self.assertEqual(self._spooled(), [])
        self.assertEqual(list(self.tickets.values()), ["fk:ntfy:network:WAN down"])

        # The same key again (a second replay or a live repeat) appends.
        nz.ntfy_zammad_spool.spool_message(self.state_dir, self.msg)
        nz.ntfy_zammad_spool.replay_spool(self.state_dir, nz.handle)
        self.assertEqual(len(self.tickets), 1)
        self.assertNotIn(("PUT", "tickets/1"), self.calls)

    def test_spooled_4xx_is_dropped(self):
        nz = self.nz
        nz.ntfy_zammad_spool.spool_message(self.state_dir, dict(self.msg, title="bad"))

        def reject(_msg):
            raise urllib.error.HTTPError("u", 422, "bad", email.message.Message(), None)

        nz.ntfy_zammad_spool.replay_spool(self.state_dir, reject)
        self.assertEqual(self._spooled(), [])

    def test_is_transient(self):
        nz, hdrs = self.nz, email.message.Message()
        self.assertTrue(nz.ntfy_zammad_spool.is_transient(urllib.error.URLError("x")))
        self.assertTrue(nz.ntfy_zammad_spool.is_transient(urllib.error.HTTPError("u", 503, "x", hdrs, None)))
        self.assertFalse(nz.ntfy_zammad_spool.is_transient(urllib.error.HTTPError("u", 422, "x", hdrs, None)))
        self.assertFalse(nz.ntfy_zammad_spool.is_transient(ValueError("x")))

    def test_cap_drops_the_oldest(self):
        nz = self.nz
        for i in range(3):
            nz.ntfy_zammad_spool.spool_message(self.state_dir, dict(self.msg, title="t%d" % i), max_files=2)
        left = [_read_json(os.path.join(nz.ntfy_zammad_spool.spool_dir(self.state_dir), n))["title"] for n in self._spooled()]
        self.assertEqual(left, ["t1", "t2"])


if __name__ == "__main__":
    unittest.main()
