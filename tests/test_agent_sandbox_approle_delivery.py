from pathlib import Path
import os
import pwd
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "agent_sandbox"
TASKS = ROLE / "tasks" / "main" / "approle.yml"
FIXTURE = ROOT / "tests" / "agent_sandbox_approle_delivery" / "missing_pair.yml"
ALERT_TOKEN_FIXTURE = "tk_" + "a" * 24


def _task(tasks, name):
    return next(task for task in tasks if task.get("name") == name)


class AgentSandboxCredentialContract(unittest.TestCase):
    def test_secret_reader_group_uses_name_keyed_getent_fields(self):
        tasks = yaml.safe_load(
            (ROLE / "tasks" / "main" / "deploy.yml").read_text()
        )
        lookup = _task(tasks, "Read the private ZCode service secret-reader group")
        self.assertEqual(
            lookup["ansible.builtin.getent"],
            {
                "database": "group",
                "key": "{{ agent_sandbox_zcode_web_secret_group }}",
            },
        )

        guard = _task(
            tasks, "Require the ZCode service secret-reader group to have no host members"
        )
        getent_facts = "{{ _agent_sandbox_zcode_secret_group.ansible_facts.getent_group }}"
        group_name = "{{ agent_sandbox_zcode_web_secret_group }}"
        self.assertEqual(guard["vars"]["_zcode_secret_group_facts"], getent_facts)
        self.assertEqual(guard["vars"]["_zcode_secret_group_name"], group_name)
        self.assertEqual(
            guard["vars"]["_zcode_secret_group_members"],
            "{{ _zcode_secret_group_facts[_zcode_secret_group_name][2] }}",
        )
        container = _task(
            tasks, "Set the ZCode service container's supplemental secret group"
        )
        self.assertEqual(
            container["vars"]["_zcode_secret_group_facts"], getent_facts
        )
        self.assertEqual(container["vars"]["_zcode_secret_group_name"], group_name)
        self.assertEqual(
            container["ansible.builtin.set_fact"]["agent_sandbox_zcode_web_secret_gid"],
            "{{ _zcode_secret_group_facts[_zcode_secret_group_name][1] }}",
        )

    def test_dispatcher_alert_settings_follow_dispatch_access_gate(self):
        role_tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        delivery = _task(role_tasks, "Deliver refused-login alert settings")
        self.assertEqual(
            delivery["when"], "agent_sandbox_dispatch_access_enabled | bool"
        )

    def test_credentials_are_tagged_and_restricted(self):
        defaults = (ROLE / "defaults" / "main.yml").read_text()
        self.assertIn("OPENBAO_APPROLE_OPEN_LLM_ROLE_ID", defaults)
        self.assertIn("OPENBAO_APPROLE_OPEN_LLM_SECRET_ID", defaults)

        role_tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        delivery = _task(role_tasks, "Deliver sandbox credentials")
        self.assertEqual(delivery["ansible.builtin.import_tasks"], "main/approle.yml")
        self.assertEqual(delivery["tags"], ["agent_sandbox", "agent_sandbox_credentials"])

        tasks = yaml.safe_load(TASKS.read_text())
        directory = _task(tasks, "Create dispatcher credential directory")["ansible.builtin.file"]
        self.assertEqual(
            (directory["owner"], directory["group"], directory["mode"]),
            ("root", "{{ agent_sandbox_dispatch_user }}", "0750"),
        )
        copies = [task["ansible.builtin.copy"] for task in tasks if "ansible.builtin.copy" in task]
        self.assertEqual(len(copies), 2)
        self.assertEqual(
            {copy["dest"] for copy in copies},
            {
                "/etc/agent-dispatch/approle/role_id",
                "/etc/agent-dispatch/approle/secret_id",
            },
        )
        for task, copy in zip(
            [task for task in tasks if "ansible.builtin.copy" in task], copies, strict=True
        ):
            self.assertIs(task["no_log"], True)
            self.assertEqual(
                (copy["owner"], copy["group"], copy["mode"]),
                ("root", "{{ agent_sandbox_dispatch_user }}", "0440"),
            )

        site = yaml.safe_load((ROOT / "playbooks/site/03-notifications-and-core-apps.yml").read_text())
        play = next(play for play in site if play.get("hosts") == "agent_sandbox_host")
        self.assertIn("agent_sandbox_credentials", play["tags"])
        block = next(task for task in play["tasks"] if "block" in task)
        self.assertIn("agent_sandbox_credentials", block["tags"])
        include = _task(block["block"], "Include agent_sandbox role")
        self.assertIn("agent_sandbox_credentials", include["tags"])
        self.assertEqual(
            include["ansible.builtin.include_role"]["apply"]["tags"], ["agent_sandbox"]
        )

        compose = (ROLE / "templates" / "docker-compose.yml.j2").read_text()
        self.assertNotIn("/etc/agent-dispatch/approle", compose)

    def test_dispatcher_alert_secret_is_written_to_root_only_env_file(self):
        tasks = yaml.safe_load(
            (ROLE / "tasks" / "main" / "dispatcher_alert.yml").read_text()
        )
        directory = _task(tasks, "Create the private dispatcher alert settings directory")
        directory_settings = directory["ansible.builtin.file"]
        self.assertEqual(
            (directory_settings["owner"], directory_settings["group"], directory_settings["mode"]),
            ("root", "root", "0700"),
        )
        delivery = _task(tasks, "Install dispatcher refused-login alert settings")
        template = delivery["ansible.builtin.template"]
        self.assertEqual(
            (template["owner"], template["group"], template["mode"]),
            ("root", "root", "0600"),
        )
        self.assertIs(delivery["no_log"], True)

        alert_template = (ROLE / "templates" / "dispatcher-alert.env.j2").read_text()
        self.assertIn("AGENT_DISPATCH_NTFY_ALERT_URL=", alert_template)
        self.assertIn("AGENT_DISPATCH_NTFY_ALERT_TOKEN=", alert_template)
        self.assertIn("NTFY_AI_JOBS_TOKEN", (ROLE / "defaults" / "main.yml").read_text())

        ssh_wrapper = (ROLE / "templates" / "dispatch-ssh-with-alert.sh.j2").read_text()
        self.assertIn("sudo -n {{ agent_sandbox_dispatch_root_command }}", ssh_wrapper)
        ssh_root = (ROLE / "templates" / "dispatch-ssh-root.sh.j2").read_text()
        self.assertIn("done < \"{{ agent_sandbox_dispatch_alert_env_file }}\"", ssh_root)
        self.assertIn(
            'exec /usr/sbin/runuser --preserve-environment --user "{{ agent_sandbox_dispatch_user }}" -- "{{ agent_sandbox_dispatch_upstream_command }}"',
            ssh_root,
        )
        self.assertNotIn(". \"{{ agent_sandbox_dispatch_alert_env_file }}\"", ssh_root)
        self.assertNotIn("sudo", ssh_root)
        sudoers = (ROLE / "templates" / "dispatch-sudoers.j2").read_text()
        self.assertIn('env_keep += "SSH_ORIGINAL_COMMAND"', sudoers)

        secret_scope = (ROOT / "playbooks/tasks/publish_secret_domain_facts.yml").read_text()
        prefetch_play = (ROOT / "playbooks/site/00-load-and-telemetry.yml").read_text()
        self.assertIn(
            "ansible.builtin.import_tasks: ../tasks/publish_secret_domain_facts.yml",
            prefetch_play,
        )
        self.assertIn("bao_apps_secrets: {}", secret_scope)
        self.assertIn(
            "when: inventory_hostname in groups.get('agent_sandbox_host', [])",
            secret_scope,
        )

    def test_dispatcher_alert_helper_parses_env_without_shell_evaluation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            env_file = temp / "dispatcher-alert.env"
            result_file = temp / "result"
            upstream = temp / "dispatcher"
            runuser = temp / "runuser"
            marker = temp / "executed"
            upstream.write_text(
                "#!/bin/sh\nprintf '%s|%s|%s' \"$AGENT_DISPATCH_NTFY_ALERT_URL\" "
                f'"$AGENT_DISPATCH_NTFY_ALERT_TOKEN" "$SSH_ORIGINAL_COMMAND" > "{result_file}"\n'
            )
            upstream.chmod(0o755)
            runuser.write_text(
                "#!/bin/sh\n"
                "[ \"$1\" = --preserve-environment ] && [ \"$2\" = --user ] && "
                "[ \"$4\" = -- ] || exit 64\n"
                "shift 4\nexec \"$@\"\n"
            )
            runuser.chmod(0o755)
            helper = (
                (ROLE / "templates" / "dispatch-ssh-root.sh.j2")
                .read_text()
                .replace("{{ agent_sandbox_dispatch_alert_env_file }}", str(env_file))
                .replace("{{ agent_sandbox_dispatch_user }}", "agent-dispatch")
                .replace("{{ agent_sandbox_dispatch_upstream_command }}", str(upstream))
                .replace("/usr/sbin/runuser", str(runuser))
            )
            helper_file = temp / "dispatcher-root-helper"
            helper_file.write_text(helper)
            helper_file.chmod(0o755)
            env_file.write_text(
                "AGENT_DISPATCH_NTFY_ALERT_URL=https://ntfy.example.invalid\n"
                f"AGENT_DISPATCH_NTFY_ALERT_TOKEN={ALERT_TOKEN_FIXTURE}\n"
            )
            env_file.chmod(0o600)
            process_env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "SSH_ORIGINAL_COMMAND": "run fixture",
            }

            result = subprocess.run(
                ["bash", str(helper_file)], env=process_env, capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result_file.read_text(),
                f"https://ntfy.example.invalid|{ALERT_TOKEN_FIXTURE}|run fixture",
            )

            env_file.write_text(
                "AGENT_DISPATCH_NTFY_ALERT_URL="
                f"https://ntfy.example.invalid/$(touch {marker})\n"
                f"AGENT_DISPATCH_NTFY_ALERT_TOKEN={ALERT_TOKEN_FIXTURE}\n"
            )
            result = subprocess.run(
                ["bash", str(helper_file)], env=process_env, capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 78)
            self.assertFalse(marker.exists())

    def test_dispatcher_alert_helper_drops_effective_uid_when_running_as_root(self):
        runuser_path = Path("/usr/sbin/runuser")
        if os.name != "posix" or os.geteuid() != 0 or not runuser_path.is_file():
            self.skipTest("requires a root Linux test runner with util-linux runuser")
        try:
            target = pwd.getpwnam("nobody")
        except KeyError:
            self.skipTest("requires the standard nobody account")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            temp.chmod(0o755)
            env_file = temp / "dispatcher-alert.env"
            result_file = temp / "result"
            upstream = temp / "dispatcher"
            upstream.write_text(
                "#!/bin/sh\n"
                f"printf '%s|%s|%s' \"$(/usr/bin/id -u)\" "
                f'"$AGENT_DISPATCH_NTFY_ALERT_TOKEN" "$SSH_ORIGINAL_COMMAND" > "{result_file}"\n'
            )
            upstream.chmod(0o755)
            result_file.touch(mode=0o666)
            result_file.chmod(0o666)
            env_file.write_text(
                "AGENT_DISPATCH_NTFY_ALERT_URL=https://ntfy.example.invalid\n"
                f"AGENT_DISPATCH_NTFY_ALERT_TOKEN={ALERT_TOKEN_FIXTURE}\n"
            )
            env_file.chmod(0o600)
            helper = (
                (ROLE / "templates" / "dispatch-ssh-root.sh.j2")
                .read_text()
                .replace("{{ agent_sandbox_dispatch_alert_env_file }}", str(env_file))
                .replace("{{ agent_sandbox_dispatch_user }}", "nobody")
                .replace("{{ agent_sandbox_dispatch_upstream_command }}", str(upstream))
            )
            helper_file = temp / "dispatcher-root-helper"
            helper_file.write_text(helper)
            helper_file.chmod(0o755)

            result = subprocess.run(
                ["/bin/bash", str(helper_file)],
                env={"PATH": "/usr/bin:/bin", "SSH_ORIGINAL_COMMAND": "run fixture"},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result_file.read_text(), f"{target.pw_uid}|{ALERT_TOKEN_FIXTURE}|run fixture"
            )

    def test_missing_pair_fails_and_credential_tag_runs_alone(self):
        result = subprocess.run(
            [
                "ansible-playbook",
                str(FIXTURE),
                "-i",
                "localhost,",
                "-c",
                "local",
                "--tags",
                "agent_sandbox_credentials",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("The dispatcher credential pair must include non-empty role ID and secret ID values", output)
        self.assertNotIn("Prepare the restricted dispatcher account", output)
        self.assertNotIn("Deploy the egress boundary network", output)


class AgentSandboxCiResolverContract(unittest.TestCase):
    def setUp(self):
        self.defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
        self.tasks = yaml.safe_load((ROLE / "tasks" / "main" / "ci_resolver.yml").read_text())
        self.install = _task(self.tasks, "Install CI resolver")
        self.install_tasks = self.install["block"]

    def test_ci_resolver_is_off_by_default_and_pinned(self):
        self.assertIs(self.defaults["agent_sandbox_ci_resolver_enabled"], False)
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
