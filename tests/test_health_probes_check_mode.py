"""Read-only health probes that must execute in Ansible check mode."""

from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
PROBES = (
    (
        "roles/grafana_stack/tasks/main.yml",
        "Verify both stack containers are running",
    ),
    (
        "roles/grafana_stack/tasks/main.yml",
        "Verify VictoriaMetrics answers /health",
    ),
    (
        "roles/grafana_stack/tasks/main.yml",
        "Verify grafana answers /api/health",
    ),
    (
        "roles/grafana_stack/tasks/main.yml",
        "Verify the provisioned datasource resolves in grafana",
    ),
    (
        "roles/grafana_stack/tasks/main.yml",
        "Capture stack diagnostics on failure",
    ),
    (
        "roles/apt_recovery/tasks/main.yml",
        "Wait for package-manager locks to clear",
    ),
    (
        "roles/cribl_docker_stack/tasks/main.yml",
        "Wait for Cribl Edge services to be ready",
    ),
    (
        "roles/cribl_docker_stack/tasks/main.yml",
        "Wait for Cribl Stream services to be ready",
    ),
    (
        "roles/cribl_docker_stack/tasks/main.yml",
        "Verify Cribl Edge health",
    ),
    (
        "roles/cribl_docker_stack/tasks/main.yml",
        "Verify Cribl Stream health",
    ),
    (
        "roles/healthchecks_docker/tasks/main.yml",
        "Verify healthchecks login page renders",
    ),
    (
        "roles/n8n_docker/tasks/main.yml",
        "Verify n8n /healthz endpoint",
    ),
    (
        "roles/n8n_docker/tasks/main.yml",
        "Read n8n frontend settings (owner-setup state)",
    ),
    (
        "roles/status_stack/tasks/main.yml",
        "Verify Gatus answers /",
    ),
    (
        "roles/status_stack/tasks/main.yml",
        "Probe whether Uptime Kuma still needs initial setup",
    ),
    (
        "roles/object_storage/tasks/iam_provision_bucket_role.yml",
        "Read the current canned policies for this bucket",
    ),
    (
        "roles/object_storage/tasks/infra_mirrors.yml",
        "Resolve pointer URLs for missing pointer-based infra artifacts",
    ),
)


def _tasks_in(value):
    if isinstance(value, list):
        for item in value:
            yield from _tasks_in(item)
    elif isinstance(value, dict):
        if "name" in value:
            yield value
        for key in ("block", "rescue", "always"):
            if key in value:
                yield from _tasks_in(value[key])


@pytest.mark.parametrize(("relative_path", "task_name"), PROBES)
def test_read_only_health_probes_run_in_check_mode(relative_path, task_name):
    tasks = yaml.safe_load((REPO / relative_path).read_text(encoding="utf-8"))
    task = next((task for task in _tasks_in(tasks) if task.get("name") == task_name), None)

    assert task is not None, f"Task not found: {task_name}"
    assert task.get("check_mode") is False
    if (
        relative_path == "roles/grafana_stack/tasks/main.yml"
        and task_name != "Capture stack diagnostics on failure"
    ):
        when = task.get("when", "")
        condition = " ".join(when) if isinstance(when, list) else when
        assert "not ansible_check_mode" in condition
        assert "grafana_stack_compose" in condition
