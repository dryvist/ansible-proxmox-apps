"""Contract for the opt-in default-bridge proxy path: the compose port
publishes on the Docker default bridge address only, the static Squid
allowlist merges the extra domains, and the openhands_host group variables
turn the path on with derived destinations."""

from pathlib import Path
import unittest

import yaml
from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "agent_sandbox"
FLAG = "agent_sandbox_default_bridge_proxy_enabled"
GROUP_VARS = ROOT / "inventory" / "group_vars" / "openhands_host.yml"

TOFU_FIXTURE = {
    "cache_proxy_urls": {
        "npm_cache": ["http://npm-cache.example.invalid:4873"],
        "pypi_cache": ["https://pypi-cache.example.invalid:3141"],
    }
}


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def render_text(template_path: Path, variables: dict) -> str:
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(template_path.read_text(encoding="utf-8")))


def render_compose(enabled: bool) -> dict:
    variables = dict(load(ROLE / "defaults/main/00-runtime.yml"))
    variables.update(
        {
            "ansible_managed": "test",
            FLAG: enabled,
            "agent_sandbox_default_bridge_proxy_address": "192.0.2.53",
            "agent_sandbox_zcode_web_enabled": False,
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
    text = (ROLE / "templates/docker-compose.yml.j2").read_text(encoding="utf-8")
    return yaml.safe_load(templar.template(trust_as_template(text)))


def rendered_allowlist(static: dict, extra: list) -> str:
    return render_text(
        ROLE / "templates/allowed-domains.txt.j2",
        {
            "ansible_managed": "test",
            "agent_sandbox_egress_domains": static,
            "agent_sandbox_extra_egress_domains": extra,
        },
    )


def rendered_group_vars(raw: dict) -> dict:
    variables = {
        "agent_sandbox_proxy_port": 3128,
        "ingress_domain": "example.invalid",
        "hostvars": {"localhost": {"tofu_data": TOFU_FIXTURE}},
    }
    rendered = {}
    for key, value in raw.items():
        if isinstance(value, str) and "{{" in value:
            rendered[key] = render_text_value(value, variables)
        elif isinstance(value, list):
            rendered[key] = [
                render_text_value(item, variables)
                if isinstance(item, str) and "{{" in item
                else item
                for item in value
            ]
        else:
            rendered[key] = value
    return rendered


def render_text_value(value: str, variables: dict) -> str:
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(value))


class ComposePortPublishing(unittest.TestCase):
    def test_disabled_compose_publishes_no_squid_port(self):
        compose = render_compose(False)

        self.assertNotIn("ports", compose["services"]["squid"])

    def test_enabled_compose_publishes_the_proxy_port_on_the_bridge_address(self):
        compose = render_compose(True)

        self.assertEqual(
            compose["services"]["squid"]["ports"],
            ["192.0.2.53:3128:3128"],
        )
        self.assertNotIn(
            "0.0.0.0",
            " ".join(compose["services"]["squid"]["ports"]),
        )

    def test_deploy_asserts_the_bridge_address_before_rendering(self):
        tasks = load(ROLE / "tasks/main/deploy.yml")
        render_index = next(
            index
            for index, task in enumerate(tasks)
            if task["name"] == "Deploy agent sandbox docker-compose template"
        )
        assert_task = tasks[render_index - 1]

        self.assertEqual(
            assert_task["name"],
            "Require the default bridge address before publishing the proxy port",
        )
        self.assertIn(
            "match('^([0-9]{1,3}[.]){3}[0-9]{1,3}$')",
            assert_task["ansible.builtin.assert"]["that"][0],
        )
        self.assertEqual(
            assert_task["when"],
            f"{FLAG} | bool",
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

    def test_proxy_url_targets_the_bridge_gateway_alias(self):
        rendered = rendered_group_vars(load(GROUP_VARS))

        self.assertEqual(
            rendered["openhands_egress_proxy_url"],
            "http://host.docker.internal:3128",
        )

    def test_extra_domains_derive_cache_hosts_from_the_published_urls(self):
        rendered = rendered_group_vars(load(GROUP_VARS))

        self.assertEqual(
            rendered["agent_sandbox_extra_egress_domains"],
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
