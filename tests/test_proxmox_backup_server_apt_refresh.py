from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = ROOT / "roles" / "proxmox_backup_server" / "tasks"
ENTERPRISE_LIST = "/etc/apt/sources.list.d/pbs-enterprise.list"


def _load(name):
    return yaml.safe_load((TASKS_DIR / name).read_text(encoding="utf-8"))


def _index(tasks, predicate):
    return next(index for index, task in enumerate(tasks) if predicate(task))


def test_apt_cache_is_refreshed_by_cli_after_each_source_change():
    tasks = _load("main.yml")
    removals = [
        index
        for index, task in enumerate(tasks)
        if task.get("ansible.builtin.file", {}).get("path") == ENTERPRISE_LIST
        and task["ansible.builtin.file"].get("state") == "absent"
    ]
    refreshes = [
        index
        for index, task in enumerate(tasks)
        if task.get("ansible.builtin.import_tasks") == "apt_refresh.yml"
    ]
    prerequisites = _index(
        tasks, lambda t: t.get("name") == "Install apt transport prerequisites"
    )
    repository = _index(tasks, lambda t: "ansible.builtin.apt_repository" in t)
    install = _index(
        tasks, lambda t: t.get("name") == "Install Proxmox Backup Server"
    )

    assert len(removals) == 2
    assert len(refreshes) == 2
    assert removals[0] < refreshes[0] < prerequisites < repository
    assert repository < refreshes[1] < install < removals[1]
    assert tasks[prerequisites]["ansible.builtin.apt"]["update_cache"] is False
    assert tasks[repository]["ansible.builtin.apt_repository"]["update_cache"] is False
    assert tasks[install]["ansible.builtin.apt"]["update_cache"] is False


def test_refresh_fails_on_any_fetch_error_and_prints_the_reason():
    tasks = _load("apt_refresh.yml")
    refresh = tasks[0]
    failure = tasks[1]

    assert refresh["ansible.builtin.command"]["argv"] == [
        "apt-get",
        "update",
        "--error-on=any",
    ]
    assert refresh["register"] == "proxmox_backup_server_apt_update"
    assert refresh["retries"] == 3
    assert refresh["delay"] == 5
    assert refresh["changed_when"] is False
    assert refresh["failed_when"] is False
    assert refresh["when"] == "not ansible_check_mode"
    assert "ansible.builtin.fail" in failure
    assert failure["when"][0] == "not ansible_check_mode"
    assert "stderr" in failure["ansible.builtin.fail"]["msg"]
    assert "stdout" in failure["ansible.builtin.fail"]["msg"]
