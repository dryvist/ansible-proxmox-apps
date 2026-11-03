"""Task contracts for wall gateway config installation: check-mode gating and
credential handling."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def _wall_tasks_by_name():
    tasks = yaml.safe_load((REPO / "roles/wall/tasks/main.yml").read_text(encoding="utf-8"))
    return {task.get("name"): task for task in _tasks_in(tasks)}


def test_gateway_config_copy_is_gated_by_guest_state_in_check_mode():
    task_by_name = _wall_tasks_by_name()

    probe = task_by_name["Check for the unpacked gateway configs"]
    install = task_by_name["Install the gateway config"]
    assert probe["ansible.builtin.stat"]["path"] == "{{ wall_feed_dir }}/{{ item }}"
    assert probe.get("register") == "wall_gateway_config_sources"
    assert probe.get("when") == "ansible_check_mode"
    assert probe["loop"] == install["loop"]
    assert "not ansible_check_mode" in install.get("when", "")
    assert "wall_gateway_config_sources.results" in install["when"]
    assert "map(attribute='stat.exists')" in install["when"]


def test_clickhouse_auth_include_is_rendered_unlogged_for_root_and_workers():
    # The include carries the ClickHouse credential: never in the play log,
    # readable by root and the nginx worker group only.
    render = _wall_tasks_by_name()["Render the gateway's ClickHouse auth include"]
    template = render["ansible.builtin.template"]
    assert template["src"] == "wall-feed-clickhouse-auth.conf.j2"
    assert template["dest"] == "/etc/nginx/wall-feed-clickhouse-auth.conf"
    assert template["owner"] == "root"
    assert template["group"] == "{{ wall_nginx_group }}"
    assert template["mode"] == "0640"
    assert render.get("no_log") is True
