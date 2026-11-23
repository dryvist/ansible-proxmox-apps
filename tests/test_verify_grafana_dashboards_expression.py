"""Grafana timestamp assertions must remain valid Jinja expressions."""

from datetime import datetime, timedelta, timezone
import base64
from pathlib import Path
import json
import subprocess
import tempfile
import unittest

import yaml


REPO = Path(__file__).resolve().parents[1]
PLAYBOOK = REPO / "playbooks" / "verify-grafana-dashboards.yml"
RELEASE_TASKS = REPO / "playbooks" / "tasks" / "verify_grafana_release_rules.yml"
TASK_NAME = "Assert every non-nodata rule evaluated within the last 10 minutes"
RELEASE_DERIVATION_TASK = "Derive alert rules from the pinned release files"
FIRING_SUMMARY_TASK = "Count firing alert instances per ruler group"


def _freshness_expression():
    plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
    tasks = [task for play in plays for task in play.get("tasks", [])]
    task = next(task for task in tasks if task.get("name") == TASK_NAME)
    return task["ansible.builtin.assert"]["that"]


def _fact_expression(task_name, fact_name):
    tasks = yaml.safe_load(RELEASE_TASKS.read_text(encoding="utf-8"))
    task = next(task for task in tasks if task.get("name") == task_name)
    return task["ansible.builtin.set_fact"][fact_name]


def _run_fact_contract(assertions, variables):
    play = [{
        "hosts": "localhost",
        "gather_facts": False,
        "vars": variables,
        "tasks": [
            {
                "name": "Evaluate production expressions",
                "ansible.builtin.set_fact": {
                    "_release_alert_rules": _fact_expression(
                        RELEASE_DERIVATION_TASK, "_release_alert_rules"
                    ),
                    "_release_alert_firing_summary": _fact_expression(
                        FIRING_SUMMARY_TASK, "_release_alert_firing_summary"
                    ),
                },
            },
            {"name": "Check fixture contract", "ansible.builtin.assert": {"that": assertions}},
        ],
    }]
    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "grafana-release-contract.yml"
        fixture.write_text(yaml.safe_dump(play), encoding="utf-8")
        return subprocess.run(
            ["ansible-playbook", str(fixture), "-i", "localhost,", "-c", "local"],
            cwd=REPO, capture_output=True, text=True,
        )


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

    def test_release_rule_derivation_and_firing_summary_on_fixtures(self):
        release_file = {
            "groups": [{
                "name": "Pinned release group",
                "rules": [{
                    "uid": "release-rule-1",
                    "title": "Example alert",
                    "for": "5m",
                    "data": [
                        {"refId": "B", "model": {"expr": "ignored expression"}},
                        {"refId": "A", "model": {"expr": "up == 0"}},
                    ],
                }],
            }],
        }
        encoded_release_file = base64.b64encode(
            yaml.safe_dump(release_file).encode("utf-8")
        ).decode("ascii")
        ruler_groups = [
            {
                "name": "critical",
                "rules": [{"alerts": [
                    {"state": "Alerting"},
                    {"state": "FIRING"},
                    {"state": "Pending"},
                    {"state": "Normal"},
                    {"state": "NoData"},
                    {"state": "Error"},
                    {},
                    {"state": ""},
                ]}],
            },
            {"name": "warning", "rules": [{"alerts": [{"state": "Firing"}]}]},
            {"name": "empty-missing-alerts", "rules": [{}]},
            {"name": "empty-rules"},
            *[{"name": f"quiet-{index}", "rules": []} for index in range(10)],
        ]
        expected_release_rules = [{
            "uid": "release-rule-1",
            "group": "Pinned release group",
            "title": "Example alert",
            "for": "5m",
            "expr": "up == 0",
        }]
        expected_groups = [
            "critical", "warning", "empty-missing-alerts", "empty-rules",
            *[f"quiet-{index}" for index in range(6)],
        ]
        expected_firing_summary = [
            {"group": group, "firing": count}
            for group, count in zip(expected_groups, [2, 1, *([0] * 8)])
        ]
        result = _run_fact_contract(
            [
                "_release_alert_rules == expected_release_rules",
                "_release_alert_firing_summary == expected_firing_summary",
            ],
            {
                "_release_alert_rule_file_reads": {"results": [{"content": encoded_release_file}]},
                "_rule_health": {"json": {"data": {"groups": ruler_groups}}},
                "expected_release_rules": expected_release_rules,
                "expected_firing_summary": expected_firing_summary,
            },
        )
        self.assertEqual(result.returncode, 0, result.stdout[-1000:] + result.stderr[-1000:])


if __name__ == "__main__":
    unittest.main()
