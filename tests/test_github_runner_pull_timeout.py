"""Runner image pulls stay cached on converges and allow a slow cold pull."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "roles" / "github_runner" / "tasks" / "main.yml"
DEFAULTS_FILE = ROOT / "roles" / "github_runner" / "defaults" / "main.yml"
TASK_NAME = "Pull the runner image"
PULL_TIMEOUT_VARIABLE = "{{ github_runner_image_pull_timeout }}"


def test_runner_image_pull_is_idempotent_and_polls_for_cold_pull():
    tasks = yaml.safe_load(TASKS_FILE.read_text(encoding="utf-8"))
    task = next((item for item in tasks if item.get("name") == TASK_NAME), None)
    assert task is not None, f"no task named {TASK_NAME!r} in {TASKS_FILE}"

    module = task["community.docker.docker_image"]
    assert module["source"] == "pull"
    assert module.get("force_source", False) is False
    assert module["timeout"] == PULL_TIMEOUT_VARIABLE
    assert task["timeout"] == PULL_TIMEOUT_VARIABLE
    assert task["async"] == PULL_TIMEOUT_VARIABLE
    assert int(task["poll"]) == 10

    defaults = yaml.safe_load(DEFAULTS_FILE.read_text(encoding="utf-8"))
    assert int(defaults["github_runner_image_pull_timeout"]) > 240
