"""Exercise the caller's matrix and gate with sanitized GitHub event metadata."""

from copy import deepcopy
import fnmatch
import json
from pathlib import Path
import re
import unittest

from jinja2 import Environment, StrictUndefined
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci-gate.yml"
FIXTURE = ROOT / "tests/ci_molecule_branch_policy/main-event.json"
HEAVY_JOBS = {
    "data-contract", "inventory-contract", "secrets-contract", "molecule", "e2e",
    "template-render", "nautobot-seed", "status-stack-autokuma-render",
    "agent-sandbox-limited-render",
}


class MoleculeBranchPolicy(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.events = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def expression(self, expression, github, scenarios="[]", relevant="false",
                   cancelled=False, heavy_jobs="true", tier="warm", labels=(),
                   molecule_workflow="false"):
        # These clauses use only boolean/string operations shared by GitHub
        # expressions and Jinja. Execute the source clauses, rather than
        # asserting their spelling or reproducing their branch decisions. The
        # label glob and contains() exist only in GitHub expressions, so they
        # run against the same fixture data as the neighbouring terms.
        expression = expression.strip().removeprefix("${{").removesuffix("}}").strip()
        expression = expression.replace(
            "github.event.pull_request.labels.*.name", "labels"
        )
        expression = expression.replace("&&", "and").replace("||", "or")
        expression = re.sub(r"!(?!=)", "not ", expression)
        return Environment(undefined=StrictUndefined).compile_expression(expression)(
            github=github,
            needs={
                "ci": {"outputs": {
                    "molecule": relevant, "molecule_scenarios": scenarios,
                    "ansible": "true",
                }},
                "changes": {"outputs": {
                    "molecule": relevant, "molecule_scenarios": scenarios,
                    "ansible": "true",
                }},
                "scope": {"outputs": {
                    "deploy": "true", "molecule_workflow": molecule_workflow,
                }},
                "lane": {"outputs": {"heavy_jobs": heavy_jobs, "tier": tier}},
            },
            vars={"E2E_RUNNERS_ENABLED": "true"},
            cancelled=lambda: cancelled,
            labels=list(labels),
            contains=lambda items, value: value in items,
        )

    def matrix(self, github, scenarios="[]", relevant="false", cancelled=False,
               molecule_workflow="false"):
        job = self.workflow["jobs"]["molecule"]
        if not self.expression(
            job["if"], github, scenarios, relevant, cancelled,
            molecule_workflow=molecule_workflow,
        ):
            return None
        full_suite = self.expression(
            job["with"]["full_suite"], github, scenarios, relevant,
            molecule_workflow=molecule_workflow,
        )
        if full_suite:
            return self.all_scenarios()
        selected = self.expression(
            job["with"]["scenarios"], github, scenarios, relevant,
            molecule_workflow=molecule_workflow,
        )
        if selected:
            return json.loads(selected)
        # The shared workflow discovers all scenarios by directory when the
        # caller supplies no focused selection (main promotion/push policy).
        return self.all_scenarios()

    def allowed_skips(self, github):
        gate = self.workflow["jobs"]["gate"]
        policy = next(
            step["with"]["allowed-skips"] for step in gate["steps"]
            if step.get("name") == "Check all results"
        )
        return {item.strip() for item in self.expression(policy, github).split(",") if item.strip()}

    def assert_full_matrix(self, actual):
        expected = self.all_scenarios()
        self.assertGreater(len(expected), 1)
        self.assertEqual(actual, expected)

    def all_scenarios(self):
        return sorted(path.parent.name for path in (ROOT / "molecule").glob("*/molecule.yml"))

    def test_merge_queue_entries_trigger_the_gate(self):
        # PyYAML reads the workflow's `on:` key as the boolean True.
        self.assertIn("merge_group", self.workflow[True])
        self.assertIn("push", self.workflow[True])

    def test_one_lane_job_decides_the_heavy_jobs(self):
        lane = self.workflow["jobs"]["lane"]
        self.assertEqual(lane["uses"], "JacobPEvans/.github/.github/workflows/_lane.yml@v1")
        self.assertEqual(lane["permissions"], {"contents": "read", "pull-requests": "read"})
        for job_id in HEAVY_JOBS:
            job = self.workflow["jobs"][job_id]
            needs = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
            with self.subTest(job=job_id):
                self.assertIn("lane", needs)
        self.assertIn("lane", self.workflow["jobs"]["gate"]["needs"])

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
        self.assertIn("changes", self.workflow["jobs"]["gate"]["needs"])

    def test_agent_platform_conformance_is_required_for_every_event(self):
        job_id = "agent-platform-conformance"
        job = self.workflow["jobs"][job_id]
        self.assertEqual(
            job["uses"],
            "dryvist/.github/.github/workflows/agent-platform-conformance.yml"
            "@198f25d695819a48e73f5a7723b47c5bd4839a7c",
        )
        self.assertEqual(job["permissions"], {"contents": "read"})
        self.assertNotIn("if", job)
        self.assertIn(job_id, self.workflow["jobs"]["gate"]["needs"])
        develop_pr = deepcopy(self.events["main_pull_request"])
        develop_pr["event"]["pull_request"]["base"]["ref"] = "develop"
        main_push = deepcopy(self.events["develop_push"])
        main_push["ref"] = "refs/heads/main"
        for github in (self.events["main_pull_request"], self.events["develop_push"],
                       develop_pr, main_push):
            with self.subTest(event=github["event_name"], ref=github.get("ref")):
                self.assertNotIn(job_id, self.allowed_skips(github))

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

    def test_molecule_workflow_changes_run_the_full_scenario_list(self):
        github = deepcopy(self.events["main_pull_request"])
        github["event"]["pull_request"]["base"]["ref"] = "develop"
        self.assert_full_matrix(
            self.matrix(
                github, '["default"]', "true", molecule_workflow="true",
            )
        )

    def test_lane_gated_develop_pr_only_skips_local_suites(self):
        for job_id in HEAVY_JOBS:
            condition = self.workflow["jobs"][job_id]["if"]
            self.assertIn("needs.lane.outputs.heavy_jobs != 'false'", condition, job_id)
            self.assertIn("needs.lane.outputs.tier != 'hot'", condition, job_id)

        molecule = self.workflow["jobs"]["molecule"]
        molecule_needs = molecule["needs"] if isinstance(molecule["needs"], list) else [molecule["needs"]]
        self.assertIn("changes", molecule_needs)
        self.assertIn("needs.changes.outputs.molecule_scenarios", molecule["with"]["scenarios"])

        develop_pr = deepcopy(self.events["main_pull_request"])
        develop_pr["event"]["pull_request"]["base"]["ref"] = "develop"
        merge_group = deepcopy(self.events["develop_push"])
        merge_group["event_name"] = "merge_group"
        for job_id in HEAVY_JOBS:
            with self.subTest(job=job_id, lane="closed"):
                self.assertFalse(
                    self.expression(
                        self.workflow["jobs"][job_id]["if"], develop_pr,
                        scenarios='["default"]', relevant="true", heavy_jobs="false",
                    )
                )

        for job_id in HEAVY_JOBS - {"e2e"}:
            with self.subTest(job=job_id, lane="open"):
                self.assertTrue(
                    self.expression(
                        self.workflow["jobs"][job_id]["if"], develop_pr,
                        scenarios='["default"]', relevant="true",
                    )
                )

        for job_id in HEAVY_JOBS - {"e2e"}:
            with self.subTest(job=job_id, tier="hot", event="merge_group"):
                self.assertTrue(
                    self.expression(
                        self.workflow["jobs"][job_id]["if"], merge_group,
                        scenarios='["default"]', relevant="true", tier="hot",
                    )
                )
            with self.subTest(job=job_id, tier="hot", event="pull_request"):
                self.assertFalse(
                    self.expression(
                        self.workflow["jobs"][job_id]["if"], develop_pr,
                        scenarios='["default"]', relevant="true", tier="hot",
                    )
                )
            with self.subTest(job=job_id, tier="hot", event="preflight pull request"):
                self.assertTrue(
                    self.expression(
                        self.workflow["jobs"][job_id]["if"], develop_pr,
                        scenarios='["default"]', relevant="true", tier="hot",
                        labels=("preflight",),
                    )
                )

        main_push = deepcopy(self.events["develop_push"])
        main_push["ref"] = "refs/heads/main"
        for github in (self.events["main_pull_request"], main_push):
            for job_id in HEAVY_JOBS:
                with self.subTest(job=job_id, event=github["event_name"]):
                    self.assertTrue(
                        self.expression(
                            self.workflow["jobs"][job_id]["if"], github,
                            scenarios='["default"]', relevant="true",
                        )
                    )

        for job_id in HEAVY_JOBS:
            with self.subTest(job=job_id, event="push"):
                self.assertFalse(
                    self.expression(
                        self.workflow["jobs"][job_id]["if"], self.events["develop_push"],
                        scenarios='["default"]', relevant="true",
                    )
                )

        self.assertTrue(HEAVY_JOBS <= self.allowed_skips(develop_pr))
        self.assertNotIn("tiny", self.workflow["jobs"]["scope"].get("if", ""))
        self.assertNotIn("tiny", self.workflow["jobs"]["gate"].get("if", ""))

    def test_gate_waives_heavy_skips_only_outside_main_runs(self):
        develop_pr = deepcopy(self.events["main_pull_request"])
        develop_pr["event"]["pull_request"]["base"]["ref"] = "develop"
        merge_group = deepcopy(self.events["develop_push"])
        merge_group["event_name"] = "merge_group"
        for github in (develop_pr, merge_group, self.events["develop_push"]):
            with self.subTest(event=github["event_name"]):
                self.assertTrue(HEAVY_JOBS <= self.allowed_skips(github))

        main_push = deepcopy(self.events["develop_push"])
        main_push["ref"] = "refs/heads/main"
        self.assertEqual(self.allowed_skips(main_push), set())
        self.assertEqual(self.allowed_skips(self.events["main_pull_request"]), set())

    def test_main_push_runs_every_scenario(self):
        github = deepcopy(self.events["develop_push"])
        github["ref"] = "refs/heads/main"
        for scenarios in ("[]", "", '["default"]'):
            with self.subTest(scenarios=scenarios):
                self.assert_full_matrix(self.matrix(github, scenarios, "true"))

    def test_develop_push_starts_no_matrix(self):
        self.assertIsNone(self.matrix(self.events["develop_push"], '["default"]', "true"))

    def test_cancelled_promotion_does_not_start_a_matrix(self):
        self.assertIsNone(self.matrix(self.events["main_pull_request"], cancelled=True))

    def test_policy_test_and_fixture_are_covered_by_the_contract_classifier(self):
        filters = self.workflow["jobs"]["ci"]["with"]["molecule_contract_filters"]
        patterns = yaml.safe_load(filters)["contract_only"]
        for path in ("tests/test_ci_molecule_branch_policy.py",
                     "tests/ci_molecule_branch_policy/fixture.yml"):
            self.assertTrue(any(fnmatch.fnmatch(path, p.replace("**", "*")) for p in patterns), path)

    def test_changes_reuses_ci_filter_maps_by_yaml_alias(self):
        ci = self.workflow["jobs"]["ci"]
        changes = self.workflow["jobs"]["changes"]
        self.assertEqual(
            changes["uses"], "JacobPEvans/.github/.github/workflows/_ansible-changes.yml@v1"
        )
        for name in ("molecule_scenario_filters", "molecule_contract_filters"):
            self.assertIs(changes["with"][name], ci["with"][name])

    def test_contract_checkouts_disable_persisted_credentials(self):
        jobs = {
            "_data-contract.yml": "pytest-suite",
            "_inventory-contract.yml": "validate-inventory-schema",
            "_secrets-contract.yml": "verify-secrets-contract",
        }
        for filename, job_id in jobs.items():
            with self.subTest(workflow=filename, job=job_id):
                workflow = yaml.safe_load(
                    (WORKFLOW.parent / filename).read_text(encoding="utf-8")
                )
                checkouts = [
                    step for step in workflow["jobs"][job_id]["steps"]
                    if step.get("uses", "").startswith("actions/checkout@")
                ]
                self.assertTrue(checkouts)
                for step in checkouts:
                    self.assertIs(step.get("with", {}).get("persist-credentials"), False)


if __name__ == "__main__":
    unittest.main()
