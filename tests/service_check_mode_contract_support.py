"""Shared assertions for first-install service check-mode contracts."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def _named_tasks(relative_path):
    tasks = yaml.safe_load((REPO / "roles" / relative_path).read_text(encoding="utf-8"))
    return {task["name"]: task for task in _tasks_in(tasks) if "name" in task}


def _conditions(task):
    conditions = task.get("when", [])
    conditions = [conditions] if isinstance(conditions, str) else conditions
    return [" ".join(str(condition).split()) for condition in conditions]


def assert_case(case):
    role = case["role"]
    for relative_path, task_name, register in case.get("installs", []):
        task = _named_tasks(f"{role}/{relative_path}")[task_name]
        assert task.get("register") == register

    for relative_path, task_name, register, unit_path in case.get("probes", []):
        task = _named_tasks(f"{role}/{relative_path}")[task_name]
        assert task.get("register") == register
        assert task["ansible.builtin.stat"].get("path") == unit_path
        assert "ansible_check_mode" in " ".join(map(str, _conditions(task)))

    for relative_path, task_name, gate in case.get("tasks", []):
        task = _named_tasks(f"{role}/{relative_path}")[task_name]
        assert gate in _conditions(task)

    for relative_path, task_name, expected in case.get("check_mode", []):
        task = _named_tasks(f"{role}/{relative_path}")[task_name]
        assert task.get("check_mode") is expected

    if case.get("handlers"):
        handlers = _named_tasks(f"{role}/handlers/main.yml")
        for task_name, gate in case["handlers"]:
            assert gate in _conditions(handlers[task_name])
