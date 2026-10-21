"""Check-mode contracts for the unpoller binary install."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def test_unpoller_install_waits_for_the_unpacked_binary_in_check_mode():
    tasks = yaml.safe_load((REPO / "roles/unpoller/tasks/main.yml").read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    probe = task_by_name["Check for the unpacked unpoller binary"]
    assert probe.get("register") == "unpoller_unpacked_binary"
    assert probe.get("when") == "ansible_check_mode"
    assert task_by_name["Install the unpoller binary"].get("when") == (
        "not ansible_check_mode or unpoller_unpacked_binary.stat.exists"
    )
