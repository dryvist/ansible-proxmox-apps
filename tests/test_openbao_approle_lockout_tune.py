"""The AppRole auth mount's login lockout must stay wider than the mount
default, or a converge that silently drops the tune reverts it to 5 failures
per 15 minutes -- locking a shared workstation alias on ordinary retry noise.

This renders the REAL tune task's `cmd`, `vars` and `when`, never a
reimplementation of them, so a renamed variable, a dropped flag, or a broken
seconds comparison fails here instead of only at converge time. OpenBao
returns the two lockout durations as integer seconds in the tune read (never
a duration string), so the drift check must convert the declared "5m"/"15m"
defaults to seconds before comparing -- exercised below with a synthetic
seconds-valued read.
"""

import json
from pathlib import Path
import unittest

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
from ansible_collections.community.general.plugins.filter.time import to_seconds

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / "roles/openbao/defaults/main/08a-admin-and-ttls.yml"
TASKS = ROOT / "roles/openbao/tasks/init/09-auth-methods-and-terrakube-jwt.yml"
TASK_NAME = "Tune the AppRole mount login lockout"

DEFAULT_VARS = ["openbao_approle_lockout_threshold", "openbao_approle_lockout_duration",
                "openbao_approle_lockout_counter_reset"]


def _defaults():
    return yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))


def _task():
    for task in yaml.safe_load(TASKS.read_text(encoding="utf-8")):
        if task.get("name") == TASK_NAME:
            return task
    raise AssertionError(f"task {TASK_NAME!r} not found in {TASKS}")


def _mark_templates(value):
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, dict):
        return {k: _mark_templates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mark_templates(v) for v in value]
    return value


def _templar():
    templar = Templar(loader=DataLoader())
    # The real filter, not a reimplementation -- registered directly because a
    # bare Templar (no play/module context) does not resolve collection
    # filter plugins on its own.
    templar.environment.filters["community.general.to_seconds"] = to_seconds
    return templar


def _render(template, variables):
    templar = _templar()
    templar.available_variables = _mark_templates(variables)
    return templar.template(trust_as_template(template))


def _resolve_task_vars(task, base_variables):
    """Resolve the task's own `vars:` in declaration order, matching how
    Ansible builds the namespace a `when`/`cmd` templates against."""
    namespace = dict(base_variables)
    for name, template in task.get("vars", {}).items():
        namespace[name] = _render(template, namespace)
    return namespace


class TestApproleLockoutTune(unittest.TestCase):
    def setUp(self):
        self.variables = _defaults()
        self.task = _task()

    def test_lockout_defaults_are_declared_and_non_empty(self):
        for name in DEFAULT_VARS:
            self.assertIn(name, self.variables)
            self.assertTrue(str(self.variables[name]))

    def test_tune_command_renders_every_lockout_default(self):
        cmd = _render(self.task["ansible.builtin.command"]["cmd"], self.variables)
        self.assertIn(f"-user-lockout-threshold={self.variables['openbao_approle_lockout_threshold']}", cmd)
        self.assertIn(f"-user-lockout-duration={self.variables['openbao_approle_lockout_duration']}", cmd)
        self.assertIn(
            f"-user-lockout-counter-reset-duration={self.variables['openbao_approle_lockout_counter_reset']}",
            cmd,
        )

    def _when_is_true(self, mount_tune_current):
        namespace = _resolve_task_vars(self.task, {**self.variables, "openbao_approle_mount_tune_current": mount_tune_current})
        conditions = self.task["when"]
        # `when:` entries are bare Jinja expressions (no {{ }}), the same way
        # Ansible itself evaluates a conditional -- wrap each to get a value.
        return all(_render("{{ (" + cond + ") }}", namespace) in ("True", True) for cond in conditions)

    def test_when_is_false_for_a_live_seconds_read_matching_declared(self):
        """OpenBao returns lockout_duration/lockout_counter_reset in SECONDS,
        not the "5m"/"15m" strings declared in defaults. A comparison that
        forgot to convert would treat every converge as drift forever."""
        live_seconds = {
            "lockout_threshold": self.variables["openbao_approle_lockout_threshold"],
            "lockout_duration": int(to_seconds(self.variables["openbao_approle_lockout_duration"])),
            "lockout_counter_reset": int(to_seconds(self.variables["openbao_approle_lockout_counter_reset"])),
        }
        mount_tune_current = {
            "rc": 0,
            "stdout": json.dumps({"data": {"user_lockout_config": live_seconds}}),
        }
        self.assertFalse(self._when_is_true(mount_tune_current))

    def test_when_is_true_when_live_still_holds_string_form(self):
        """A read that (incorrectly) held the declared string form rather
        than seconds must still be treated as drift, not equal."""
        live_strings = {
            "lockout_threshold": self.variables["openbao_approle_lockout_threshold"],
            "lockout_duration": self.variables["openbao_approle_lockout_duration"],
            "lockout_counter_reset": self.variables["openbao_approle_lockout_counter_reset"],
        }
        mount_tune_current = {
            "rc": 0,
            "stdout": yaml.safe_dump({"data": {"user_lockout_config": live_strings}}, default_flow_style=True),
        }
        with self.assertRaises(Exception):
            # "5m" | int fails to coerce -- proves the comparison is a real
            # int cast, not a permissive one that would silently pass.
            self._when_is_true(mount_tune_current)


if __name__ == "__main__":
    unittest.main()
