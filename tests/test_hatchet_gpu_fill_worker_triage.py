"""Contracts for scheduled, comment-only Vikunja triage."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
WORKER_PACKAGE = ROOT / "roles/hatchet_docker/files/gpu_fill_worker"
if str(WORKER_PACKAGE) not in sys.path:
    sys.path.insert(0, str(WORKER_PACKAGE))
sys.dont_write_bytecode = True

from config import load_config  # noqa: E402
from triage import tasks as triage_tasks  # noqa: E402
from triage.vikunja import VikunjaClient  # noqa: E402


NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
TRIAGE = {
    "api_url": "https://vikunja.example.test/api/v2",
    "auth_env": "VIKUNJA_TRIAGE_API_TOKEN",
    "cron": "7,37 * * * *",
    "platform": "medium",
    "state_path": "/triage-state/cursor.json",
}
PLATFORM = {
    "kind": "chat",
    "base_url": "https://router.example.test/v1",
    "model": "medium",
    "max_tokens": 1024,
    "auth_env": "GPU_FILL_ROUTER_API_KEY",
    "timeout_s": 300,
}
DEFAULTS = yaml.safe_load((ROOT / "roles/hatchet_docker/defaults/main.yml").read_text())


def task(task_id, updated, project=7, done=False):
    return {
        "id": task_id,
        "project_id": project,
        "title": f"Task {task_id}",
        "description": "Do useful work.",
        "created": (updated - timedelta(days=1)).isoformat(),
        "updated": updated.isoformat(),
        "done": done,
    }


def reply(**overrides):
    proposal = {
        "labels": ["operations"],
        "priority": 3,
        "priority_reason": "Unblocks planned work.",
        "duplicates": [{"task_id": 2, "reason": "Both update the same service."}],
        "size": "M",
        "plan": [
            "Inspect the current state.",
            "Make the change.",
            "Verify the result.",
        ],
    }
    proposal.update(overrides)
    return {"choices": [{"message": {"content": json.dumps(proposal)}}]}


class FakeClient:
    def __init__(self, tasks, comments=None, current_tasks=None):
        self.tasks = tasks
        self.comments = comments or {}
        self.current_tasks = current_tasks or {}
        self.comment_posts = []
        self.task_filters = []

    def list_tasks(self, filter_query):
        self.task_filters.append(filter_query)
        if filter_query == "done = false":
            return [task for task in self.tasks if task.get("done") is False]
        return self.tasks

    def list_labels(self):
        return [{"title": "operations"}, {"title": "maintenance"}]

    def list_comments(self, task_id):
        return self.comments.get(task_id, [])

    def get_task(self, task_id):
        return self.current_tasks.get(
            task_id, next(task for task in self.tasks if task["id"] == task_id)
        )

    def create_comment(self, task_id, comment):
        self.comment_posts.append((task_id, comment))


def test_config_accepts_triage_and_rejects_bad_schedule_or_platform(tmp_path):
    config = {
        "roles": {"medium": {"max_runs": 2}},
        "platforms": {"medium": PLATFORM},
        "triage": TRIAGE,
    }
    path = tmp_path / "worker.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    assert load_config(path) == config

    for field, value, error in [
        ("cron", "0,30 * * * *", "7,37"),
        ("auth_env", "bad-name", "env var name"),
        ("state_path", "relative.json", "absolute path"),
        ("platform", "noop", "active chat platform"),
    ]:
        invalid = {**config, "triage": {**TRIAGE, field: value}}
        path.write_text(json.dumps(invalid), encoding="utf-8")
        with pytest.raises(ValueError, match=error):
            load_config(path)


def test_triage_is_disabled_by_default_and_worker_config_renders_the_v2_api():
    assert DEFAULTS["hatchet_docker_worker_triage_enabled"] is False
    assert DEFAULTS["hatchet_docker_worker_triage_platform"] == "medium"
    medium_platform = next(
        item
        for item in DEFAULTS["hatchet_docker_worker_chat_platforms"]
        if item["name"] == "medium"
    )
    assert medium_platform["model"] == "pro6000-direct"

    template = (
        ROOT / "roles/hatchet_docker/templates/gpu_fill_worker_config.json.j2"
    ).read_text()
    values = {
        "hatchet_docker_worker_roles": {"medium": {"max_runs": 2}},
        "hatchet_docker_worker_platforms": [{**PLATFORM, "name": "medium"}],
        "hatchet_docker_worker_latency_guard_enabled": False,
        "hatchet_docker_worker_fill_enabled": False,
        "hatchet_docker_eval_enabled": False,
        "hatchet_docker_worker_triage_enabled": True,
        "hatchet_docker_worker_triage_api_url": TRIAGE["api_url"],
        "hatchet_docker_worker_triage_auth_env": TRIAGE["auth_env"],
        "hatchet_docker_worker_triage_platform": TRIAGE["platform"],
        "hatchet_docker_worker_triage_state_path": TRIAGE["state_path"],
    }
    templar = Templar(loader=DataLoader())
    templar.available_variables = values
    rendered = json.loads(templar.template(trust_as_template(template)))
    assert rendered["triage"] == TRIAGE


def test_triage_registers_one_low_priority_task_on_the_required_cron(monkeypatch):
    sdk = ModuleType("hatchet_sdk")
    sdk.ConcurrencyExpression = lambda **values: SimpleNamespace(**values)
    sdk.ConcurrencyLimitStrategy = SimpleNamespace(GROUP_ROUND_ROBIN="round-robin")
    sdk.NonRetryableException = type("NonRetryableException", (Exception,), {})
    sdk.Priority = SimpleNamespace(LOW="low")
    monkeypatch.setitem(sys.modules, "hatchet_sdk", sdk)
    registered = []

    def register(**options):
        return lambda handler: (
            registered.append((options, handler)) or SimpleNamespace()
        )

    assert (
        triage_tasks.build_triage_tasks(
            SimpleNamespace(task=register), {"platforms": {}}
        )
        == []
    )
    tasks = triage_tasks.build_triage_tasks(
        SimpleNamespace(task=register),
        {"platforms": {"medium": PLATFORM}, "triage": TRIAGE},
    )
    assert len(tasks) == 1
    assert registered[0][0]["name"] == "gpu-vikunja-triage"
    assert registered[0][0]["on_crons"] == ["7,37 * * * *"]
    assert registered[0][0]["default_priority"] == "low"
    assert triage_tasks.triage_slots({"triage": TRIAGE}) == 1
    assert triage_tasks.triage_slots({}) == 0


def test_run_posts_one_comment_with_same_project_duplicates_and_saves_cursor(tmp_path):
    target = task(1, NOW - timedelta(minutes=10))
    same_project = task(2, NOW - timedelta(hours=1))
    other_project = task(3, NOW - timedelta(hours=1), project=8)
    client = FakeClient([target, same_project, other_project])
    calls = []

    def chat(platform, payload, latency_guard=None):
        calls.append((platform, payload, latency_guard))
        prompt = payload["payload"]["prompt"]
        assert '"id": 2' in prompt
        assert '"id": 3' not in prompt
        assert "existing_labels" in prompt
        return reply()

    config = {**TRIAGE, "state_path": str(tmp_path / "state" / "cursor.json")}
    result = triage_tasks.run_triage(
        config, {"medium": PLATFORM}, client=client, chat=chat, now=NOW
    )

    assert result == {"processed": 1, "posted": 1, "skipped": 0}
    assert client.task_filters == [
        'updated >= "2026-11-05T11:30:00+00:00"',
        'created >= "2026-11-05T11:30:00+00:00"',
        "done = false",
    ]
    assert len(calls) == 1
    assert client.comment_posts[0][0] == 1
    assert client.comment_posts[0][1].startswith("[triage]\n")
    assert "Priority: 3" in client.comment_posts[0][1]
    assert "Size: M" in client.comment_posts[0][1]
    assert json.loads(Path(config["state_path"]).read_text()) == {
        "last_run": NOW.isoformat()
    }


def test_newer_triage_comment_skips_model_and_comment_post(tmp_path):
    target = task(1, NOW - timedelta(minutes=10))
    client = FakeClient(
        [target],
        comments={
            1: [
                {
                    "comment": "[triage]\nDone",
                    "created": (NOW - timedelta(minutes=5)).isoformat(),
                }
            ]
        },
    )
    state_path = tmp_path / "cursor.json"
    state_path.write_text(
        json.dumps({"last_run": (NOW - timedelta(hours=1)).isoformat()})
    )
    config = {**TRIAGE, "state_path": str(state_path)}

    def fail_chat(*_args, **_kwargs):
        raise AssertionError("a current triage comment must skip the model")

    result = triage_tasks.run_triage(
        config, {"medium": PLATFORM}, client=client, chat=fail_chat, now=NOW
    )

    assert result == {"processed": 1, "posted": 0, "skipped": 1}
    assert client.comment_posts == []


def test_task_changed_during_model_run_is_deferred_to_next_cron(tmp_path):
    target = task(1, NOW - timedelta(minutes=10))
    changed_again = task(1, NOW - timedelta(minutes=2))
    client = FakeClient([target], current_tasks={1: changed_again})
    config = {**TRIAGE, "state_path": str(tmp_path / "cursor.json")}

    result = triage_tasks.run_triage(
        config,
        {"medium": PLATFORM},
        client=client,
        chat=lambda *_args, **_kwargs: reply(duplicates=[]),
        now=NOW,
    )

    assert result == {"processed": 1, "posted": 0, "skipped": 1}
    assert client.comment_posts == []


@pytest.mark.parametrize(
    "proposal",
    [
        {
            "labels": ["not-existing"],
            "priority": 2,
            "priority_reason": "x",
            "duplicates": [],
            "size": "S",
            "plan": ["1", "2", "3"],
        },
        {
            "labels": [],
            "priority": True,
            "priority_reason": "x",
            "duplicates": [],
            "size": "S",
            "plan": ["1", "2", "3"],
        },
        {
            "labels": [],
            "priority": 2,
            "priority_reason": "x",
            "duplicates": [{"task_id": 77, "reason": "x"}],
            "size": "S",
            "plan": ["1", "2", "3"],
        },
        {
            "labels": [],
            "priority": 2,
            "priority_reason": "x",
            "duplicates": [],
            "size": "S",
            "plan": ["1", "2"],
        },
    ],
)
def test_model_output_is_rejected_when_it_breaks_the_contract(proposal):
    with pytest.raises(ValueError):
        triage_tasks._decode_result(
            {"choices": [{"message": {"content": json.dumps(proposal)}}]},
            task(1, NOW),
            [{"id": 2, "title": "another", "description": ""}],
            {"operations"},
        )


def test_failed_model_does_not_advance_cursor(tmp_path):
    target = task(1, NOW - timedelta(minutes=10))
    path = tmp_path / "cursor.json"
    config = {**TRIAGE, "state_path": str(path)}
    with pytest.raises(ValueError, match="strict JSON"):
        triage_tasks.run_triage(
            config,
            {"medium": PLATFORM},
            client=FakeClient([target]),
            chat=lambda *_args, **_kwargs: {"choices": []},
            now=NOW,
        )
    assert not path.exists()


def test_vikunja_client_paginates_and_uses_only_the_configured_bearer_env(monkeypatch):
    token = "test-only-secret"
    monkeypatch.setenv("VIKUNJA_TRIAGE_API_TOKEN", token)
    calls = []

    def request_fn(url, headers, method, body, timeout_s):
        calls.append((url, headers, method, body, timeout_s))
        page = int(parse_qs(urlsplit(url).query)["page"][0])
        items = [{"id": item} for item in range(50)] if page == 1 else [{"id": 50}]
        return (
            200,
            json.dumps({"items": items, "page": page, "total_pages": 2}).encode(),
        )

    client = VikunjaClient(TRIAGE["api_url"], TRIAGE["auth_env"], request_fn=request_fn)
    assert len(client.list_tasks("done = false")) == 51
    assert [call[2] for call in calls] == ["GET", "GET"]
    assert all(call[1]["Authorization"] == f"Bearer {token}" for call in calls)
    assert token not in repr(calls[0][0])
    assert all(call[4] == 30 for call in calls)
    assert all(
        parse_qs(urlsplit(call[0]).query)["filter"] == ["done = false"]
        for call in calls
    )
    assert all(
        parse_qs(urlsplit(call[0]).query)["format"] == ["markdown"] for call in calls
    )


def test_vikunja_client_unwraps_paginated_markdown_comments(monkeypatch):
    monkeypatch.setenv("VIKUNJA_TRIAGE_API_TOKEN", "test-only-secret")

    def request_fn(url, headers, method, body, timeout_s):
        assert "/tasks/12/comments" in url
        assert parse_qs(urlsplit(url).query)["format"] == ["markdown"]
        assert method == "GET"
        return (
            200,
            json.dumps(
                {
                    "items": [
                        {"comment": "[triage]\nPlan", "created": NOW.isoformat()}
                    ],
                    "page": 1,
                    "total_pages": 1,
                }
            ).encode(),
        )

    client = VikunjaClient(TRIAGE["api_url"], TRIAGE["auth_env"], request_fn=request_fn)
    assert client.list_comments(12) == [
        {"comment": "[triage]\nPlan", "created": NOW.isoformat()}
    ]


def test_vikunja_client_posts_only_a_markdown_task_comment(monkeypatch):
    monkeypatch.setenv("VIKUNJA_TRIAGE_API_TOKEN", "test-only-secret")
    calls = []

    def request_fn(url, headers, method, body, timeout_s):
        calls.append((url, headers, method, json.loads(body), timeout_s))
        return 201, b'{"id":9}'

    client = VikunjaClient(TRIAGE["api_url"], TRIAGE["auth_env"], request_fn=request_fn)
    assert client.create_comment(12, "[triage]\nPlan") == {"id": 9}
    url, headers, method, body, timeout_s = calls[0]
    assert url.endswith("/tasks/12/comments?format=markdown")
    assert headers["Authorization"] == "Bearer test-only-secret"
    assert method == "POST"
    assert body == {"comment": "[triage]\nPlan"}
    assert timeout_s == 30
