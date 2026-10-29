from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = ROOT / "roles" / "proxmox_backup_server" / "tasks" / "main.yml"


def test_enterprise_source_is_removed_before_refresh_and_after_install():
    tasks = yaml.safe_load(TASKS_PATH.read_text(encoding="utf-8"))
    removals = [
        index
        for index, task in enumerate(tasks)
        if task.get("ansible.builtin.file", {}).get("path")
        == "/etc/apt/sources.list.d/pbs-enterprise.list"
        and task["ansible.builtin.file"].get("state") == "absent"
    ]
    refresh_index = next(
        index
        for index, task in enumerate(tasks)
        if task.get("ansible.builtin.command", {}).get("argv") == ["apt-get", "update"]
    )
    prerequisite_index = next(
        index
        for index, task in enumerate(tasks)
        if task.get("name") == "Install apt transport prerequisites"
    )
    package_install_index = next(
        index
        for index, task in enumerate(tasks)
        if task.get("name") == "Install Proxmox Backup Server"
    )
    failure_index = next(
        index
        for index, task in enumerate(tasks)
        if "ansible.builtin.fail" in task
    )
    failure_message = tasks[failure_index]["ansible.builtin.fail"]["msg"]
    refresh_task = tasks[refresh_index]

    assert len(removals) == 2
    assert removals[0] < refresh_index < prerequisite_index
    assert tasks[prerequisite_index]["ansible.builtin.apt"]["update_cache"] is False
    assert refresh_index + 1 == failure_index
    assert package_install_index < removals[1]
    assert refresh_task["register"] == "proxmox_backup_server_apt_update"
    assert refresh_task["retries"] == 3
    assert refresh_task["delay"] == 5
    assert refresh_task["changed_when"] is False
    assert refresh_task["failed_when"] is False
    assert refresh_task["when"] == "not ansible_check_mode"
    assert tasks[failure_index]["when"][0] == "not ansible_check_mode"
    assert "stderr" in failure_message
    assert "stdout" in failure_message
