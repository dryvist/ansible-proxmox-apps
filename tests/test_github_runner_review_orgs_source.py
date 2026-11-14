"""Runner review pools come only from the env document key, never public inventory."""

from pathlib import Path
import re
import unittest

import yaml

from app_agent_helpers import _render, _task


ROOT = Path(__file__).resolve().parents[1]
DOCKER_VMS = ROOT / "inventory" / "group_vars" / "docker_vms.yml"
LOAD_PLAY = ROOT / "playbooks" / "site" / "00-load-and-telemetry.yml"
POOLS = [{"org": "example-org", "replicas": 1, "group": "example-group"}]


def _expression(name="github_runner_review_orgs"):
    return yaml.safe_load(DOCKER_VMS.read_text(encoding="utf-8"))[name]


def _with_doc(doc):
    return _render(_expression(), {"hostvars": {"localhost": {"openbao_platform_env_doc": doc}}})


def _kept_keys():
    plays = yaml.safe_load(LOAD_PLAY.read_text(encoding="utf-8"))
    keep = next(
        _task(play["tasks"], name)
        for play in plays
        for name in [t.get("name", "") for t in play.get("tasks", [])]
        if name.startswith("Keep AppRole pairs")
    )
    return keep["vars"]["_kept_keys"].strip()


def _owners_after_load(raw_doc):
    """Filter the raw env document the way the load play does, then render."""
    kept = {k: v for k, v in raw_doc.items() if re.match(_kept_keys(), k)}
    return _render(
        _expression("github_runner_register_owners"),
        {"hostvars": {"localhost": {"openbao_platform_env_doc": kept}}},
    )


class RunnerReviewOrgsSource(unittest.TestCase):
    def test_unset_key_or_missing_document_gives_no_pools(self):
        self.assertEqual(_with_doc({}), [])
        self.assertEqual(_with_doc({"GITHUB_RUNNER_REVIEW_ORGS": ""}), [])
        self.assertEqual(_render(_expression(), {"hostvars": {"localhost": {}}}), [])

    def test_json_list_in_the_env_document_becomes_the_pool_list(self):
        self.assertEqual(_with_doc({"GITHUB_RUNNER_REVIEW_ORGS": '[{"org": "example-org", '
                                    '"replicas": 1, "group": "example-group"}]'}), POOLS)
        self.assertEqual(_with_doc({"GITHUB_RUNNER_REVIEW_ORGS": POOLS}), POOLS)

    def test_load_play_keeps_the_key_from_the_env_document(self):
        plays = yaml.safe_load(LOAD_PLAY.read_text(encoding="utf-8"))
        keep = next(
            _task(play["tasks"], name)
            for play in plays
            for name in [t.get("name", "") for t in play.get("tasks", [])]
            if name.startswith("Keep AppRole pairs")
        )
        pattern = keep["vars"]["_kept_keys"].strip()
        self.assertRegex("GITHUB_RUNNER_REVIEW_ORGS", pattern)
        self.assertIsNone(re.match(pattern, "GITHUB_RUNNER_REVIEW_ORGS_EXTRA"))

    def test_register_owners_survive_the_load_play(self):
        raw = {"OPENBAO_GITHUB_RUNNER_REGISTER_OWNERS": " example-org, example-other ",
               "UNRELATED_KEY": "dropped"}
        self.assertEqual(_owners_after_load(raw), ["example-org", "example-other"])
        self.assertIsNone(re.match(_kept_keys(), "OPENBAO_GITHUB_RUNNER_REGISTER_OWNERS_EXTRA"))

    def test_unset_register_owners_gives_an_empty_list(self):
        self.assertEqual(_owners_after_load({}), [])
        self.assertEqual(_owners_after_load({"OPENBAO_GITHUB_RUNNER_REGISTER_OWNERS": ""}), [])


if __name__ == "__main__":
    unittest.main()
