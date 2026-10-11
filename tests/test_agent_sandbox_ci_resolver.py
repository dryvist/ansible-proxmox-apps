from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "agent_sandbox"


def _task(tasks, name):
    return next(task for task in tasks if task.get("name") == name)


class AgentSandboxCiResolverContract(unittest.TestCase):
    def setUp(self):
        self.defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
        self.tasks = yaml.safe_load((ROLE / "tasks" / "main" / "ci_resolver.yml").read_text())
        self.install = _task(self.tasks, "Install CI resolver")
        self.install_tasks = self.install["block"]

    def test_ci_resolver_is_off_by_default_and_pinned(self):
        self.assertIs(self.defaults["agent_sandbox_ci_resolver_enabled"], False)
        self.assertIs(self.defaults["agent_sandbox_ci_resolver_shadow"], True)
        self.assertEqual(self.defaults["agent_sandbox_ci_resolver_app_id"], "4282473")
        self.assertEqual(self.defaults["agent_sandbox_ci_resolver_github_mount"], "github-admin")
        self.assertEqual(self.defaults["agent_sandbox_ci_resolver_permission_set"], "ci-resolver-dryvist")
        self.assertEqual(self.defaults["agent_sandbox_ci_resolver_approle_dir"], "/etc/ci-resolver/approle")
        self.assertIn(
            "OPENBAO_APPROLE_CI_RESOLVER_ROLE_ID",
            self.defaults["agent_sandbox_ci_resolver_role_id"],
        )
        self.assertIn(
            "OPENBAO_APPROLE_CI_RESOLVER_SECRET_ID",
            self.defaults["agent_sandbox_ci_resolver_secret_id"],
        )
        self.assertEqual(
            self.defaults["agent_sandbox_ci_resolver_source_commit"],
            "{{ agent_sandbox_dispatch_source_commit }}",
        )
        self.assertRegex(self.defaults["agent_sandbox_dispatch_source_commit"], r"^[0-9a-f]{40}$")
        self.assertRegex(self.defaults["agent_sandbox_ci_resolver_source_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(self.install["when"], "agent_sandbox_ci_resolver_enabled | bool")

        fetch = _task(self.install_tasks, "Fetch the pinned CI resolver source on the controller")
        self.assertEqual(
            fetch["ansible.builtin.get_url"]["checksum"],
            "sha256:{{ agent_sandbox_ci_resolver_source_sha256 }}",
        )
        source = _task(self.install_tasks, "Install the pinned CI resolver source")
        self.assertEqual(
            source["ansible.builtin.copy"]["dest"],
            "{{ agent_sandbox_ci_resolver_script }}",
        )
        self.assertEqual(
            (
                source["ansible.builtin.copy"]["owner"],
                source["ansible.builtin.copy"]["group"],
                source["ansible.builtin.copy"]["mode"],
            ),
            ("root", "root", "0755"),
        )

    def test_ci_resolver_delivers_its_own_approle_for_the_service_user(self):
        validation = _task(self.tasks, "Validate CI resolver prerequisites")
        conditions = validation["ansible.builtin.assert"]["that"]
        self.assertIn("agent_sandbox_ci_resolver_role_id is string", conditions)
        self.assertIn("agent_sandbox_ci_resolver_role_id | trim | length > 0", conditions)
        self.assertIn("agent_sandbox_ci_resolver_secret_id is string", conditions)
        self.assertIn("agent_sandbox_ci_resolver_secret_id | trim | length > 0", conditions)

        service_template = (ROLE / "templates" / "ci-resolver.service.j2").read_text()
        self.assertIn("User={{ agent_sandbox_dispatch_user }}", service_template)
        self.assertIn("Group={{ agent_sandbox_dispatch_user }}", service_template)

        directory = _task(
            self.install_tasks, "Create the CI resolver AppRole credential directory"
        )
        directory_settings = directory["ansible.builtin.file"]
        self.assertEqual(directory_settings["path"], "{{ agent_sandbox_ci_resolver_approle_dir }}")
        self.assertEqual(
            (directory_settings["owner"], directory_settings["group"], directory_settings["mode"]),
            ("root", "{{ agent_sandbox_dispatch_user }}", "0750"),
        )

        deliveries = {
            "Install the CI resolver AppRole role ID": (
                "{{ agent_sandbox_ci_resolver_approle_dir }}/role_id",
                "{{ agent_sandbox_ci_resolver_role_id }}",
            ),
            "Install the CI resolver AppRole secret ID": (
                "{{ agent_sandbox_ci_resolver_approle_dir }}/secret_id",
                "{{ agent_sandbox_ci_resolver_secret_id }}",
            ),
        }
        for task_name, (destination, content) in deliveries.items():
            with self.subTest(task=task_name):
                task = _task(self.install_tasks, task_name)
                settings = task["ansible.builtin.copy"]
                self.assertEqual((settings["dest"], settings["content"]), (destination, content))
                self.assertEqual(
                    (settings["owner"], settings["group"], settings["mode"]),
                    ("root", "{{ agent_sandbox_dispatch_user }}", "0440"),
                )
                self.assertIs(task["no_log"], True)

        cleanup = _task(self.tasks, "Remove CI resolver files and workbook checkout when disabled")
        self.assertIn("{{ agent_sandbox_ci_resolver_approle_dir }}", cleanup["loop"])

    def test_ci_resolver_helper_uses_permission_set_without_secret_lookup(self):
        helper = (ROLE / "templates" / "ci-resolver-secret.sh.j2").read_text()
        self.assertIn(
            '"${BAO_ADDR%/}/v1/{{ agent_sandbox_ci_resolver_github_mount }}/token/'
            '{{ agent_sandbox_ci_resolver_permission_set }}"',
            helper,
        )
        self.assertNotIn(
            '"${BAO_ADDR%/}/v1/{{ agent_sandbox_ci_resolver_github_mount }}/token"',
            helper,
        )
        self.assertIn("printf '{}'", helper)
        self.assertNotIn("GITHUB_AGENTS_INSTALLATION_ID", helper)
        self.assertIn(
            '"${BAO_ADDR%/}/v1/{{ agent_sandbox_ci_resolver_secret_path }}"',
            helper,
        )

    def test_helper_and_environment_file_are_root_owned_with_required_modes(self):
        expected = {
            "Install the CI resolver secret helper": ("{{ agent_sandbox_ci_resolver_secret_helper }}", "0755"),
            "Install the CI resolver environment file": ("{{ agent_sandbox_ci_resolver_env_file }}", "0644"),
        }
        for task_name, (destination, mode) in expected.items():
            with self.subTest(task=task_name):
                task = _task(self.install_tasks, task_name)
                settings = task["ansible.builtin.template"]
                self.assertEqual(settings["dest"], destination)
                self.assertEqual(
                    (settings["owner"], settings["group"], settings["mode"]),
                    ("root", "root", mode),
                )

    def test_resolver_units_are_root_owned_and_disabled_units_are_removed(self):
        units = _task(self.install_tasks, "Install the CI resolver service and timers")
        settings = units["ansible.builtin.template"]
        self.assertEqual((settings["owner"], settings["group"], settings["mode"]), ("root", "root", "0644"))
        self.assertEqual(
            {item["dest"] for item in units["loop"]},
            {
                "ci-resolver.service",
                "ci-resolver-workbook.service",
                "ci-resolver-workbook.timer",
                "ci-resolver-learn.service",
                "ci-resolver-learn.timer",
            },
        )
        cleanup = _task(self.tasks, "Remove CI resolver files and workbook checkout when disabled")
        self.assertEqual(cleanup["when"], "not (agent_sandbox_ci_resolver_enabled | bool)")
        self.assertIn("/etc/systemd/system/ci-resolver.service", cleanup["loop"])
        self.assertIn("{{ agent_sandbox_ci_resolver_secret_helper }}", cleanup["loop"])


if __name__ == "__main__":
    unittest.main()
