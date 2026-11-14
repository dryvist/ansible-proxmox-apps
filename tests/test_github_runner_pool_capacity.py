# Copyright (c) 2026 JacobPEvans
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""The pool capacity gate judges real declarations, not just syntax.

tasks/validate_pool_limits.yml sums every pool a host would run -- the
standard pool, each selected review pool, and the heavy pool when enabled --
and fails the converge when the totals exceed the host's own vCPUs and
memory minus the reserve. These tests run that task file through real
ansible-core against fixture playbooks, so an expression that stopped
evaluating (a filter renamed, a variable renamed away) fails here rather
than silently passing a structural check: an over-committed host must fail
with the summed numbers, and a fitting host must pass.
"""

from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "github_runner_pool_capacity"


def _run(fixture):
    return subprocess.run(
        ["ansible-playbook", str(fixture), "-c", "local"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


class PoolCapacityGate(unittest.TestCase):
    def test_an_over_committed_host_fails_with_the_numbers(self):
        proc = _run(FIXTURES / "overcommitted.yml")
        self.assertNotEqual(proc.returncode, 0)
        # 3x1.0 standard + 2x1.0 review (the default replica count) + 1x8.0
        # heavy CPUs, and 3x4g + 2x4g + 24g of memory, against a 4-vCPU /
        # 8 GiB host minus the reserve. The message must carry the totals it
        # computed, not just a generic failure.
        self.assertIn("need 13.0 CPUs and 45056.0 MB", proc.stdout + proc.stderr)

    def test_a_fitting_host_passes(self):
        proc = _run(FIXTURES / "fitting.yml")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
