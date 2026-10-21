"""Check-mode contracts for the GitHub Runner ARC Helm installation."""

import yaml

from health_probes_check_mode_support import REPO, _tasks_in


def test_helm_binary_copy_is_gated_by_guest_state_in_check_mode():
    relative_path = "roles/github_runner_arc/tasks/k3s.yml"
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task_by_name = {task.get("name"): task for task in _tasks_in(tasks)}

    probe = task_by_name["Check for the extracted Helm binary"]
    assert probe["ansible.builtin.stat"]["path"] == "/tmp/linux-amd64/helm"
    assert probe.get("register") == "github_runner_arc_helm_binary_present"
    assert probe.get("when") == "ansible_check_mode"
    install_condition = task_by_name["Install the Helm binary"].get("when", "")
    assert "not ansible_check_mode" in install_condition
    assert "github_runner_arc_helm_binary_present.stat.exists" in install_condition
