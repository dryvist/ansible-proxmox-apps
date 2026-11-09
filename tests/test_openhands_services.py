"""OpenHands service contract: pinned installs that resolve through the
site's PyPI cache, units and secrets gated on openhands_service_enabled, the
router LLM wiring, and no key value anywhere in the repository."""

from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "openhands"
SERVICES = ROOT / "roles" / "openhands" / "tasks" / "services.yml"
GROUP_VARS = ROOT / "inventory" / "group_vars" / "openhands_host.yml"
DOMAIN_GROUPS = ROOT / "playbooks" / "site" / "vars" / "openbao_secrets_domain_groups.yml"

# A rendered file must never carry a real secret; the templates reference
# variables and the verify-play fixtures use this placeholder.
PLACEHOLDER = "test-placeholder"


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
        self.assertEqual(install["notify"], "Restart the OpenHands services")

    def test_install_reinstalls_only_when_a_pin_is_not_installed(self):
        tasks = _load(SERVICES)
        read = _task(tasks, "Read the installed service releases")
        self.assertIs(read["changed_when"], False)
        self.assertIs(read["failed_when"], False)
        self.assertIs(read["check_mode"], False)
        install = _task(tasks, "Install the agent server and automation through the PyPI cache")
        self.assertIs(install["changed_when"], True)
        condition = " ".join(str(part) for part in install["when"].split())
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
        venv = _task(_load(SERVICES), "Create the services virtualenv")
        self.assertEqual(
            venv["args"]["creates"], "{{ openhands_services_venv }}/bin/python"
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
        self.assertEqual(argv[1:3], ["venv", "--python"])
        self.assertEqual(argv[3], "{{ openhands_services_python_version }}")
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
            "Require the service inputs when enabled",
            "Create the service secrets directory",
            "Create the automation state directory",
            "Read the generate-once service secrets",
            "Generate the service secrets a first enable is missing",
            "Resolve the effective service secrets",
            "Render the service environment file",
        ):
            self.assertIn("openhands_service_enabled", _condition(_task(tasks, name)), name)

    def test_the_units_stay_disabled_and_stopped_when_the_flag_is_off(self):
        manage = _task(_load(SERVICES), "Set the OpenHands services' enable state")
        systemd = manage["ansible.builtin.systemd_service"]
        self.assertEqual(systemd["enabled"], "{{ openhands_service_enabled | bool }}")
        self.assertEqual(
            systemd["state"],
            "{{ 'started' if (openhands_service_enabled | bool) else 'stopped' }}",
        )
        self.assertEqual(
            manage["loop"], ["openhands-agent-server", "openhands-automation"]
        )

    def test_the_environment_file_is_removed_when_disabled(self):
        tasks = _load(SERVICES)
        removal = _task(tasks, "Remove the service environment file when disabled")
        self.assertEqual(removal["ansible.builtin.file"]["state"], "absent")
        self.assertIn("not (openhands_service_enabled | bool)", _condition(removal))

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
        self.assertEqual(store["notify"], "Restart the OpenHands services")


class OpenHandsServiceUnits(unittest.TestCase):
    def test_units_render_through_the_template_render_harness(self):
        harness = _load(ROOT / "tests" / "template_render" / "verify_templates.yml")
        plays = [play.get("import_playbook") for play in harness if "import_playbook" in play]
        self.assertIn("verify/openhands.yml", plays)

    def test_units_wire_the_shared_hardening_template(self):
        for unit in (
            "openhands-agent-server.service.j2",
            "openhands-automation.service.j2",
        ):
            text = (ROLE / "templates" / unit).read_text(encoding="utf-8")
            self.assertIn(
                "{{ lookup('ansible.builtin.file', _service_hardening_template) }}", text
            )
            self.assertIn("ReadWritePaths={{ openhands_state_dir }}", text)
            self.assertIn("Restart=on-failure", text)
        install = _task(_load(SERVICES), "Install the service units")
        self.assertIn(
            "_service_hardening_template",
            str(install["vars"]),
        )
        self.assertEqual(
            install["vars"]["_service_hardening_template"],
            "{{ role_path }}/../_shared/templates/systemd-service-hardening.conf.j2",
        )

    def test_units_bind_loopback_and_run_as_the_service_user(self):
        for unit, exec_line in (
            (
                "openhands-agent-server.service.j2",
                "agent-server --host 127.0.0.1 --port {{ openhands_agent_server_port }}",
            ),
            (
                "openhands-automation.service.j2",
                "uvicorn openhands.automation.app:app --host 127.0.0.1 --port {{ openhands_automation_port }}",
            ),
        ):
            text = (ROLE / "templates" / unit).read_text(encoding="utf-8")
            self.assertIn("User={{ openhands_user }}", text)
            self.assertIn("WorkingDirectory={{ openhands_state_dir }}", text)
            self.assertIn("{{ openhands_services_venv }}/bin/" + exec_line, text)

    def test_the_environment_file_is_loaded_only_while_enabled(self):
        for unit in (
            "openhands-agent-server.service.j2",
            "openhands-automation.service.j2",
        ):
            text = (ROLE / "templates" / unit).read_text(encoding="utf-8")
            self.assertIn("{% if openhands_service_enabled | bool %}", text)
            self.assertIn("EnvironmentFile={{ openhands_service_env_file }}", text)


class OpenHandsRouterLLM(unittest.TestCase):
    def test_group_vars_resolve_the_router_key_bao_first(self):
        text = GROUP_VARS.read_text(encoding="utf-8")
        self.assertIn(
            'openhands_router_key: "{{ bao_apps_secrets.openhands_router_key | default(\'\', true) }}"',
            text,
        )

    def test_the_apps_domain_scope_names_the_openhands_group(self):
        domain_groups = _load(DOMAIN_GROUPS)["openbao_secrets_domain_groups"]
        self.assertIn("openhands_host", domain_groups["apps"])

    def test_the_env_file_carries_the_router_llm_settings(self):
        defaults = _load(ROLE / "defaults" / "main.yml")
        self.assertEqual(
            defaults["openhands_router_base_url"],
            "https://llm.{{ ingress_domain }}/v1",
        )
        self.assertEqual(defaults["openhands_router_model"], "small")
        env = (ROLE / "templates" / "openhands.env.j2").read_text(encoding="utf-8")
        self.assertIn("LLM_MODEL={{ openhands_router_model }}", env)
        self.assertIn("LLM_BASE_URL={{ openhands_router_base_url }}", env)
        self.assertIn("LLM_API_KEY={{ openhands_router_key }}", env)

    def test_the_automation_runs_in_local_agent_server_mode(self):
        env = (ROLE / "templates" / "openhands.env.j2").read_text(encoding="utf-8")
        self.assertIn(
            "AUTOMATION_AGENT_SERVER_URL=http://127.0.0.1:{{ openhands_agent_server_port }}", env
        )
        self.assertIn(
            "AUTOMATION_AGENT_SERVER_API_KEY={{ openhands_service_secrets['session-api-key'] }}",
            env,
        )
        self.assertIn(
            "AUTOMATION_DB_URL=sqlite+aiosqlite:///{{ openhands_automation_db_path }}", env
        )
        self.assertIn("AUTOMATION_KV_SECRET={{ openhands_service_secrets['automation-kv-secret'] }}", env)
        self.assertIn(
            "AUTOMATION_LOCAL_API_KEY={{ openhands_service_secrets['automation-local-api-key'] }}", env
        )


class OpenHandsNoKeyValues(unittest.TestCase):
    def test_no_role_file_assigns_a_key_value(self):
        """Every secret reaching a rendered file flows through a variable or
        the generate-once files; no line in the role or its group_vars carries
        a literal credential."""
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

    def test_the_verify_fixture_declares_only_placeholder_values(self):
        verify = _load(ROOT / "tests" / "template_render" / "verify" / "openhands.yml")
        play = verify[0]
        self.assertEqual(play["vars"]["openhands_router_key"], PLACEHOLDER)
        for name, value in play["vars"]["openhands_service_secrets"].items():
            self.assertEqual(
                value, PLACEHOLDER, f"fixture secret {name} is not the placeholder"
            )

    def test_the_units_render_without_any_key_value(self):
        for unit in (
            "openhands-agent-server.service.j2",
            "openhands-automation.service.j2",
        ):
            text = (ROLE / "templates" / unit).read_text(encoding="utf-8")
            for marker in ("{{ openhands_router_key", "LLM_API_KEY=", "OH_SECRET_KEY="):
                self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
