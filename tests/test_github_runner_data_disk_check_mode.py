"""Read-only checks and runtime-only sandbox probes must respect check mode."""

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
    "roles/agent_sandbox/tasks/main/probe.yml": (
        "Check the ZCode Web service file contains no OpenBao address or workstation credential name",
    ),
}
STATE_CHANGING_MODULES = {
    "ansible.builtin.file",
    "ansible.builtin.systemd",
    "ansible.posix.mount",
    "community.general.filesystem",
    "community.docker.docker_container",
}
SANDBOX_TASK_FILES = tuple(
    (REPO / "roles/agent_sandbox/tasks").rglob("*.yml")
)
EDITED_SANDBOX_TASK_FILES = (
    "roles/agent_sandbox/tasks/main/probe.yml",
    "roles/agent_sandbox/tasks/main/probe_egress.yml",
    "roles/agent_sandbox/tasks/main/validate_and_prune.yml",
)


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
    container_command = task.get("community.docker.docker_container_exec", {}).get("command", "")
    return command.startswith(
        (
            "cp ",
            "mv ",
            "docker system prune",
            "docker network connect ",
            "docker run ",
        )
    ) or container_command.startswith("ip route replace ")


def is_throwaway_container_block(task):
    return "block" in task and any(
        "throwaway" in nested.get("name", "").lower()
        and nested.get("community.docker.docker_container", {}).get("state") == "started"
        for nested in iter_tasks(task["block"])
    )


def iter_tasks_with_throwaway_context(tasks, inside_throwaway_block=False):
    for task in tasks:
        if not isinstance(task, dict):
            continue
        yield task, inside_throwaway_block
        nested_context = inside_throwaway_block or is_throwaway_container_block(task)
        for section in ("block", "rescue", "always"):
            yield from iter_tasks_with_throwaway_context(task.get(section, []), nested_context)


def load_sandbox_tasks(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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

    def test_sandbox_throwaway_container_blocks_skip_check_mode(self):
        found = 0
        for path in SANDBOX_TASK_FILES:
            tasks = load_sandbox_tasks(path)
            for task in iter_tasks(tasks):
                if is_throwaway_container_block(task):
                    with self.subTest(task=task.get("name"), path=path):
                        self.assertEqual(task.get("when"), "not ansible_check_mode")
                    found += 1
        self.assertEqual(found, 2)

    def test_sandbox_container_execs_do_not_force_check_mode_inside_throwaway_blocks(self):
        for path in SANDBOX_TASK_FILES:
            tasks = load_sandbox_tasks(path)
            for task, inside_throwaway_block in iter_tasks_with_throwaway_context(tasks):
                if (
                    "community.docker.docker_container_exec" in task
                    and task.get("check_mode") is False
                ):
                    with self.subTest(task=task.get("name"), path=path):
                        self.assertFalse(inside_throwaway_block)

    def test_sandbox_state_changes_keep_check_mode_enabled(self):
        for relative_path in EDITED_SANDBOX_TASK_FILES:
            tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
            for task in iter_tasks(tasks):
                if is_state_changing(task):
                    with self.subTest(task=task.get("name"), path=relative_path):
                        self.assertIsNot(task.get("check_mode"), False)


if __name__ == "__main__":
    unittest.main()
