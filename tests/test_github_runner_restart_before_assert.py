# Copyright (c) 2026 JacobPEvans
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""The runner pool restart is applied before the pool is judged.

A failed assert ends the play for that host, and handlers only flush at the
end of a play that reaches it. With the pool-health assert ahead of the
restart handler, a unit file change on a host whose pool happened to be
between jobs at read time was never applied -- on that converge or any later
one, each failing the same assert.
"""

from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "roles/github_runner/tasks/main.yml"


def _tasks():
    return yaml.safe_load(MAIN.read_text(encoding="utf-8"))


class RestartAppliedBeforeTheAssert(unittest.TestCase):
    def test_handlers_flush_before_the_pool_assert(self):
        names = [t.get("name", "") for t in _tasks()]
        flush = next(
            i
            for i, t in enumerate(_tasks())
            if t.get("ansible.builtin.meta") == "flush_handlers"
            and i < names.index("Assert every pooled runner unit is running")
        )
        self.assertLess(flush, names.index("Re-read the installed services"))

    def test_the_re_read_waits_out_an_ephemeral_restart_gap(self):
        task = next(t for t in _tasks() if t.get("name") == "Re-read the installed services")
        self.assertIn("until", task)
        self.assertGreaterEqual(int(task["retries"]) * int(task["delay"]), 30)
        self.assertIs(task.get("failed_when"), False)


class ZeroReplicasRetiresTheHost(unittest.TestCase):
    """A host declared with zero replicas stops its units and agent and ends
    there; nothing later in the role (input asserts, agent, token wait) runs."""

    def test_the_retire_block_precedes_the_input_assert_and_ends_the_host(self):
        tasks = _tasks()
        retire = tasks[0]
        self.assertEqual(retire["when"], "github_runner_replicas | int == 0")
        inner = retire["block"]
        self.assertEqual(inner[-1]["ansible.builtin.meta"], "end_host")
        stop = next(t for t in inner if "ansible.builtin.systemd" in t)
        self.assertEqual(stop["ansible.builtin.systemd"]["state"], "stopped")
        self.assertIn("openbao-github-runner-agent", stop["loop"])
        self.assertIn(
            "Validate the native organization runner pool",
            [t.get("name") for t in tasks[1:]],
        )

    def test_the_management_plane_guest_declares_zero_replicas(self):
        host_vars = yaml.safe_load(
            (ROOT / "inventory/host_vars/iac-platform.yml").read_text(encoding="utf-8")
        )
        self.assertEqual(host_vars["github_runner_replicas"], 0)


if __name__ == "__main__":
    unittest.main()
