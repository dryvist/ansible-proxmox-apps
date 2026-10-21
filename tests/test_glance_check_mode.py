"""Check-mode contracts for glance binary installation."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def test_glance_binary_copy_is_gated_by_guest_state_in_check_mode():
    relative_path = "roles/glance/tasks/main.yml"
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    probe = task_by_name["Check for the unpacked glance binary"]
    assert probe["ansible.builtin.stat"]["path"] == "{{ glance_dist_dir }}/glance"
    assert probe.get("register") == "glance_unpacked_binary"
    assert probe.get("when") == "ansible_check_mode"
    assert task_by_name["Install the glance binary"].get("when") == (
        "not ansible_check_mode or glance_unpacked_binary.stat.exists"
    )
