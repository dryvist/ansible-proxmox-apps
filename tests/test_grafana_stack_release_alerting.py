"""Alerting files deployed from the pinned grafana-dashboards release: one list, two consumers."""

from pathlib import Path
import re
import unittest

import jinja2
import yaml


REPO = Path(__file__).resolve().parents[1]
DEFAULTS = "roles/grafana_stack/defaults/main/00-core.yml"
TASKS = "roles/grafana_stack/tasks/provisioning.yml"
VERIFY = "playbooks/verify-grafana-dashboards.yml"
RELEASE_TASKS = "playbooks/tasks/verify_grafana_release_rules.yml"
LIST_VAR = "grafana_stack_release_alert_rule_files"
DEPLOY_TASK = (
    "Deploy the accelerator and spend alert rules and their critical Slack contact point "
    "from the pinned release"
)
EXPECTED_RULE_FILES = {
    "accelerator-underutilized.yml",
    "pay-per-token-spend.yml",
    "hermes-cron-jobs.yml",
    "runner-guest-blocked.yml",
    "tracker-exporter-health.yml",
    "postgres-resilience.yml",
}
CONTACT_POINT = "critical-slack-contact-point.yml"


def _load(path):
    return yaml.safe_load((REPO / path).read_text(encoding="utf-8"))


class GrafanaStackReleaseAlerting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.defaults = _load(DEFAULTS)
        cls.deploy = {task["name"]: task for task in _load(TASKS)}[DEPLOY_TASK]

    def test_the_role_default_lists_the_release_rule_files(self):
        self.assertEqual(set(self.defaults[LIST_VAR]), EXPECTED_RULE_FILES)

    def test_provisioning_builds_its_unpack_patterns_from_the_default(self):
        extra_opts = self.deploy["ansible.builtin.unarchive"]["extra_opts"]
        self.assertIsInstance(extra_opts, str)
        self.assertIn(LIST_VAR, extra_opts)
        env = jinja2.Environment()
        env.filters["regex_replace"] = lambda value, pattern, repl: re.sub(pattern, repl, value)
        rendered = yaml.safe_load(env.from_string(extra_opts).render({LIST_VAR: self.defaults[LIST_VAR]}))
        self.assertEqual(rendered[:2], ["--strip-components=3", "--wildcards"])
        self.assertEqual(
            set(rendered[2:]),
            {f"*/provisioning/alerting/{name}" for name in EXPECTED_RULE_FILES | {CONTACT_POINT}},
        )

    def test_the_verifier_reads_the_role_default_and_keeps_no_copy(self):
        play = next(p for p in _load(VERIFY) if p.get("name") == "Verify provisioned dashboards are loaded")
        self.assertIn("../roles/grafana_stack/defaults/main/00-core.yml", play["vars_files"])
        self.assertNotIn(LIST_VAR, play.get("vars", {}))
        self.assertIn("tasks/verify_grafana_release_rules.yml", (REPO / VERIFY).read_text(encoding="utf-8"))
        self.assertIn(LIST_VAR, (REPO / RELEASE_TASKS).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
