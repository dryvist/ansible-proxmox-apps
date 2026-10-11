"""The ZCode Web service is optional: off removes it from the compose project and the tasks."""

from pathlib import Path
import unittest

import yaml
from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "agent_sandbox"
FLAG = "agent_sandbox_zcode_web_enabled"
# Tasks that stay on because the dispatcher and alert settings share the directory.
ALWAYS_ON = {
    "Create the ZCode service credential mount directory",
    "Allow dispatcher traversal without listing secrets",
}


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def render_compose(enabled: bool) -> dict:
    variables = dict(load(ROLE / "defaults/main.yml"))
    variables.update(
        {
            "ansible_managed": "test",
            FLAG: enabled,
            "agent_sandbox_zcode_web_bind_address": "192.0.2.20",
            "agent_sandbox_zcode_web_secret_gid": 1901,
        }
    )
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    # Defaults reference each other; resolve the ones that need no host facts.
    for _ in range(3):
        for key, value in list(variables.items()):
            if isinstance(value, str) and "{{" in value:
                try:
                    variables[key] = templar.template(trust_as_template(value))
                except AnsibleError:
                    pass
    text = (ROLE / "templates/docker-compose.yml.j2").read_text(encoding="utf-8")
    return yaml.safe_load(templar.template(trust_as_template(text)))


def guarded(task: dict) -> bool:
    conditions = task.get("when", [])
    conditions = [conditions] if isinstance(conditions, str) else conditions
    return f"{FLAG} | bool" in conditions


def zcode_tasks(path: Path):
    return [
        task
        for task in load(path)
        if "ZCode" in task["name"] and task["name"] not in ALWAYS_ON
    ]


class ZcodeWebGate(unittest.TestCase):
    def test_role_default_keeps_the_service_on(self):
        self.assertIs(load(ROLE / "defaults/main.yml")[FLAG], True)

    def test_sandbox_guest_turns_it_off(self):
        self.assertIs(load(ROOT / "inventory/host_vars/ai-sandbox-01.yml")[FLAG], False)

    def test_compose_has_the_service_only_when_enabled(self):
        self.assertIn("zcode-web", render_compose(True)["services"])
        self.assertEqual(
            sorted(render_compose(False)["services"]), ["cribl-edge", "squid"]
        )

    def test_deploy_tasks_for_the_service_are_guarded(self):
        tasks = zcode_tasks(ROLE / "tasks/main/deploy.yml")
        self.assertGreaterEqual(len(tasks), 8)
        self.assertEqual([t["name"] for t in tasks if not guarded(t)], [])

    def test_probe_tasks_for_the_service_are_guarded(self):
        tasks = zcode_tasks(ROLE / "tasks/main/probe.yml")
        self.assertGreaterEqual(len(tasks), 3)
        self.assertEqual([t["name"] for t in tasks if not guarded(t)], [])


if __name__ == "__main__":
    unittest.main()
