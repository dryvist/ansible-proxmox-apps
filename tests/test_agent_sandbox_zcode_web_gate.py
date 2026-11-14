"""The ZCode Web service is optional: off removes it from the compose project and the tasks."""

import json
import os
from pathlib import Path
import re
import unittest
from unittest import mock

import yaml
from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "agent_sandbox"
FLAG = "agent_sandbox_zcode_web_enabled"
DOCS_FLAG = "agent_sandbox_mirror_docs_enabled"
# The role default names this example repository; the deployment sets the real
# one through this environment variable, which the renovate manager tracks as
# its depName.
EXAMPLE_IMAGE_REPOSITORY = "ghcr.io/example-org/example-image"
ENV_IMAGE_REPOSITORY = "AGENT_SANDBOX_ZCODE_WEB_IMAGE_REPOSITORY"
# Tasks that stay on because the dispatcher and alert settings share the directory.
ALWAYS_ON = {
    "Create the ZCode service credential mount directory",
    "Allow dispatcher traversal without listing secrets",
}


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def render_compose(enabled: bool, docs_enabled: bool = False) -> dict:
    variables = dict(load(ROLE / "defaults/main/00-runtime.yml"))
    variables.update(
        {
            "ansible_managed": "test",
            FLAG: enabled,
            DOCS_FLAG: docs_enabled,
            "agent_sandbox_git_mirror_url": "https://mirror.example.invalid/public",
            "agent_sandbox_docs_checkout_path": "/srv/agent-docs",
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
    return any(f"{FLAG} | bool" in condition for condition in conditions)


def evaluate_image_refusal(enabled: bool) -> tuple[bool, bool, str]:
    """Evaluate the role's example-repository gate: (runs, passes, fail_msg)."""
    defaults = load(ROLE / "defaults/main/00-runtime.yml")
    templar = Templar(loader=DataLoader())
    # Resolve the default first: a trusted template never expands untrusted
    # strings nested inside it, so the condition must see the resolved image.
    image = templar.template(
        trust_as_template(defaults["agent_sandbox_zcode_web_image"])
    )
    templar.available_variables = {FLAG: enabled, "agent_sandbox_zcode_web_image": image}

    def condition(expression: str):
        # Bare assert/when expressions carry no template markers, so wrap them
        # to force evaluation instead of the identity render.
        return templar.template(trust_as_template("{{ " + expression + " }}"))

    task = next(
        task for task in load(ROLE / "tasks/main.yml")
        if "example image repository" in task["name"]
    )
    spec = task["ansible.builtin.assert"]
    runs = condition(task["when"])
    passes = condition(spec["that"][0])
    message = templar.template(trust_as_template(spec["fail_msg"]))
    return bool(runs), bool(passes), message


def zcode_tasks(path: Path):
    return [
        task
        for task in load(path)
        if "ZCode" in task["name"] and task["name"] not in ALWAYS_ON
    ]


class ZcodeWebGate(unittest.TestCase):
    def test_renovate_extracts_the_image_digest_from_role_defaults(self):
        config = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))
        manager = next(
            item for item in config["customManagers"]
            if ENV_IMAGE_REPOSITORY in " ".join(item.get("matchStrings", []))
        )
        files = [
            path for path in (ROLE / "defaults").rglob("*.yml")
            if any(
                re.search(pattern[1:-1], path.relative_to(ROOT).as_posix())
                for pattern in manager["managerFilePatterns"]
            )
        ]
        self.assertEqual(len(files), 1)
        text = files[0].read_text(encoding="utf-8")
        pattern = manager["matchStrings"][0].replace(
            "(?<currentDigest>", "(?P<currentDigest>"
        )
        match = re.search(pattern, text)
        self.assertIsNotNone(match)
        image = render_compose(True)["services"]["zcode-web"]["image"]
        self.assertEqual(
            image, EXAMPLE_IMAGE_REPOSITORY + "@" + match["currentDigest"]
        )
        with mock.patch.dict(
            os.environ, {ENV_IMAGE_REPOSITORY: manager["depNameTemplate"]}
        ):
            tracked = render_compose(True)["services"]["zcode-web"]["image"]
        self.assertEqual(
            tracked, manager["depNameTemplate"] + "@" + match["currentDigest"]
        )
        self.assertEqual(
            re.search(r"sha256:[a-f0-9]{64}", tracked).group(), match["currentDigest"]
        )

    def test_example_repository_refuses_while_enabled(self):
        runs, passes, message = evaluate_image_refusal(True)
        self.assertTrue(runs)
        self.assertFalse(passes)
        self.assertIn(ENV_IMAGE_REPOSITORY, message)
        self.assertIn("unset", message)

    def test_environment_repository_passes_while_enabled(self):
        repository = "registry.example.invalid/example-agent"
        with mock.patch.dict(os.environ, {ENV_IMAGE_REPOSITORY: repository}):
            runs, passes, _ = evaluate_image_refusal(True)
            image = render_compose(True)["services"]["zcode-web"]["image"]
        self.assertTrue(runs)
        self.assertTrue(passes)
        digest = re.search(r"sha256:[a-f0-9]{64}", image).group()
        self.assertEqual(image, repository + "@" + digest)

    def test_disabled_service_never_runs_the_refusal(self):
        runs, _passes, _message = evaluate_image_refusal(False)
        self.assertFalse(runs)

    def test_role_default_keeps_the_service_on(self):
        self.assertIs(load(ROLE / "defaults/main/00-runtime.yml")[FLAG], True)

    def test_sandbox_guest_turns_it_off(self):
        self.assertIs(load(ROOT / "inventory/host_vars/ai-sandbox-01.yml")[FLAG], False)

    def test_compose_has_the_service_only_when_enabled(self):
        self.assertIn("zcode-web", render_compose(True)["services"])
        self.assertEqual(
            sorted(render_compose(False)["services"]), ["cribl-edge", "squid"]
        )

    def test_docs_mount_and_mirror_url_are_feature_gated(self):
        compose = render_compose(True, docs_enabled=True)["services"]["zcode-web"]
        self.assertIn(
            "GIT_MIRROR_URL=https://mirror.example.invalid/public",
            compose["environment"],
        )
        self.assertIn(
            {
                "type": "bind",
                "source": "/srv/agent-docs",
                "target": "/docs",
                "read_only": True,
                "bind": {"create_host_path": False},
            },
            compose["volumes"],
        )
        disabled = render_compose(True)["services"]["zcode-web"]
        self.assertFalse(
            any(item.startswith("GIT_MIRROR_URL=") for item in disabled["environment"])
        )
        self.assertFalse(
            any(item.get("target") == "/docs" for item in disabled["volumes"])
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
