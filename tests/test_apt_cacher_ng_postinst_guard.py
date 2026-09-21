#!/usr/bin/env python3
"""A fresh install must not let the vendor postinst start the service.

Debian's apt-cacher-ng postinst calls invoke-rc.d to start the service
immediately after unpacking, using whatever default acng.conf ships in the
.deb -- before this role's own "Deploy apt-cacher-ng configuration" task
overwrites it. On a guest where the package has never been installed before,
that vendor-default first start can fail and abort the whole apt transaction
(dpkg exits 1, package left half-configured) even though the role's own
config works fine once deployed. Every previously-converged host in this
fleet already had the package installed (a no-op "Install" task, no postinst
re-run), so this ordering bug was never exercised until the first genuinely
new apt-cacher-ng-tagged guest.

policy-rc.d is the standard Debian mechanism for deferring service actions
during package operations: invoke-rc.d consults it, systemctl/the systemd
module do not. Guarding the Install task with it removes the vendor-config
first start from the picture entirely.

This test renders tasks/main.yml and checks the guard is written before
Install, exits 101, and is removed again right after -- so it protects only
the package transaction, not the role's own explicit `Enable` task.
"""

import unittest
from pathlib import Path

import yaml

ROLE = Path(__file__).resolve().parent.parent / "roles" / "apt_cacher_ng"
GUARD_PATH = "/usr/sbin/policy-rc.d"


def _tasks():
    return yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())


def _names(tasks):
    return [t.get("name") for t in tasks]


class AptCacherNgPostinstGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = _tasks()
        cls.names = _names(cls.tasks)

    def test_install_is_bracketed_by_a_policy_rc_d_guard(self):
        install_idx = self.names.index("Install apt-cacher-ng package")
        write_idx = next(
            i
            for i, t in enumerate(self.tasks)
            if t.get("ansible.builtin.copy", {}).get("dest") == GUARD_PATH
        )
        remove_idx = next(
            i
            for i, t in enumerate(self.tasks)
            if t.get("ansible.builtin.file", {}).get("path") == GUARD_PATH
            and t.get("ansible.builtin.file", {}).get("state") == "absent"
        )
        self.assertLess(
            write_idx, install_idx, "policy-rc.d guard must be written before Install"
        )
        self.assertGreater(
            remove_idx, install_idx, "policy-rc.d guard must be removed after Install"
        )

    def test_guard_content_blocks_every_service_action(self):
        task = next(
            t
            for t in self.tasks
            if t.get("ansible.builtin.copy", {}).get("dest") == GUARD_PATH
        )["ansible.builtin.copy"]
        self.assertIn("exit 101", task["content"])
        self.assertEqual(task["mode"], "0755")


if __name__ == "__main__":
    unittest.main()
