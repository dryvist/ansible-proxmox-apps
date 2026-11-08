"""Alerting files deployed from the pinned grafana-dashboards release."""

from pathlib import Path
import unittest

import yaml


REPO = Path(__file__).resolve().parents[1]
TASKS = "roles/grafana_stack/tasks/provisioning.yml"
DEPLOY_TASK = (
    "Deploy the accelerator and spend alert rules and their critical Slack contact point "
    "from the pinned release"
)
EXPECTED = {
    "accelerator-underutilized.yml",
    "pay-per-token-spend.yml",
    "critical-slack-contact-point.yml",
}


class GrafanaStackReleaseAlerting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tasks = yaml.safe_load((REPO / TASKS).read_text(encoding="utf-8"))
        cls.tasks_by_name = {task["name"]: task for task in tasks}

    def test_deploys_exactly_the_rules_and_their_contact_point(self):
        task = self.tasks_by_name[DEPLOY_TASK]
        patterns = [
            opt for opt in task["ansible.builtin.unarchive"]["extra_opts"] if opt.startswith("*/")
        ]
        self.assertEqual(len(patterns), len(EXPECTED))
        self.assertEqual({p.rsplit("/", 1)[-1] for p in patterns}, EXPECTED)
        for pattern in patterns:
            self.assertTrue(pattern.startswith("*/provisioning/alerting/"), pattern)


if __name__ == "__main__":
    unittest.main()
