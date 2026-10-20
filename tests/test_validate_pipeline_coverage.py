"""The pipeline validator rejects declared LXC tiers omitted from live inventory."""

import json
from pathlib import Path
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "playbooks/validate-pipeline/summary.yml"
FIXTURE = ROOT / "tests/validate_pipeline/verify_coverage.yml"


def _tier_facts():
    play = yaml.safe_load(SUMMARY.read_text(encoding="utf-8"))[0]
    tiers = play["vars"]["validate_pipeline_tiers"]
    containers = {}
    live_nodes = {}
    live_status = {}

    for index, tier in enumerate(tiers, start=1):
        tags = list(tier["required_tags"])
        if tier["any_tags"]:
            tags.append(tier["any_tags"][0])
        name = "fixture-" + tier["name"].lower().replace(" ", "-")
        vmid = 5000 + index
        containers[name] = {"vmid": vmid, "tags": tags}
        live_nodes[str(vmid)] = "fixture-node"
        live_status[str(vmid)] = "running"

    return {
        "validate_pipeline_tiers": tiers,
        "tofu_data": {"containers": containers},
        "add_lxc_hosts_live_node": live_nodes,
        "add_lxc_hosts_live_status": live_status,
    }, containers


def _run_coverage(facts):
    return subprocess.run(
        [
            "ansible-playbook",
            "-i",
            "tests/inventory_load/localhost.yml",
            "-c",
            "local",
            str(FIXTURE),
            "--extra-vars",
            json.dumps(facts),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class ValidatePipelineCoverage(unittest.TestCase):
    def test_all_declared_tiers_live_passes(self):
        facts, _ = _tier_facts()

        result = _run_coverage(facts)
        output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("HAProxy: VALIDATED", output)
        self.assertIn("Cribl Edge metrics: SKIPPED", output)
        self.assertIn("CRIBL_EDGE_API_TOKEN is not set", output)

    def test_declared_tier_with_zero_live_hosts_fails_and_names_it(self):
        facts, containers = _tier_facts()
        edge = next(name for name in containers if name == "fixture-cribl-edge")
        vmid = str(containers[edge]["vmid"])
        facts["add_lxc_hosts_live_status"][vmid] = "unknown"

        result = _run_coverage(facts)
        output = result.stdout + result.stderr

        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("Cribl Edge: FAILED", output)
        self.assertIn("Cribl Edge", output)
        self.assertIn(edge, output)
        self.assertIn("unknown", output)


if __name__ == "__main__":
    unittest.main()
