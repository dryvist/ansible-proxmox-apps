"""OpenHands launcher key agent: the per-host OpenBao Agent that renders the
launcher's two key files. Every task is gated on the service flag, the agent
starts before the launcher, each key renders at 0600 with error_on_missing_key
from one KV path, and the AppRole secret-zero is never printed."""

from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "openhands"
GROUP_VARS = ROOT / "inventory" / "group_vars" / "openhands_host.yml"
SERVICES = ROLE / "tasks" / "services.yml"
KEY_AGENT = ROLE / "tasks" / "key_agent.yml"
AGENT_HCL = ROLE / "templates" / "openhands-secrets-agent.hcl.j2"
AGENT_UNIT = ROLE / "templates" / "openhands-secrets-agent.service.j2"
LAUNCHER_UNIT = ROLE / "templates" / "openhands-canvas.service.j2"
FLAG = "openhands_service_enabled"
SECRET_ZERO = ("openhands_approle_role_id", "openhands_approle_secret_id")


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _when(task):
    when = task.get("when", "")
    if isinstance(when, list):
        when = " ".join(map(str, when))
    return str(when)


class OpenHandsKeyAgentGate(unittest.TestCase):
    def test_every_key_agent_task_is_gated_on_the_service_flag(self):
        for task in _load(KEY_AGENT):
            self.assertIn(FLAG, _when(task), task.get("name"))

    def test_key_agent_runs_before_the_launcher_unit_and_enable_state(self):
        names = [task.get("name") for task in _load(SERVICES)]
        include = names.index("Deploy the launcher key agent")
        self.assertLess(include, names.index("Install the Agent Canvas launcher unit"))
        self.assertLess(
            include, names.index("Set the Agent Canvas launcher's enable state")
        )

    def test_tasks_touching_the_approle_secret_zero_are_no_log(self):
        for task in _load(KEY_AGENT):
            if any(name in yaml.safe_dump(task) for name in SECRET_ZERO):
                self.assertIs(task.get("no_log"), True, task.get("name"))


class OpenHandsKeyAgentUnits(unittest.TestCase):
    def test_agent_unit_starts_before_the_launcher_and_restarts_on_failure(self):
        text = AGENT_UNIT.read_text(encoding="utf-8")
        for line in (
            "Before=openhands-canvas.service",
            "Restart=on-failure",
            "WantedBy=multi-user.target",
        ):
            self.assertIn(line, text)

    def test_launcher_orders_after_and_wants_the_agent_only_while_enabled(self):
        text = LAUNCHER_UNIT.read_text(encoding="utf-8")
        gate = text[text.index("{% if openhands_service_enabled | bool %}"):text.index("{% endif %}")]
        outside = text.replace(gate, "")
        for line in (
            "After=openhands-secrets-agent.service",
            "Wants=openhands-secrets-agent.service",
        ):
            self.assertIn(line, gate)
            self.assertNotIn(line, outside)


class OpenHandsKeyAgentRender(unittest.TestCase):
    def test_hcl_renders_both_fields_from_one_kv_path_at_0600_and_fails_on_a_missing_field(self):
        text = AGENT_HCL.read_text(encoding="utf-8")
        defaults = _load(ROLE / "defaults" / "main.yml")
        self.assertEqual(defaults["openhands_kv_path"], "secret/data/apps/openhands")
        self.assertIn("{{ openhands_kv_path }}", text)
        self.assertIn(".Data.data.openhands_backend_api_key", text)
        self.assertIn(".Data.data.openhands_llm_router_key", text)
        self.assertEqual(len(re.findall(r'perms\s*=\s*"0600"', text)), 2)
        self.assertEqual(len(re.findall(r"error_on_missing_key\s*=\s*true", text)), 2)
        for key_file in ("openhands_backend_key_file", "openhands_router_key_file"):
            self.assertEqual(
                len(re.findall(r'destination\s*=\s*"\{\{ ' + key_file + r' \}\}"', text)), 1
            )

    def test_agent_logs_in_from_files_and_keeps_the_secret_id_on_restart(self):
        text = AGENT_HCL.read_text(encoding="utf-8")
        self.assertIn("role_id_file_path", text)
        self.assertIn("secret_id_file_path", text)
        self.assertRegex(text, r"remove_secret_id_file_after_reading\s*=\s*false")


class OpenHandsKeyAgentInputs(unittest.TestCase):
    def test_group_vars_map_the_agent_inputs_from_the_shared_sources(self):
        group = _load(GROUP_VARS)
        self.assertIn("OPENBAO_APPROLE_OPENHANDS_ROLE_ID", group["openhands_approle_role_id"])
        self.assertIn(
            "OPENBAO_APPROLE_OPENHANDS_SECRET_ID", group["openhands_approle_secret_id"]
        )
        self.assertIn("PROXMOX_SUBDOMAIN", group["openhands_store_subdomain"])
        self.assertEqual(group["openhands_store_version"], "{{ openbao_client_version }}")

    def test_agent_release_comes_through_the_raw_cache_not_a_public_host(self):
        deb = _load(GROUP_VARS)["openhands_store_deb_url"]
        self.assertIn("{{ openhands_raw_cache_url", deb)
        self.assertIn("/github_releases/openbao/openbao/releases/download/v", deb)
        self.assertNotIn("https://github.com", deb)


if __name__ == "__main__":
    unittest.main()
