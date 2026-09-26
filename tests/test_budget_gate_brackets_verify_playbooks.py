# Copyright (c) 2026 JacobPEvans
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Every playbook a template can dispatch is bounded by the wall-clock gate.

site.yml gates between its stages and starts the clock in its first stage
(playbooks/site/00-load-and-telemetry.yml). The verify/validate playbooks
never pass through that stage, so the gate starts the clock itself on first
import and each of them imports it first and last: a run that outlives the
budget fails at the end instead of running on with `task_timeout` as its
only bound.

The gate's own cap-derivation and clock-start logic live once in the
dryvist.homelab collection (homelab-contracts, ansible/roles/converge_gate)
and are tested there, not here — this file's job is only the wiring
contract: that playbooks/site/budget-gate.yml delegates to that shared
role, and that every entry point brackets its run with the gate.
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


class GateDelegatesToTheSharedCollection(unittest.TestCase):
    def test_local_gate_imports_the_collection_playbook(self):
        play = _plays("playbooks/site/budget-gate.yml")[0]
        self.assertEqual(play.get("import_playbook"), "dryvist.homelab.converge_gate")
        self.assertNotIn("tasks", play)

    def test_first_stage_starts_the_clock_the_shared_gate_reads(self):
        plays = _plays("playbooks/site/00-load-and-telemetry.yml")
        tasks = [t for p in plays for t in p.get("tasks", [])]
        start = next(
            t for t in tasks if t.get("name") == "Start the converge wall clock"
        )
        self.assertIn("converge_gate_started_epoch", start["ansible.builtin.set_fact"])

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
