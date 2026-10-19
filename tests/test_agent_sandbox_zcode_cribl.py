"""Render agent-sandbox Cribl inputs and the generic Stream destination."""

from pathlib import Path
import unittest

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "agent_sandbox"


def render_text(path: Path, variables: dict) -> str:
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(path.read_text(encoding="utf-8")))


def render(path: Path, variables: dict) -> dict:
    return yaml.safe_load(render_text(path, variables))


class AgentSandboxCriblRoute(unittest.TestCase):
    def test_s2s_port_uses_the_shared_tofu_constant(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))

        self.assertIn(
            "hostvars['localhost']['tofu_data']['constants']['service_ports']['cribl_s2s']",
            defaults["agent_sandbox_cribl_s2s_port"],
        )

    def test_zcode_jsonl_spool_uses_generic_s2s_with_splunk_metadata(self):
        inputs = render(
            ROLE / "templates/cribl/inputs.yml.j2",
            {
                "ansible_managed": "test",
                "agent_sandbox_spool_mount": "/spool",
                "agent_sandbox_allowlist_log_dir": "/var/log/agent-sandbox",
            },
        )["inputs"]["in_agent_zcode"]

        self.assertEqual(inputs["filenames"], ["*/zcode/*.jsonl"])
        self.assertEqual(
            {item["name"]: item["value"] for item in inputs["metadata"]},
            {"index": "'llm'", "sourcetype": "'zcode:cli'", "source": "'zcode-cli'"},
        )
        self.assertEqual(inputs["connections"], [{"output": "cribl_stream_s2s"}])

    def test_allowlist_log_uses_generic_s2s_with_splunk_metadata(self):
        inputs = render(
            ROLE / "templates/cribl/inputs.yml.j2",
            {
                "ansible_managed": "test",
                "agent_sandbox_spool_mount": "/spool",
                "agent_sandbox_allowlist_log_dir": "/var/log/agent-sandbox",
            },
        )["inputs"]["in_agent_allowlist"]

        self.assertEqual(inputs["path"], "/var/log/agent-sandbox")
        self.assertEqual(inputs["filenames"], ["*/allowed-domains.log"])
        self.assertEqual(
            {item["name"]: item["value"] for item in inputs["metadata"]},
            {
                "index": "'llm'",
                "sourcetype": "'agent-sandbox:allowlist'",
                "source": "'allowed-domains.log'",
            },
        )
        self.assertEqual(inputs["connections"], [{"output": "cribl_stream_s2s"}])

    def test_s2s_destination_uses_shared_port(self):
        output = render(
            ROLE / "templates/cribl/outputs.yml.j2",
            {
                "ansible_managed": "test",
                "agent_sandbox_cribl_stream_host": "syslog.example.invalid",
                "agent_sandbox_cribl_s2s_port": 10300,
                "agent_sandbox_cribl_ports": {
                    "claude": 10311,
                    "codex": 10312,
                    "gemini": 10313,
                },
            },
        )["outputs"]["cribl_stream_s2s"]

        self.assertEqual(output["type"], "tcpjson")
        self.assertEqual(output["host"], "syslog.example.invalid")
        self.assertEqual(output["port"], 10300)

    def test_s2s_firewall_destination_uses_existing_tofu_inventory(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))

        self.assertIn(
            "hostvars['localhost']['tofu_data']['containers']['haproxy']['ip']",
            defaults["agent_sandbox_cribl_stream_address"],
        )
        self.assertIn(
            "hostvars['localhost']['tofu_data']['constants']['service_ports']['cribl_s2s']",
            defaults["agent_sandbox_cribl_s2s_port"],
        )

    def test_s2s_firewall_rule_keeps_the_existing_https_rule_only(self):
        rendered = render_text(
            ROLE / "templates/agent-sandbox.nft.j2",
            {
                "ansible_managed": "test",
                "agent_sandbox_nft_table": "agent_sandbox",
                "agent_sandbox_bridge": "br-agents",
                "agent_sandbox_egress_bridge": "br-agents-out",
                "agent_sandbox_zcode_web_ingress_source_ips": [],
                "agent_sandbox_zcode_web_port": 8080,
                "agent_sandbox_zcode_web_host_port": 443,
                "agent_sandbox_proxy_port": 3128,
                "agent_sandbox_cribl_edge_mac_address": "edge_mac_fixture",
                "agent_sandbox_cribl_stream_address": "stream_address_fixture",
                "agent_sandbox_cribl_s2s_port": 10300,
            },
        )
        egress_accepts = [
            line.strip()
            for line in rendered.splitlines()
            if line.strip().startswith('iifname "br-agents-out"')
            and line.strip().endswith(" accept")
        ]

        self.assertEqual(
            egress_accepts,
            [
                "iifname \"br-agents-out\" tcp dport 443 accept",
                "iifname \"br-agents-out\" ether saddr edge_mac_fixture "
                "ip daddr stream_address_fixture tcp dport 10300 accept",
            ],
        )


if __name__ == "__main__":
    unittest.main()
