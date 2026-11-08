"""Grafana provisioning files are written before the stack restart and health check.

Grafana reads provisioning only at start, so a health check ahead of the
provisioning part keeps a broken provisioned file from ever being replaced.
"""

from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
ROLE_TASKS = REPO / "roles/grafana_stack/tasks"
FILE_WRITERS = {
    "ansible.builtin.get_url",
    "ansible.builtin.replace",
    "ansible.builtin.template",
    "ansible.builtin.unarchive",
}
RELEASE_DASHBOARDS_AND_ALERTING = {
    "Deploy provisioned dashboards from the pinned grafana-dashboards release",
    "Deploy the accelerator and spend alert rules and their critical Slack contact point "
    "from the pinned release",
    "Render grafana unified-alerting provisioning",
}
STACK_DEPLOY = "Deploy the grafana stack via docker compose"
HEALTH_CHECK = "Verify grafana answers /api/health"


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _run_order(tasks):
    for task in tasks:
        if "ansible.builtin.import_tasks" in task:
            yield from _run_order(_load(ROLE_TASKS / task["ansible.builtin.import_tasks"]))
        elif "block" in task:
            for key in ("block", "rescue", "always"):
                yield from _run_order(task.get(key, []))
        else:
            yield task


def _role_main_order():
    return list(_run_order(_load(ROLE_TASKS / "main.yml")))


def _site_playbook_order():
    playbook = _load(REPO / "playbooks/site/04e-grafana-stack.yml")
    play = next(play for play in playbook if play.get("hosts") == "grafana_group")
    block = next(task for task in play["tasks"] if task.get("block"))["block"]
    return [
        task
        for include in block
        if include.get("ansible.builtin.include_role", {}).get("name") == "grafana_stack"
        for task in _run_order(
            _load(ROLE_TASKS / f"{include['ansible.builtin.include_role']['tasks_from']}.yml")
        )
    ]


def _part_task_names(filename):
    return [task["name"] for task in _run_order(_load(ROLE_TASKS / filename))]


RUN_ORDERS = pytest.mark.parametrize(
    "run_order", [_role_main_order, _site_playbook_order], ids=["role_main", "site_playbook"]
)


@RUN_ORDERS
def test_provisioning_files_are_written_before_the_stack_restart_and_health_check(run_order):
    tasks = run_order()
    names = [task.get("name") for task in tasks]
    writers = [
        task["name"]
        for task in _run_order(_load(ROLE_TASKS / "provisioning.yml"))
        if FILE_WRITERS & task.keys()
    ]
    assert RELEASE_DASHBOARDS_AND_ALERTING <= set(writers)

    first_restart = next(
        index
        for index, task in enumerate(tasks)
        if task.get("ansible.builtin.meta") == "flush_handlers"
    )
    last_write = max(names.index(name) for name in writers)
    assert last_write < first_restart
    assert last_write < names.index(STACK_DEPLOY) < names.index(HEALTH_CHECK)


@RUN_ORDERS
def test_health_check_runs_once_after_deploy_and_provisioning(run_order):
    names = [task.get("name") for task in run_order()]
    assert names.count(HEALTH_CHECK) == 1
    health_check = names.index(HEALTH_CHECK)
    for filename in ("deploy.yml", "provisioning.yml"):
        assert all(names.index(name) < health_check for name in _part_task_names(filename))
