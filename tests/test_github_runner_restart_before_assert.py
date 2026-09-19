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


if __name__ == "__main__":
    unittest.main()
