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


def _expression():
    return yaml.safe_load(DOCKER_VMS.read_text(encoding="utf-8"))["github_runner_review_orgs"]


def _with_doc(doc):
    return _render(_expression(), {"hostvars": {"localhost": {"openbao_platform_env_doc": doc}}})


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


if __name__ == "__main__":
    unittest.main()
