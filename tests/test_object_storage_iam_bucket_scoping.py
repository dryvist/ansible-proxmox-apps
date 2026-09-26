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
IAM_TASKS = ROLE / "tasks" / "iam.yml"
INGRESS_ROUTE_TASK = "Find the machine-S3 ingress route"
INGRESS_ASSERT_TASK = "Assert the machine-S3 ingress route exists and is not SSO-gated"
PUBLIC_ENDPOINT_TASK = "Set the public S3 endpoint from the live ingress route"

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


def _flatten_tasks(tasks):
    """Descend into block:/always:/rescue: the same way Ansible itself
    flattens a task list, so a task nested inside iam.yml's OpenBao block is
    found just like a top-level one."""
    for task in tasks:
        yield task
        for key in ("block", "always", "rescue"):
            if key in task:
                yield from _flatten_tasks(task[key])


def _iam_task(name):
    for task in _flatten_tasks(yaml.safe_load(IAM_TASKS.read_text(encoding="utf-8"))):
        if task.get("name") == name:
            return task
    raise AssertionError(f"task {name!r} not found in {IAM_TASKS}")


def _render_ingress_endpoint(ingress, proxmox_domain="pve.example.test"):
    """Render the REAL ingress-route lookup, assert conditions, and endpoint
    expressions out of iam.yml against a fixture tofu_data.ingress list --
    exactly what a real converge builds from the tofu-published inventory.
    Returns (route, assert_holds, endpoint_or_None)."""
    templar = Templar(loader=DataLoader())
    templar._loader.set_basedir(str(ROLE))
    # Explicitly widened to dict[str, object]: this dict's slots hold a mix of
    # a nested dict (tofu_data), a rendered route (dict), and plain strings
    # (proxmox_domain) -- narrowing to the first literal's shape is what a
    # bare `templar.available_variables = {...}` would do, then reject the
    # later string assignment.
    available_vars: dict[str, object] = {"tofu_data": {"ingress": ingress}}
    templar.available_variables = available_vars

    route_expr = _iam_task(INGRESS_ROUTE_TASK)["ansible.builtin.set_fact"]["object_storage_iam_ingress_route"]
    route = templar.template(trust_as_template(route_expr))

    available_vars["object_storage_iam_ingress_route"] = route
    conditions = _iam_task(INGRESS_ASSERT_TASK)["ansible.builtin.assert"]["that"]
    assert_holds = all(
        str(templar.template(trust_as_template("{{ (" + cond + ") }}"))) == "True" for cond in conditions
    )

    endpoint = None
    if assert_holds:
        available_vars["proxmox_domain"] = proxmox_domain
        endpoint_expr = _iam_task(PUBLIC_ENDPOINT_TASK)["ansible.builtin.set_fact"][
            "object_storage_iam_public_endpoint"
        ]
        endpoint = templar.template(trust_as_template(endpoint_expr))

    return route, assert_holds, endpoint


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

    def test_public_endpoint_is_derived_from_the_live_s3_ingress_route(self):
        # tasks/iam.yml derives the endpoint from the tofu-owned ingress table
        # (tofu_data.ingress, the same one roles/traefik reads) rather than
        # composing "s3.{{ proxmox_domain }}" as a bare literal -- proves the
        # happy path resolves to the same hostname the old literal always
        # produced, PLUS that a route rename/removal or an sso flip is
        # rejected instead of silently composing a dead/wrong host.
        route, assert_holds, endpoint = _render_ingress_endpoint(
            ingress=[{"name": "s3", "sso": False}, {"name": "other-route", "sso": True}]
        )
        self.assertEqual(route, {"name": "s3", "sso": False})
        self.assertTrue(assert_holds)
        self.assertEqual(endpoint, "https://s3.pve.example.test")

    def test_public_endpoint_honours_a_hostname_override_like_traefik_does(self):
        # Same {name, hostname} precedence roles/traefik/tasks/main.yml uses
        # for every other ingress row -- an "s3" row need not fix its public
        # hostname to its route name.
        _, assert_holds, endpoint = _render_ingress_endpoint(
            ingress=[{"name": "s3", "hostname": "s3-alt", "sso": False}]
        )
        self.assertTrue(assert_holds)
        self.assertEqual(endpoint, "https://s3-alt.pve.example.test")

    def test_a_missing_s3_ingress_route_fails_the_assert(self):
        # A route rename/removal in tofu-proxmox's ingress.tf must fail this
        # converge loudly, never silently compose a dead host.
        route, assert_holds, endpoint = _render_ingress_endpoint(
            ingress=[{"name": "object-storage", "sso": True}]
        )
        self.assertEqual(route, {})
        self.assertFalse(assert_holds)
        self.assertIsNone(endpoint)

    def test_an_sso_gated_s3_ingress_route_fails_the_assert(self):
        # An accidental sso flip on the machine-S3 route must also fail loud
        # -- SSO-gated means browser/human auth, not a machine S3 client.
        route, assert_holds, endpoint = _render_ingress_endpoint(ingress=[{"name": "s3", "sso": True}])
        self.assertEqual(route, {"name": "s3", "sso": True})
        self.assertFalse(assert_holds)
        self.assertIsNone(endpoint)

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
