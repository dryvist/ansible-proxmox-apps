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
