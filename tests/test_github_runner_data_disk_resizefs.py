"""The runner data filesystem grows onto an enlarged disk before the headroom check reads it."""

from pathlib import Path

import yaml

DATA_DISK = Path(__file__).resolve().parents[1] / "roles" / "github_runner" / "tasks" / "data_disk.yml"
TASKS = yaml.safe_load(DATA_DISK.read_text(encoding="utf-8"))
NAMES = [task["name"] for task in TASKS]
CREATE = "Create the Docker data filesystem"
HEADROOM = "Assert the Docker data filesystem still has headroom"


def test_data_filesystem_task_resizes():
    task = TASKS[NAMES.index(CREATE)]
    assert task["community.general.filesystem"]["resizefs"] is True
    assert "force" not in task["community.general.filesystem"]


def test_resize_runs_before_the_headroom_assert():
    assert NAMES.index(CREATE) < NAMES.index(HEADROOM)


def test_data_filesystem_task_polls_past_the_task_timeout():
    task = TASKS[NAMES.index(CREATE)]
    assert task["timeout"] == task["async"] == "{{ github_runner_data_mkfs_timeout }}"
    assert task["poll"] > 0
