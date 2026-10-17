"""Read-only filesystem and sandbox probes must run during check mode."""

from pathlib import Path
import unittest

import yaml


REPO = Path(__file__).resolve().parents[1]
READ_ONLY_PROBES = {
    "roles/github_runner/tasks/data_disk.yml": (
        "Resolve the Docker data device",
        "Read existing signatures on the Docker data device",
        "Read the Docker data filesystem UUID",
        "Check whether /var/lib/docker already has its own filesystem",
        "Read the filesystem backing /",
        "Check whether /var/lib/containerd is already redirected",
        "Read the filesystems backing / and every Docker data path",
        "Read Docker's own data root",
        "Read free space on the filesystem backing Docker's data root",
    ),
    "roles/agent_sandbox/tasks/main/validate_and_prune.yml": (
        "Validate squid parses the deployed configuration",
        "Read squid access evidence for the egress probes",
        "Egress invariant — inspect egress-network membership",
        "Egress invariant — inspect internal-network membership",
        "Host filter — read the loaded container-egress table",
        "Read the host filter after the default-bridge probe",
    ),
    "roles/agent_sandbox/tasks/main/probe.yml": (
        "Inspect the ZCode Web container without exposing its environment",
        "Check the ZCode Web service file contains no OpenBao address or workstation credential name",
        "Read the sandbox network gateways for the packet probe",
        "Read the sandbox nftables drop counter before the packet probe",
        "Verify the throwaway probe container name is unused",
        "Read the throwaway container's network endpoints",
        "Confirm the throwaway container has a routed default gateway",
        "Confirm the external probe route uses the internal bridge gateway",
        "Read the sandbox nftables drop counter after the packet probe",
    ),
    "roles/agent_sandbox/tasks/main/probe_egress.yml": (
        "Check the static container-facing allowlist for the OpenBao FQDN",
        "Check the operator list does not contain the OpenBao FQDN",
        "Verify the throwaway proxy probe container name is unused",
    ),
}
STATE_CHANGING_MODULES = {
    "ansible.builtin.file",
    "ansible.builtin.systemd",
    "ansible.posix.mount",
    "community.general.filesystem",
}


def iter_tasks(tasks):
    for task in tasks:
        if not isinstance(task, dict):
            continue
        yield task
        for section in ("block", "rescue", "always"):
            yield from iter_tasks(task.get(section, []))


def task_by_name(tasks, name):
    return next((task for task in iter_tasks(tasks) if task.get("name") == name), None)


def is_state_changing(task):
    if STATE_CHANGING_MODULES.intersection(task):
        return True
    command = task.get("ansible.builtin.command", {}).get("cmd", "")
    return command.startswith(("cp ", "mv ", "docker system prune"))


class GitHubRunnerDataDiskCheckMode(unittest.TestCase):
    def test_read_only_probes_run_in_check_mode(self):
        for relative_path, task_names in READ_ONLY_PROBES.items():
            tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
            for name in task_names:
                with self.subTest(task=name, path=relative_path):
                    task = task_by_name(tasks, name)
                    self.assertIsNotNone(task, f"Task not found: {name}")
                    self.assertIs(task.get("check_mode"), False)

    def test_data_disk_state_changes_keep_check_mode_enabled(self):
        tasks = yaml.safe_load(
            (REPO / "roles/github_runner/tasks/data_disk.yml").read_text(encoding="utf-8")
        )
        for task in iter_tasks(tasks):
            if is_state_changing(task):
                with self.subTest(task=task.get("name")):
                    self.assertIsNot(task.get("check_mode"), False)


if __name__ == "__main__":
    unittest.main()
