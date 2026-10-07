"""Render the ZCode spool input and generic Cribl Stream destination."""

from pathlib import Path
import unittest

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "agent_sandbox"


def render(path: Path, variables: dict) -> dict:
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return yaml.safe_load(
        templar.template(trust_as_template(path.read_text(encoding="utf-8")))
    )


class ZcodeCriblRoute(unittest.TestCase):
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
            },
        )["inputs"]["in_agent_zcode"]

        self.assertEqual(inputs["filenames"], ["*/zcode/*.jsonl"])
        self.assertEqual(
            {item["name"]: item["value"] for item in inputs["metadata"]},
            {"index": "'llm'", "sourcetype": "'zcode:cli'", "source": "'zcode-cli'"},
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


if __name__ == "__main__":
    unittest.main()
