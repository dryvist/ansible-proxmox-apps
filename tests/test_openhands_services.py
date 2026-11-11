"""OpenHands service contract: pinned installs that resolve through the
site's PyPI cache, the Agent Canvas launcher unit and its credentials gated on
openhands_service_enabled, retired units removed on every converge, the router
settings, and no key value anywhere in the repository."""

from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "openhands"
SERVICES = ROLE / "tasks" / "services.yml"
GROUP_VARS = ROOT / "inventory" / "group_vars" / "openhands_host.yml"
DOMAIN_GROUPS = ROOT / "playbooks" / "site" / "vars" / "openbao_secrets_domain_groups.yml"
UNIT = ROLE / "templates" / "openhands-canvas.service.j2"
COMMON_CONF = ROLE / "templates" / "openhands-service-common.conf.j2"
RETIRED_TEMPLATES = (
    "openhands-agent-server.service.j2",
    "openhands-automation.service.j2",
    "openhands.env.j2",
)
RETIRED_UNITS = ("openhands-agent-server", "openhands-automation")
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


class OpenHandsServiceInstall(unittest.TestCase):
    def test_install_header_points_to_the_existing_service_tasks(self):
        header = (ROLE / "tasks" / "install.yml").read_text(encoding="utf-8").splitlines()[:5]
        self.assertIn("services.yml", " ".join(header))
        self.assertNotIn("later PR", " ".join(header))

    def test_both_services_install_at_their_pins_through_the_pypi_cache(self):
        defaults = _load(ROLE / "defaults" / "main.yml")
        self.assertEqual(defaults["openhands_agent_server_version"], "1.58.1")
        self.assertEqual(defaults["openhands_automation_version"], "1.26.0")
        install = _task(_load(SERVICES), "Install the agent server and automation through the PyPI cache")
        argv = install["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[0], "{{ openhands_uv_venv }}/bin/uv")
        self.assertIn("--index-url={{ openhands_pypi_cache_url }}", argv)
        self.assertIn(
            "openhands-agent-server=={{ openhands_agent_server_version }}", argv
        )
        self.assertIn(
            "openhands-automation=={{ openhands_automation_version }}", argv
        )
        self.assertEqual(install["notify"], "Restart the OpenHands launcher")

    def test_install_reinstalls_only_when_a_pin_is_not_installed(self):
        tasks = _load(SERVICES)
        read = _task(tasks, "Read the installed service releases")
        self.assertIs(read["changed_when"], False)
        self.assertIs(read["failed_when"], False)
        self.assertIs(read["check_mode"], False)
        install = _task(tasks, "Install the agent server and automation through the PyPI cache")
        self.assertIs(install["changed_when"], True)
        condition = _condition(install)
        self.assertIn("_openhands_installed_versions", condition)
        self.assertIn("openhands_agent_server_version", condition)
        self.assertIn("openhands_automation_version", condition)

    def test_the_services_venv_is_separate_from_the_uv_toolchain(self):
        defaults = _load(ROLE / "defaults" / "main.yml")
        self.assertEqual(
            defaults["openhands_services_venv"],
            "{{ openhands_install_dir }}/services-py312",
        )
        self.assertEqual(
            defaults["openhands_uv_venv"], "{{ openhands_install_dir }}/uv"
        )
        tasks = _load(SERVICES)
        venv = _task(tasks, "Create the services virtualenv")
        self.assertIn("--clear", venv["ansible.builtin.command"]["argv"])
        creates = venv["args"]["creates"]
        self.assertEqual(
            creates,
            "{{ openhands_services_venv }}/.python-{{ openhands_services_python_version }}",
        )
        self.assertNotIn("/bin/python", creates)
        self.assertIn("{{ openhands_services_python_version }}", creates)
        marker = _task(tasks, "Mark the services virtualenv's Python version")
        self.assertEqual(marker["ansible.builtin.copy"]["dest"], creates)
        self.assertEqual(
            marker["ansible.builtin.copy"]["content"],
            "{{ openhands_services_python_version }}\n",
        )

    def test_the_services_venv_uses_uv_managed_python_from_the_release_cache(self):
        defaults = _load(ROLE / "defaults" / "main.yml")
        inventory = _load(ROOT / "tests" / "inventory_load" / "tofu_inventory.json")
        self.assertEqual(defaults["openhands_services_python_version"], "3.12")
        self.assertGreater(len(inventory["cache_proxy_urls"]["raw_cache"]), 0)
        self.assertIn(".get('raw_cache', [])", defaults["openhands_raw_cache_url"])
        self.assertIn(
            "/github_releases/astral-sh/python-build-standalone/releases/download",
            defaults["openhands_python_install_mirror"],
        )
        venv = _task(_load(SERVICES), "Create the services virtualenv")
        argv = venv["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[0], "{{ openhands_uv_venv }}/bin/uv")
        self.assertEqual(argv[1:4], ["venv", "--clear", "--python"])
        self.assertEqual(argv[4], "{{ openhands_services_python_version }}")
        self.assertEqual(
            venv["environment"],
            {
                "UV_PYTHON_INSTALL_DIR": "{{ openhands_python_install_dir }}",
                "UV_PYTHON_INSTALL_MIRROR": "{{ openhands_python_install_mirror }}",
            },
        )


class OpenHandsServiceGate(unittest.TestCase):
    def test_service_defaults_to_disabled(self):
        defaults = _load(ROLE / "defaults" / "main.yml")
        self.assertIs(defaults["openhands_service_enabled"], False)

    def test_every_secret_touching_task_is_gated_on_the_flag(self):
        tasks = _load(SERVICES)
        for name in (
            "Create the service secrets directory",
            "Read the generate-once service secrets",
            "Generate the service secrets a first enable is missing",
            "Resolve the effective service secrets",
        ):
            self.assertIn("openhands_service_enabled", _condition(_task(tasks, name)), name)

    def test_only_the_launcher_secrets_are_generated(self):
        tasks = _load(SERVICES)
        read = _task(tasks, "Read the generate-once service secrets")
        self.assertEqual(
            read["loop"], ["secret-key", "automation-kv-secret"]
        )
        require = _task(tasks, "Require the resolved service secrets")
        self.assertEqual(
            require["ansible.builtin.assert"]["that"],
            [
                "openhands_service_secrets['secret-key'] | length > 0",
                "openhands_service_secrets['automation-kv-secret'] | length > 0",
            ],
        )

    def test_the_service_gate_requires_both_key_files_only_when_enabled(self):
        defaults = _load(ROLE / "defaults" / "main.yml")
        self.assertEqual(defaults["openhands_router_key_file"], "")
        self.assertEqual(defaults["openhands_backend_key_file"], "")
        gate = _task(
            _load(ROLE / "tasks" / "assert_service_inputs.yml"),
            "Assert the service startup inputs",
        )
        self.assertIn("openhands_service_enabled | bool", _condition(gate))
        that = gate["ansible.builtin.assert"]["that"]
        self.assertIn("openhands_router_key_file | trim | length > 0", that)
        self.assertIn("openhands_backend_key_file | trim | length > 0", that)

    def test_the_launcher_stays_disabled_and_stopped_when_the_flag_is_off(self):
        manage = _task(_load(SERVICES), "Set the Agent Canvas launcher's enable state")
        systemd = manage["ansible.builtin.systemd_service"]
        self.assertEqual(systemd["name"], "openhands-canvas")
        self.assertEqual(systemd["enabled"], "{{ openhands_service_enabled | bool }}")
        self.assertEqual(
            systemd["state"],
            "{{ 'started' if (openhands_service_enabled | bool) else 'stopped' }}",
        )
        self.assertIs(systemd["daemon_reload"], True)

    def test_retired_units_and_environment_file_are_removed_on_every_converge(self):
        tasks = _load(SERVICES)
        find = _task(tasks, "Find the retired OpenHands units")
        self.assertIs(find["check_mode"], False)
        self.assertEqual(find["loop"], list(RETIRED_UNITS))
        stop = _task(tasks, "Stop and disable the retired OpenHands units")
        self.assertNotIn("when", stop)
        self.assertIn("stat.exists", stop["loop"])
        systemd = stop["ansible.builtin.systemd_service"]
        self.assertEqual(systemd["state"], "stopped")
        self.assertIs(systemd["enabled"], False)
        remove = _task(tasks, "Remove the retired OpenHands units, environment file and secrets")
        self.assertNotIn("when", remove)
        self.assertEqual(remove["ansible.builtin.file"]["state"], "absent")
        paths = " ".join(remove["loop"])
        for unit in RETIRED_UNITS:
            self.assertIn(f"/etc/systemd/system/{unit}.service", paths)
        self.assertIn("{{ openhands_install_dir }}/openhands.env", paths)
        for secret in ("session-api-key", "automation-local-api-key"):
            self.assertIn(f"{{{{ openhands_secrets_dir }}}}/{secret}", paths)

    def test_the_generate_once_secrets_are_never_regenerated_behind_a_file(self):
        tasks = _load(SERVICES)
        read = _task(tasks, "Read the generate-once service secrets")
        self.assertIn("openhands_secrets_dir", read["ansible.builtin.slurp"]["src"])
        generate = _task(tasks, "Generate the service secrets a first enable is missing")
        loop = " ".join(str(part) for part in generate["loop"].split())
        self.assertIn("rejectattr('content', 'defined')", loop)
        store = _task(tasks, "Store the generated service secrets")
        self.assertEqual(store["ansible.builtin.copy"]["mode"], "0600")
        self.assertIs(store["no_log"], True)
        self.assertEqual(store["notify"], "Restart the OpenHands launcher")


class OpenHandsRouterLLM(unittest.TestCase):
    def test_group_vars_do_not_resolve_the_router_key(self):
        text = GROUP_VARS.read_text(encoding="utf-8")
        self.assertNotIn("openhands_router_key", text)

    def test_the_apps_domain_scope_does_not_request_openhands_secrets(self):
        domain_groups = _load(DOMAIN_GROUPS)["openbao_secrets_domain_groups"]
        self.assertNotIn("openhands_host", domain_groups["apps"])

    def test_the_router_settings_stay_defaults_and_no_unit_reads_the_router_key(self):
        defaults = _load(ROLE / "defaults" / "main.yml")
        self.assertEqual(
            defaults["openhands_router_base_url"],
            "https://llm.{{ ingress_domain }}/v1",
        )
        self.assertEqual(defaults["openhands_router_model"], "small")
        text = UNIT.read_text(encoding="utf-8")
        self.assertNotIn("openhands_router_key_file", text)
        self.assertNotIn("LLM_API_KEY", text)
        self.assertFalse((ROLE / "templates" / "openhands.env.j2").exists())


class OpenHandsNoKeyValues(unittest.TestCase):
    def test_no_role_file_assigns_a_key_value(self):
        scanned = (
            sorted(ROLE.rglob("*.yml"))
            + sorted(ROLE.rglob("*.j2"))
            + [GROUP_VARS, ROLE / "README.md"]
        )
        self.assertGreaterEqual(len(scanned), 8)
        quoted_secret_assignment = re.compile(
            r"(key|secret|password)\s*[:=]\s*[\"'](?![\{\[])[^\"']{8,}[\"']",
            re.IGNORECASE,
        )
        for path in scanned:
            for line in path.read_text(encoding="utf-8").splitlines():
                self.assertIsNone(
                    quoted_secret_assignment.search(line),
                    f"{path.relative_to(ROOT)} carries a literal: {line.strip()!r}",
                )

    def test_the_verify_fixture_declares_no_secret_values(self):
        verify = _load(ROOT / "tests" / "template_render" / "verify" / "openhands.yml")
        play = verify[0]
        self.assertNotIn("openhands_router_key", play["vars"])
        self.assertNotIn("openhands_service_secrets", play["vars"])
        self.assertNotIn("openhands_backend_key", play["vars"])

    def test_the_units_render_without_any_key_value(self):
        text = UNIT.read_text(encoding="utf-8")
        for marker in (
            "Environment=LOCAL_BACKEND_API_KEY=",
            "Environment=OH_SECRET_KEY=",
            "Environment=AUTOMATION_KV_SECRET=",
            "LLM_API_KEY={{",
        ):
            self.assertNotIn(marker, text)

    def test_the_launcher_reads_each_key_only_through_a_loaded_credential(self):
        text = UNIT.read_text(encoding="utf-8")
        self.assertEqual(text.count("openhands_backend_key_file"), 1)
        self.assertIn(
            "LoadCredential=openhands-backend-key:{{ openhands_backend_key_file }}",
            text,
        )
        self.assertIn('"$$CREDENTIALS_DIRECTORY/openhands-backend-key"', text)
        self.assertIn('"$$CREDENTIALS_DIRECTORY/openhands-secret-key"', text)
        self.assertIn('"$$CREDENTIALS_DIRECTORY/openhands-automation-kv-secret"', text)
        self.assertNotIn("Environment=LOCAL_BACKEND_API_KEY", text)


if __name__ == "__main__":
    unittest.main()
