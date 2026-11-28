"""Vikunja task-event webhooks: gated, attributed, target-matched and read back."""

from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / "roles/vikunja/defaults/main/16-task-webhooks.yml"
MAIN = ROOT / "roles/vikunja/tasks/main.yml"
ONE = ROOT / "roles/vikunja/tasks/task_webhook_one.yml"
ALL = ROOT / "roles/vikunja/tasks/task_webhooks.yml"


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _uri_tasks(path):
    return [t for t in _load(path) if "ansible.builtin.uri" in t]


def _render_expr(condition, variables):
    """Render a bare assert/when source: it is not wrapped in {{ }}."""
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template("{{ " + condition + " }}"))


def _assert_task():
    for task in _load(ONE):
        if "ansible.builtin.assert" in task:
            return task
    raise AssertionError("no assert task found in task_webhook_one.yml")


def _task(path, name):
    return next(task for task in _load(path) if task.get("name") == name)


def _assert_clauses(matches, events):
    variables = {
        "_matches": matches,
        "vikunja_task_webhook": {"events": events, "task_events": False},
        "vikunja_task_events_basic_user": "vikunja-task-events",
    }
    return [bool(_render_expr(clause, variables))
            for clause in _assert_task()["ansible.builtin.assert"]["that"]]


def test_no_webhooks_by_default_and_include_is_gated():
    assert _load(DEFAULTS)["vikunja_task_webhooks"] == []
    assert _load(DEFAULTS)["vikunja_task_events_enabled"] is False
    [inc] = [t for t in _load(MAIN) if t.get("ansible.builtin.include_tasks") == "task_webhooks.yml"]
    assert inc["when"] == "vikunja_task_webhooks | length > 0 or vikunja_task_events_enabled | bool"


def test_secret_is_required_before_any_request():
    first = _load(ALL)[0]
    assert first["name"] == "Require the task-event target and shared Basic password"
    assert "vikunja_task_events_basic_password | default('', true) | length > 0" in first["ansible.builtin.assert"]["that"]
    assert "VIKUNJA_TASK_EVENTS_PASSWORD" in first["ansible.builtin.assert"]["fail_msg"]
    secret = _task(ALL, "Require the route-only webhook secret")
    assert "vikunja_task_webhook_secret | length > 0" in secret["ansible.builtin.assert"]["that"]
    assert secret["when"] == "vikunja_task_webhooks | length > 0"


def test_reconcile_creates_or_updates_only_a_matching_target():
    tasks = _load(ONE)
    requests = _uri_tasks(ONE)
    assert [task["ansible.builtin.uri"]["method"] for task in requests] == ["POST", "GET", "PUT", "PUT", "GET"]
    create = requests[2]
    update = requests[3]
    assert create["ansible.builtin.uri"]["body"]["secret"].startswith("{{ vikunja_task_webhook_secret if not")
    assert "_matches | length == 0" in create["when"]
    assert update["name"].startswith("Update the task-event webhook")
    assert "webhooks/{{ (_matches | first).id }}" in update["ansible.builtin.uri"]["url"]
    assert all(
        "selectattr('target_url', 'equalto', vikunja_task_webhook.target_url)" in task["vars"]["_matches"]
        for task in tasks
        if "_matches" in task.get("vars", {})
    )
    assert "basic_auth_password" in create["ansible.builtin.uri"]["body"]
    assert create["no_log"] is True and update["no_log"] is True


def test_password_default_and_password_requests_are_secret_safe():
    defaults = _load(DEFAULTS)
    assert defaults["vikunja_task_events_basic_password"] == "{{ lookup('ansible.builtin.env', 'VIKUNJA_TASK_EVENTS_PASSWORD') }}"
    password_requests = [
        task for task in _uri_tasks(ONE)
        if "basic_auth_password" in task["ansible.builtin.uri"].get("body", {})
    ]
    assert password_requests
    assert all(task["no_log"] is True for task in password_requests)


def test_task_event_defaults_and_project_listing_are_complete_and_paged():
    defaults = _load(DEFAULTS)
    events = defaults["vikunja_task_events_events"]
    assert events and all(isinstance(event, str) and event.startswith("task") for event in events)
    assert defaults["vikunja_task_events_owner"] == "{{ vikunja_mcp_ro_share_owner_usernames | first }}"
    assert {"task.created", "task.updated", "task.deleted"} <= set(events)
    assert {"task.comment.created", "task.comment.edited", "task.comment.deleted"} <= set(events)
    assert {"task.restored", "task.purged"} <= set(events)
    assert {"task.assignee.created", "task.assignee.deleted"} <= set(events)
    assert {"task.relation.created", "task.relation.deleted"} <= set(events)
    assert {"task.attachment.created", "task.attachment.deleted"} <= set(events)
    assert defaults["vikunja_task_events_url"]
    assert "vikunja_task_events_cribl_host" in defaults["vikunja_task_events_url"]
    assert "vikunja_task_events_cribl_port" in defaults["vikunja_task_events_url"]
    assert "range(2," in str(_task(ALL, "List the remaining pages of task-event projects")["loop"])
    assert _task(ALL, "List the first page of projects visible to the task-event owner")["check_mode"] is False
    login = _task(ALL, "Log in to Vikunja to list task-event projects")["ansible.builtin.uri"]
    assert login["body"]["username"] == "{{ vikunja_task_events_owner }}"
    assert _task(ALL, "Log in to Vikunja to list task-event projects")["no_log"] is True


def test_every_request_hides_credentials():
    assert all(t.get("no_log") is True for t in _uri_tasks(ONE))


# --- the readback assert: renders in every outcome, fails with its fail_msg ----
#
# The assert names the match count in its fail_msg, so it must EVALUATE even
# when the readback holds no matching webhook: `first` of an empty list is
# undefined, and an unguarded clause would raise AnsibleUndefinedVariable
# there, failing the task on a raw Jinja error instead of the fail_msg.


def test_the_readback_assert_passes_on_the_declared_webhook():
    matches = [{"target_url": "https://example.invalid/hook",
                "events": ["task.created", "task.updated"]}]
    assert _assert_clauses(matches, ["task.created", "task.updated"]) == [True, True, True]


def test_the_readback_assert_fails_on_drifted_events():
    matches = [{"target_url": "https://example.invalid/hook", "events": ["task.updated"]}]
    assert _assert_clauses(matches, ["task.created"]) == [True, False, True]


def test_the_readback_assert_fails_cleanly_when_the_webhook_is_absent():
    # The regression: with no matching webhook, both clauses must render False
    # (so the assert fails with its fail_msg) rather than raise.
    assert _assert_clauses([], ["task.created"]) == [False, False, True]


def test_the_readback_assert_fails_on_a_match_without_events():
    assert _assert_clauses([{"target_url": "https://example.invalid/hook"}],
                           ["task.created"]) == [True, False, True]


def test_the_readback_assert_runs_only_outside_check_mode():
    assert _assert_task()["when"] == "not ansible_check_mode"
