#!/usr/bin/env python3
"""ansible_managed is defined only while rendering a template file. A task
that references it (say, in copy content) fails at run time with
"'ansible_managed' is undefined", which neither lint nor syntax-check sees."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class NoAnsibleManagedInTasks(unittest.TestCase):
    def test_tasks_and_playbooks_do_not_reference_ansible_managed(self):
        files = list(ROOT.glob("roles/*/tasks/**/*.yml")) + list(ROOT.glob("playbooks/**/*.yml"))
        self.assertTrue(files)
        offenders = [str(f.relative_to(ROOT)) for f in files if "ansible_managed" in f.read_text()]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
