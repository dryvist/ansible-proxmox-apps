"""Zammad webhook + trigger seeding is data-driven, validated and secret-clean.

zammad_webhooks/zammad_triggers (default []) seed native Webhook and Trigger
objects idempotently by name. With both lists empty nothing is seeded and no
rendered bootstrap input changes. Entries are validated before anything is
written, a trigger carries only its webhook action, bearer values reach the
guest via the no_log bootstrap environment only, and staged fragments the role
no longer ships are swept off the target before the bootstrap runs.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from ansible.errors import AnsibleError

from app_agent_helpers import ROOT, _render, _task, _task_tree, _yaml

BOOTSTRAP_TASKS = "roles/zammad/tasks/main/nginx_and_bootstrap.yml"
FRAGMENT = "roles/zammad/files/zammad_bootstrap/55-webhooks-and-triggers.rb"

WEBHOOK = {
    "name": "ticket-created",
    "endpoint": "https://automation.example.com/hooks/ticket-created",
    "bearer_token": "fixture-secret-token-value",
    "custom_payload": (
        '{\n  "ticket_id": "#{ticket.id}",\n  "ticket_number": "#{ticket.number}",\n'
        '  "title": "#{ticket.title}",\n  "group": "#{ticket.group.name}",\n'
        '  "priority": "#{ticket.priority.name}"\n}'
    ),
}
TRIGGER = {
    "name": "notify-automation-ticket-created",
    "condition": {
        "ticket.action": {"operator": "is", "value": ["create"]},
        "ticket.group_id": {"operator": "is", "value": [1]},
    },
    "webhook": "ticket-created",
}


def _zammad_defaults() -> dict:
    values = {}
    for path in sorted((ROOT / "roles/zammad/defaults/main").glob("*.yml")):
        values.update(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    return values


def _bootstrap_tasks() -> list:
    return _yaml(BOOTSTRAP_TASKS)


def _run_env() -> dict:
    return _task(_bootstrap_tasks(), "Run the idempotent Zammad bootstrap")["environment"]


def _conditions_pass(task: dict, item: dict, extra_vars: dict) -> bool:
    return all(_render("{{ " + c + " }}", {"item": item, **extra_vars}) for c in task["ansible.builtin.assert"]["that"])


def _webhook_validation_task() -> dict:
    return _task(_bootstrap_tasks(), "Validate each declared Zammad webhook entry")


def _trigger_validation_task() -> dict:
    return _task(_bootstrap_tasks(), "Validate each declared Zammad trigger entry")


def test_empty_lists_default_and_change_nothing():
    defaults = _zammad_defaults()
    assert defaults["zammad_webhooks"] == []
    assert defaults["zammad_triggers"] == []

    run_env = _run_env()
    assert _render(run_env["ZAMMAD_WEBHOOKS"], {"zammad_webhooks": []}) == "[]"
    assert _render(run_env["ZAMMAD_TRIGGERS"], {"zammad_triggers": []}) == "[]"
    for key, value in run_env.items():
        if key not in ("ZAMMAD_WEBHOOKS", "ZAMMAD_TRIGGERS"):
            assert "zammad_webhook" not in value and "zammad_trigger" not in value, key

    webhook_task = _webhook_validation_task()
    assert _render(webhook_task["vars"]["webhooks_inspectable"], {"zammad_webhooks": []}) == []
    assert _render(_trigger_validation_task()["vars"]["webhook_names"], {"zammad_webhooks": []}) == []
    unique_task = _task(_bootstrap_tasks(), "Require unique Zammad webhook and trigger names")
    for condition in unique_task["ansible.builtin.assert"]["that"]:
        assert _render("{{ " + condition + " }}", {"webhook_names": [], "trigger_names": []}) is True

    # Every model access sits behind the empty-list gate, so an unused feature
    # never even touches the product's model.
    fragment = (ROOT / FRAGMENT).read_text(encoding="utf-8")
    code_lines = [(i, line) for i, line in enumerate(fragment.splitlines()) if not line.strip().startswith("#")]
    gate_line = next(i for i, line in code_lines if line.strip().startswith("if webhooks.any?"))
    model_lines = [i for i, line in code_lines if re.search(r"\b(Webhook|Trigger)\.", line)]
    assert model_lines and all(i > gate_line for i in model_lines)
    assert "destroy" not in fragment and ".delete(" not in fragment


def test_declared_entries_render_and_pass_validation():
    run_env = _run_env()
    rendered = json.loads(_render(run_env["ZAMMAD_WEBHOOKS"], {"zammad_webhooks": [WEBHOOK]}))
    assert rendered == [WEBHOOK]
    assert json.loads(_render(run_env["ZAMMAD_TRIGGERS"], {"zammad_triggers": [TRIGGER]})) == [TRIGGER]

    webhook_task = _webhook_validation_task()
    view = _render(webhook_task["vars"]["webhooks_inspectable"], {"zammad_webhooks": [WEBHOOK]})
    assert view == [{k: v for k, v in WEBHOOK.items() if k != "bearer_token"}]
    assert _conditions_pass(webhook_task, view[0], {})

    trigger_task = _trigger_validation_task()
    names = _render(trigger_task["vars"]["webhook_names"], {"zammad_webhooks": [WEBHOOK]})
    assert names == ["ticket-created"]
    assert _conditions_pass(trigger_task, TRIGGER, {"webhook_names": names})


def test_validation_failures_name_the_entry():
    webhook_task = _webhook_validation_task()
    rendered_fail = _render(
        webhook_task["ansible.builtin.assert"]["fail_msg"],
        {"item": {"name": "ticket-created", "endpoint": "http://automation.example.com/hook"}},
    )
    assert "ticket-created" in rendered_fail

    trigger_task = _trigger_validation_task()
    rendered_trigger_fail = _render(
        trigger_task["ansible.builtin.assert"]["fail_msg"],
        {"item": {"name": "notify-automation-ticket-created", "webhook": "missing"}},
    )
    assert "notify-automation-ticket-created" in rendered_trigger_fail


def test_duplicate_names_fail_validation():
    unique_task = _task(_bootstrap_tasks(), "Require unique Zammad webhook and trigger names")
    duplicate_webhooks = [{"name": "ticket-created", "endpoint": "https://a.example.com"}, {"name": "ticket-created"}]
    duplicate_triggers = [{"name": "notify-x"}, {"name": "notify-x"}]
    names = {
        "webhook_names": _render(unique_task["vars"]["webhook_names"], {"zammad_webhooks": duplicate_webhooks}),
        "trigger_names": _render(unique_task["vars"]["trigger_names"], {"zammad_triggers": duplicate_triggers}),
    }
    for condition in unique_task["ansible.builtin.assert"]["that"]:
        assert _render("{{ " + condition + " }}", names) is False
    single = {"webhook_names": ["ticket-created"], "trigger_names": ["notify-x"]}
    for condition in unique_task["ansible.builtin.assert"]["that"]:
        assert _render("{{ " + condition + " }}", single) is True


def test_non_https_endpoint_fails_validation():
    webhook_task = _webhook_validation_task()
    ok = {"name": "ticket-created", "endpoint": "https://automation.example.com/hooks/ticket-created"}
    plain_http = {"name": "ticket-created", "endpoint": "http://automation.example.com/hooks/ticket-created"}
    no_endpoint = {"name": "ticket-created"}
    assert _conditions_pass(webhook_task, ok, {})
    assert not _conditions_pass(webhook_task, plain_http, {})
    assert not _conditions_pass(webhook_task, no_endpoint, {})
    endpoint_condition = next(c for c in webhook_task["ansible.builtin.assert"]["that"] if "endpoint" in c)
    assert _render("{{ " + endpoint_condition + " }}", {"item": plain_http}) is False


def test_custom_payload_must_be_valid_json_after_placeholder_substitution():
    webhook_task = _webhook_validation_task()
    ok = {"name": "ticket-created", "endpoint": "https://a.example.com", "custom_payload": '{"ticket_id": "#{ticket.id}"}'}
    not_json = {"name": "ticket-created", "endpoint": "https://a.example.com", "custom_payload": '{"ticket_id": #{ticket.id}}'}
    not_object = {"name": "ticket-created", "endpoint": "https://a.example.com", "custom_payload": '"just a string"'}
    assert _conditions_pass(webhook_task, ok, {})
    payload_condition = next(c for c in webhook_task["ansible.builtin.assert"]["that"] if "custom_payload" in c)
    assert _render("{{ " + payload_condition + " }}", {"item": not_object}) is False
    with pytest.raises(AnsibleError):
        _render("{{ " + payload_condition + " }}", {"item": not_json})


def test_unknown_trigger_webhook_fails_validation():
    trigger_task = _trigger_validation_task()
    names = ["ticket-created"]
    ok_condition = {"ticket.action": {"operator": "is", "value": ["create"]}}
    ok = {"name": "notify-x", "condition": ok_condition, "webhook": "ticket-created"}
    unknown_webhook = {"name": "notify-x", "condition": ok_condition, "webhook": "not-declared"}
    no_condition = {"name": "notify-x", "webhook": "ticket-created"}
    assert _conditions_pass(trigger_task, ok, {"webhook_names": names})
    assert not _conditions_pass(trigger_task, unknown_webhook, {"webhook_names": names})
    assert not _conditions_pass(trigger_task, no_condition, {"webhook_names": names})


def test_no_token_value_appears_in_any_rendered_output():
    run_task = _task(_bootstrap_tasks(), "Run the idempotent Zammad bootstrap")
    assert run_task.get("no_log") is True

    webhook_task = _webhook_validation_task()
    # The key name itself must stay out of the validation task: its loop items
    # are what this task can print on a failure.
    assert "bearer_token" not in str(webhook_task)
    view = _render(webhook_task["vars"]["webhooks_inspectable"], {"zammad_webhooks": [WEBHOOK]})
    assert "fixture-secret-token-value" not in json.dumps(view)
    rendered_fail = _render(webhook_task["ansible.builtin.assert"]["fail_msg"], {"item": view[0]})
    assert "fixture-secret-token-value" not in rendered_fail
    assert "fixture-secret-token-value" not in str(_bootstrap_tasks())


def test_trigger_performs_only_the_webhook_action():
    fragment = (ROOT / FRAGMENT).read_text(encoding="utf-8")
    assert fragment.count("'notification.") == 1
    assert "'notification.webhook'" in fragment
    assert "declared['perform']" not in fragment
    perform_line = next(line for line in fragment.splitlines() if "'notification.webhook'" in line)
    assert perform_line.strip().startswith("perform:")
    assert perform_line.count("=>") == 2
    assert "'webhook_id' => target.id.to_s" in perform_line
    # Version guards fail naming the missing attribute before either optional
    # attribute is used.
    assert "Webhook.attribute_names" in fragment
    assert "is missing" in fragment


def test_bootstrap_fragments_are_valid_ruby():
    fragments = sorted((ROOT / "roles/zammad/files/zammad_bootstrap").glob("*.rb"))
    assert len(fragments) >= 8
    ruby = shutil.which("ruby")
    if ruby is None:
        pytest.skip("ruby is not available in this environment")
    for fragment in fragments:
        result = subprocess.run([ruby, "-c", str(fragment)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, f"{fragment.relative_to(ROOT)}: {result.stderr or result.stdout}"


def test_stale_staged_fragments_are_removed():
    tasks = _bootstrap_tasks()
    task_names = [task.get("name") for task in _task_tree(tasks)]

    shipped_task = _task(tasks, "Record the bootstrap fragments the role ships")
    shipped_expression = shipped_task["ansible.builtin.set_fact"]["zammad_bootstrap_shipped_fragments"]
    assert "fileglob" in shipped_expression and "zammad_bootstrap" in str(shipped_task)

    find_task = _task(tasks, "List the staged Zammad bootstrap fragments on the target")
    assert find_task["ansible.builtin.find"]["paths"] == "{{ zammad_root }}/ansible_bootstrap"
    assert find_task["ansible.builtin.find"]["patterns"] == "*.rb"

    removal = _task(tasks, "Remove staged bootstrap fragments the role no longer ships")
    when = removal["when"]
    assert "zammad_bootstrap_shipped_fragments" in when and "basename" in when

    shipped_names = sorted(path.name for path in (ROOT / "roles/zammad/files/zammad_bootstrap").glob("*.rb"))
    stale = {"item": {"path": "/opt/zammad/ansible_bootstrap/55-agent-webhooks.rb"}}
    assert _render("{{ " + when + " }}", {**stale, "zammad_bootstrap_shipped_fragments": shipped_names}) is True
    kept = {"item": {"path": "/opt/zammad/ansible_bootstrap/50-jobs-and-slas.rb"}}
    assert _render("{{ " + when + " }}", {**kept, "zammad_bootstrap_shipped_fragments": shipped_names}) is False

    assert task_names.index("Stage the Zammad bootstrap fragments on the target") < task_names.index(
        "List the staged Zammad bootstrap fragments on the target"
    ) < task_names.index("Remove staged bootstrap fragments the role no longer ships") < task_names.index(
        "Run the idempotent Zammad bootstrap"
    )


def test_readme_example_stays_generic_and_lookup_only():
    readme = (ROOT / "roles/zammad/README.md").read_text(encoding="utf-8")
    assert "https://automation.example.com/hooks/ticket-created" in readme
    assert "lookup('env'" in readme
    assert not re.search(r"\b(?:10|172|192)\.\d+\.\d+\.\d+", readme)
