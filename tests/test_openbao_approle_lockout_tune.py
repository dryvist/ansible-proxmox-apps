"""The AppRole auth mount's login lockout must stay wider than the mount
default, or a converge that silently drops the tune reverts it to 5 failures
per 15 minutes -- locking a shared workstation alias on ordinary retry noise.

This renders the REAL tune task's `cmd`, never a reimplementation of it, so a
renamed variable or a dropped flag fails here instead of only at converge time.
"""

from pathlib import Path
import unittest

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

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


def _render(template, variables):
    templar = Templar(loader=DataLoader())
    templar.available_variables = _mark_templates(variables)
    return templar.template(trust_as_template(template))


class TestApproleLockoutTune(unittest.TestCase):
    def setUp(self):
        self.variables = _defaults()

    def test_lockout_defaults_are_declared_and_non_empty(self):
        for name in DEFAULT_VARS:
            self.assertIn(name, self.variables)
            self.assertTrue(str(self.variables[name]))

    def test_tune_command_renders_every_lockout_default(self):
        cmd = _render(_task()["ansible.builtin.command"]["cmd"], self.variables)
        self.assertIn(f"-user-lockout-threshold={self.variables['openbao_approle_lockout_threshold']}", cmd)
        self.assertIn(f"-user-lockout-duration={self.variables['openbao_approle_lockout_duration']}", cmd)
        self.assertIn(
            f"-user-lockout-counter-reset-duration={self.variables['openbao_approle_lockout_counter_reset']}",
            cmd,
        )


if __name__ == "__main__":
    unittest.main()
