"""Guard the read-only Git mirror's owner, access, and refresh contracts."""

from pathlib import Path
import unittest

from jinja2 import Environment
import yaml


ROOT = Path(__file__).resolve().parents[1]


class GitMirrorContract(unittest.TestCase):
    def test_installation_owner_and_private_repository_policy(self):
        defaults = yaml.safe_load((ROOT / "roles/git_mirror/defaults/main.yml").read_text())
        installations = defaults["git_mirror_installations"]
        self.assertEqual(
            [item["owner"] for item in installations],
            ["dryvist", "JacobPEvans", "JacobPEvans-personal"],
        )
        self.assertEqual([item["private_for_all"] for item in installations], [True, True, False])

        script = (ROOT / "roles/git_mirror/templates/git-mirror-sync.sh.j2").read_text()
        self.assertIn("write -field=token", script)
        self.assertIn('git clone --mirror "https://github.com/$full_name.git"', script)
        self.assertIn("remote update --prune", script)
        self.assertIn("GIT_CONFIG_VALUE_0", script)
        self.assertNotIn("https://$installation_token@github.com", script)

    def test_public_and_authenticated_roots_are_separate_and_read_only(self):
        apache = (ROOT / "roles/git_mirror/templates/git-mirror.conf.j2").read_text()
        public_vhost = apache.split("<VirtualHost", 2)[1]
        all_vhost = apache.split("<VirtualHost", 2)[2]
        public_vhost = public_vhost.split("</VirtualHost>", 1)[0]
        all_vhost = all_vhost.split("</VirtualHost>", 1)[0]
        self.assertIn("git_mirror_public_port", public_vhost)
        self.assertNotIn("AuthType Basic", public_vhost)
        self.assertIn("git_mirror_all_port", all_vhost)
        self.assertIn("AuthType Basic", all_vhost)
        self.assertIn("AuthUserFile", all_vhost)
        self.assertIn('<LocationMatch "^{{ git_mirror_all_path }}(/|$)">', all_vhost)

        tasks = yaml.safe_load((ROOT / "roles/git_mirror/tasks/main.yml").read_text())
        service_user = next(task for task in tasks if task["name"] == "Create git-mirror service user")
        self.assertNotIn("www-data", service_user["ansible.builtin.user"].get("groups", []))
        approle_directory = next(task for task in tasks if task["name"] == "Create Git mirror directories")
        approle = next(item for item in approle_directory["loop"] if "approle" in item["path"])
        self.assertEqual(approle["group"], "{{ git_mirror_group }}")
        self.assertEqual(approle["mode"], "0750")
        htpasswd = next(task for task in tasks if task["name"] == "Generate the protected tree htpasswd entry")
        self.assertEqual(htpasswd["community.general.htpasswd"]["group"], "www-data")
        self.assertEqual(htpasswd["community.general.htpasswd"]["mode"], "0640")
        receivepack = next(task for task in tasks if task["name"] == "Disable Git receive-pack for all mirror repositories")
        self.assertEqual(receivepack["community.general.git_config"]["name"], "http.receivepack")
        self.assertEqual(receivepack["community.general.git_config"]["value"], "false")

    def test_refresh_metrics_and_probes_are_wired(self):
        timer = (ROOT / "roles/git_mirror/templates/git-mirror-sync.timer.j2").read_text()
        script = (ROOT / "roles/git_mirror/templates/git-mirror-sync.sh.j2").read_text()
        task_text = (ROOT / "roles/git_mirror/tasks/main.yml").read_text()
        self.assertIn("OnUnitActiveSec={{ git_mirror_sync_interval }}", timer)
        self.assertEqual(
            yaml.safe_load((ROOT / "roles/git_mirror/defaults/main.yml").read_text())[
                "git_mirror_sync_interval"
            ],
            "6h",
        )
        self.assertIn("git_mirror_sync_success", script)
        self.assertIn("git_mirror_sync_last_success_timestamp_seconds", script)
        self.assertIn("Probe the public tree without credentials", task_text)
        self.assertIn("Probe the all tree with HTTP basic authentication", task_text)
        self.assertIn("http_401_tls", (ROOT / "roles/prometheus_stack/defaults/main.yml").read_text())

    def test_grafana_git_mirror_alerts_check_freshness_and_sync_status(self):
        defaults = yaml.safe_load((ROOT / "roles/grafana_stack/defaults/main.yml").read_text())
        template = Environment().from_string(
            (ROOT / "roles/grafana_stack/templates/alerting/rules-git-mirror.yml.j2").read_text()
        )
        render_vars = {
            "grafana_stack_alert_folder": "Alerting",
            "grafana_stack_alert_eval_interval": "1m",
            "grafana_stack_alert_git_mirror_max_age_seconds": defaults[
                "grafana_stack_alert_git_mirror_max_age_seconds"
            ],
        }
        rules_config = yaml.safe_load(
            template.render(
                grafana_stack_prometheus_url="http://prometheus.example.test:9090",
                **render_vars,
            )
        )
        grafana_tasks = yaml.safe_load((ROOT / "roles/grafana_stack/tasks/main.yml").read_text())
        alert_task = next(
            task for task in grafana_tasks if task["name"] == "Render grafana unified-alerting provisioning"
        )
        self.assertIn("rules-git-mirror", alert_task["loop"])
        groups = rules_config["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["name"], "git-mirror-sync")
        rules = groups[0]["rules"]
        self.assertEqual(
            [rule["uid"] for rule in rules],
            ["git-mirror-sync-stale", "git-mirror-sync-failed"],
        )
        stale, failed = rules
        self.assertEqual(
            stale["data"][0]["model"]["expr"],
            "(time() - git_mirror_sync_last_success_timestamp_seconds) > bool 43200",
        )
        self.assertEqual(
            failed["data"][0]["model"]["expr"],
            "git_mirror_sync_success == bool 0",
        )
        self.assertTrue(all("bool" in rule["data"][0]["model"]["expr"] for rule in rules))
        for rule in rules:
            self.assertEqual(rule["for"], "15m")
            self.assertEqual(rule["labels"]["severity"], "warning")
            self.assertEqual(rule["noDataState"], "Alerting")

        no_prometheus = yaml.safe_load(
            template.render(grafana_stack_prometheus_url="", **render_vars)
        )
        self.assertIsNone(no_prometheus["groups"])

    def test_inventory_and_secret_field_are_wired(self):
        tag_map = (ROOT / "inventory/nautobot.yml").read_text()
        group_vars = (ROOT / "inventory/group_vars/git_mirror_group.yml").read_text()
        domain_map_file = yaml.safe_load(
            (ROOT / "playbooks/site/vars/openbao_secrets_domain_groups.yml").read_text()
        )
        domain_map = domain_map_file["openbao_secrets_domain_groups"]
        playbook = (ROOT / "playbooks/site/01-baseline-infra.yml").read_text()
        self.assertIn("git_mirror_group: \"'git-mirror' in nautobot_tag_names\"", tag_map)
        self.assertIn("bao_apps_secrets.all_password", group_vars)
        self.assertIn("git_mirror_group", domain_map["apps"])
        self.assertIn("hosts: git_mirror_group", playbook)


if __name__ == "__main__":
    unittest.main()
