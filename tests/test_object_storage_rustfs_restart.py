"""The object-storage service restarts when its installed RustFS binary changes."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "roles" / "object_storage" / "tasks" / "main.yml"


def test_rustfs_binary_change_restarts_object_storage():
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    binary_task = next(task for task in tasks if task.get("name") == "Copy rustfs binary to target")

    assert "ansible.builtin.copy" in binary_task
    assert binary_task["notify"] == "Restart object-storage"
