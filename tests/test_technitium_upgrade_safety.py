"""Contract for checksum preflight and recovery around Technitium upgrades."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "technitium_install"


def _task(tasks, name):
    return next(task for task in tasks if task.get("name") == name)


class TechnitiumUpgradeSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))
        cls.upgrade = yaml.safe_load((ROLE / "tasks" / "upgrade.yml").read_text(encoding="utf-8"))
        cls.download = yaml.safe_load((ROLE / "tasks" / "download_app.yml").read_text(encoding="utf-8"))

    def test_download_is_checksum_pinned_before_install_mutates_the_host(self):
        preflight = _task(self.main, "Download and verify the pinned Technitium app build before installation")
        install = _task(self.main, "Install Technitium DNS server (bare-metal from mirror)")
        names = [task["name"] for task in install["block"]]
        self.assertLess(self.main.index(preflight), self.main.index(install))
        self.assertEqual(preflight["ansible.builtin.include_tasks"], "download_app.yml")
        self.assertEqual(names[0], "Deploy the pinned Technitium app build")
        self.assertIn("checksum", self.download[0]["ansible.builtin.get_url"])

    def test_upgrade_download_is_first_and_precedes_the_stop(self):
        upgrade_include = _task(self.main, "Upgrade Technitium DNS server to the pinned version")
        self.assertEqual(upgrade_include["ansible.builtin.include_tasks"], "upgrade.yml")
        self.assertEqual(
            upgrade_include["when"],
            [
                "technitium_install_check.status != -1",
                "(technitium_install_session.json.info.version | default('', true)) != "
                "(technitium_install_app_version_clean | trim)",
            ],
        )

        upgrade = _task(self.upgrade, "Upgrade Technitium DNS server to the pinned version")
        block = upgrade["block"]
        preflight = block[0]
        stop = _task(block, "Stop dns.service before swapping the app binaries")
        self.assertEqual(preflight["ansible.builtin.include_tasks"], "download_app.yml")
        self.assertLess(block.index(preflight), block.index(stop))
        self.assertIn("checksum", self.download[0]["ansible.builtin.get_url"])
        self.assertEqual(stop["ansible.builtin.systemd_service"]["state"], "stopped")

    def test_archive_and_rescue_restore_use_the_same_backup_list(self):
        upgrade = _task(self.upgrade, "Upgrade Technitium DNS server to the pinned version")
        backup_list = "{{ technitium_install_upgrade_backups }}"
        backups = upgrade["vars"]["technitium_install_upgrade_backups"]
        self.assertEqual(len(backups), 2)
        self.assertEqual(
            [backup["path"] for backup in backups],
            ["{{ technitium_install_app_dir }}/dns", "{{ technitium_install_data_dir }}"],
        )
        for backup, prefix in zip(backups, ("dns-app-", "dns-data-")):
            self.assertIn(prefix, backup["archive"])
            self.assertIn("technitium_install_session.json.info.version", backup["archive"])
            self.assertIn("ansible_facts.date_time.epoch", backup["archive"])

        block = upgrade["block"]
        archives = [task for task in block if "community.general.archive" in task]
        self.assertEqual(len(archives), 1)
        archive = archives[0]
        self.assertEqual(archive["community.general.archive"]["path"], "{{ item.path }}")
        self.assertEqual(archive["community.general.archive"]["dest"], "{{ item.archive }}")
        self.assertEqual(archive["loop"], backup_list)
        self.assertEqual(archive["register"], "technitium_install_upgrade_backup")
        names = [task.get("name") for task in block]
        self.assertEqual(
            names[:5],
            [
                "Download and verify the pinned Technitium app build before upgrade",
                "Ensure the backup directory exists",
                "Stop dns.service before swapping the app binaries",
                "Back up the existing Technitium app build and data for rollback",
                "Deploy the pinned Technitium app build",
            ],
        )

        remove, restore, start, fail = upgrade["rescue"]
        self.assertEqual(remove["ansible.builtin.file"]["path"], "{{ item.path }}")
        self.assertEqual(remove["ansible.builtin.file"]["state"], "absent")
        self.assertEqual(remove["loop"], backup_list)
        self.assertEqual(restore["ansible.builtin.unarchive"]["src"], "{{ item.archive }}")
        self.assertEqual(restore["ansible.builtin.unarchive"]["dest"], "{{ item.path | dirname }}")
        self.assertIs(restore["ansible.builtin.unarchive"]["remote_src"], True)
        self.assertEqual(restore["loop"], backup_list)
        self.assertEqual(restore["when"], remove["when"])
        self.assertEqual(start["ansible.builtin.systemd_service"]["state"], "started")
        self.assertEqual(
            fail["ansible.builtin.fail"]["msg"],
            "Technitium upgrade failed at '{{ ansible_failed_task.name }}'; restored the "
            "pre-upgrade build and data when they were archived, and started dns.service.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
