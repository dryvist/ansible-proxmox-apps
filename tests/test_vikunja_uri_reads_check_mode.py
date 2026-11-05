"""Read-only Vikunja URI requests must run during Ansible check mode."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "roles/vikunja/tasks"


def _walk_tasks(value):
    if isinstance(value, list):
        for item in value:
            yield from _walk_tasks(item)
    elif isinstance(value, dict):
        yield value
        for key in ("block", "rescue", "always"):
            if key in value:
                yield from _walk_tasks(value[key])


def _is_get_method(method):
    if method is None:
        return True
    if not isinstance(method, str):
        return False
    return method.strip().upper() == "GET"


def test_every_get_uri_task_runs_in_check_mode():
    for path in sorted(TASKS.glob("*.yml")):
        for task in _walk_tasks(yaml.safe_load(path.read_text(encoding="utf-8")) or []):
            uri = next(
                (
                    task[module]
                    for module in ("ansible.builtin.uri", "ansible.legacy.uri", "uri")
                    if module in task
                ),
                None,
            )
            if isinstance(uri, dict) and _is_get_method(uri.get("method")):
                assert task.get("check_mode") is False, (
                    f"{path.relative_to(ROOT)}: {task.get('name', '<unnamed>')} "
                    "must set check_mode: false for GET requests"
                )
