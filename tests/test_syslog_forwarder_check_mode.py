"""Check-mode contracts for the syslog forwarder."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def test_rsyslog_service_steps_skip_a_previewed_install():
    tasks = yaml.safe_load((REPO / "roles/syslog_forwarder/tasks/main.yml").read_text(encoding="utf-8"))
    handlers = yaml.safe_load((REPO / "roles/syslog_forwarder/handlers/main.yml").read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    assert task_by_name["Install rsyslog"].get("register") == "syslog_forwarder_rsyslog_install"
    gate = "not (ansible_check_mode and syslog_forwarder_rsyslog_install is changed)"
    assert task_by_name["Enable and start rsyslog"].get("when") == gate
    assert handlers[0].get("when") == gate
