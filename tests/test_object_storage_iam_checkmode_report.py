"""Check mode must report the IAM writes it would otherwise skip.

iam_provision_bucket_role.yml reads the current canned policy, decides
idempotently whether it differs, and skips its three mutating commands in
check mode without reporting anything. The dedicated debug task must fire
in check mode instead, marking the run changed and naming only the
bucket/role it would have written.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROVISION_TASKS = ROOT / "roles" / "object_storage" / "tasks" / "iam_provision_bucket_role.yml"
REPORT_TASK = "Report write policy, create user and attach policy (check mode)"
WRITE_TASK = "Write the bucket-scoped policy (write-if-changed)"


def _provision_tasks():
    return yaml.safe_load(PROVISION_TASKS.read_text(encoding="utf-8"))


class CheckModeReport(unittest.TestCase):
    def test_check_mode_report_precedes_the_policy_write_and_reports_changed(self):
        tasks = _provision_tasks()
        report = next(task for task in tasks if task.get("name") == REPORT_TASK)
        write = next(task for task in tasks if task.get("name") == WRITE_TASK)

        self.assertIn("ansible.builtin.debug", report)
        self.assertIs(report["changed_when"], True)
        when = report["when"]
        when = [when] if isinstance(when, str) else list(when)
        self.assertIn("object_storage_iam_policy_differs", when)
        self.assertIn("ansible_check_mode", when)
        self.assertLess(tasks.index(report), tasks.index(write))


if __name__ == "__main__":
    unittest.main()
