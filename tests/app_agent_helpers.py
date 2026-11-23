"""Shared loaders for the app-agent identity and publisher tests."""

from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]


def _yaml(relative_path: str, _depth: int = 0):
    tasks = yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))
    if _depth < 10 and isinstance(tasks, list):
        tasks = _resolve_imports(tasks, relative_path, _depth)
    return tasks


def _resolve_imports(tasks, relative_path: str, depth: int):
    i = 0
    while i < len(tasks):
        task = tasks[i]
        if "ansible.builtin.import_tasks" in task:
            imported = task.pop("ansible.builtin.import_tasks")
            parent = (ROOT / relative_path).parent
            tasks[i] = _yaml(str(parent / imported), depth + 1)
            i += 1
            continue
        for branch in ("block", "rescue", "always"):
            if branch in task:
                task[branch] = _resolve_imports(task[branch], relative_path, depth)
        i += 1
    return tasks


def _vikunja_defaults():
    merged = {}
    for path in sorted((ROOT / "roles/vikunja/defaults/main").glob("*.yml")):
        merged.update(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    return merged


def _render(value, variables: dict):
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(value))


def _task_tree(tasks: list[dict]):
    for task in tasks or []:
        if isinstance(task, list):
            yield from _task_tree(task)
            continue
        yield task
        for branch in ("block", "rescue", "always"):
            yield from _task_tree(task.get(branch, []))


def _task(tasks: list[dict], name: str) -> dict:
    return next(task for task in _task_tree(tasks) if task.get("name") == name)
