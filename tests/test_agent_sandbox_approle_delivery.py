from pathlib import Path
import subprocess
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
