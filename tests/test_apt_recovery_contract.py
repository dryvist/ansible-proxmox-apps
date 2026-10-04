"""Contract checks for bounded package-lock recovery before Homarr installs."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_recovery_precedes_homarr_package_install_and_long_installer_is_polled():
    tasks = _load(ROOT / "roles/homarr/tasks/main.yml")
    recovery_index = next(
        index
        for index, task in enumerate(tasks)
        if task.get("ansible.builtin.import_role", {}).get("name") == "apt_recovery"
    )
    apt_index = next(
        index
        for index, task in enumerate(tasks)
        if "ansible.builtin.apt" in task
    )
    installer = next(
        task
        for task in tasks
        if task.get("name") == "Install Homarr via the pinned community-scripts installer"
    )

    assert recovery_index < apt_index
    assert installer["async"] == "{{ homarr_install_timeout }}"
    assert installer["poll"] > 0


def test_lock_wait_is_bounded_and_recovery_only_runs_for_incomplete_dpkg():
    defaults = _load(ROOT / "roles/apt_recovery/defaults/main.yml")
    tasks = _load(ROOT / "roles/apt_recovery/tasks/main.yml")

    lock_wait = tasks[0]
    audit_index = next(
        index for index, task in enumerate(tasks) if "dpkg" in task.get("ansible.builtin.command", {}).get("argv", [])
    )
    configure_index = next(
        index
        for index, task in enumerate(tasks)
        if task.get("ansible.builtin.command", {}).get("argv") == ["dpkg", "--configure", "-a"]
    )
    configure = tasks[configure_index]

    assert lock_wait["retries"] == "{{ apt_recovery_lock_retries }}"
    assert lock_wait["delay"] == "{{ apt_recovery_lock_delay }}"
    assert lock_wait["changed_when"] is False
    assert defaults["apt_recovery_lock_retries"] * defaults["apt_recovery_lock_delay"] < 240
    assert audit_index == 1
    assert configure_index > audit_index
    assert "apt_recovery_audit.stdout" in configure["when"]
    assert configure["changed_when"]
    assert tasks[-1]["failed_when"]
