"""Declared project webhooks: off by default, signed, matched by target, create-only."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / "roles/vikunja/defaults/main/16-task-webhooks.yml"
MAIN = ROOT / "roles/vikunja/tasks/main.yml"
ONE = ROOT / "roles/vikunja/tasks/task_webhook_one.yml"
ALL = ROOT / "roles/vikunja/tasks/task_webhooks.yml"


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _uri_tasks(path):
    return [t for t in _load(path) if "ansible.builtin.uri" in t]


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
