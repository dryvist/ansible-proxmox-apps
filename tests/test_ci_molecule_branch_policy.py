"""Exercise the caller's matrix and gate with sanitized GitHub event metadata."""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from jinja2 import Environment, StrictUndefined
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci-gate.yml"
FIXTURE = ROOT / "tests/ci_molecule_branch_policy/main-event.json"


class MoleculeBranchPolicy(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.events = json.loads(FIXTURE.read_text(encoding="utf-8"))
        molecule = yaml.safe_load(
            (ROOT / ".github/workflows/_molecule.yml").read_text(encoding="utf-8")
        )
        self.discovery = next(
            step["run"] for step in molecule["jobs"]["scenarios"]["steps"]
            if step.get("name") == "Discover all scenarios for a full matrix"
        )

    def expression(self, expression, github, scenarios="[]", relevant="false", cancelled=False):
        # These clauses use only boolean/string operations shared by GitHub
        # expressions and Jinja. Execute the source clauses, rather than
        # asserting their spelling or reproducing their branch decisions.
        expression = expression.strip().removeprefix("${{").removesuffix("}}").strip()
        expression = expression.replace("&&", "and").replace("||", "or")
        expression = re.sub(r"!(?!=)", "not ", expression)
        return Environment(undefined=StrictUndefined).compile_expression(expression)(
            github=github,
            needs={"ci": {"outputs": {
                "molecule": relevant, "molecule_scenarios": scenarios,
            }}},
            cancelled=lambda: cancelled,
        )

    def matrix(self, github, scenarios="[]", relevant="false", cancelled=False):
        job = self.workflow["jobs"]["molecule"]
        if not self.expression(job["if"], github, scenarios, relevant, cancelled):
            return None
        selected = self.expression(job["with"]["scenarios"], github, scenarios, relevant)
        if selected:
            return json.loads(selected)
        # Run the workflow's actual full-matrix discovery, without Docker.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            subprocess.run(
                ["bash", "-c", self.discovery], cwd=ROOT, check=True,
                env={**os.environ, "GITHUB_OUTPUT": str(output)},
                capture_output=True, text=True,
            )
            return json.loads(output.read_text(encoding="utf-8").removeprefix("list="))

    def allowed_skips(self, github):
        gate = self.workflow["jobs"]["gate"]
        policy = next(
            step["with"]["allowed-skips"] for step in gate["steps"]
            if step.get("name") == "Check all results"
        )
        return {item.strip() for item in self.expression(policy, github).split(",") if item.strip()}

    def assert_full_matrix(self, actual):
        expected = sorted(path.parent.name for path in (ROOT / "molecule").glob("*/molecule.yml"))
        self.assertGreater(len(expected), 1)
        self.assertEqual(actual, expected)

    def test_main_promotion_runs_every_scenario_for_empty_or_focused_classifier_outputs(self):
        github = self.events["main_pull_request"]
        for scenarios in ("[]", "", '["default"]'):
            with self.subTest(scenarios=scenarios):
                self.assert_full_matrix(self.matrix(github, scenarios, "true"))
        self.assert_full_matrix(self.matrix(github))

    def test_main_promotion_requires_molecule_in_the_gate(self):
        github = self.events["main_pull_request"]
        self.assertNotIn("molecule", self.allowed_skips(github))
        self.assertIn("molecule", self.workflow["jobs"]["gate"]["needs"])

    def test_fork_main_pr_runs_full_matrix_and_only_waives_live_e2e(self):
        github = deepcopy(self.events["main_pull_request"])
        github["event"]["pull_request"]["head"]["repo"]["full_name"] = "fixture/fork"
        self.assert_full_matrix(self.matrix(github))
        self.assertEqual(self.allowed_skips(github), {"e2e"})

    def test_develop_pr_keeps_focused_selection_and_contract_only_selection(self):
        github = deepcopy(self.events["main_pull_request"])
        github["event"]["pull_request"]["base"]["ref"] = "develop"
        self.assertEqual(self.matrix(github, '["default"]', "true"), ["default"])
        self.assertIsNone(self.matrix(github))

    def test_main_push_runs_every_scenario(self):
        github = deepcopy(self.events["develop_push"])
        github["ref"] = "refs/heads/main"
        for scenarios in ("[]", "", '["default"]'):
            with self.subTest(scenarios=scenarios):
                self.assert_full_matrix(self.matrix(github, scenarios, "true"))

    def test_develop_push_preserves_the_shared_focused_policy(self):
        self.assertEqual(
            self.matrix(self.events["develop_push"], '["default"]', "true"), ["default"]
        )

    def test_cancelled_promotion_does_not_start_a_matrix(self):
        self.assertIsNone(self.matrix(self.events["main_pull_request"], cancelled=True))

    def test_policy_test_and_fixture_are_covered_by_the_contract_classifier(self):
        filters = self.workflow["jobs"]["ci"]["with"]["molecule_contract_filters"]
        self.assertIn("tests/test_ci_molecule_branch_policy.py", filters)
        self.assertIn("tests/ci_molecule_branch_policy/**", filters)


if __name__ == "__main__":
    unittest.main()
