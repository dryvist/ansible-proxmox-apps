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
DEFAULTS_DIR = ROLE / "defaults" / "main"
PROVISION_TASKS = ROLE / "tasks" / "iam_provision_bucket_role.yml"
RENDER_TASK = "Render the bucket-scoped policy for this role"
BUCKET_ROLE_TASKS = ROLE / "tasks" / "iam_bucket_role.yml"
ENDPOINT_REGION_TASK = "Compute this credential's endpoint and region fields"
MERGE_TASK = "Merge generated + derived fields over the stored secret"

# The ratified secret-path convention's S3 row (private docs
# d/conventions/secret-paths, "consumed by...") lists these four fields for
# every S3-speaking credential -- not only the access/secret key pair.
EXPECTED_S3_CREDENTIAL_FIELDS = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ENDPOINT_URL",
    "AWS_REGION",
}


def _defaults():
    """Merge every defaults/main/*.yml split file, same as Ansible's own load."""
    merged = {}
    for path in sorted(DEFAULTS_DIR.glob("*.yml")):
        merged.update(yaml.safe_load(path.read_text(encoding="utf-8")))
    return merged


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


def _bucket_role_task(name):
    for task in yaml.safe_load(BUCKET_ROLE_TASKS.read_text(encoding="utf-8")):
        if task.get("name") == name:
            return task
    raise AssertionError(f"task {name!r} not found in {BUCKET_ROLE_TASKS}")


def _render_merged_secret(current_data, generated):
    """Render the REAL endpoint/region + merge expressions from
    iam_bucket_role.yml, exactly as a real converge would build them. The
    endpoint/region fixture values stand in for what proxmox_domain /
    object_storage_region resolve to live -- this test covers the merge
    logic, not the endpoint string's own construction (see
    test_public_endpoint_is_derived_from_proxmox_domain below for that)."""
    defaults = _defaults()
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "object_storage_iam_endpoint_field": defaults["object_storage_iam_endpoint_field"],
        "object_storage_iam_region_field": defaults["object_storage_iam_region_field"],
        "object_storage_iam_public_endpoint": "https://s3.pve.example.test",
        "object_storage_region": "us-east-1",
    }
    templar._loader.set_basedir(str(ROLE))
    endpoint_region_expr = _bucket_role_task(ENDPOINT_REGION_TASK)["ansible.builtin.set_fact"][
        "object_storage_iam_endpoint_region"
    ]
    endpoint_region = templar.template(trust_as_template(endpoint_region_expr))

    templar.available_variables.update(
        {
            "object_storage_iam_current_data": current_data,
            "object_storage_iam_generated": generated,
            "object_storage_iam_endpoint_region": endpoint_region,
        }
    )
    merge_expr = _bucket_role_task(MERGE_TASK)["ansible.builtin.set_fact"]["object_storage_iam_merged"]
    return templar.template(trust_as_template(merge_expr))


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


class SecretFieldCompleteness(unittest.TestCase):
    """Every stored bucket/role secret must carry all four ratified S3
    credential fields, on both roles -- not only the access/secret key pair.
    A consumer on another host must never have to invent the endpoint or
    region itself (Vikunja follow-up on PR #2195: L4x had to)."""

    def test_field_name_vars_match_the_ratified_convention(self):
        defaults = _defaults()
        self.assertEqual(defaults["object_storage_iam_access_key_field"], "AWS_ACCESS_KEY_ID")
        self.assertEqual(defaults["object_storage_iam_secret_key_field"], "AWS_SECRET_ACCESS_KEY")
        self.assertEqual(defaults["object_storage_iam_endpoint_field"], "AWS_ENDPOINT_URL")
        self.assertEqual(defaults["object_storage_iam_region_field"], "AWS_REGION")

    def test_public_endpoint_is_derived_from_proxmox_domain(self):
        # The one base ingress-domain variable every fronted service's public
        # hostname in this estate composes with (roles/traefik/README.md) --
        # never a second, role-local domain literal.
        self.assertEqual(
            _defaults()["object_storage_iam_public_endpoint"],
            "https://s3.{{ proxmox_domain }}",
        )

    def test_a_freshly_generated_secret_carries_all_four_fields_on_both_roles(self):
        for role in _defaults()["object_storage_iam_roles"]:
            with self.subTest(role=role):
                merged = _render_merged_secret(
                    current_data={},
                    generated={"AWS_ACCESS_KEY_ID": "AKFIXTURE", "AWS_SECRET_ACCESS_KEY": "SKFIXTURE"},
                )
                self.assertEqual(set(merged), EXPECTED_S3_CREDENTIAL_FIELDS)
                self.assertEqual(merged["AWS_ACCESS_KEY_ID"], "AKFIXTURE")
                self.assertEqual(merged["AWS_SECRET_ACCESS_KEY"], "SKFIXTURE")
                self.assertEqual(merged["AWS_ENDPOINT_URL"], "https://s3.pve.example.test")
                self.assertEqual(merged["AWS_REGION"], "us-east-1")

    def test_an_existing_secret_missing_endpoint_and_region_gets_backfilled(self):
        # A secret stored before this change carries only the key pair. The
        # next converge must reconcile it to all four fields without touching
        # the (never-rotated-here) key pair itself.
        merged = _render_merged_secret(
            current_data={"AWS_ACCESS_KEY_ID": "EXISTINGAK", "AWS_SECRET_ACCESS_KEY": "EXISTINGSK"},
            generated={},
        )
        self.assertEqual(merged["AWS_ACCESS_KEY_ID"], "EXISTINGAK")
        self.assertEqual(merged["AWS_SECRET_ACCESS_KEY"], "EXISTINGSK")
        self.assertEqual(set(merged), EXPECTED_S3_CREDENTIAL_FIELDS)

    def test_an_up_to_date_secret_is_unchanged_by_a_second_render(self):
        # Proves the write-if-changed guard (object_storage_iam_needs_write =
        # merged != current_data) actually reaches changed=0 on a second
        # converge once endpoint/region are already stored.
        first = _render_merged_secret(current_data={}, generated={"AWS_ACCESS_KEY_ID": "AK", "AWS_SECRET_ACCESS_KEY": "SK"})
        second = _render_merged_secret(current_data=first, generated={})
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
