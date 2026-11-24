"""Declared project webhooks: off by default, signed, matched by target, create-only."""

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


def _assert_clauses(matches, events):
    variables = {
        "_matches": matches,
        "vikunja_task_webhook": {"events": events},
    }
    return [bool(_render_expr(clause, variables))
            for clause in _assert_task()["ansible.builtin.assert"]["that"]]


def test_no_webhooks_by_default_and_include_is_gated():
    assert _load(DEFAULTS)["vikunja_task_webhooks"] == []
    [inc] = [t for t in _load(MAIN) if t.get("ansible.builtin.include_tasks") == "task_webhooks.yml"]
    assert inc["when"] == "vikunja_task_webhooks | length > 0"


def test_secret_is_required_before_any_request():
    first = _load(ALL)[0]
    assert "vikunja_task_webhook_secret | length > 0" in first["ansible.builtin.assert"]["that"]


def test_only_login_reads_and_create_no_delete_or_update():
    methods = [t["ansible.builtin.uri"]["method"] for t in _uri_tasks(ONE)]
    assert methods == ["POST", "GET", "PUT", "GET"]
    put = _uri_tasks(ONE)[2]
    assert put["ansible.builtin.uri"]["body"]["secret"] == "{{ vikunja_task_webhook_secret }}"
    assert "target_url not in" in put["when"]


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
    assert _assert_clauses(matches, ["task.created", "task.updated"]) == [True, True]


def test_the_readback_assert_fails_on_drifted_events():
    matches = [{"target_url": "https://example.invalid/hook", "events": ["task.updated"]}]
    assert _assert_clauses(matches, ["task.created"]) == [True, False]


def test_the_readback_assert_fails_cleanly_when_the_webhook_is_absent():
    # The regression: with no matching webhook, both clauses must render False
    # (so the assert fails with its fail_msg) rather than raise.
    assert _assert_clauses([], ["task.created"]) == [False, False]


def test_the_readback_assert_fails_on_a_match_without_events():
    assert _assert_clauses([{"target_url": "https://example.invalid/hook"}],
                           ["task.created"]) == [True, False]


def test_the_readback_assert_runs_only_outside_check_mode():
    assert _assert_task()["when"] == "not ansible_check_mode"
