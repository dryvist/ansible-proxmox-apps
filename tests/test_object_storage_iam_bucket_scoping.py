"""Every bucket in object_storage_default_buckets must get both an ro and an
rw RustFS IAM user/policy, and no rendered bucket policy may name a Resource
ARN for any OTHER bucket.

Two failure classes this guards against, both silent at converge time
because loop-rendered YAML never asserts its own output:
  1. A bucket added to object_storage_default_buckets is silently skipped
     because iam.yml/iam_bucket.yml grew a second, hand-maintained bucket or
     role list instead of deriving from the real ones.
  2. rustfs-iam-policy.json.j2 hardcodes a bucket name (copy-paste from
     testing against one bucket) instead of using the loop variable, so
     every bucket's policy silently grants access to the SAME bucket -- the
     exact one-bucket-per-workload isolation this feature exists to provide.

Renders the REAL lookup expression out of iam_provision_bucket_role.yml with
the REAL template file, never a reimplementation of either.
"""

import json
import unittest
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "object_storage"
DEFAULTS = ROLE / "defaults" / "main.yml"
PROVISION_TASKS = ROLE / "tasks" / "iam_provision_bucket_role.yml"
RENDER_TASK = "Render the bucket-scoped policy for this role"


def _defaults():
    return yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))


def _bucket_names():
    return [b["name"] for b in _defaults()["object_storage_default_buckets"]]


def _policy_lookup_expr():
    for task in yaml.safe_load(PROVISION_TASKS.read_text(encoding="utf-8")):
        if task.get("name") == RENDER_TASK:
            return task["ansible.builtin.set_fact"]["object_storage_iam_policy_json"]
    raise AssertionError(f"task {RENDER_TASK!r} not found in {PROVISION_TASKS}")


def _render_policy(bucket, role, policy_actions):
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "object_storage_iam_bucket": bucket,
        "object_storage_iam_role": role,
        "object_storage_iam_policy_actions": policy_actions,
    }
    templar._loader.set_basedir(str(ROLE))
    rendered = templar.template(trust_as_template(_policy_lookup_expr()))
    return json.loads(rendered)


class BucketRoleDerivation(unittest.TestCase):
    """iam.yml / iam_bucket.yml must loop over the real lists, never a copy."""

    def test_both_roles_are_declared(self):
        self.assertEqual(_defaults()["object_storage_iam_roles"], ["ro", "rw"])

    def test_at_least_one_bucket_is_declared(self):
        self.assertTrue(_bucket_names(), "object_storage_default_buckets is empty")

    def test_iam_loops_over_the_real_bucket_list_not_a_copy(self):
        text = (ROLE / "tasks" / "iam.yml").read_text(encoding="utf-8")
        self.assertIn(
            "object_storage_default_buckets | map(attribute='name')",
            text,
            "iam.yml's bucket loop must derive from object_storage_default_buckets",
        )

    def test_iam_bucket_loops_over_the_real_role_list_not_a_copy(self):
        text = (ROLE / "tasks" / "iam_bucket.yml").read_text(encoding="utf-8")
        self.assertIn(
            "{{ object_storage_iam_roles }}",
            text,
            "iam_bucket.yml's role loop must derive from object_storage_iam_roles",
        )


class PolicyActionAsymmetry(unittest.TestCase):
    """rw must be able to write and delete; ro must never be able to."""

    def test_ro_excludes_write_and_delete(self):
        actions = _defaults()["object_storage_iam_policy_actions"]["ro"]
        self.assertNotIn("s3:PutObject", actions)
        self.assertNotIn("s3:DeleteObject", actions)

    def test_rw_includes_write_and_delete(self):
        actions = _defaults()["object_storage_iam_policy_actions"]["rw"]
        self.assertIn("s3:PutObject", actions)
        self.assertIn("s3:DeleteObject", actions)


class PolicyResourceScoping(unittest.TestCase):
    """Every declared bucket's rendered policy names ONLY that bucket."""

    def test_every_bucket_policy_resource_is_bucket_scoped(self):
        actions = _defaults()["object_storage_iam_policy_actions"]
        buckets = _bucket_names()
        self.assertGreaterEqual(
            len(buckets), 2, "need >= 2 buckets in fixtures to prove cross-bucket isolation"
        )
        for bucket in buckets:
            for role in ("ro", "rw"):
                with self.subTest(bucket=bucket, role=role):
                    policy = _render_policy(bucket, role, actions)
                    resources = policy["Statement"][0]["Resource"]
                    self.assertEqual(
                        resources,
                        [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
                    )
                    for other in buckets:
                        if other == bucket:
                            continue
                        self.assertNotIn(
                            other,
                            "".join(resources),
                            f"{bucket}/{role} policy leaks a reference to bucket {other!r}",
                        )


if __name__ == "__main__":
    unittest.main()
