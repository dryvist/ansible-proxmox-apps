"""Check-mode behavior for pinned Grafana community dashboard downloads."""

from pathlib import Path
import unittest

import yaml


REPO = Path(__file__).resolve().parents[1]
TASKS = "roles/grafana_stack/tasks/main.yml"
PREVIEW_TASK = "Preview pinned community dashboard downloads"
DOWNLOAD_TASK = "Fetch pinned community dashboards from grafana.com"
REPLACE_TASK = "Point the community dashboards at the provisioned datasource"


class GrafanaStackDashboardCheckMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = yaml.safe_load((REPO / TASKS).read_text(encoding="utf-8"))
        cls.tasks_by_name = {task["name"]: task for task in cls.tasks}

    def test_preview_reads_destinations_and_predicts_missing_files(self):
        task = self.tasks_by_name[PREVIEW_TASK]

        self.assertEqual(
            task["ansible.builtin.stat"]["path"],
            "{{ grafana_stack_data_dir }}/dashboards/{{ item.file }}",
        )
        self.assertIs(task.get("check_mode"), False)
        self.assertEqual(task.get("loop"), "{{ grafana_stack_community_dashboards }}")
        self.assertIn("ansible_check_mode", task["changed_when"])
        self.assertIn("not grafana_stack_community_dashboard_file.stat.exists", task["changed_when"])

    def test_download_keeps_real_run_force_and_skips_check_mode_network(self):
        task = self.tasks_by_name[DOWNLOAD_TASK]
        downloader = task["ansible.builtin.get_url"]

        self.assertEqual(
            downloader["url"],
            "https://grafana.com/api/dashboards/{{ item.id }}/revisions/{{ item.revision }}/download",
        )
        self.assertIs(downloader["force"], True)
        self.assertNotIn("check_mode", task)
        self.assertIn("not ansible_check_mode", task["when"])
        self.assertNotIn("failed_when", task)
        self.assertNotIn("ignore_errors", task)

    def test_replacement_skips_destinations_missing_during_check_mode(self):
        task = self.tasks_by_name[REPLACE_TASK]
        conditions = " ".join(task["when"])

        self.assertIn("not ansible_check_mode", conditions)
        self.assertIn("grafana_stack_community_dashboard_file.results", conditions)
        self.assertIn("selectattr('stat.exists')", conditions)


if __name__ == "__main__":
    unittest.main()
