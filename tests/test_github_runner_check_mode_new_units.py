# Copyright (c) 2026 JacobPEvans
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""The pool assert judges only installed units in check mode, and every wanted unit live."""

from pathlib import Path
import unittest

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
RECONCILE = ROOT / "roles/github_runner/tasks/reconcile_service_units.yml"
WANTED = ["github-runner@1.service", "github-runner@7.service"]
SERVICES = {"github-runner@1.service": {"state": "running"}}


def _bad(check_mode):
    task = next(
        t
        for t in yaml.safe_load(RECONCILE.read_text(encoding="utf-8"))
        if t.get("name") == "Assert every pooled runner unit is running"
    )
    env = jinja2.Environment()
    env.filters["dict2items"] = lambda d: [{"key": k, "value": v} for k, v in d.items()]
    return env.from_string(task["vars"]["_bad"]).render(
        github_runner_all_wanted_units=WANTED,
        ansible_facts={"services": SERVICES},
        ansible_check_mode=check_mode,
    ).strip()


class CheckModeNewUnits(unittest.TestCase):
    def test_check_mode_skips_a_unit_it_never_installed(self):
        self.assertEqual(_bad(True), "[]")

    def test_live_run_flags_a_missing_unit(self):
        self.assertEqual(_bad(False), "['github-runner@7.service']")


if __name__ == "__main__":
    unittest.main()
