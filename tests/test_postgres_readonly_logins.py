"""Contract tests for the Postgres read-only login model."""

from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = "roles/postgres/tasks/main/readonly_logins.yml"
PATRONI_PATH = "roles/postgres/templates/patroni.yml.j2"
FIXTURE = {
    "name": "metrics_reader",
    "database": "app_db",
    "tables": ["tasks", "users"],
    "password": "example-password",
    "client_cidr": "192.0.2.0/24",
}


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _tasks() -> list:
    return yaml.safe_load(_read(TASKS_PATH))


def _render(value, variables: dict):
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    if isinstance(value, dict):
        return {key: _render(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [_render(item, variables) for item in value]
    if isinstance(value, str):
        return templar.template(trust_as_template(value))
    return value


def _task(name: str) -> dict:
    return next(task for task in _tasks() if task["name"] == name)


def _render_patroni_readonly_lines(logins: list) -> str:
    template = _read(PATRONI_PATH)
    start = template.index("{% for login in postgres_readonly_logins %}")
    end = template.index("{% endfor %}", start) + len("{% endfor %}")
    return (_render(template[start:end], {"postgres_readonly_logins": logins}) or "").strip()


def test_empty_default_leaves_all_readonly_login_loops_empty():
    defaults = yaml.safe_load(
        _read("roles/postgres/defaults/main/00-install-and-backup.yml")
    )
    assert defaults["postgres_readonly_logins"] == []
    assert all(
        task.get("loop") == "{{ postgres_readonly_logins }}"
        for task in _tasks()
        if "loop" in task
    )
    assert _render_patroni_readonly_lines([]) == ""


def test_one_login_renders_only_named_select_grants_and_pg_hba_line():
    variables = {"item": FIXTURE}
    user_task = _task("Ensure each read-only login exists with the source password")
    user_args = _render(user_task["community.postgresql.postgresql_user"], variables)
    assert user_args["name"] == "metrics_reader"
    assert user_args["password"] == "example-password"
    assert user_args["role_attr_flags"] == (
        "LOGIN,NOSUPERUSER,NOCREATEDB,NOCREATEROLE,NOINHERIT"
    )
    assert user_task["no_log"] is True

    connect = _render(
        _task("Grant each read-only login CONNECT on its database")[
            "community.postgresql.postgresql_privs"
        ],
        variables,
    )
    usage = _render(
        _task("Grant each read-only login USAGE on the public schema")[
            "community.postgresql.postgresql_privs"
        ],
        variables,
    )
    select = _render(
        _task("Grant each read-only login SELECT on its named public tables")[
            "community.postgresql.postgresql_privs"
        ],
        variables,
    )
    assert (connect["type"], connect["objs"], connect["privs"]) == (
        "database",
        "app_db",
        "CONNECT",
    )
    assert (usage["type"], usage["objs"], usage["privs"]) == (
        "schema",
        "public",
        "USAGE",
    )
    assert (select["type"], select["schema"], select["objs"], select["privs"]) == (
        "table",
        "public",
        "tasks,users",
        "SELECT",
    )

    hba = _render(
        _task("Allow each read-only login from its client CIDR (scram)")
        ["community.postgresql.postgresql_pg_hba"],
        {**variables, "postgres_conf_dir": "/etc/postgresql/18/main"},
    )
    assert (hba["databases"], hba["users"], hba["source"], hba["method"]) == (
        "app_db",
        "metrics_reader",
        "192.0.2.0/24",
        "scram-sha-256",
    )
    assert _render_patroni_readonly_lines([FIXTURE]) == (
        "- host app_db metrics_reader 192.0.2.0/24 scram-sha-256"
    )


def test_missing_tables_fails_the_clear_validation_assertion():
    validation = _task("Assert each read-only login names its allowed tables")
    assert validation["ansible.builtin.assert"]["fail_msg"] == (
        "Each postgres_readonly_logins item must include a non-empty 'tables' list."
    )
    conditions = validation["ansible.builtin.assert"]["that"]
    assert "item.tables is defined" in conditions
    assert (
        _render(f"{{{{ {conditions[0]} }}}}", {"item": {"name": "metrics_reader"}})
        is False
    )
