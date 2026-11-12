"""The workstation token publisher loads the nautobot role defaults before group_vars."""

from pathlib import Path
import unittest

import yaml


REPO = Path(__file__).resolve().parents[1]
PLAYBOOK = REPO / "playbooks/nautobot-service-tokens.yml"
ROLE_DEFAULTS_DIR = REPO / "roles/nautobot/defaults/main"
GROUP_VARS = "../inventory/group_vars/nautobot_group.yml"


class NautobotServiceTokensRoleDefaults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
        cls.service_play = next(play for play in plays if play["hosts"] == "nautobot_group")

    def test_play_loads_every_nautobot_role_defaults_file_before_group_vars(self):
        role_defaults = [
            f"../roles/nautobot/defaults/main/{path.name}"
            for path in sorted(ROLE_DEFAULTS_DIR.glob("*.yml"))
        ]

        self.assertTrue(role_defaults, "roles/nautobot/defaults/main has no files")
        self.assertEqual(self.service_play["vars_files"], [*role_defaults, GROUP_VARS])


if __name__ == "__main__":
    unittest.main()
