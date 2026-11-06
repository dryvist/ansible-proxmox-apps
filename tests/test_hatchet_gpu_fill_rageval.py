"""Fake-backed contracts for the nightly RAG evaluation."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
WORKER_PACKAGE = ROOT / "roles/hatchet_docker/files/gpu_fill_worker"
if str(WORKER_PACKAGE) not in sys.path:
    sys.path.insert(0, str(WORKER_PACKAGE))
sys.dont_write_bytecode = True

from config import load_config  # noqa: E402
from rageval import runner, tasks  # noqa: E402


TEST_URL = "https://" + ".".join(("198", "51", "100", "10"))
NOW = datetime(2026, 11, 5, 4, 29, tzinfo=timezone.utc)


def environment():
    return {
        "RAGEVAL_HINDSIGHT_RECALL_URL": TEST_URL + "/hindsight/recall",
        "RAGEVAL_HINDSIGHT_API_KEY": "test-hindsight-key",
        "RAGEVAL_LLAMA_INDEX_QUERY_URL": TEST_URL + "/llama/query",
        "RAGEVAL_LLAMA_INDEX_API_KEY": "test-llama-key",
        "RAGEVAL_QDRANT_QUERY_URL": TEST_URL + "/qdrant/query",
        "RAGEVAL_QDRANT_API_KEY": "test-qdrant-key",
        "RAGEVAL_QDRANT_MODEL": "local-embedder",
        "RAGEVAL_SLACK_WEBHOOK_URL": TEST_URL + "/slack",
    }


def worker_config(tmp_path):
    source = tmp_path / "fill" / "medium"
    source.mkdir(parents=True)
    (source / "2026-11-05.jsonl").write_text(
        json.dumps(
            {
                "question": "Which value is supported?",
                "answer": "42",
                "timestamp": NOW.isoformat(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "roles": {"medium": {"max_runs": 1}},
        "platforms": {
            "local": {
                "kind": "chat",
                "base_url": TEST_URL,
                "model": "local-model",
                "max_tokens": 512,
                "auth_env": "LOCAL_TOKEN",
                "timeout_s": 30,
            }
        },
        "fill": {
            "cron": "7,37 * * * *",
            "corpus_dir": "/corpus",
            "output_dir": str(tmp_path / "fill"),
            "roles": {"medium": "local"},
        },
        "rageval": {
            "cron": "29 4 * * *",
            "results_dir": str(tmp_path / "results"),
            "k": 2,
        },
    }


def test_rageval_configuration_requires_fill_and_exact_nightly_schedule(tmp_path):
    config = worker_config(tmp_path)
    path = tmp_path / "worker.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    assert load_config(path) == config

    config["rageval"]["cron"] = "0 4 * * *"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="04:29"):
        load_config(path)

    config["rageval"]["cron"] = "29 4 * * *"
    config.pop("fill")
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="requires the fill generator"):
        load_config(path)


def test_worker_template_uses_one_flag_for_fill_and_rageval():
    template = (
        ROOT / "roles/hatchet_docker/templates/gpu_fill_worker_config.json.j2"
    ).read_text(encoding="utf-8")
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "hatchet_docker_worker_roles": {"medium": {"max_runs": 1}},
        "hatchet_docker_worker_platforms": [
            {
                "name": "local",
                "kind": "chat",
                "base_url": TEST_URL,
                "model": "local-model",
                "max_tokens": 512,
                "auth_env": "LOCAL_TOKEN",
                "timeout_s": 30,
            }
        ],
        "hatchet_docker_worker_latency_guard_enabled": False,
        "hatchet_docker_worker_rageval_enabled": True,
        "hatchet_docker_worker_fill_cron": "7,37 * * * *",
        "hatchet_docker_worker_fill_corpus_dir": "/corpus",
        "hatchet_docker_worker_fill_output_dir": "/output",
        "hatchet_docker_worker_fill_roles": {"medium": "local"},
        "hatchet_docker_worker_rageval_cron": "29 4 * * *",
        "hatchet_docker_worker_rageval_results_dir": "/output/rageval",
        "hatchet_docker_worker_rageval_k": 5,
        "hatchet_docker_eval_enabled": False,
    }

    rendered = json.loads(templar.template(trust_as_template(template)))

    assert rendered["fill"]["roles"] == {"medium": "local"}
    assert rendered["rageval"] == {
        "cron": "29 4 * * *",
        "results_dir": "/output/rageval",
        "k": 5,
    }


def test_load_pairs_uses_recent_records_and_skips_bad_lines(tmp_path):
    role_dir = tmp_path / "medium"
    role_dir.mkdir()
    current = {"question": "new", "answer": "answer", "timestamp": NOW.isoformat()}
    stale = {
        "question": "old",
        "answer": "answer",
        "timestamp": (NOW - timedelta(days=2)).isoformat(),
    }
    (role_dir / "pairs.jsonl").write_text(
        "\n".join((json.dumps(current), json.dumps(stale), "broken")), encoding="utf-8"
    )
    assert runner.load_pairs(tmp_path, ["medium"], NOW) == [
        {"role": "medium", "question": "new", "answer": "answer"}
    ]


def test_runner_queries_configured_backends_judges_locally_and_sends_one_summary(
    tmp_path,
):
    config = worker_config(tmp_path)
    calls = []
    judge_calls = []

    def request(url, body, headers, timeout_s):
        calls.append((url, body, headers, timeout_s))
        path = urlsplit(url).path
        if path.endswith("/hindsight/recall"):
            return (
                200,
                json.dumps(
                    {"results": [{"text": "The supported value is 42."}]}
                ).encode(),
            )
        if path.endswith("/qdrant/query"):
            return (
                200,
                json.dumps(
                    {
                        "result": {
                            "points": [
                                {"payload": {"text": "The supported value is 42."}}
                            ]
                        }
                    }
                ).encode(),
            )
        if path.endswith("/llama/query"):
            return (
                200,
                json.dumps(
                    {"source_nodes": [{"node": {"text": "The supported value is 42."}}]}
                ).encode(),
            )
        return 200, b"ok"

    def judge(platform, payload, latency_guard=None):
        judge_calls.append((platform, payload, latency_guard))
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": "42",
                                "answer_recalled": True,
                                "answer_grounded": True,
                            }
                        )
                    }
                }
            ]
        }

    report = runner.run_rageval(
        config, chat_fn=judge, request_fn=request, environ=environment(), now=NOW
    )

    assert set(report["backends"]) == {"hindsight", "llamaindex", "qdrant"}
    for metric in report["backends"].values():
        assert metric["queries_total"] == metric["queries_scored"] == 1
        assert metric["recall_at_k"] == metric["answer_grounding"] == 1.0
        assert metric["errors"] == 0
    assert len(judge_calls) == 3
    assert (
        len([call for call in calls if urlsplit(call[0]).path.endswith("/slack")]) == 1
    )

    hindsight = next(
        call for call in calls if urlsplit(call[0]).path.endswith("/hindsight/recall")
    )
    assert json.loads(hindsight[1]) == {
        "query": "Which value is supported?",
        "budget": "low",
        "max_tokens": 4096,
    }
    assert hindsight[2]["Authorization"] == "Bearer test-hindsight-key"
    qdrant = next(
        call for call in calls if urlsplit(call[0]).path.endswith("/qdrant/query")
    )
    assert json.loads(qdrant[1]) == {
        "query": {"text": "Which value is supported?", "model": "local-embedder"},
        "limit": 2,
        "with_payload": True,
    }
    assert qdrant[2]["api-key"] == "test-qdrant-key"
    llama = next(
        call for call in calls if urlsplit(call[0]).path.endswith("/llama/query")
    )
    assert parse_qs(urlsplit(llama[0]).query) == {
        "text": ["Which value is supported?"],
        "similarity_top_k": ["2"],
    }

    report_text = Path(report["results_file"]).read_text(encoding="utf-8")
    assert report["slack_summary_sent"] is True
    assert "Which value is supported?" not in report_text
    assert "test-hindsight-key" not in report_text
    assert '"answer": "42"' not in report_text
    assert set(report) == {
        "date",
        "status",
        "k",
        "backends",
        "results_file",
        "slack_summary_sent",
    }


def test_backend_failure_writes_metrics_and_still_attempts_one_slack_summary(tmp_path):
    config = worker_config(tmp_path)
    calls = []
    env = environment()
    env.pop("RAGEVAL_LLAMA_INDEX_QUERY_URL")
    env.pop("RAGEVAL_LLAMA_INDEX_API_KEY")
    env.pop("RAGEVAL_QDRANT_QUERY_URL")
    env.pop("RAGEVAL_QDRANT_API_KEY")
    env.pop("RAGEVAL_QDRANT_MODEL")

    def request(url, body, headers, timeout_s):
        calls.append(url)
        return (
            (401, b"denied")
            if urlsplit(url).path.endswith("/hindsight/recall")
            else (200, b"ok")
        )

    report = runner.run_rageval(
        config,
        chat_fn=lambda *_a, **_k: pytest.fail("judge called without evidence"),
        request_fn=request,
        environ=env,
        now=NOW,
    )

    assert report["status"] == "partial"
    assert report["backends"]["hindsight"]["errors"] == 1
    assert report["backends"]["hindsight"]["queries_scored"] == 0
    assert report["slack_summary_sent"] is True
    assert len([url for url in calls if urlsplit(url).path.endswith("/slack")]) == 1


def test_task_builder_registers_one_low_priority_nightly_run(monkeypatch, tmp_path):
    sdk = ModuleType("hatchet_sdk")
    sdk.ConcurrencyExpression = lambda **values: SimpleNamespace(**values)
    sdk.ConcurrencyLimitStrategy = SimpleNamespace(GROUP_ROUND_ROBIN="round-robin")
    sdk.Context = type("Context", (), {})
    sdk.NonRetryableException = type("NonRetryableException", (Exception,), {})
    sdk.Priority = SimpleNamespace(LOW="low")
    monkeypatch.setitem(sys.modules, "hatchet_sdk", sdk)

    class FakeHatchet:
        def __init__(self):
            self.registered = []

        def task(self, **options):
            def decorate(handler):
                self.registered.append((options, handler))
                return SimpleNamespace(name=options["name"])

            return decorate

    hatchet = FakeHatchet()
    built = tasks.build_tasks(hatchet, worker_config(tmp_path))
    options, _handler = hatchet.registered[0]
    assert [task.name for task in built] == ["gpu-rageval-nightly"]
    assert options["on_crons"] == ["29 4 * * *"]
    assert options["default_priority"] == "low"
    assert options["retries"] == 0
    assert options["execution_timeout"].total_seconds() == 6 * 60 * 60
