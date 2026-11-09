"""The Log Exporter re-save runs on drift, or on the one-shot force input."""

from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

TASKS = Path(__file__).resolve().parents[1] / "roles/technitium_dns/tasks/query_log.yml"
DEFAULTS = (
    Path(__file__).resolve().parents[1]
    / "roles/technitium_dns/defaults/main/03-forwarders-and-query-log.yml"
)
TASK_NAME = "Configure Log Exporter syslog export (drift-gated)"

EQUAL_CONFIGS = {"syslog": {"address": "syslog.example.net", "port": 522}}


def _ansible_bool(value):
    # Ansible's `| bool` coercion for the value types the condition sees here
    # (the default feeds a real bool; an extra -e feed can hand over a str).
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "on", "1")
    return bool(value)


def _configure_task():
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    return next(task for task in tasks if task.get("name") == TASK_NAME)


def _task_runs(when, **variables):
    # Ansible ANDs the when-list items, rendering each as a standalone Jinja
    # template. Rendering the role's own expression strings — not a rewritten
    # copy — is what keeps this test honest when the condition moves.
    env = Environment(undefined=StrictUndefined)
    env.filters["bool"] = _ansible_bool
    for condition in when:
        rendered = str(env.from_string(condition).render(**variables)).strip().lower()
        assert rendered in ("true", "false"), f"unexpected condition result {rendered!r}: {condition}"
        if rendered != "true":
            return False
    return True


def test_force_set_defaults_to_false():
    defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))
    assert defaults["technitium_dns_query_log_force_set"] is False


def test_equal_configs_skip_the_re_save_by_default():
    task = _configure_task()
    assert not _task_runs(
        task["when"],
        ansible_check_mode=False,
        technitium_dns_apply=True,
        technitium_dns_query_log_desired_config=EQUAL_CONFIGS,
        technitium_dns_query_log_live_config=EQUAL_CONFIGS,
        technitium_dns_query_log_force_set=False,
    )


def test_force_set_runs_the_re_save_even_when_configs_are_equal():
    task = _configure_task()
    assert _task_runs(
        task["when"],
        ansible_check_mode=False,
        technitium_dns_apply=True,
        technitium_dns_query_log_desired_config=EQUAL_CONFIGS,
        technitium_dns_query_log_live_config=EQUAL_CONFIGS,
        technitium_dns_query_log_force_set=True,
    )


def test_drift_still_runs_the_re_save_without_the_force_input():
    task = _configure_task()
    assert _task_runs(
        task["when"],
        ansible_check_mode=False,
        technitium_dns_apply=True,
        technitium_dns_query_log_desired_config={"syslog": {"port": 523}},
        technitium_dns_query_log_live_config=EQUAL_CONFIGS,
        technitium_dns_query_log_force_set=False,
    )


def test_force_set_cannot_bypass_the_apply_or_check_mode_gates():
    task = _configure_task()
    forced_equal = dict(
        technitium_dns_query_log_desired_config=EQUAL_CONFIGS,
        technitium_dns_query_log_live_config=EQUAL_CONFIGS,
        technitium_dns_query_log_force_set=True,
    )
    assert not _task_runs(
        task["when"], ansible_check_mode=False, technitium_dns_apply=False, **forced_equal
    )
    assert not _task_runs(
        task["when"], ansible_check_mode=True, technitium_dns_apply=True, **forced_equal
    )


def test_the_re_save_keeps_no_log():
    assert _configure_task().get("no_log") is True
