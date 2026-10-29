from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "roles" / "proxmox_backup_server" / "tasks" / "main.yml"
START = "Start and enable the Proxmox Backup Server services"


def _rescue():
    tasks = yaml.safe_load(MAIN.read_text(encoding="utf-8"))
    block = next(task for task in tasks if task.get("name") == START and "block" in task)
    return block["rescue"]


def test_failed_start_reports_runtime_directory_and_unit_identity():
    rescue = _rescue()
    capture = next(
        task for task in rescue if "ansible.builtin.command" in task
        and "argv" in task["ansible.builtin.command"]
    )
    commands = [" ".join(item) for item in capture["loop"]]

    assert any("/run/proxmox-backup" in command for command in commands)
    assert any(command.startswith("systemctl show proxmox-backup") for command in commands)
    assert capture["failed_when"] is False
    assert capture["changed_when"] is False

    names = [task.get("name") for task in rescue]
    assert names.index(capture["name"]) < names.index("Re-raise the original failure")


def test_runtime_directory_is_owned_by_the_service_user_before_the_services_start():
    tasks = yaml.safe_load(MAIN.read_text(encoding="utf-8"))
    names = [task.get("name") for task in tasks]
    tmpfiles = tasks[names.index("Declare the Proxmox Backup Server runtime directory at boot")]
    live = tasks[names.index("Own the Proxmox Backup Server runtime directory now")]

    copy = tmpfiles["ansible.builtin.copy"]
    assert copy["dest"] == "/etc/tmpfiles.d/proxmox-backup-run.conf"
    assert "d /run/proxmox-backup 0755" in copy["content"]
    assert "proxmox_backup_server_user" in copy["content"]

    directory = live["ansible.builtin.file"]
    assert directory["path"] == "/run/proxmox-backup"
    assert directory["owner"] == "{{ proxmox_backup_server_user }}"
    assert directory["state"] == "directory"

    assert names.index(tmpfiles["name"]) < names.index(live["name"]) < names.index(START)
