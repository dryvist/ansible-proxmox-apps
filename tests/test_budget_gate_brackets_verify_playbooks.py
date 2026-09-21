# Copyright (c) 2026 JacobPEvans
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Every playbook a template can dispatch is bounded by the wall-clock gate.

site.yml gates between its stages and starts the clock in its first stage.
The verify/validate playbooks never pass through that stage, so the gate
starts the clock itself on first import and each of them imports it first
and last: a run that outlives the budget fails at the end instead of
running on with `task_timeout` as its only bound.
"""

from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
GATE = "site/budget-gate.yml"
BRACKETED = [
    "playbooks/validate-pipeline.yml",
    "playbooks/verify-grafana-dashboards.yml",
    "playbooks/verify-approle-ttls.yml",
    "playbooks/nautobot-drift.yml",
]


def _plays(rel):
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))


class GateStartsItsOwnClock(unittest.TestCase):
    def test_first_gate_starts_the_clock_when_no_stage_did(self):
        tasks = _plays("playbooks/site/budget-gate.yml")[0]["tasks"]
        start = tasks[0]
        self.assertIn("converge_started_epoch", start["ansible.builtin.set_fact"])
        self.assertEqual(start["when"], "converge_started_epoch is not defined")

    def test_site_still_gates_between_stages(self):
        gates = [p for p in _plays("playbooks/site.yml") if p.get("import_playbook") == GATE]
        self.assertGreaterEqual(len(gates), 5)


class VerifyPlaybooksAreBracketed(unittest.TestCase):
    def test_gate_is_the_first_and_last_play(self):
        for rel in BRACKETED:
            with self.subTest(playbook=rel):
                plays = _plays(rel)
                self.assertEqual(plays[0].get("import_playbook"), GATE)
                self.assertEqual(plays[-1].get("import_playbook"), GATE)
                self.assertGreater(len(plays), 2)


if __name__ == "__main__":
    unittest.main()
