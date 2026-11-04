"""Check-mode contracts for wall gateway config installation."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def test_gateway_config_copy_is_gated_by_guest_state_in_check_mode():
    relative_path = "roles/wall/tasks/main.yml"
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    probe = task_by_name["Check for the unpacked gateway configs"]
    install = task_by_name["Install the gateway config"]
    assert probe["ansible.builtin.stat"]["path"] == "{{ wall_feed_dir }}/{{ item }}"
    assert probe.get("register") == "wall_gateway_config_sources"
    assert probe.get("when") == "ansible_check_mode"
    assert probe["loop"] == install["loop"]
    assert "not ansible_check_mode" in install.get("when", "")
    assert "wall_gateway_config_sources.results" in install["when"]
    assert "map(attribute='stat.exists')" in install["when"]
