"""Fake-backed contracts for nightly Langfuse trace judging."""

import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "roles/hatchet_docker/files/gpu_fill_worker"
if str(WORKER) not in sys.path:
    sys.path.insert(0, str(WORKER))
sys.dont_write_bytecode = True

from config import load_config  # noqa: E402
from adapter import run_chat  # noqa: E402
from tracejudge.judge import judge_trace  # noqa: E402
from tracejudge.tasks import build_tasks, run_daily, sample_traces  # noqa: E402


def base_config():
    return {
        "roles": {"small": {"max_runs": 1}},
        "platforms": {
            "local-judge": {
                "kind": "chat",
                "base_url": "https://router.example.invalid/v1",
                "model": "local-judge",
                "max_tokens": 1024,
                "auth_env": "ROUTER_TOKEN",
                "timeout_s": 300,
            }
        },
        "tracejudge": {
            "cron": "43 2 * * *",
            "sample_per_agent": 2,
            "platform": "local-judge",
            "langfuse_base_url": "https://langfuse.example.invalid",
            "auth_env": {"public_key": "LANGFUSE_PUBLIC_KEY", "secret_key": "LANGFUSE_SECRET_KEY"},
            "slack_webhook_env": "SLACK_WEBHOOK_URL",
            "output_dir": "/tmp/tracejudge",
        },
    }


def observation(trace_id, name, tag, timestamp, *, root=False):
    return {
        "id": f"obs-{trace_id}",
        "traceId": trace_id,
        "traceName": name,
        "tags": [tag],
        "isRootObservation": root,
        "startTime": timestamp,
        "type": "AGENT",
        "name": name,
        "input": '{"request":"password=sample-secret"}',
        "output": "Completed with a tool call.",
        "toolCallNames": ["search"],
        "toolCalls": [{"name": "search", "arguments": {"q": "example"}}],
    }


def test_worker_config_accepts_tracejudge_and_role_default_is_off(tmp_path):
    path = tmp_path / "worker.json"
    config = base_config()
    path.write_text(json.dumps(config), encoding="utf-8")
    defaults = yaml.safe_load((ROOT / "roles/hatchet_docker/defaults/main.yml").read_text())

    assert load_config(path) == config
    assert defaults["hatchet_docker_worker_tracejudge_enabled"] is False
    assert defaults["hatchet_docker_worker_tracejudge_cron"] == "43 2 * * *"


def test_worker_config_template_renders_tracejudge_contract():
    template = ROOT / "roles/hatchet_docker/templates/gpu_fill_worker_config.json.j2"
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "hatchet_docker_worker_roles": {"small": {"max_runs": 1}},
        "hatchet_docker_worker_platforms": [
            {
                "name": "local-judge",
                "kind": "chat",
                "base_url": "https://router.example.invalid/v1",
                "model": "local-judge",
                "max_tokens": 1024,
                "auth_env": "ROUTER_TOKEN",
                "timeout_s": 300,
            }
        ],
        "hatchet_docker_worker_latency_guard_enabled": False,
        "hatchet_docker_eval_enabled": False,
        "hatchet_docker_worker_tracejudge_enabled": True,
        "hatchet_docker_worker_tracejudge_cron": "43 2 * * *",
        "hatchet_docker_worker_tracejudge_sample_per_agent": 10,
        "hatchet_docker_worker_tracejudge_platform": "local-judge",
        "hatchet_docker_worker_tracejudge_langfuse_base_url": "https://langfuse.example.invalid",
        "hatchet_docker_worker_tracejudge_slack_webhook_env": "SLACK_WEBHOOK_URL",
        "hatchet_docker_worker_tracejudge_output_dir": "/tmp/tracejudge",
    }

    rendered = templar.template(trust_as_template(template.read_text(encoding="utf-8")))
    tracejudge = json.loads(rendered)["tracejudge"]

    assert tracejudge["cron"] == "43 2 * * *"
    assert tracejudge["platform"] == "local-judge"
    assert tracejudge["auth_env"] == {
        "public_key": "LANGFUSE_PUBLIC_KEY",
        "secret_key": "LANGFUSE_SECRET_KEY",
    }
    assert tracejudge["output_dir"] == "/tmp/tracejudge"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sample_per_agent", True, "positive integer"),
        ("cron", "hourly", "five-field cron"),
        ("langfuse_base_url", "//invalid", "absolute HTTP"),
        ("slack_webhook_env", "not-an-env", "env var name"),
    ],
)
def test_tracejudge_config_rejects_invalid_values(tmp_path, field, value, message):
    config = base_config()
    config["tracejudge"][field] = value
    path = tmp_path / "worker.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_config(path)


def test_sampling_caps_each_name_and_tag_and_deduplicates_traces():
    rows = [
        observation("new", "agent-a", "gpu", "2026-11-04T22:00:00Z"),
        observation("old", "agent-a", "gpu", "2026-11-04T18:00:00Z"),
        observation("other", "agent-b", "gpu", "2026-11-04T17:00:00Z"),
    ]

    selected = sample_traces(rows, 1)

    assert [trace["trace_id"] for trace in selected] == ["new", "other"]
    assert selected[0]["groups"] == [("name", "agent-a"), ("tag", "gpu")]
    assert selected[1]["groups"] == [("name", "agent-b")]


def test_judge_requires_strict_json_and_redacts_generated_secrets():
    trace = {"name": "agent", "tags": [], "observations": []}
    valid = {
        "task_success": {"score": 4, "reason": "token=hidden-value"},
        "tool_use_correctness": {"score": 3, "reason": "Tool matched the request."},
        "hallucination_risk": {"score": 2, "reason": "No unsupported claim found."},
    }

    result = judge_trace(trace, {}, chat_fn=lambda *_args, **_kwargs: {"choices": [{"message": {"content": json.dumps(valid)}}]})

    assert "hidden-value" not in result["task_success"]["reason"]
    with pytest.raises(ValueError, match="invalid JSON"):
        judge_trace(trace, {}, chat_fn=lambda *_args, **_kwargs: {"choices": [{"message": {"content": "```json{} ```"}}]})


def test_local_chat_adapter_keeps_judge_in_system_role_and_low_priority(monkeypatch):
    monkeypatch.setenv("ROUTER_TOKEN", "router-test-token")
    calls = []

    def fake_post(url, body, headers, timeout_s):
        calls.append((url, json.loads(body), headers, timeout_s))
        return 200, b'{"choices":[]}'

    run_chat(
        {
            "kind": "chat",
            "base_url": "https://router.example.invalid/v1",
            "model": "local-judge",
            "max_tokens": 500,
            "auth_env": "ROUTER_TOKEN",
            "timeout_s": 300,
        },
        {"payload": {"system_prompt": "Judge safely.", "prompt": "Trace data.", "priority": 100, "temperature": 0}},
        http_post=fake_post,
    )

    assert calls[0][1]["messages"] == [
        {"role": "system", "content": "Judge safely."},
        {"role": "user", "content": "Trace data."},
    ]
    assert calls[0][1]["priority"] == 100
    assert calls[0][1]["temperature"] == 0


def test_tracejudge_registers_a_retryable_nightly_low_priority_task(monkeypatch):
    module = ModuleType("hatchet_sdk")
    module.Priority = SimpleNamespace(LOW="low")
    monkeypatch.setitem(sys.modules, "hatchet_sdk", module)
    registered = {}

    class FakeHatchet:
        def task(self, **options):
            registered.update(options)
            return lambda handler: handler

    task = build_tasks(FakeHatchet(), base_config()["tracejudge"], base_config()["platforms"])

    assert len(task) == 1 and callable(task[0])
    assert registered["name"] == "tracejudge-previous-day"
    assert registered["on_crons"] == ["43 2 * * *"]
    assert registered["default_priority"] == "low"
    assert registered["retries"] == 6

    def failed_run(*_args):
        raise RuntimeError("secret response detail")

    monkeypatch.setattr("tracejudge.tasks.run_daily", failed_run)
    with pytest.raises(RuntimeError, match="trace judging failed: RuntimeError") as error:
        task[0](None, None)
    assert "secret response detail" not in str(error.value)


def test_daily_job_paginates_scores_slack_and_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test-key")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.invalid/test")
    requests = []
    pages = [
        [
            observation("trace-new", "agent-a", "gpu", "2026-11-04T22:00:00Z", root=True),
            observation("trace-old", "agent-a", "gpu", "2026-11-04T20:00:00Z"),
            observation("trace-other", "agent-b", "gpu", "2026-11-04T18:00:00Z", root=True),
        ],
        [],
    ]

    def fake_request(method, url, body, headers, timeout_s):
        requests.append((method, url, body, headers, timeout_s))
        if method == "GET":
            query = parse_qs(urlsplit(url).query)
            assert query["fromStartTime"] == ["2026-11-04T00:00:00Z"]
            assert query["toStartTime"] == ["2026-11-05T00:00:00Z"]
            return 200, json.dumps({"data": pages.pop(0), "meta": {"cursor": "next" if pages else None}}).encode()
        if url.endswith("/api/public/scores"):
            return 200, b'{"id":"accepted"}'
        return 200, b"ok"

    def fake_chat(_platform, payload, **_kwargs):
        system = payload["payload"]["system_prompt"]
        if system.startswith("Summarize"):
            content = {"top_failure_patterns": [{"pattern": "tool result not checked", "count": 1}]}
        else:
            content = {
                "task_success": {"score": 2, "reason": "Output token=trace-secret was incomplete."},
                "tool_use_correctness": {"score": 3, "reason": "Tool call was reasonable."},
                "hallucination_risk": {"score": 4, "reason": "One unsupported claim."},
            }
            assert "sample-secret" not in payload["payload"]["prompt"]
        return {"choices": [{"message": {"content": json.dumps(content)}}]}

    config = base_config()["tracejudge"]
    config["sample_per_agent"] = 1
    config["output_dir"] = str(tmp_path)
    result = run_daily(
        config,
        {"max_tokens": 1024, "auth_env": "ROUTER_TOKEN", "timeout_s": 300},
        now=datetime(2026, 11, 5, 2, 43, tzinfo=timezone.utc),
        request_fn=fake_request,
        chat_fn=fake_chat,
    )

    assert result == {"date": "2026-11-04", "traces_scored": 2, "agents_summarized": 3}
    gets = [request for request in requests if request[0] == "GET"]
    assert len(gets) == 2
    assert parse_qs(urlsplit(gets[1][1]).query)["cursor"] == ["next"]
    scores = [json.loads(request[2]) for request in requests if request[0] == "POST" and request[1].endswith("/api/public/scores")]
    assert len(scores) == 6
    assert {score["traceId"] for score in scores} == {"trace-new", "trace-other"}
    assert all(score["dataType"] == "NUMERIC" and score["timestamp"].startswith("2026-11-04") for score in scores)
    assert all("trace-secret" not in score["comment"] for score in scores)
    assert base64.b64decode(gets[0][3]["Authorization"].split()[1]) == b"public-test-key:secret-test-key"
    lessons = (tmp_path / "lessons-2026-11-04.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lessons) == 3
    assert all(json.loads(line)["top_failure_patterns"] for line in lessons)
    assert all(json.loads(line)["document_id"].startswith("tracejudge-2026-11-04-") for line in lessons)
    assert all("Agent:" in json.loads(line)["content"] for line in lessons)
    slack = [json.loads(request[2]) for request in requests if request[0] == "POST" and request[1].startswith("https://hooks.")]
    assert len(slack) == 1 and "tool result not checked" in slack[0]["text"]
