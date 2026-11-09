"""The bounded compose-image pre-pull covers exactly the images the compose project renders."""

from pathlib import Path
import unittest

import yaml
from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "agent_sandbox"
DEPLOY = ROLE / "tasks/main/deploy.yml"
COMPOSE_TEMPLATE = ROLE / "templates/docker-compose.yml.j2"
VARS = ROLE / "vars/main.yml"
PULL_TASK = "Pull every agent sandbox compose image before compose recreates the containers"
COMPOSE_UP_TASK = "Deploy agent sandbox networks and proxy via docker compose"


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def deploy_tasks():
    return load(DEPLOY)


def task_by_name(name: str) -> dict:
    return next(task for task in deploy_tasks() if task.get("name") == name)


def resolve_variables(zcode_enabled: bool) -> dict:
    variables = dict(load(ROLE / "defaults/main/00-runtime.yml"))
    variables.update(
        {
            "ansible_managed": "test",
            "agent_sandbox_zcode_web_enabled": zcode_enabled,
            "agent_sandbox_zcode_web_bind_address": "192.0.2.20",
            "agent_sandbox_zcode_web_secret_gid": 1901,
            "agent_sandbox_git_mirror_url": "https://mirror.example.invalid/public",
            "agent_sandbox_docs_checkout_path": "/srv/agent-docs",
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
    return variables


def render_compose(variables: dict) -> dict:
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return yaml.safe_load(
        templar.template(trust_as_template(COMPOSE_TEMPLATE.read_text(encoding="utf-8")))
    )


def compose_images(variables: dict) -> list:
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return list(
        templar.template(trust_as_template(load(VARS)["agent_sandbox_compose_images"]))
    )


class ComposeImagePrePull(unittest.TestCase):
    def test_the_new_input_defaults_to_nine_hundred_seconds(self):
        defaults = load(ROLE / "defaults/main/00-runtime.yml")

        self.assertEqual(defaults["agent_sandbox_image_pull_timeout"], 900)

    def test_the_pull_task_sits_before_compose_up(self):
        names = [task["name"] for task in deploy_tasks()]

        self.assertLess(names.index(PULL_TASK), names.index(COMPOSE_UP_TASK))

    def test_the_only_image_pull_before_compose_up_is_the_bounded_one(self):
        tasks = deploy_tasks()
        compose_up = next(
            index
            for index, task in enumerate(tasks)
            if task["name"] == COMPOSE_UP_TASK
        )
        pulls = [
            task["name"]
            for task in tasks[:compose_up]
            if task.get("ansible.builtin.command", {}).get("argv", [])[0:2] == ["docker", "pull"]
        ]

        self.assertEqual(pulls, [PULL_TASK])

    def test_the_pull_task_loops_over_the_derived_compose_images(self):
        self.assertEqual(task_by_name(PULL_TASK)["loop"], "{{ agent_sandbox_compose_images }}")

    def test_the_pull_bound_comes_from_the_new_input(self):
        task = task_by_name(PULL_TASK)

        self.assertEqual(task["timeout"], "{{ agent_sandbox_image_pull_timeout }}")
        self.assertEqual(task["async"], "{{ agent_sandbox_image_pull_timeout }}")

    def test_the_compose_task_keeps_its_existing_bound(self):
        task = task_by_name(COMPOSE_UP_TASK)

        self.assertIsNone(task.get("async"))
        self.assertIsNone(task.get("timeout"))

    def test_the_derived_list_matches_the_compose_template(self):
        for zcode_enabled in (True, False):
            variables = resolve_variables(zcode_enabled)
            rendered = [
                service["image"]
                for service in render_compose(variables)["services"].values()
            ]

            with self.subTest(zcode_enabled=zcode_enabled):
                self.assertEqual(compose_images(variables), rendered)


if __name__ == "__main__":
    unittest.main()
