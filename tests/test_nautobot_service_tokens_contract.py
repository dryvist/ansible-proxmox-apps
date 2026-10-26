"""The workstation token publisher matches the collection's Nautobot contract."""

from pathlib import Path
import unittest

import yaml


REPO = Path(__file__).resolve().parents[1]
PLAYBOOK = REPO / "playbooks/nautobot-service-tokens.yml"
GROUP_VARS = REPO / "inventory/group_vars/nautobot_group.yml"


class NautobotServiceTokensContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plays = yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))
        cls.group_vars = yaml.safe_load(GROUP_VARS.read_text(encoding="utf-8"))
        cls.local_play = next(play for play in cls.plays if play["hosts"] == "localhost")
        cls.service_play = next(
            play for play in cls.plays if play["hosts"] == "nautobot_group"
        )
        cls.publisher = next(
            task["ansible.builtin.include_role"]
            for task in cls.service_play["tasks"]
            if task.get("name") == "Mint and publish the selected Nautobot service-account tokens"
        )

    def test_selected_accounts_and_collection_secret_paths_are_exact(self):
        read_secret = self.group_vars["nautobot_collection_read_token_secret"]
        write_secret = self.group_vars["nautobot_collection_write_token_secret"]
        role_vars = self.service_play["vars"]

        self.assertEqual(role_vars["server_managed_account_names"], ["pipeline", "writer"])
        self.assertEqual(read_secret, {"path": "apps/nautobot/pipeline", "field": "pipeline_ro_token"})
        self.assertEqual(write_secret, {"path": "apps/nautobot/sync-write", "field": "sync_write_token"})
        self.assertEqual(
            role_vars["server_pipeline_token_path"],
            "{{ nautobot_collection_read_token_secret.path }}",
        )
        self.assertEqual(
            role_vars["server_pipeline_token_key"],
            "{{ nautobot_collection_read_token_secret.field }}",
        )
        self.assertEqual(
            role_vars["server_write_token_path"],
            "{{ nautobot_collection_write_token_secret.path }}",
        )
        self.assertEqual(
            role_vars["server_write_token_key"],
            "{{ nautobot_collection_write_token_secret.field }}",
        )
        self.assertEqual(self.publisher["name"], "jpe_ansible.nautobot.server")
        self.assertEqual(self.publisher["tasks_from"], "accounts.yml")
        self.assertNotIn("server_pipeline_url_key", role_vars)
        self.assertNotIn("server_write_url_key", role_vars)

    def test_publisher_token_is_required_and_only_loads_the_app_secret_separately(self):
        local_tasks = self.local_play["tasks"]
        service_tasks = self.service_play["tasks"]

        self.assertEqual(local_tasks[0]["name"], "Require the human-unlocked publisher token")
        self.assertIn("lookup('env', 'BAO_TOKEN') | length > 0", str(local_tasks[0]))
        self.assertIn("lookup('env', 'BAO_TOKEN')", self.service_play["vars"]["server_openbao_token"])
        self.assertEqual(
            self.local_play["vars"]["openbao_secrets_domains"],
            [
                {
                    "name": "apps",
                    "workstation_issuer_role": "apps-workstation",
                    "paths": ["apps/nautobot"],
                }
            ],
        )
        self.assertEqual(service_tasks[0]["name"], "Require the human-unlocked publisher token before any account API call")

    def test_playbook_is_not_scheduled_or_referenced_by_semaphore_templates(self):
        site = (REPO / "playbooks/site.yml").read_text(encoding="utf-8")
        self.assertNotIn(PLAYBOOK.name, site)

        semaphore_templates = [
            path
            for path in REPO.rglob("*.j2")
            if "semaphore" in str(path).lower()
        ]
        for template in semaphore_templates:
            with self.subTest(template=template.relative_to(REPO)):
                self.assertNotIn(
                    PLAYBOOK.name,
                    template.read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
