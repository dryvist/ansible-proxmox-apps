"""Check-mode contracts for node_exporter installation."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def test_node_exporter_guest_copy_gates_check_mode_unpack_and_binary_copy():
    relative_path = "roles/node_exporter/tasks/main.yml"
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    stage = task_by_name["Stage the pinned node_exporter release tarball on the controller"]
    assert stage.get("run_once") is True
    assert "throttle" not in stage
    assert "ansible_play_hosts" in stage["loop"]
    assert "unique(attribute='node_exporter_release')" in stage["loop"]
    # Role defaults are absent from hostvars, so the loop must extract a fact.
    assert "map('extract', hostvars, 'node_exporter_stage_item')" in stage["loop"]
    record = task_by_name["Record this host's pinned node_exporter release for controller staging"]
    assert set(record["ansible.builtin.set_fact"]["node_exporter_stage_item"]) == {
        "node_exporter_release",
        "node_exporter_download_url",
        "node_exporter_sha256sums_url",
    }
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

    # Under --check the guest copy writes nothing, so what reads it must skip.
    assert task_by_name["Copy the staged release tarball to the guest"].get("register") == "node_exporter_tarball_copy"
    unpack_condition = task_by_name["Unpack the node_exporter release"].get("when", "")
    assert "not ansible_check_mode" in unpack_condition
    assert "node_exporter_tarball_copy.changed" in unpack_condition
    probe = task_by_name["Check for the unpacked node_exporter binary"]
    assert probe.get("register") == "node_exporter_unpacked_binary"
    assert task_by_name["Install the node_exporter binary"].get("when") == (
        "not ansible_check_mode or node_exporter_unpacked_binary.stat.exists"
    )
