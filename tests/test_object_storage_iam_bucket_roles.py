"""Per-bucket IAM selection and bucket-safety contracts."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "object_storage"
DEFAULTS = ROLE / "defaults" / "main" / "00-core.yml"
IAM = ROLE / "tasks" / "iam.yml"
BUCKET_IAM = ROLE / "tasks" / "iam_bucket.yml"
BUCKET_TASKS = ROLE / "tasks" / "main.yml"


def _task(tasks, name):
    for task in tasks:
        if task.get("name") == name:
            return task
        for key in ("block", "always", "rescue"):
            if key in task:
                try:
                    return _task(task[key], name)
                except AssertionError:
                    pass
    raise AssertionError(f"task {name!r} not found")


def _buckets():
    return yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))["object_storage_default_buckets"]


class BucketRoleSelection(unittest.TestCase):
    def test_terrakube_is_reader_only_without_bucket_settings(self):
        bucket = next(bucket for bucket in _buckets() if bucket["name"] == "terrakube")
        self.assertEqual(bucket["iam_roles"], ["ro"])
        self.assertFalse({"policy", "versioning"} & bucket.keys())

    def test_bucket_ensure_does_not_recreate_or_configure_terrakube(self):
        tasks = yaml.safe_load(BUCKET_TASKS.read_text(encoding="utf-8"))
        create = _task(tasks, "Create missing default buckets")
        self.assertEqual(create["when"], "item.rc != 0")
        self.assertIn("create-bucket", create["ansible.builtin.command"]["cmd"])
        self.assertIn("selectattr('versioning', 'defined')", _task(tasks, "Read current versioning status")["loop"])
        self.assertIn("selectattr('policy', 'defined')", _task(tasks, "Read current bucket policy")["loop"])
        commands = [task.get("ansible.builtin.command", {}).get("cmd", "") for task in tasks]
        self.assertFalse(any("delete-bucket" in cmd or "s3 rm" in cmd for cmd in commands))

    def test_iam_loops_over_bucket_configs_and_selected_roles(self):
        task = _task(yaml.safe_load(IAM.read_text(encoding="utf-8")), "Resolve each bucket's configured credentials")
        self.assertEqual(task["loop"], "{{ object_storage_default_buckets }}")
        self.assertEqual(task["loop_control"]["loop_var"], "object_storage_iam_bucket_config")
        bucket_iam = yaml.safe_load(BUCKET_IAM.read_text(encoding="utf-8"))[0]
        self.assertEqual(
            bucket_iam["loop"],
            "{{ object_storage_iam_bucket_config.iam_roles | default(object_storage_iam_roles) }}",
        )

    def test_only_terrakube_overrides_the_default_roles(self):
        roles = ["ro", "rw"]
        overrides = [bucket["name"] for bucket in _buckets() if bucket.get("iam_roles", roles) != roles]
        self.assertEqual(overrides, ["terrakube"])


if __name__ == "__main__":
    unittest.main()
