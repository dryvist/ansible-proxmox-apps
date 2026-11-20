"""The first pgBackRest backup starts through its installed systemd unit."""

import re

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


TASKS = list(_tasks_in(yaml.safe_load(
    (REPO / "roles/postgres/tasks/pgbackrest.yml").read_text(encoding="utf-8")
)))
INITIAL = "Take the initial full backup so PITR has a base to replay onto"
DEPLOY = "Deploy the instanced pgBackRest backup service"
BY_NAME = {task["name"]: task for task in TASKS}
BACKUP_COUNT = (
    "((postgres_pgbackrest_info.stdout | default('[]', true) | from_json\n"
    "  | map(attribute='backup') | flatten | length) == 0)"
)


def test_initial_backup_queues_the_systemd_service_as_root():
    task = BY_NAME[INITIAL]
    assert task["ansible.builtin.systemd"] == {
        "name": "pgbackrest-backup@full.service",
        "state": "started",
        "no_block": True,
        "daemon_reload": True,
    }
    assert task["become"] is True
    assert "become_user" not in task


def test_initial_backup_follows_service_deployment_and_checks_existing_backups():
    names = [task["name"] for task in TASKS]
    assert BY_NAME[DEPLOY]["ansible.builtin.template"]["dest"] == (
        "/etc/systemd/system/pgbackrest-backup@.service"
    )
    assert names.index(DEPLOY) < names.index(INITIAL)
    assert BACKUP_COUNT in BY_NAME[INITIAL]["when"]


def test_check_mode_requires_an_existing_service_unit():
    probe = next(
        task for task in TASKS
        if task.get("register") == "postgres_pgbackrest_backup_service_unit_file"
    )
    assert probe["ansible.builtin.stat"]["path"] == (
        "/etc/systemd/system/pgbackrest-backup@.service"
    )
    assert probe["when"] == "ansible_check_mode"
    assert TASKS.index(probe) < TASKS.index(BY_NAME[INITIAL])
    assert " ".join(BY_NAME[INITIAL]["when"][0].split()) == (
        "not ansible_check_mode or "
        "(postgres_pgbackrest_backup_service_unit_file.stat.exists | default(false))"
    )


def test_no_pgbackrest_backup_runs_inline():
    for task in TASKS:
        for module in ("command", "shell", "ansible.builtin.command", "ansible.builtin.shell"):
            command = task.get(module, "")
            if isinstance(command, dict):
                command = " ".join(command.get("argv", [])) or command.get("cmd", "")
            assert not re.search(r"\bpgbackrest\b.*\bbackup\b", command, re.DOTALL), task["name"]
