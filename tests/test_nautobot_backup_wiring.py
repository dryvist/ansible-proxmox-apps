"""Nautobot hands the restic_backup role one B2 repository from its own OpenBao record."""

from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
VARS = yaml.safe_load((ROOT / "inventory/group_vars/nautobot_group.yml").read_text())


class NautobotBackupWiring(unittest.TestCase):
    def test_one_b2_repository_carries_every_key_the_environment_file_reads(self):
        repos = VARS["nautobot_backup_repositories"]
        self.assertEqual([r["name"] for r in repos], ["b2"])
        self.assertEqual(
            sorted(repos[0]),
            ["access_key_id", "bucket", "enabled", "endpoint", "name", "region", "secret_access_key"],
        )

    def test_b2_needs_the_whole_key_pair_and_reads_its_own_record(self):
        enabled = VARS["nautobot_backup_b2_enabled"]
        for part in ("endpoint", "bucket", "access_key_id", "secret_access_key"):
            self.assertIn(f"nautobot_backup_b2_{part} | length > 0", enabled)
        fields = {
            "endpoint": "AWS_ENDPOINT_URL",
            "bucket": "BUCKET",
            "access_key_id": "AWS_ACCESS_KEY_ID",
            "secret_access_key": "AWS_SECRET_ACCESS_KEY",
        }
        for part, field in fields.items():
            self.assertIn(
                f"(bao_nautobot_backup_b2_secrets | default({{}})).{field}",
                VARS[f"nautobot_backup_b2_{part}"],
            )

    def test_restic_password_is_optional_so_the_play_runs_before_it_is_seeded(self):
        self.assertIn("default('', true)", VARS["nautobot_restic_password"])
        self.assertNotIn("mandatory", VARS["nautobot_restic_password"])

    def test_record_is_published_and_scoped_to_the_nautobot_group(self):
        groups = yaml.safe_load(
            (ROOT / "playbooks/site/vars/openbao_secrets_domain_groups.yml").read_text()
        )["openbao_secrets_domain_groups"]
        self.assertEqual(groups["nautobot_backup_b2"], ["nautobot_group"])
        facts = (ROOT / "playbooks/tasks/publish_secret_domain_facts.yml").read_text()
        self.assertEqual(facts.count("bao_nautobot_backup_b2_secrets"), 2)


if __name__ == "__main__":
    unittest.main()
