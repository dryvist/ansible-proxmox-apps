"""The pipeline validator fails when declared target containers are unavailable."""

import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "tests/inventory_load/tofu_inventory.json"
SUMMARY_FIXTURE = ROOT / "tests/validate_pipeline/verify_guard.yml"
SKIPPED_GROUPS_FIXTURE = ROOT / "tests/inventory_load/verify_skipped_lxc_groups.yml"
VALIDATE_PIPELINE = ROOT / "playbooks/validate-pipeline.yml"


def _run(playbook, extra_vars, start_at_task=None):
    command = [
        "ansible-playbook",
        "-i",
        "tests/inventory_load/localhost.yml",
        "-c",
        "local",
        str(playbook),
    ]
    if start_at_task:
        command.extend(["--start-at-task", start_at_task])
    command.extend(["--extra-vars", json.dumps(extra_vars)])
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class ValidatePipelineCoverage(unittest.TestCase):
    def test_live_validation_checks_ssh_known_hosts_coverage(self):
        playbook = VALIDATE_PIPELINE.read_text(encoding="utf-8")

        inventory_load = "import_playbook: ../inventory/load_tofu.yml"
        coverage_play = "- name: Validate SSH known_hosts coverage for CA-rollout VMs"
        self.assertLess(playbook.index(inventory_load), playbook.index(coverage_play))
        self.assertIn("  hosts: localhost\n  gather_facts: false", playbook)
        self.assertIn(
            "lookup('env', 'SSH_KNOWN_HOSTS_FILE') | length > 0",
            playbook,
        )
        self.assertIn(
            "ansible.builtin.import_tasks: ../tests/inventory_load/verify_ssh_known_hosts_coverage.yml",
            playbook,
        )

    def test_all_tiers_live_passes(self):
        result = _run(SUMMARY_FIXTURE, {"validate_pipeline_test_skipped": []})
        output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)
        self.assertIn("LOGGING PIPELINE VALIDATION COMPLETE", output)
        self.assertIn("CRIBL_EDGE_API_TOKEN is not set", output)

    def test_skipped_container_in_validated_group_fails_and_names_it(self):
        skipped = [
            {
                "container": "fixture-cribl-edge",
                "vmid": 501,
                "status": "stopped",
                "groups": ["lxc_containers", "all", "cribl_edge"],
            }
        ]
        result = _run(SUMMARY_FIXTURE, {"validate_pipeline_test_skipped": skipped})
        output = result.stdout + result.stderr

        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn("fixture-cribl-edge", output)
        self.assertIn("vmid 501", output)
        self.assertIn("stopped", output)
        self.assertIn("cribl_edge", output)

    def test_skipped_inventory_fixture_preserves_validator_groups(self):
        inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
        name = "cribl-edge-01"
        container = dict(inventory["containers"][name])
        container["ansible_connection"] = "community.proxmox.proxmox_pct_remote"
        vmid = str(container["vmid"])
        tofu_data = dict(inventory)
        tofu_data["containers"] = {name: container}
        tofu_data["nodes"] = {}
        tofu_data["domain"] = inventory.get("domain", "fixture.invalid")
        facts = {
            "tofu_data": tofu_data,
            "add_lxc_hosts_live_node": {vmid: "fixture-node"},
            "add_lxc_hosts_live_status": {vmid: "stopped"},
        }

        result = _run(
            SKIPPED_GROUPS_FIXTURE,
            facts,
            "Load shared LXC group expression",
        )
        output = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, output)


if __name__ == "__main__":
    unittest.main()
