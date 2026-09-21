"""The excess-replica teardown must discover units systemd actually runs.

`ansible_facts.services` (the `service_facts` module) sources unit state from
`systemctl list-unit-files`, which lists a systemd TEMPLATE by its bare
generic name (`github-runner@.service`) -- an instantiated unit like
`github-runner@1.service` only exists in `list-units`. A "stop everything not
wanted" task that filters `ansible_facts.services` for the instance pattern
therefore always matches nothing: the loop silently evaluates to an empty
list, and no unit is ever stopped, regardless of how many are actually
running.

That is exactly what happened on the execution-plane host: it converges with
`github_runner_replicas: 0`, so nothing is ever "wanted", and the same empty
match meant three already-running `github-runner@N` units were never told to
stop -- confirmed live (a real converge's own task output showed the stop
task's loop matching zero items while three instances were actively
crash-looping on that host).

This test is a structural, host-independent guard against the same class of
regression recurring: it parses the role's own task file and asserts the
excess-replica teardown enumerates candidate units from a live `systemctl
list-units` query (which resolves template instances) and never from
`ansible_facts.services` (which cannot see them). It fails against the
pre-fix task file and passes against the fixed one.
"""

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "roles" / "github_runner" / "tasks" / "main.yml"
STOP_TASK_NAME = "Stop runners above the configured replica count"


def _load_tasks():
    text = TASKS_FILE.read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _find_task(tasks, name):
    for task in tasks:
        if isinstance(task, dict) and task.get("name") == name:
            return task
    return None


def _loop_source_text(task):
    """Render the task's `loop:` value back to a single string for matching.

    The loop is a folded (`>-`) Jinja block scalar, so PyYAML already hands
    it back as one plain string -- no re-serialization needed.
    """
    loop = task.get("loop")
    assert isinstance(loop, str), f"expected a string loop expression, got {loop!r}"
    return loop


def test_stop_task_exists():
    tasks = _load_tasks()
    task = _find_task(tasks, STOP_TASK_NAME)
    assert task is not None, f"no task named {STOP_TASK_NAME!r} in {TASKS_FILE}"


def test_stop_task_never_sources_units_from_service_facts():
    """RED on the pre-fix file: its loop read `ansible_facts.services`."""
    task = _find_task(_load_tasks(), STOP_TASK_NAME)
    loop_text = _loop_source_text(task)
    assert "ansible_facts.services" not in loop_text, (
        "the excess-replica teardown loop reads ansible_facts.services, "
        "which cannot see an instantiated systemd template unit "
        "(github-runner@N.service) -- it only ever matches the template's "
        "own bare name, so this loop always evaluates empty and nothing "
        "ever gets stopped"
    )


def test_stop_task_sources_units_from_a_live_systemctl_query():
    """GREEN on the fixed file: the loop reads a systemctl list-units result."""
    tasks = _load_tasks()
    stop_task = _find_task(tasks, STOP_TASK_NAME)
    loop_text = _loop_source_text(stop_task)

    registered_var_match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\.stdout_lines", loop_text)
    assert registered_var_match, (
        "the excess-replica teardown loop does not read `<var>.stdout_lines` "
        "from a registered command result"
    )
    registered_var = registered_var_match.group(1)

    source_task = None
    for task in tasks:
        if isinstance(task, dict) and task.get("register") == registered_var:
            source_task = task
            break
    assert source_task is not None, (
        f"no task registers {registered_var!r}, which the teardown loop reads"
    )

    command = source_task.get("ansible.builtin.command")
    assert command is not None, (
        f"the task registering {registered_var!r} must query systemd "
        "directly (ansible.builtin.command), not service_facts -- that is "
        "the only source that resolves an instantiated template unit name"
    )
    cmd_text = command.get("cmd") if isinstance(command, dict) else command
    assert isinstance(cmd_text, str) and "systemctl list-units" in cmd_text, (
        f"expected a `systemctl list-units` query, got {cmd_text!r}"
    )
    assert "github-runner@" in cmd_text, (
        f"the systemctl query must glob on the github-runner@ instance "
        f"prefix, got {cmd_text!r}"
    )


def test_no_service_facts_task_feeds_the_stop_loop():
    """A service_facts task earlier in the file must not be what the loop reads.

    This is the precise pre-fix shape: a `service_facts` task registered no
    variable of its own (it populates the global `ansible_facts` instead), so
    the previous test already covers that direct reference. This test guards
    the equivalent regression where a future edit reintroduces a
    service_facts-backed variable and points the loop at it by name.
    """
    tasks = _load_tasks()
    stop_task = _find_task(tasks, STOP_TASK_NAME)
    loop_text = _loop_source_text(stop_task)

    service_facts_vars = {
        task.get("register")
        for task in tasks
        if isinstance(task, dict)
        and "ansible.builtin.service_facts" in task
        and task.get("register")
    }
    for var in service_facts_vars:
        assert var not in loop_text, (
            f"the excess-replica teardown loop reads {var!r}, which is "
            "populated by service_facts -- that source cannot see an "
            "instantiated systemd template unit"
        )
