"""Only the main push may turn an empty scenario input into the full matrix."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci-gate.yml"


class MoleculeBranchPolicy(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def test_shared_classifier_uses_focused_non_main_policy(self):
        uses = self.workflow["jobs"]["ci"]["uses"]
        self.assertEqual(
            uses,
            "dryvist/.github/.github/workflows/_ansible-ci.yml@"
            "1ee6eaa788a7d713019c71493cd2a03b9021dc2a",
        )

    def test_full_matrix_only_runs_on_main_push(self):
        condition = self.workflow["jobs"]["molecule"]["if"]
        self.assertIn(
            "github.event_name == 'push' && github.ref == 'refs/heads/main'",
            condition,
        )
        self.assertIn("needs.ci.outputs.molecule_scenarios != ''", condition)
        self.assertIn("needs.ci.outputs.molecule_scenarios != '[]'", condition)
        self.assertIn("needs.ci.outputs.molecule == 'true'", condition)
        self.assertNotIn("github.event_name == 'push' ||", condition)

    def test_empty_non_main_selections_are_gate_accepted_after_classification(self):
        gate = self.workflow["jobs"]["gate"]
        policy = next(
            step["with"]["allowed-skips"]
            for step in gate["steps"]
            if step.get("name") == "Check all results"
        )
        self.assertIn("github.event_name == 'push' && github.ref == 'refs/heads/develop'", policy)
        self.assertIn("github.event.pull_request.base.ref == 'main'", policy)
        self.assertIn("'e2e, molecule'", policy)
        self.assertIn("'molecule'", policy)
        self.assertIn("ci", gate["needs"])

    def test_policy_test_path_is_covered_by_the_contract_classifier(self):
        contract_filters = self.workflow["jobs"]["ci"]["with"][
            "molecule_contract_filters"
        ]
        self.assertIn("tests/test_ci_molecule_branch_policy.py", contract_filters)


if __name__ == "__main__":
    unittest.main()
