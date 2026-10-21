"""Check-mode contracts for Homarr upgrades."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def test_homarr_post_upgrade_assertion_skips_check_mode():
    relative_path = "roles/homarr/tasks/upgrade.yml"
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    assertion = task_by_name["Assert the pinned release is what deployed"]
    assert assertion.get("when") == "not ansible_check_mode"


def test_homarr_converger_output_consumers_skip_check_mode():
    relative_path = "roles/homarr/tasks/integrations.yml"
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    report = task_by_name["Report what the converger did"]
    assert report.get("when") == "not ansible_check_mode"
    publish = task_by_name["Publish the Homarr admin password and API key to OpenBao"]
    assert "not ansible_check_mode" in publish.get("when")
