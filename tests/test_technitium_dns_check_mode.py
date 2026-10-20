"""Check-mode contracts for technitium_dns."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def test_technitium_check_mode_skips_query_log_followups_when_install_is_skipped():
    tasks = yaml.safe_load((REPO / "roles/technitium_dns/tasks/query_log.yml").read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    guarded_tasks = (
        "Re-read the DNS app list after install or update",
        "Require the Log Exporter app to have actually loaded",
        "Read the live Log Exporter app config",
        "Compute the desired Log Exporter config (app config + our syslog block)",
    )
    for task_name in guarded_tasks:
        when = task_by_name[task_name].get("when", "")
        condition = " ".join(when) if isinstance(when, list) else when
        assert "not ansible_check_mode" in condition
        assert "technitium_dns_query_log_app_installed" in condition

    for task_name in (
        "Install the Log Exporter app from the internal object-storage mirror",
        "Update the Log Exporter app to the pinned version",
        "Configure Log Exporter syslog export (drift-gated)",
    ):
        when = task_by_name[task_name].get("when", "")
        condition = " ".join(when) if isinstance(when, list) else when
        assert "not ansible_check_mode" in condition
        assert task_by_name[task_name].get("check_mode") is not False

    # A real run configures the app it just installed, so the write must not
    # gate on the fact read before the install.
    when = task_by_name["Configure Log Exporter syslog export (drift-gated)"].get("when", "")
    assert "technitium_dns_query_log_app_installed" not in " ".join(when)


def test_technitium_write_result_assertion_skips_check_mode():
    tasks = yaml.safe_load(
        (REPO / "roles/technitium_dns/tasks/main/infra_a_records.yml").read_text(encoding="utf-8")
    )
    task = next(
        task for task in _tasks_in(tasks)
        if task.get("name") == "Assert the infrastructure A records were actually written"
    )
    when = task.get("when", "")
    condition = " ".join(when) if isinstance(when, list) else when
    assert "not ansible_check_mode" in condition
