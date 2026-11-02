"""Runtime safety contracts for the Hatchet kill test."""

from pathlib import Path
import re

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
from jinja2 import meta, nodes
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks/hatchet-killtest.yml"
TASK_DIR = ROOT / "playbooks/tasks"
TASK_FILES = sorted(TASK_DIR.glob("hatchet_killtest_*.yml"))
FILES = [PLAYBOOK, *TASK_FILES]
RESTORE_READINESS_FILES = [
    TASK_DIR / "hatchet_killtest_phases.yml",
    TASK_DIR / "hatchet_killtest_ready.yml",
    TASK_DIR / "hatchet_killtest_ready_poll.yml",
    TASK_DIR / "hatchet_killtest_start.yml",
]
JINJA_BUILTIN_NAMES = {
    "ansible_failed_task",
    "groups",
    "hostvars",
    "inventory_hostname",
    "lookup",
    "now",
}
RAW_EXPRESSION_KEYS = {"changed_when", "failed_when", "that", "until", "when"}
_JINJA = Templar(loader=DataLoader()).environment


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _tasks(node):
    for task in node or []:
        if not isinstance(task, dict):
            continue
        yield task
        for key in ("block", "rescue", "always"):
            yield from _tasks(task.get(key))


def _all_tasks():
    for path in FILES:
        data = _load(path)
        plays = data if path == PLAYBOOK else [{"tasks": data}]
        for play in plays:
            yield from _tasks(play.get("tasks"))


def _refusal_task():
    return next(
        task for task in _load(PLAYBOOK)[0]["tasks"]
        if task.get("name", "").startswith("Refuse caller-supplied")
    )


def _strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)
    elif isinstance(value, str):
        yield value


def _parsed_templates(value, expression=False):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _parsed_templates(child, key in RAW_EXPRESSION_KEYS)
    elif isinstance(value, list):
        for child in value:
            yield from _parsed_templates(child, expression)
    elif isinstance(value, str):
        if "{{" in value or "{%" in value:
            yield _JINJA.parse(value)
        elif expression:
            yield _JINJA.parse("{{ " + value + " }}")


def _loop_variables(paths):
    variables = set()
    for path in paths:
        for task in _tasks(_load(path)):
            if "loop" in task or any(key.startswith("with_") for key in task):
                variables.add(task.get("loop_control", {}).get("loop_var", "item"))
    return variables


def test_every_set_fact_and_register_name_is_refused():
    state_names = set()
    for task in _all_tasks():
        state_names.update(task.get("ansible.builtin.set_fact", {}))
        if "register" in task:
            state_names.add(task["register"])

    refusal = _refusal_task()
    refused_names = set(refusal["loop"])
    assert state_names <= refused_names, sorted(state_names - refused_names)

    templates = [
        tree
        for path in RESTORE_READINESS_FILES
        for tree in _parsed_templates(_load(path))
    ]
    read_names = set().union(*(meta.find_undeclared_variables(tree) for tree in templates))
    loop_names = _loop_variables(RESTORE_READINESS_FILES)
    covered_names = refused_names | loop_names | JINJA_BUILTIN_NAMES | state_names
    assert read_names <= covered_names, sorted(read_names - covered_names)

    hostvar_fields = {
        node.attr
        for tree in templates
        for node in tree.find_all(nodes.Getattr)
        if isinstance(node.node, nodes.Getitem)
        and isinstance(node.node.node, nodes.Name)
        and node.node.node.name == "hostvars"
    }
    assert hostvar_fields <= refused_names, sorted(hostvar_fields - refused_names)
    caller_overrides = {"container_ip", "host_tags", "ingress_domain", "_task", "_exitstatus"}
    assert caller_overrides <= refused_names, sorted(caller_overrides - refused_names)


def test_each_refused_name_with_the_old_sentinel_is_rejected_by_presence():
    refusal = _refusal_task()
    expression = refusal["ansible.builtin.assert"]["that"]
    assert expression == "item not in hostvars[inventory_hostname]"

    for name in refusal["loop"]:
        templar = Templar(
            loader=DataLoader(),
            variables={
                "inventory_hostname": "localhost",
                "hostvars": {"localhost": {name: "__unset__"}},
                "item": name,
            },
        )
        result = templar.template(trust_as_template("{{ " + expression + " }}"))
        assert result is False, name


def test_each_deadline_timestamp_renders_to_a_number_with_ansible_templar():
    timestamps = []
    expressions = []
    pattern = re.compile(r"now\([^)]*\)\.timestamp\(\)")
    for path in FILES:
        for value in _strings(_load(path)):
            timestamps.extend(pattern.findall(value))
            stripped = value.strip()
            if stripped.startswith("{{") and "now(" in stripped:
                expressions.append(stripped)

    assert timestamps
    assert set(timestamps) == {"now(utc=True).timestamp()"}
    variables = {
        "hatchet_killtest_budget_seconds": 570,
        "hatchet_killtest_deadline_epoch": 1_800_000_000.0,
        "hatchet_killtest_recovery_reserve": 300,
        "hatchet_killtest_ready_pause": 5,
        "hatchet_killtest_poll": 0,
        "hatchet_killtest_ready_polls": 20,
    }
    for timestamp in timestamps:
        result = Templar(loader=DataLoader(), variables=variables).template(
            trust_as_template("{{ " + timestamp + " }}")
        )
        assert type(result) in (int, float), (timestamp, result)
    for expression in expressions:
        result = Templar(loader=DataLoader(), variables=variables).template(
            trust_as_template(expression)
        )
        assert type(result) in (int, float), (expression, result)


def test_alert_result_is_reported_without_suppressing_restore_failure():
    phases = _load(TASK_DIR / "hatchet_killtest_phases.yml")[0]
    rescue = phases["always"][0]["rescue"]
    alert = next(task for task in rescue if task["name"].startswith("Alert when"))
    failure = next(task for task in rescue if task["name"].startswith("Fail loudly"))

    assert alert["register"] == "hatchet_killtest_alert"
    assert alert["failed_when"] is False
    assert "ignore_errors" not in alert
    message = failure["ansible.builtin.fail"]["msg"]
    assert "hatchet_killtest_alert.status" in message
    assert "hatchet_killtest_alert.msg" in message


def test_imported_preflight_is_bounded_inside_the_run_deadline():
    plays = _load(PLAYBOOK)
    first_play = plays[0]
    refusal = next(
        index for index, task in enumerate(first_play["tasks"])
        if task.get("name", "").startswith("Refuse caller-supplied")
    )
    timer = next(
        index for index, task in enumerate(first_play["tasks"])
        if task.get("name", "").startswith("Start the single end-to-end")
    )
    assert first_play["gather_facts"] is False
    assert refusal < timer < len(first_play["tasks"])
    assert [task["name"] for task in first_play["tasks"][:timer]] == [
        "Refuse caller-supplied inventory, secret and kill-test values",
        "Require the published inventory source",
        "Set the fixed kill-test time budget and recovery reserve",
    ]
    assert plays[1]["import_playbook"] == "../inventory/load_tofu.yml"

    inventory_play = _load(ROOT / "inventory/load_tofu.yml")[0]
    assert inventory_play["gather_facts"] is False

    preflight = _load(ROOT / "inventory/load_tofu/add_lxc_hosts.yml")
    placement = next(task for task in preflight if task["name"] == "Read live container placement from the cluster")
    assert placement["ansible.builtin.command"].split()[:3] == ["timeout", "--kill-after=1", "15"]
