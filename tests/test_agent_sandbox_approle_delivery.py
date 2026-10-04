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


def _task(tasks, name):
    return next(task for task in tasks if task.get("name") == name)


class AgentSandboxCredentialContract(unittest.TestCase):
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

        service = (ROLE / "templates" / "zcode-feeder.service.j2").read_text()
        self.assertIn(
            "EnvironmentFile={{ agent_sandbox_dispatch_alert_env_file }}", service
        )
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

        secret_scope = (ROOT / "playbooks/site/00-load-and-telemetry.yml").read_text()
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
                "AGENT_DISPATCH_NTFY_ALERT_TOKEN=test\n"
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
                "https://ntfy.example.invalid|test|run fixture",
            )

            env_file.write_text(
                "AGENT_DISPATCH_NTFY_ALERT_URL="
                f"https://ntfy.example.invalid/$(touch {marker})\n"
                "AGENT_DISPATCH_NTFY_ALERT_TOKEN=test\n"
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
                "AGENT_DISPATCH_NTFY_ALERT_TOKEN=test\n"
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
                result_file.read_text(), f"{target.pw_uid}|test|run fixture"
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


if __name__ == "__main__":
    unittest.main()
