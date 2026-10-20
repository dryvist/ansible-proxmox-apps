"""Controller-side staging inputs must exist during Ansible check mode."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE_TASKS = ROOT / "roles" / "agent_sandbox" / "tasks" / "main"
STAGING_TASKS = {
    "dispatcher_install.yml": (
        "Fetch the pinned dispatcher sources on the controller",
        "Stage the OpenBao release checksum manifest on controller",
        "Stage the OpenBao release checksum manifest signature on controller",
        "Fetch the pinned OpenBao client to controller",
        "Extract the OpenBao client on controller",
        "Remove the OpenBao client staging files from controller",
        "Remove the dispatcher staging files from the controller",
    ),
    "deploy.yml": (
        "Fetch session-log pack .crbl to controller",
        "Remove pack staging files from controller",
    ),
    "ci_resolver.yml": (
        "Fetch the pinned CI resolver source on the controller",
        "Remove the CI resolver source staging file from the controller",
    ),
}
CHECK_MODE_GUARD_FILES = ("dispatcher_install.yml", "deploy.yml")
CHECK_MODE_ALLOWLIST = (
    "Read the task profiles baked into the pinned job image",
)
# These mirror downloads can omit a checksum, so check mode must not fetch them.
CHECK_MODE_STAGING_EXCLUSIONS = {
    (
        "roles/object_storage/tasks/infra_mirrors.yml",
        "Stage missing infra artifacts on controller",
    ),
    (
        "roles/object_storage/tasks/infra_mirrors.yml",
        "Stage the sha256 sidecar for missing checksummed infra artifacts",
    ),
}
NESTED = ("block", "rescue", "always")


def walk(tasks):
    for task in tasks or []:
        yield task
        for key in NESTED:
            yield from walk(task.get(key))


def tasks_in(filename):
    tasks = yaml.safe_load((ROLE_TASKS / filename).read_text(encoding="utf-8"))
    return list(walk(tasks))


def task_by_name(tasks, name):
    return next((task for task in tasks if task.get("name") == name), None)


class AgentSandboxControllerStagingCheckMode(unittest.TestCase):
    def test_staging_downloads_extracts_and_removals_run_on_controller(self):
        for filename, task_names in STAGING_TASKS.items():
            tasks = tasks_in(filename)
            for name in task_names:
                with self.subTest(file=filename, task=name):
                    task = task_by_name(tasks, name)
                    self.assertIsNotNone(task, f"Task not found: {name}")
                    self.assertEqual(task.get("delegate_to"), "localhost")
                    self.assertIs(task.get("check_mode"), False)

    def test_managed_host_tasks_do_not_force_check_mode_off(self):
        for filename in CHECK_MODE_GUARD_FILES:
            for task in tasks_in(filename):
                if task.get("check_mode") is False:
                    with self.subTest(file=filename, task=task.get("name")):
                        if task.get("name") not in CHECK_MODE_ALLOWLIST:
                            self.assertEqual(task.get("delegate_to"), "localhost")

    def test_controller_get_url_staging_runs_in_check_mode(self):
        roles = ROOT / "roles"
        for path in sorted(roles.rglob("*.yml")):
            if "tasks" not in path.relative_to(roles).parts:
                continue
            relative_path = path.relative_to(ROOT).as_posix()
            tasks = yaml.safe_load(path.read_text(encoding="utf-8"))
            for task in walk(tasks):
                if (
                    "ansible.builtin.get_url" in task
                    and task.get("delegate_to") == "localhost"
                ):
                    if (
                        relative_path,
                        task.get("name"),
                    ) in CHECK_MODE_STAGING_EXCLUSIONS:
                        continue
                    with self.subTest(file=relative_path, task=task.get("name")):
                        self.assertIs(task.get("check_mode"), False)

    def test_image_profiles_are_read_in_check_mode_and_installed_from_result(self):
        tasks = tasks_in("dispatcher_install.yml")
        read_task = task_by_name(
            tasks, "Read the task profiles baked into the pinned job image"
        )
        install_task = task_by_name(
            tasks, "Install the image task profiles for the dispatcher"
        )

        self.assertIsNotNone(read_task)
        self.assertIs(read_task.get("check_mode"), False)
        self.assertIsNotNone(install_task)
        self.assertEqual(
            install_task["ansible.builtin.copy"].get("content"),
            "{{ _agent_sandbox_task_profiles.stdout }}\n",
        )


if __name__ == "__main__":
    unittest.main()
