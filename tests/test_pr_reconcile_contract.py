"""Guard the pr_reconcile role's owner, token, pin, and unit contracts."""

from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/pr_reconcile"
FORBIDDEN_OWNERS = ("VisiCore", "X10")


def load_defaults():
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text())


def unit_section(text, name):
    """Return the key=value pairs of one systemd section, ignoring comments."""
    body = text.split(f"[{name}]", 1)[1].split("\n[", 1)[0]
    pairs = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        pairs[key] = value
    return pairs


HARDENING = {
    "NoNewPrivileges": "true",
    "ProtectSystem": "strict",
    "PrivateTmp": "true",
    "ProtectHome": "true",
}


def assert_hardened(test, service):
    for key, value in HARDENING.items():
        test.assertEqual(service.get(key), value, key)
    test.assertIn("ReadWritePaths", service)


class PrReconcileContract(unittest.TestCase):
    def test_owners_and_token_paths(self):
        owners = load_defaults()["pr_reconcile_owners"]
        self.assertEqual(
            [(item["owner"], item["token_path"]) for item in owners],
            [
                ("JacobPEvans-ai", "github-admin/token/pr-reconcile-JacobPEvans-ai"),
                ("JacobPEvans", "github-admin/token/pr-reconcile-JacobPEvans"),
            ],
        )
        for item in owners:
            self.assertRegex(item["token_path"], r"^[A-Za-z0-9_/-]+$")

    def test_no_forbidden_owner_is_configured(self):
        for item in load_defaults()["pr_reconcile_owners"]:
            owner = item["owner"]
            self.assertFalse(owner.startswith("vct-"), owner)
            for forbidden in FORBIDDEN_OWNERS:
                self.assertNotEqual(owner, forbidden)

    def test_ref_and_commit_are_empty_until_deployment_sets_them(self):
        defaults = load_defaults()
        self.assertEqual(defaults["pr_reconcile_ref"], "")
        self.assertEqual(defaults["pr_reconcile_commit"], "")

    def test_ref_has_renovate_github_tags_comment(self):
        text = (ROLE / "defaults/main.yml").read_text()
        self.assertIn(
            "# renovate: datasource=github-tags depName=JacobPEvans/.github-ai\npr_reconcile_ref:",
            text,
        )

    def test_bun_pin_is_a_version_and_a_sha256(self):
        defaults = load_defaults()
        self.assertRegex(defaults["pr_reconcile_bun_version"], r"^\d+\.\d+\.\d+$")
        self.assertRegex(defaults["pr_reconcile_bun_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("bun-linux-x64.zip", defaults["pr_reconcile_bun_url"])

    def test_approle_pair_reads_the_platform_env_doc(self):
        text = (ROLE / "defaults/main.yml").read_text()
        self.assertIn("OPENBAO_APPROLE_PR_RECONCILE_ROLE_ID", text)
        self.assertIn("OPENBAO_APPROLE_PR_RECONCILE_SECRET_ID", text)
        self.assertNotIn("OPENBAO_APPROLE_GIT_MIRROR", text)

    def test_service_user_is_separate_from_the_mirror_user(self):
        defaults = load_defaults()
        self.assertEqual(defaults["pr_reconcile_user"], "pr-reconcile")
        self.assertEqual(defaults["pr_reconcile_group"], "pr-reconcile")
        self.assertNotEqual(defaults["pr_reconcile_user"], "git-mirror")

    def test_ref_and_commit_are_asserted_before_the_service_runs(self):
        tasks = (ROLE / "tasks/main.yml").read_text()
        self.assertIn("pr_reconcile_ref is match('^[A-Za-z0-9._/-]+$')", tasks)
        self.assertIn("pr_reconcile_commit is match('^[0-9a-f]{40}$')", tasks)
        self.assertIn("pr_reconcile_head.stdout == pr_reconcile_commit", tasks)
        self.assertIn("git rev-parse HEAD", tasks)

    def test_agent_unit_runs_as_the_service_user_with_a_private_runtime_dir(self):
        unit = (ROLE / "templates/openbao-pr-reconcile-agent.service.j2").read_text()
        service = unit_section(unit, "Service")
        self.assertEqual(service["User"], "{{ pr_reconcile_user }}")
        self.assertEqual(service["RuntimeDirectory"], "pr-reconcile")
        self.assertEqual(service["RuntimeDirectoryMode"], "0700")
        assert_hardened(self, service)

    def test_token_sink_lives_under_run(self):
        defaults = load_defaults()
        self.assertTrue(defaults["pr_reconcile_bao_token_file"].startswith("/run/"))
        self.assertTrue(defaults["pr_reconcile_runtime_dir"].startswith("/run/"))


if __name__ == "__main__":
    unittest.main()
