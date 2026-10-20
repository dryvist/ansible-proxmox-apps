"""Check-mode contracts for node_exporter installation."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def test_node_exporter_stage_result_gates_check_mode_unpack_and_binary_copy():
    relative_path = "roles/node_exporter/tasks/main.yml"
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    stage = task_by_name["Stage the pinned node_exporter release tarball on the controller"]
    assert stage.get("register") == "node_exporter_release_stage"
    assert stage.get("run_once") is True
    assert "throttle" not in stage
    assert "ansible_play_hosts" in stage["loop"]
    assert "unique(attribute='node_exporter_release')" in stage["loop"]
    assert "item.node_exporter_download_url" in stage["ansible.builtin.get_url"]["url"]
    assert "item.node_exporter_release" in stage["ansible.builtin.get_url"]["dest"]
    assert "item.node_exporter_sha256sums_url" in stage["ansible.builtin.get_url"]["checksum"]

    critical_assert = task_by_name["Assert critical variables are defined and valid"]
    assert "ansible_facts['architecture'] in ['x86_64', 'aarch64']" in critical_assert["ansible.builtin.assert"]["that"]
    assert any("node_exporter_version is defined" in condition for condition in critical_assert["ansible.builtin.assert"]["that"])
    assert any("node_exporter_port is defined" in condition for condition in critical_assert["ansible.builtin.assert"]["that"])
    assert all(
        "default_ipv4" not in condition
        for condition in critical_assert["ansible.builtin.assert"]["that"]
    )

    for task_name in (
        "Unpack the node_exporter release",
        "Install the node_exporter binary",
    ):
        condition = task_by_name[task_name].get("when", "")
        assert "not ansible_check_mode" in condition
        assert "node_exporter_release_stage.changed" in condition
