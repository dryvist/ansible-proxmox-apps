"""Render actual policy and secret expressions to verify their boundaries."""

import json
import re
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
SEED_BLOCK_TASK = "Seed this bucket/role's RustFS credential through the shared task"
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


def _seed_fields():
    """Render the field spec iam_bucket_role.yml passes to seed_generated. The
    public endpoint fixture stands in for what the live s3 ingress route
    resolves to (see test_public_endpoint_is_derived_from_the_live_s3_ingress_route)."""
    include = _bucket_role_task(SEED_BLOCK_TASK)["block"][0]
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        **_defaults(),
        "object_storage_iam_public_endpoint": "https://s3.pve.example.test",
    }
    templar._loader.set_basedir(str(ROLE))
    return [
        {
            key: templar.template(trust_as_template(value)) if isinstance(value, str) else value
            for key, value in field.items()
        }
        for field in include["vars"]["openbao_secrets_seed_fields"]
    ]


def _planned_fields(fields, stored):
    """Names seed_generated would write for a stored map: a field that is absent,
    or whose valid_pattern rejects the stored value. Mirrors the plan predicate in
    homelab-contracts v5.36.0 ansible/roles/openbao_secrets/tasks/seed_generated.yml."""
    planned = []
    for field in fields:
        current = stored.get(field["name"], "")
        pattern = field.get("valid_pattern", "")
        if not current or (pattern and not re.match(pattern, current)):
            planned.append(field["name"])
    return planned


class BucketRoleDerivation(unittest.TestCase):
    """Keep both default IAM roles available."""

    def test_both_roles_are_declared(self):
        self.assertEqual(_defaults()["object_storage_iam_roles"], ["ro", "rw"])

    def test_at_least_one_bucket_is_declared(self):
        self.assertTrue(_bucket_names(), "object_storage_default_buckets is empty")

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


class SystemOneBucketContract(unittest.TestCase):
    def test_system1_is_versioned_and_its_ro_policy_is_read_only(self):
        bucket = next(b for b in _defaults()["object_storage_default_buckets"] if b["name"] == "system1")
        self.assertIs(bucket["versioning"], True)

        policy = _render_policy("system1", "ro", _defaults()["object_storage_iam_policy_actions"])
        statement = policy["Statement"][0]
        self.assertIn("s3:GetObject", statement["Action"])
        self.assertIn("s3:ListBucket", statement["Action"])
        self.assertNotIn("s3:PutObject", statement["Action"])
        self.assertNotIn("s3:DeleteObject", statement["Action"])
        self.assertEqual(statement["Resource"], ["arn:aws:s3:::system1", "arn:aws:s3:::system1/*"])


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

    def test_a_fresh_secret_plans_all_four_fields_with_the_derived_endpoint_and_region(self):
        fields = _seed_fields()
        by_name = {field["name"]: field for field in fields}
        self.assertEqual(set(by_name), EXPECTED_S3_CREDENTIAL_FIELDS)
        self.assertEqual(
            _planned_fields(fields, {}),
            ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_ENDPOINT_URL", "AWS_REGION"],
        )
        defaults = _defaults()
        self.assertEqual(by_name["AWS_ACCESS_KEY_ID"]["charset"], "upper_numeric")
        self.assertEqual(by_name["AWS_ACCESS_KEY_ID"]["length"], defaults["object_storage_iam_access_key_length"])
        self.assertEqual(by_name["AWS_SECRET_ACCESS_KEY"]["charset"], "alnum")
        self.assertEqual(by_name["AWS_SECRET_ACCESS_KEY"]["length"], defaults["object_storage_iam_secret_key_length"])
        self.assertEqual(by_name["AWS_ENDPOINT_URL"]["value"], "https://s3.pve.example.test")
        self.assertEqual(by_name["AWS_REGION"]["value"], "us-east-1")

    def test_an_existing_key_pair_missing_endpoint_and_region_gets_backfilled(self):
        # A secret stored before this change carries only the key pair. Only the
        # endpoint and region are planned; the key pair is left as stored.
        self.assertEqual(
            _planned_fields(
                _seed_fields(),
                {"AWS_ACCESS_KEY_ID": "EXISTINGAK", "AWS_SECRET_ACCESS_KEY": "EXISTINGSK"},
            ),
            ["AWS_ENDPOINT_URL", "AWS_REGION"],
        )

    def test_a_stale_endpoint_is_reconciled_and_a_stored_key_is_never_planned(self):
        # The key pair has no valid_pattern, so a stored value is never rewritten,
        # even one that would not match the generator's alphabet.
        self.assertEqual(
            _planned_fields(
                _seed_fields(),
                {
                    "AWS_ACCESS_KEY_ID": "AK",
                    "AWS_SECRET_ACCESS_KEY": "not-the-generator-alphabet!",
                    "AWS_ENDPOINT_URL": "https://old.example.test",
                    "AWS_REGION": "us-east-1",
                },
            ),
            ["AWS_ENDPOINT_URL"],
        )

    def test_an_up_to_date_secret_plans_no_write_on_a_second_run(self):
        # After the first run every field is stored and matches, so the second
        # run plans nothing and seed_generated issues no KV write.
        after_first_run = {
            "AWS_ACCESS_KEY_ID": "AK",
            "AWS_SECRET_ACCESS_KEY": "SK",
            "AWS_ENDPOINT_URL": "https://s3.pve.example.test",
            "AWS_REGION": "us-east-1",
        }
        self.assertEqual(_planned_fields(_seed_fields(), after_first_run), [])


if __name__ == "__main__":
    unittest.main()
