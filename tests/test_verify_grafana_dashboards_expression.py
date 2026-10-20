"""Grafana timestamp assertions must remain valid Jinja expressions."""

from pathlib import Path
import unittest

import yaml


REPO = Path(__file__).resolve().parents[1]
PLAYBOOK = REPO / "playbooks" / "verify-grafana-dashboards.yml"
TASK_NAME = "Assert every non-nodata rule evaluated within the last 10 minutes"


class VerifyGrafanaDashboardsExpression(unittest.TestCase):
    def test_freshness_expression_contains_no_jinja_comment_tokens(self):
        plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
        tasks = [task for play in plays for task in play.get("tasks", [])]
        task = next(task for task in tasks if task.get("name") == TASK_NAME)
        expression = task["ansible.builtin.assert"]["that"]

        self.assertNotIn("#", expression)

    def test_read_only_api_calls_run_in_check_mode(self):
        plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
        tasks = [task for play in plays for task in play.get("tasks", [])]
        uri_tasks = [task for task in tasks if "ansible.builtin.uri" in task]

        self.assertTrue(uri_tasks)
        for task in uri_tasks:
            with self.subTest(task=task["name"]):
                self.assertIs(task.get("check_mode"), False)


if __name__ == "__main__":
    unittest.main()
