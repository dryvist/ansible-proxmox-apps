# Copyright (c) 2026 JacobPEvans
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Contract for the standalone monthly Debian guest upgrade playbook."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLAYS = yaml.safe_load((ROOT / "playbooks/upgrade.yml").read_text(encoding="utf-8"))
SHARED = yaml.safe_load((ROOT / "playbooks/tasks/guest-os-upgrade.yml").read_text(encoding="utf-8"))


def _when(tasks, module):
    return [t.get("when", "") for t in tasks if module in t]


class MonthlyGuestUpgradeContract(unittest.TestCase):
    def test_brackets_the_run_and_guards_later_saturdays(self):
        self.assertEqual(PLAYS[1]["import_playbook"], "site/00-load-and-telemetry.yml")
        skip = PLAYS[2]["tasks"][0]["ansible.builtin.set_fact"]["guest_os_upgrade_skip"]
        self.assertIn("now(utc=true, fmt='%w') == '6'", skip)
        self.assertIn("| int > 7", skip)

    def test_targets_and_batch_sizes(self):
        lxc, vm, plane = PLAYS[3:6]
        for play in (lxc, vm):
            self.assertIn("!windows_group", play["hosts"])
            self.assertIn("!llm_vllm_group", play["hosts"])
        self.assertEqual(lxc["serial"], "25%")
        self.assertEqual(vm["serial"], 1)
        self.assertIn("inventory_hostname == plane_host", _when(vm["tasks"], "ansible.builtin.meta"))
        self.assertIn("inventory_hostname != plane_host", _when(plane["tasks"], "ansible.builtin.meta"))
        for play in (lxc, vm, plane):
            self.assertIn(
                "tasks/guest-os-upgrade.yml",
                [t.get("ansible.builtin.import_tasks") for t in play["tasks"]],
            )

    def test_shared_steps_skip_unowned_hosts_then_upgrade(self):
        skip = SHARED[0]
        self.assertIn("guest_os_upgrade_skip", skip["when"])
        self.assertEqual(len(skip["block"]), 2)
        self.assertIn("ansible.builtin.debug", skip["block"][0])
        self.assertEqual(skip["block"][1].get("ansible.builtin.meta"), "end_host")
        ends = _when(SHARED[1:], "ansible.builtin.meta")
        self.assertIn("ansible_facts.os_family != 'Debian'", ends)
        self.assertIn("guest_os_upgrade_nvidia_driver.stat.exists", ends)
        apt = next(t for t in SHARED if "ansible.builtin.apt" in t)
        self.assertEqual(apt["ansible.builtin.apt"]["upgrade"], "dist")

    def test_only_vms_reboot_and_the_plane_reboot_is_deferred(self):
        lxc, vm, plane = PLAYS[3:6]
        self.assertFalse(any("ansible.builtin.reboot" in t for t in lxc["tasks"]))
        self.assertTrue(any("ansible.builtin.reboot" in t for t in vm["tasks"]))
        shutdown = next(t for t in plane["tasks"] if "ansible.builtin.command" in t)
        self.assertEqual(shutdown["ansible.builtin.command"]["cmd"], "shutdown -r +2")


if __name__ == "__main__":
    unittest.main()
