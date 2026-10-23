#!/usr/bin/env python3
"""Every in-repo OpenBao domain is published on both host paths."""

from pathlib import Path
import unittest

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DOMAIN_GROUPS_FILE = (
    REPO_ROOT / "playbooks" / "site" / "vars" / "openbao_secrets_domain_groups.yml"
)
PUBLISH_TASK_FILE = REPO_ROOT / "playbooks" / "tasks" / "publish_secret_domain_facts.yml"
PUBLISH_TASK_NAMES = (
    "Publish each domain's merged secrets to application hosts",
    "Publish empty secret-domain facts to sandbox hosts",
)

# clickhouse is consumed outside this repo by the AI repository.
DOMAIN_PUBLISH_EXEMPTIONS = {"clickhouse"}


def _published_facts() -> dict[str, dict]:
    tasks = yaml.safe_load(PUBLISH_TASK_FILE.read_text())
    return {
        task_name: next(
            task["ansible.builtin.set_fact"]
            for task in tasks
            if task.get("name") == task_name
        )
        for task_name in PUBLISH_TASK_NAMES
    }


class TestSecretDomainPublishCoverage(unittest.TestCase):
    def test_every_in_repo_secret_domain_has_a_published_fact_on_both_host_paths(self):
        domain_groups = yaml.safe_load(DOMAIN_GROUPS_FILE.read_text())[
            "openbao_secrets_domain_groups"
        ]
        expected_facts = {
            f"bao_{domain.replace('-', '_')}_secrets"
            for domain in domain_groups
            if domain not in DOMAIN_PUBLISH_EXEMPTIONS
        }

        for task_name, facts in _published_facts().items():
            missing_facts = expected_facts - facts.keys()
            self.assertFalse(
                missing_facts,
                f"{task_name!r} does not publish the fact(s) for domain(s) "
                f"{sorted(missing_facts)}",
            )


if __name__ == "__main__":
    unittest.main()
