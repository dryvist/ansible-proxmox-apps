"""Behavioral contracts for the converge-freshness callback plugin.

The alert built on these events is only as trustworthy as the success verdict
the plugin publishes, so these tests pin the verdict rules and the event shape.
"""

import importlib.util
import json
from pathlib import Path
import unittest

from ansible import context
from ansible.module_utils.common.collections import ImmutableDict


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "callback_plugins" / "converge_telemetry.py"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("converge_telemetry", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


telemetry = _load_plugin()


CONFIG = {
    "hec_url": "https://splunk.example.test:8088/services/collector/event",
    "index": "ansible",
    "git_sha": "0123456789abcdef0123456789abcdef01234567",
    "roster": ["alpha", "bravo", "charlie"],
    "fqdns": {
        "alpha": "alpha.example.test",
        "bravo": "bravo.example.test",
        "charlie": "charlie.example.test",
    },
}


def summary(**kwargs):
    base = {
        "ok": 10,
        "changed": 2,
        "skipped": 3,
        "failures": 0,
        "unreachable": 0,
        "rescued": 0,
        "ignored": 0,
    }
    base.update(kwargs)
    return base


class HostStatusContract(unittest.TestCase):
    def test_clean_host_is_success(self):
        self.assertEqual(telemetry.host_status(summary()), "success")

    def test_failed_host_is_not_success(self):
        self.assertEqual(telemetry.host_status(summary(failures=1)), "failed")

    def test_unreachable_host_is_not_success(self):
        self.assertEqual(telemetry.host_status(summary(unreachable=1)), "failed")

    def test_rescued_host_is_not_success(self):
        # site.yml uses rescue blocks exclusively to record isolated play
        # failures, so a rescued host did NOT converge cleanly even though
        # Ansible reports failures=0 for it.
        self.assertEqual(telemetry.host_status(summary(rescued=1)), "failed")


class EventShapeContract(unittest.TestCase):
    def setUp(self):
        self.events = telemetry.build_events(
            {"alpha": summary(), "bravo": summary(rescued=1)},
            CONFIG,
            "site.yml",
            1_700_000_000.0,
        )
        self.converge = [
            e for e in self.events if e["sourcetype"] == telemetry.SOURCETYPE_CONVERGE
        ]
        self.roster = [
            e for e in self.events if e["sourcetype"] == telemetry.SOURCETYPE_ROSTER
        ]

    def test_one_converge_event_per_processed_host(self):
        self.assertEqual(
            sorted(e["host"] for e in self.converge),
            ["alpha.example.test", "bravo.example.test"],
        )

    def test_roster_covers_every_inventory_host(self):
        self.assertEqual(
            sorted(e["host"] for e in self.roster),
            ["alpha.example.test", "bravo.example.test", "charlie.example.test"],
        )

    def test_status_reflects_the_per_host_verdict(self):
        statuses = {e["event"]["inventory_hostname"]: e["event"]["status"] for e in self.converge}
        self.assertEqual(statuses, {"alpha": "success", "bravo": "failed"})

    def test_required_alert_fields_are_present(self):
        event = self.converge[0]
        self.assertEqual(event["index"], "ansible")
        self.assertEqual(event["time"], 1_700_000_000.0)
        for field in ("host", "playbook", "git_sha", "ok", "changed",
                      "failures", "unreachable", "rescued", "status"):
            self.assertIn(field, event["event"])
        self.assertEqual(event["event"]["playbook"], "site.yml")
        self.assertEqual(event["event"]["git_sha"], CONFIG["git_sha"])

    def test_no_secret_material_is_ever_emitted(self):
        body = telemetry.encode_batch(self.events)
        self.assertNotIn("token", body.lower())

    def test_batch_is_concatenated_json_objects(self):
        body = telemetry.encode_batch(self.events)
        decoder = json.JSONDecoder()
        index, decoded = 0, 0
        while index < len(body):
            _, offset = decoder.raw_decode(body, index)
            index, decoded = offset, decoded + 1
        self.assertEqual(decoded, len(self.events))

    def test_unknown_host_falls_back_to_the_inventory_name(self):
        events = telemetry.build_events({"delta": summary()}, CONFIG, "site.yml", 0.0)
        converge = [e for e in events if e["sourcetype"] == telemetry.SOURCETYPE_CONVERGE]
        self.assertEqual(converge[0]["host"], "delta")


class FakeStats(object):
    """Minimal stand-in for Ansible's end-of-run ``AggregateStats``."""

    def __init__(self, config):
        self.custom = {"_run": {telemetry.STATS_KEY: config}}
        self.processed = {"alpha": 1}

    def summarize(self, host):  # noqa: ARG002 - one fixed clean host is enough
        return summary()


class RecordingCallback(telemetry.CallbackModule):
    """The real callback with only its Ansible plumbing stubbed out."""

    def __init__(self):
        telemetry.CallbackModule.__init__(self)
        self._plugin_options = {"enabled": True, "hec_token": "unit-test-token"}

    def get_option(self, name):
        return self._plugin_options[name]


def emit_and_capture(config, cliargs):
    """Run the callback's emit path; return every ``open_url`` call it made."""
    posted = []
    original_open_url = telemetry.open_url
    original_cliargs = context.CLIARGS
    telemetry.open_url = lambda url, **kwargs: posted.append((url, kwargs))
    context.CLIARGS = ImmutableDict(cliargs)
    try:
        callback = RecordingCallback()
        callback.v2_playbook_on_stats(FakeStats(config))
    finally:
        telemetry.open_url = original_open_url
        context.CLIARGS = original_cliargs
    return posted


class CheckModeContract(unittest.TestCase):
    """A dry run must never refresh a host's converge-freshness clock.

    A ``--check`` run changes nothing on the targets, but Ansible still reports
    ``ok>0`` for every host it walked, so ``host_status`` would call it a
    success. Publishing that would make a genuinely stale host look fresh and
    silently defeat the >7-day staleness alert this telemetry exists to feed.
    """

    def test_a_real_run_does_publish(self):
        # Instrument validation: this proves the harness CAN observe an emit,
        # so a "nothing was posted" assertion below is evidence, not an
        # artefact of a test that could never fail.
        posted = emit_and_capture(CONFIG, {"check": False})
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0][0], CONFIG["hec_url"])

    def test_cli_check_flag_suppresses_every_event(self):
        self.assertEqual(emit_and_capture(CONFIG, {"check": True}), [])

    def test_published_check_mode_flag_suppresses_every_event(self):
        # Covers API-driven runs (ansible-runner and friends) where CLIARGS
        # carries no --check flag at all.
        config = dict(CONFIG, **{telemetry.CHECK_MODE_KEY: True})
        self.assertEqual(emit_and_capture(config, {}), [])

    def test_absent_signals_are_not_read_as_check_mode(self):
        original = context.CLIARGS
        context.CLIARGS = ImmutableDict({})
        try:
            self.assertFalse(telemetry.is_check_mode(CONFIG))
        finally:
            context.CLIARGS = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
