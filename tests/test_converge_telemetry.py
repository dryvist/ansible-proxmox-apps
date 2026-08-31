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


class DesiredStateFieldsContract(unittest.TestCase):
    """The 'was this converge fed a stale inventory?' fields.

    The alert built on them treats their absence as "not checked" and their
    presence as a real verdict, so the boundary between the two is the whole
    contract: a run that could not check must publish nothing rather than a
    default.
    """

    def converge_event(self, config):
        events = telemetry.build_events({"alpha": summary()}, config, "site.yml", 0.0)
        return next(
            e for e in events if e["sourcetype"] == telemetry.SOURCETYPE_CONVERGE
        )["event"]

    def test_no_verdict_publishes_no_claim(self):
        event = self.converge_event(CONFIG)
        for field in ("desired_state_current", "desired_state_published",
                      "desired_state_live"):
            self.assertNotIn(field, event)

    def test_stale_artifact_is_published_as_false(self):
        config = dict(CONFIG, desired_state_current=False,
                      desired_state_published="aaa", desired_state_live="bbb")
        event = self.converge_event(config)
        self.assertIs(event["desired_state_current"], False)
        self.assertEqual(event["desired_state_published"], "aaa")
        self.assertEqual(event["desired_state_live"], "bbb")

    def test_current_artifact_is_published_as_true(self):
        config = dict(CONFIG, desired_state_current=True,
                      desired_state_published="aaa", desired_state_live="aaa")
        self.assertIs(self.converge_event(config)["desired_state_current"], True)

    def test_roster_events_carry_no_verdict(self):
        # The verdict is a property of a converge, not of inventory membership.
        # Emitting it on the roster too would double every alert result row.
        config = dict(CONFIG, desired_state_current=False)
        events = telemetry.build_events({"alpha": summary()}, config, "site.yml", 0.0)
        roster = [e for e in events if e["sourcetype"] == telemetry.SOURCETYPE_ROSTER]
        self.assertTrue(roster)
        for event in roster:
            self.assertNotIn("desired_state_current", event["event"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TaskTimingEvents(unittest.TestCase):
    """Per-task duration is the number that explains converge wall clock.

    It previously existed only in `profile_tasks` stdout, which is written to a
    local run log and shipped nowhere — so a single task burning 776 seconds of
    a 40-minute converge was invisible to every dashboard. These tests pin the
    timing bookkeeping, because a callback that silently records nothing looks
    exactly like a converge with no slow tasks.
    """

    def _task(self, name, action="command", role="openbao"):
        class _Role:
            def __str__(self):
                return role

        class _Task:
            def __init__(self):
                self.action = action
                self._role = _Role() if role else None

            def get_name(self):
                return name

        return _Task()

    def _result(self, changed=False):
        class _Result:
            def __init__(self):
                self._result = {"changed": changed}

        return _Result()

    def _plugin(self):
        cb = telemetry.CallbackModule()
        cb._playbook_name = "site.yml"
        return cb

    def test_durations_are_recorded_per_task(self):
        cb = self._plugin()
        cb.v2_playbook_on_task_start(self._task("slow render"))
        cb.v2_runner_on_ok(self._result(changed=True))
        cb.v2_runner_on_ok(self._result())
        cb.v2_playbook_on_task_start(self._task("fast thing"))
        cb._close_open_task()

        self.assertEqual([t["name"] for t in cb._tasks], ["slow render", "fast thing"])
        first = cb._tasks[0]
        self.assertEqual(first["hosts"], 2)
        self.assertEqual(first["changed"], 1)
        self.assertEqual(first["failed"], 0)
        self.assertGreaterEqual(first["duration"], 0.0)
        self.assertIsNotNone(first["ended"])

    def test_failures_and_unreachable_count_as_failed(self):
        cb = self._plugin()
        cb.v2_playbook_on_task_start(self._task("flaky"))
        cb.v2_runner_on_failed(self._result())
        cb.v2_runner_on_unreachable(self._result())
        cb.v2_runner_on_failed(self._result(), ignore_errors=True)
        cb._close_open_task()

        task = cb._tasks[0]
        self.assertEqual(task["hosts"], 3)
        self.assertEqual(task["failed"], 2, "ignored errors must not count as failures")

    def test_handler_tasks_are_timed_separately(self):
        cb = self._plugin()
        cb.v2_playbook_on_task_start(self._task("main work"))
        cb.v2_playbook_on_handler_task_start(self._task("restart service"))
        cb._close_open_task()

        self.assertEqual(
            [t["name"] for t in cb._tasks],
            ["main work", "restart service"],
            "a handler must not have its runtime attributed to the previous task",
        )

    def test_event_shape_carries_duration_and_identity(self):
        cb = self._plugin()
        cb.v2_playbook_on_task_start(self._task("render policies"))
        cb.v2_runner_on_ok(self._result(changed=True))
        cb._close_open_task()

        events = telemetry.build_task_events(cb._tasks, CONFIG, "site.yml", 1000.0)
        self.assertEqual(len(events), 1)
        envelope = events[0]
        self.assertEqual(envelope["sourcetype"], "ansible:converge:task")
        self.assertEqual(envelope["index"], "ansible")
        event = envelope["event"]
        self.assertEqual(event["task"], "render policies")
        self.assertEqual(event["role"], "openbao")
        self.assertEqual(event["git_sha"], CONFIG["git_sha"])
        self.assertIn("duration_seconds", event)
        self.assertEqual(event["changed"], 1)
        # Must survive the HEC encoder the transport actually uses.
        json.loads(json.dumps(envelope))

    def test_no_tasks_produces_no_task_events(self):
        self.assertEqual(telemetry.build_task_events([], CONFIG, "site.yml", 1.0), [])
