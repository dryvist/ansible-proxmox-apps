# Copyright (c) 2026 JacobPEvans
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Contract for the standalone monthly Debian guest upgrade playbook."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = "playbooks/upgrade.yml"


def _plays():
    return yaml.safe_load((ROOT / PLAYBOOK).read_text(encoding="utf-8"))


def _tasks(play):
    return play.get("pre_tasks", []) + play.get("tasks", [])


class MonthlyGuestUpgradeContract(unittest.TestCase):
    def test_imports_inventory_and_brackets_the_run(self):
        plays = _plays()
        self.assertEqual(plays[0].get("import_playbook"), "site/budget-gate.yml")
        self.assertEqual(plays[1].get("import_playbook"), "site/00-load-and-telemetry.yml")
        self.assertEqual(plays[-1].get("import_playbook"), "site/budget-gate.yml")

    def test_guard_skips_only_later_saturdays_in_utc_and_is_visible(self):
        guard = _plays()[2]
        self.assertEqual(guard["hosts"], "localhost")
        self.assertIs(guard["become"], False)
        tasks = guard["tasks"]
        utc_fact = next(t for t in tasks if "guest_os_upgrade_utc_date" in t.get("ansible.builtin.set_fact", {}))
        self.assertIn("now(utc=true", utc_fact["ansible.builtin.set_fact"]["guest_os_upgrade_utc_date"])
        skip_fact = next(t for t in tasks if "guest_os_upgrade_skip" in t.get("ansible.builtin.set_fact", {}))
        condition = skip_fact["ansible.builtin.set_fact"]["guest_os_upgrade_skip"]
        self.assertIn("== '6'", condition)
        self.assertIn("> 7", condition)
        self.assertTrue(any(t.get("ansible.builtin.debug") and t.get("when") == "guest_os_upgrade_skip" for t in tasks))

    def test_targets_exclusions_and_batch_sizes(self):
        lxc, vm, plane = _plays()[3:6]
        for play in (lxc, vm, plane):
            self.assertTrue(any(t.get("ansible.builtin.meta") == "end_play" and "guest_os_upgrade_skip" in t.get("when", "") for t in play["pre_tasks"]))
        for play in (lxc, vm):
            self.assertIn("!windows_group", play["hosts"])
            self.assertIn("!llm_vllm_group", play["hosts"])
        self.assertEqual(lxc["serial"], "25%")
        self.assertEqual(vm["serial"], 1)
        self.assertTrue(any(t.get("ansible.builtin.meta") == "end_host" and t.get("when") == "inventory_hostname == plane_host" for t in _tasks(vm)))
        self.assertEqual(plane["hosts"], "docker_vms")
        self.assertTrue(any(t.get("ansible.builtin.meta") == "end_host" and t.get("when") == "inventory_hostname != plane_host" for t in plane["pre_tasks"]))
        for play in (lxc, vm, plane):
            self.assertTrue(any(t.get("ansible.builtin.meta") == "end_host" and "ansible_facts.os_family != 'Debian'" in t.get("when", "") for t in _tasks(play)))
            self.assertTrue(any(t.get("ansible.builtin.stat", {}).get("path") == "/proc/driver/nvidia/version" for t in _tasks(play)))

    def test_all_plays_patch_through_apt_recovery_and_plane_reboot_is_deferred(self):
        lxc, vm, plane = _plays()[3:6]
        for play in (lxc, vm, plane):
            tasks = _tasks(play)
            self.assertTrue(any(t.get("ansible.builtin.import_role", {}).get("name") == "apt_recovery" for t in tasks))
            apt = next(t["ansible.builtin.apt"] for t in tasks if "ansible.builtin.apt" in t)
            self.assertEqual(apt, {"update_cache": True, "upgrade": "dist", "autoremove": True})
            self.assertEqual(next(t["environment"] for t in tasks if "ansible.builtin.apt" in t), {"DEBIAN_FRONTEND": "noninteractive"})
        self.assertTrue(any("ansible.builtin.reboot" in t for t in _tasks(vm)))
        shutdown = next(t for t in _tasks(plane) if "ansible.builtin.command" in t)
        self.assertEqual(shutdown["ansible.builtin.command"]["cmd"], "shutdown -r +2")
        self.assertIs(shutdown["changed_when"], True)


if __name__ == "__main__":
    unittest.main()
