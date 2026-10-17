"""Reviewed host-key pins must be materialized during check-mode runs."""

from pathlib import Path
import unittest

import yaml


REPO = Path(__file__).resolve().parents[1]
PIN_TASKS = (
    (
        "inventory/load_tofu/ssh_known_hosts.yml",
        "Pin reviewed inventory host keys in the wrapper-managed known_hosts",
    ),
    (
        "inventory/load_tofu/pin_node_host_keys.yml",
        "Pin reviewed Proxmox node host keys in the wrapper-managed known_hosts",
    ),
)


class InventoryKnownHostsCheckMode(unittest.TestCase):
    def test_pins_write_the_per_run_file_in_check_mode(self):
        for relative_path, task_name in PIN_TASKS:
            with self.subTest(task=task_name):
                tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
                task = next((task for task in tasks if task.get("name") == task_name), None)
                self.assertIs(task.get("check_mode") if task else None, False)


if __name__ == "__main__":
    unittest.main()
