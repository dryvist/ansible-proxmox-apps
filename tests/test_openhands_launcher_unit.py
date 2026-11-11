"""OpenHands launcher unit contract: the rendered openhands-canvas.service, its
port and capability, credentials, Docker limits and the loopback health probe."""

from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "openhands"
SERVICES = ROLE / "tasks" / "services.yml"
UNIT = ROLE / "templates" / "openhands-canvas.service.j2"
COMMON_CONF = ROLE / "templates" / "openhands-service-common.conf.j2"
RETIRED_TEMPLATES = (
    "openhands-agent-server.service.j2",
    "openhands-automation.service.j2",
    "openhands.env.j2",
)
HEALTH_STATUSES = [200, 204, 301, 302, 303, 307, 308, 401]


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _task(tasks, name):
    return next(task for task in tasks if task.get("name") == name)


def _condition(task):
    when = task.get("when", "")
    if isinstance(when, list):
        when = " ".join(map(str, when))
    return when


class OpenHandsServiceUnit(unittest.TestCase):
    def test_units_render_through_the_template_render_harness(self):
        harness = _load(ROOT / "tests" / "template_render" / "verify_templates.yml")
        plays = [play.get("import_playbook") for play in harness if "import_playbook" in play]
        self.assertIn("verify/openhands.yml", plays)

    def test_the_retired_unit_and_environment_templates_are_gone(self):
        for name in RETIRED_TEMPLATES:
            self.assertFalse((ROLE / "templates" / name).exists(), name)

    def test_the_launcher_binds_the_published_port_with_only_the_bind_capability(self):
        text = UNIT.read_text(encoding="utf-8")
        self.assertIn("AmbientCapabilities=CAP_NET_BIND_SERVICE\n", text)
        self.assertIn("CapabilityBoundingSet=CAP_NET_BIND_SERVICE\n", text)

    def test_the_launcher_unit_wires_the_shared_hardening_template(self):
        text = UNIT.read_text(encoding="utf-8")
        self.assertIn(
            "{{ lookup('ansible.builtin.template', _service_common_template) }}", text
        )
        common = COMMON_CONF.read_text(encoding="utf-8")
        self.assertIn(
            "{{ lookup('ansible.builtin.file', _service_hardening_template) }}",
            common,
        )
        self.assertIn("ReadWritePaths={{ openhands_state_dir }}", common)
        self.assertIn("Restart=on-failure", common)
        self.assertIn("WantedBy=multi-user.target", text)
        install = _task(_load(SERVICES), "Install the Agent Canvas launcher unit")
        self.assertEqual(install["ansible.builtin.template"]["src"], "openhands-canvas.service.j2")
        self.assertEqual(
            install["ansible.builtin.template"]["dest"],
            "/etc/systemd/system/openhands-canvas.service",
        )
        self.assertEqual(
            install["vars"]["_service_hardening_template"],
            "{{ role_path }}/../_shared/templates/systemd-service-hardening.conf.j2",
        )
        self.assertEqual(
            install["vars"]["_service_common_template"],
            "{{ role_path }}/templates/openhands-service-common.conf.j2",
        )

    def test_the_launcher_runs_the_installed_node_and_canvas_bin_on_the_port(self):
        text = UNIT.read_text(encoding="utf-8")
        self.assertIn(
            "exec {{ openhands_node_dir }}/bin/node {{ openhands_canvas_dir }}/bin/agent-canvas"
            " --public --port {{ openhands_canvas_port }}'",
            text,
        )
        self.assertIn("ExecStart=/bin/sh -ec '", text)
        common = COMMON_CONF.read_text(encoding="utf-8")
        self.assertIn("User={{ openhands_user }}", common)
        self.assertIn("WorkingDirectory={{ openhands_state_dir }}", common)
        self.assertIn("Environment=HOME={{ openhands_state_dir }}", common)
        self.assertIn("Environment=PATH={{ openhands_node_dir }}/bin:", common)
        self.assertIn("/usr/local/bin", common)

    def test_the_launcher_loads_its_keys_only_while_enabled(self):
        text = UNIT.read_text(encoding="utf-8")
        blocks = re.findall(r"\{% if openhands_service_enabled \| bool %\}.*?\{% endif %\}", text, re.S)
        gate = "".join(blocks)
        outside = re.sub(r"\{% if openhands_service_enabled \| bool %\}.*?\{% endif %\}", "", text, flags=re.S)
        for credential in (
            "LoadCredential=openhands-backend-key:{{ openhands_backend_key_file }}",
            "LoadCredential=openhands-secret-key:{{ openhands_secrets_dir }}/secret-key",
            "LoadCredential=openhands-automation-kv-secret:"
            "{{ openhands_secrets_dir }}/automation-kv-secret",
        ):
            self.assertIn(credential, gate)
            self.assertNotIn(credential, outside)
        common = COMMON_CONF.read_text(encoding="utf-8")
        self.assertNotIn("EnvironmentFile", common)

    def test_the_launcher_selects_docker_and_the_role_resource_limits(self):
        defaults = _load(ROLE / "defaults" / "main.yml")
        text = UNIT.read_text(encoding="utf-8")
        self.assertEqual(defaults["openhands_conversation_memory_limit"], "4g")
        self.assertEqual(defaults["openhands_conversation_cpus"], "2.0")
        self.assertEqual(defaults["openhands_conversation_pids_limit"], 512)
        self.assertIn("Environment=OH_CONVERSATION_RUNTIME=docker", text)
        self.assertIn(
            "Environment=OH_CONVERSATION_CONTAINER_MEMORY={{ openhands_conversation_memory_limit }}",
            text,
        )
        self.assertIn(
            "Environment=OH_CONVERSATION_CONTAINER_CPUS={{ openhands_conversation_cpus }}",
            text,
        )
        self.assertIn(
            "Environment=OH_CONVERSATION_CONTAINER_PIDS_LIMIT={{ openhands_conversation_pids_limit }}",
            text,
        )

    def test_the_health_probe_hits_the_root_path_and_never_sends_the_key(self):
        defaults = _load(ROLE / "defaults" / "main.yml")
        self.assertEqual(defaults["openhands_canvas_health_statuses"], HEALTH_STATUSES)
        probe = _task(_load(SERVICES), "Verify the Agent Canvas launcher answers on loopback")
        uri = probe["ansible.builtin.uri"]
        self.assertEqual(uri["url"], "http://127.0.0.1:{{ openhands_canvas_port }}/")
        self.assertEqual(uri["status_code"], "{{ openhands_canvas_health_statuses }}")
        self.assertNotIn("headers", uri)
        self.assertNotIn("body", uri)
        self.assertIs(probe["check_mode"], False)
        self.assertIn("not ansible_check_mode", _condition(probe))
        self.assertEqual(
            probe["until"],
            "openhands_canvas_health.status in openhands_canvas_health_statuses",
        )
        wait = _task(_load(SERVICES), "Wait for the Agent Canvas launcher to accept connections")
        self.assertEqual(wait["ansible.builtin.wait_for"]["port"], "{{ openhands_canvas_port }}")


if __name__ == "__main__":
    unittest.main()
