"""Check-mode contracts for the nautobot role."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def test_export_schedule_assertion_skips_check_mode():
    tasks = yaml.safe_load((REPO / "roles/nautobot/tasks/application_bringup.yml").read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    assert task_by_name["Schedule the export Job via celery beat"].get("check_mode") is not False
    assertion = task_by_name["Assert the export schedule was reconciled"]
    assert assertion.get("when") == "not ansible_check_mode"
