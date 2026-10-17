"""Controller-side Cribl pack staging must complete during check-mode runs."""

from pathlib import Path
import unittest

import yaml


REPO = Path(__file__).resolve().parents[1]
DEPLOY_TASKS = "roles/agent_sandbox/tasks/main/deploy.yml"
FETCH_TASK = "Fetch session-log pack .crbl to controller"
REMOVE_TASK = "Remove pack staging files from controller"


class AgentSandboxCriblPackCheckMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = yaml.safe_load((REPO / DEPLOY_TASKS).read_text(encoding="utf-8"))

    def test_pack_download_runs_on_controller_in_check_mode(self):
        task = next((task for task in self.tasks if task.get("name") == FETCH_TASK), None)

        self.assertIsNotNone(task, f"Task not found: {FETCH_TASK}")
        self.assertIn("ansible.builtin.get_url", task)
        self.assertEqual(task.get("delegate_to"), "localhost")
        self.assertIs(task.get("check_mode"), False)

    def test_staging_files_are_removed_on_controller_in_check_mode(self):
        task = next((task for task in self.tasks if task.get("name") == REMOVE_TASK), None)

        self.assertIsNotNone(task, f"Task not found: {REMOVE_TASK}")
        self.assertEqual(task.get("ansible.builtin.file", {}).get("state"), "absent")
        self.assertEqual(task.get("delegate_to"), "localhost")
        self.assertIs(task.get("check_mode"), False)

    def test_managed_host_tasks_do_not_force_check_mode_off(self):
        for task in self.tasks:
            if task.get("check_mode") is False:
                with self.subTest(task=task.get("name")):
                    self.assertEqual(task.get("delegate_to"), "localhost")


if __name__ == "__main__":
    unittest.main()
