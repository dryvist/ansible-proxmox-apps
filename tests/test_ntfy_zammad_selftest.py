#!/usr/bin/env python3
"""Run the ntfy-zammad bridge's own --selftest in CI."""

import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "roles" / "ntfy_docker" / "files" / "ntfy-zammad.py"


class NtfyZammadSelftest(unittest.TestCase):
    def test_selftest_passes(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--selftest"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("selftest OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
