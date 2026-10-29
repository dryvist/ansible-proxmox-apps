from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = ROOT / "roles" / "proxmox_backup_server" / "tasks"
REMOVAL_FILE = "remove_enterprise_sources.yml"
REFRESH_FILE = "apt_refresh.yml"


def _load(name):
    return yaml.safe_load((TASKS_DIR / name).read_text(encoding="utf-8"))


def _index(tasks, predicate):
    return next(index for index, task in enumerate(tasks) if predicate(task))


def _imports(tasks, name):
    return [
        index
        for index, task in enumerate(tasks)
        if task.get("ansible.builtin.import_tasks") == name
    ]


def test_apt_cache_is_refreshed_by_cli_after_each_source_change():
    tasks = _load("main.yml")
    refreshes = _imports(tasks, REFRESH_FILE)
    removals = _imports(tasks, REMOVAL_FILE)
    prerequisites = _index(
        tasks, lambda t: t.get("name") == "Install apt transport prerequisites"
    )
    repository = _index(tasks, lambda t: "ansible.builtin.apt_repository" in t)
    install = _index(
        tasks, lambda t: t.get("name") == "Install Proxmox Backup Server"
    )

    assert len(refreshes) == 2
    assert len(removals) == 1
    assert refreshes[0] < prerequisites < repository < refreshes[1] < install
    assert install < removals[0]
    assert tasks[prerequisites]["ansible.builtin.apt"]["update_cache"] is False
    assert tasks[repository]["ansible.builtin.apt_repository"]["update_cache"] is False
    assert tasks[install]["ansible.builtin.apt"]["update_cache"] is False


def test_refresh_removes_enterprise_sources_then_fails_on_any_fetch_error():
    tasks = _load(REFRESH_FILE)
    removal = tasks[0]
    refresh = tasks[1]
    failure = tasks[2]

    assert removal["ansible.builtin.import_tasks"] == REMOVAL_FILE
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


def test_enterprise_sources_are_matched_by_vendor_host_in_both_formats():
    tasks = _load(REMOVAL_FILE)
    find = tasks[0]["ansible.builtin.find"]
    removal = tasks[1]

    assert find["paths"] == "/etc/apt/sources.list.d"
    assert set(find["patterns"]) == {"*.list", "*.sources"}
    assert find["contains"] == r"enterprise\.proxmox\.com"
    assert tasks[0]["register"] == "proxmox_backup_server_enterprise_sources"
    assert removal["ansible.builtin.file"]["state"] == "absent"
    assert removal["ansible.builtin.file"]["path"] == "{{ item.path }}"
    assert (
        removal["loop"] == "{{ proxmox_backup_server_enterprise_sources.files }}"
    )
