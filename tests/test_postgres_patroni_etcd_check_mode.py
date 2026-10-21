"""Check-mode contracts for Patroni etcd binary installation."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def test_etcd_binary_copy_is_gated_by_guest_state_in_check_mode():
    relative_path = "roles/postgres/tasks/main/patroni_etcd.yml"
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    probe = task_by_name["Check for the extracted etcd binaries"]
    install = task_by_name["Install the etcd and etcdctl binaries"]
    assert probe["ansible.builtin.stat"]["path"] == (
        "/tmp/etcd-v{{ postgres_ha_etcd_version }}-linux-amd64/{{ item }}"
    )
    assert probe.get("register") == "postgres_ha_etcd_binary_sources"
    assert probe.get("when") == "ansible_check_mode"
    assert probe["loop"] == install["loop"]
    assert "not postgres_ha_etcd_already_installed" in install["when"]
    assert "not ansible_check_mode" in install["when"]
    assert "postgres_ha_etcd_binary_sources.results" in install["when"]
    assert "map(attribute='stat.exists')" in install["when"]
