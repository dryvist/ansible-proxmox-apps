"""Opt-in default-bridge proxy path: the compose port, the docker0 address
guard, the allowlist merge and the openhands_host group variables."""

from pathlib import Path
import unittest

import yaml
from ansible.errors import AnsibleError

from app_agent_helpers import _render, _task
from test_agent_sandbox_zcode_cribl import render, render_text

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "agent_sandbox"
FLAG = "agent_sandbox_default_bridge_proxy_enabled"
GROUP_VARS = ROOT / "inventory" / "group_vars" / "openhands_host.yml"
DOCKER0_FACTS = {"docker0": {"ipv4": {"address": "192.0.2.53"}}}

TOFU_FIXTURE = {
    "cache_proxy_urls": {
        "npm_cache": ["http://npm-cache.example.invalid:4873"],
        "pypi_cache": ["https://pypi-cache.example.invalid:3141"],
    }
}


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def render_compose(enabled: bool) -> dict:
    variables = dict(load(ROLE / "defaults/main/00-runtime.yml"))
    variables.update(
        {
            "ansible_managed": "test",
            "ansible_facts": DOCKER0_FACTS,
            FLAG: enabled,
            "agent_sandbox_zcode_web_enabled": False,
            "agent_sandbox_zcode_web_bind_address": "192.0.2.20",
            "agent_sandbox_zcode_web_secret_gid": 1901,
            "agent_sandbox_git_mirror_url": "https://mirror.example.invalid/public",
            "agent_sandbox_docs_checkout_path": "/srv/agent-docs",
        }
    )
    # Defaults reference each other; resolve the ones that need no host facts.
    for _ in range(3):
        for key, value in list(variables.items()):
            if isinstance(value, str) and "{{" in value:
                try:
                    variables[key] = _render(value, variables)
                except AnsibleError:
                    pass
    return render(ROLE / "templates/docker-compose.yml.j2", variables)


def rendered_allowlist(static: dict, extra: list) -> str:
    return render_text(
        ROLE / "templates/allowed-domains.txt.j2",
        {
            "ansible_managed": "test",
            "agent_sandbox_egress_domains": static,
            "agent_sandbox_extra_egress_domains": extra,
        },
    )


def rendered_extra_domains() -> list:
    variables = {
        "ingress_domain": "example.invalid",
        "hostvars": {"localhost": {"tofu_data": TOFU_FIXTURE}},
    }
    return [
        _render(item, variables)
        for item in load(GROUP_VARS)["agent_sandbox_extra_egress_domains"]
    ]


class ComposePortPublishing(unittest.TestCase):
    def test_disabled_compose_publishes_no_squid_port(self):
        compose = render_compose(False)

        self.assertNotIn("ports", compose["services"]["squid"])

    def test_enabled_compose_publishes_the_proxy_port_on_the_docker0_address(self):
        compose = render_compose(True)

        self.assertEqual(
            compose["services"]["squid"]["ports"],
            ["192.0.2.53:3128:3128"],
        )

    def test_deploy_gathers_and_requires_the_docker0_address_before_rendering(self):
        tasks = load(ROLE / "tasks/main/deploy.yml")
        names = [task.get("name") for task in tasks]
        render_index = names.index("Deploy agent sandbox docker-compose template")
        gather = _task(tasks, "Gather the Docker default bridge facts")
        guard = _task(
            tasks,
            "Require the default bridge address before publishing the proxy port",
        )

        self.assertEqual(tasks[render_index - 2 : render_index], [gather, guard])
        self.assertEqual(gather["ansible.builtin.setup"]["filter"], "ansible_docker0")
        self.assertEqual(gather["when"], f"{FLAG} | bool")
        self.assertEqual(guard["when"], f"{FLAG} | bool")
        for facts, expected in (
            (DOCKER0_FACTS, True),
            ({}, False),
            ({"docker0": {"active": True}}, False),
        ):
            with self.subTest(facts=facts):
                self.assertIs(
                    all(
                        _render("{{ " + condition + " }}", {"ansible_facts": facts})
                        for condition in guard["ansible.builtin.assert"]["that"]
                    ),
                    expected,
                )


class AllowlistMerge(unittest.TestCase):
    STATIC = {
        "first": ["alpha.example", "beta.example"],
        "second": ["gamma.example"],
    }

    def test_extra_domains_render_deduplicated_in_list_order(self):
        rendered = rendered_allowlist(self.STATIC, ["delta.example", "alpha.example", "delta.example"])
        lines = [line.strip() for line in rendered.splitlines() if line.strip()]
        domains = [line for line in lines if not line.startswith("#")]

        self.assertEqual(
            domains,
            [
                "alpha.example",
                "beta.example",
                "gamma.example",
                "delta.example",
            ],
        )
        self.assertEqual(domains.count("alpha.example"), 1)
        self.assertEqual(domains.count("delta.example"), 1)
        self.assertLess(lines.index("# extra"), lines.index("delta.example"))

    def test_empty_extra_list_renders_no_extra_group(self):
        rendered = rendered_allowlist(self.STATIC, [])

        self.assertNotIn("# extra", rendered)


class OpenHandsHostGroupVars(unittest.TestCase):
    def test_group_vars_enable_the_path_and_keep_zcode_web_off(self):
        raw = load(GROUP_VARS)

        self.assertIs(raw[FLAG], True)
        self.assertIs(raw["agent_sandbox_zcode_web_enabled"], False)

    def test_extra_domains_derive_cache_hosts_from_the_published_urls(self):
        self.assertEqual(
            rendered_extra_domains(),
            [
                "llm.example.invalid",
                "vikunja.example.invalid",
                "npm-cache.example.invalid",
                "pypi-cache.example.invalid",
            ],
        )
        # The cache hosts must come from the inventory URLs, not literals.
        text = GROUP_VARS.read_text(encoding="utf-8")
        self.assertIn("cache_proxy_urls", text)
        self.assertIn("urlsplit('hostname')", text)
        self.assertNotIn("npm-cache.example.invalid", text)
        self.assertNotIn("pypi-cache.example.invalid", text)


if __name__ == "__main__":
    unittest.main()
