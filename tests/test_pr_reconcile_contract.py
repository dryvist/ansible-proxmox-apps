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


if __name__ == "__main__":
    unittest.main()
