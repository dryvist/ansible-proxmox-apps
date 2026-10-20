"""Read-only HTTP probes consumed by later tasks run in check mode."""

from pathlib import Path
import unittest

import yaml


REPO = Path(__file__).resolve().parents[1]
PROBES = (
    (
        "roles/ssh_ca_trust/tasks/main.yml",
        "Fetch the CA public key from OpenBao",
    ),
    (
        "roles/technitium_install/tasks/main.yml",
        "Check if Technitium is already running",
    ),
)


class ReadProbesCheckMode(unittest.TestCase):
    def test_registered_read_probes_run_in_check_mode(self):
        for relative_path, task_name in PROBES:
            with self.subTest(task=task_name):
                tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
                task = next((task for task in tasks if task.get("name") == task_name), None)

                self.assertIsNotNone(task, f"Task not found: {task_name}")
                self.assertIn("ansible.builtin.uri", task)
                self.assertIs(task.get("check_mode"), False)


if __name__ == "__main__":
    unittest.main()
