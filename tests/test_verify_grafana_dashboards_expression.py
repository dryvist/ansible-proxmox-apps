"""Grafana timestamp assertions must remain valid Jinja expressions."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import subprocess
import tempfile
import unittest

import yaml


REPO = Path(__file__).resolve().parents[1]
PLAYBOOK = REPO / "playbooks" / "verify-grafana-dashboards.yml"
TASK_NAME = "Assert every non-nodata rule evaluated within the last 10 minutes"


def _freshness_expression():
    plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    tasks = [task for play in plays for task in play.get("tasks", [])]
    task = next(task for task in tasks if task.get("name") == TASK_NAME)
    return task["ansible.builtin.assert"]["that"]


class VerifyGrafanaDashboardsExpression(unittest.TestCase):
    def test_freshness_expression_contains_no_jinja_comment_tokens(self):
        self.assertNotIn("#", _freshness_expression())

    def test_freshness_expression_parses_every_grafana_timestamp_shape(self):
        recent = datetime.now(timezone.utc) - timedelta(minutes=1)
        stale = datetime.now(timezone.utc) - timedelta(minutes=20)
        cases = {
            "no fraction": (recent.strftime("%Y-%m-%dT%H:%M:%SZ"), True),
            "milliseconds": (recent.strftime("%Y-%m-%dT%H:%M:%S.123Z"), True),
            "nanoseconds": (recent.strftime("%Y-%m-%dT%H:%M:%S.123456789Z"), True),
            "stale": (stale.strftime("%Y-%m-%dT%H:%M:%S.5Z"), False),
        }
        # Evaluated as an assert conditional, as the playbook does: that path
        # unescapes string literals differently from a {{ }} template.
        play = [{
            "hosts": "localhost",
            "gather_facts": False,
            "tasks": [{
                "name": "Evaluate the freshness expression",
                "ansible.builtin.assert": {"that": _freshness_expression()},
                "vars": {"item": {"title": "rule"}},
            }],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "freshness.yml"
            fixture.write_text(yaml.safe_dump(play), encoding="utf-8")
            for label, (stamp, fresh) in cases.items():
                with self.subTest(label):
                    rules = [{"name": "rule", "lastEvaluation": stamp}]
                    run = subprocess.run(
                        ["ansible-playbook", str(fixture), "-i", "localhost,", "-c", "local",
                         "-e", json.dumps({"_evaluated_rules": rules})],
                        cwd=REPO, capture_output=True, text=True,
                    )
                    self.assertNotIn("filter plugin", run.stdout + run.stderr)
                    self.assertEqual(run.returncode == 0, fresh, run.stdout[-500:])

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
