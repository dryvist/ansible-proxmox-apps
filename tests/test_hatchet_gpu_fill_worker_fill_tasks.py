"""Contracts for the grounded Q&A fill tasks: registration, top-up arithmetic, and fill runs."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKER_PACKAGE = ROOT / "roles/hatchet_docker/files/gpu_fill_worker"
FIXTURES = ROOT / "tests/hatchet_gpu_fill_worker"
for path in (WORKER_PACKAGE, FIXTURES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
sys.dont_write_bytecode = True

from adapter import LatencyGuardError  # noqa: E402
from fill import tasks as fill_tasks  # noqa: E402
from fill_fixtures import GOOD, PLATFORM, chat_reply  # noqa: E402


class FakeTask:
    def __init__(self, fn, **options):
        self.fn = fn
        self.options = options
        self.enqueued = []
        self.run_many_flags = []

    def create_bulk_run_item(self, input=None, additional_metadata=None):
        return {"input": input, "additional_metadata": additional_metadata}

    def run_many(self, items, wait_for_result=True):
        self.enqueued.extend(items)
        self.run_many_flags.append(wait_for_result)
        return items


class FakeHatchet:
    def __init__(self, in_flight):
        self.in_flight = in_flight
        self.task_calls = []
        self.list_calls = []
        self.runs = SimpleNamespace(list=self._list)

    def task(self, **options):
        self.task_calls.append(options)

        def decorate(fn):
            return FakeTask(fn, **options)

        return decorate

    def _list(self, **kwargs):
        self.list_calls.append(kwargs)
        return SimpleNamespace(rows=[None] * min(self.in_flight, kwargs["limit"]))


@pytest.fixture
def fake_sdk(monkeypatch):
    sdk = ModuleType("hatchet_sdk")
    sdk.ConcurrencyExpression = lambda **kwargs: SimpleNamespace(**kwargs)
    sdk.ConcurrencyLimitStrategy = SimpleNamespace(GROUP_ROUND_ROBIN="GROUP_ROUND_ROBIN")
    sdk.Priority = SimpleNamespace(LOW=3)
    sdk.V1TaskStatus = SimpleNamespace(QUEUED="QUEUED", RUNNING="RUNNING")
    sdk.NonRetryableException = type("NonRetryableException", (Exception,), {})
    monkeypatch.setitem(sys.modules, "hatchet_sdk", sdk)
    return sdk


def worker_config(corpus_dir, output_dir, fill=True):
    config = {
        "roles": {"medium": {"max_runs": 3}},
        "platforms": {"pro6000-direct": dict(PLATFORM)},
    }
    if fill:
        config["fill"] = {
            "cron": "7,37 * * * *",
            "corpus_dir": str(corpus_dir),
            "output_dir": str(output_dir),
            "roles": {"medium": "pro6000-direct"},
        }
    return config


def write_corpus(tmp_path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "guide.md").write_text("# Guide\nAlpha fact.\n", encoding="utf-8")
    return corpus_dir


def test_fill_disabled_registers_no_tasks(fake_sdk, tmp_path):
    hatchet = FakeHatchet(in_flight=0)
    config = worker_config(tmp_path, tmp_path, fill=False)
    assert fill_tasks.build_fill_tasks(hatchet, config) == []
    assert hatchet.task_calls == []
    assert fill_tasks.fill_slots(config) == 0


def test_fill_enabled_registers_a_fill_and_cron_task_per_mapped_role(fake_sdk, tmp_path):
    corpus_dir = write_corpus(tmp_path)
    hatchet = FakeHatchet(in_flight=0)
    config = worker_config(corpus_dir, tmp_path / "out")

    fill_task, topup_task = fill_tasks.build_fill_tasks(hatchet, config)

    assert fill_task.options["name"] == "gpu-qa-fill-medium"
    assert fill_task.options["input_validator"] is dict
    assert fill_task.options["retries"] == 0
    # Two timeout_s budgets (latency-guard query plus completion) plus a margin.
    assert fill_task.options["execution_timeout"].total_seconds() == 2 * 300 + 60
    assert fill_task.options["schedule_timeout"].total_seconds() == 10 * 60
    assert fill_task.options["concurrency"][0].max_runs == 3
    assert fill_task.options["concurrency"][0].name == "gpu-medium"
    assert topup_task.options["name"] == "gpu-qa-topup-medium"
    assert topup_task.options["on_crons"] == ["7,37 * * * *"]
    assert fill_tasks.fill_slots(config) == 1


@pytest.mark.parametrize("in_flight", [0, 1, 2, 3, 5])
def test_top_up_enqueues_only_the_deficit_and_never_above_max_runs(fake_sdk, tmp_path, in_flight):
    corpus_dir = write_corpus(tmp_path)
    hatchet = FakeHatchet(in_flight=in_flight)
    fill_task, topup_task = fill_tasks.build_fill_tasks(
        hatchet, worker_config(corpus_dir, tmp_path / "out")
    )

    result = topup_task.fn(None, None)

    expected = max(0, 3 - in_flight)
    assert result == {"llm_role": "medium", "in_flight": min(in_flight, 3), "enqueued": expected}
    assert len(fill_task.enqueued) == expected
    assert min(in_flight, 3) + len(fill_task.enqueued) <= 3
    assert fill_task.run_many_flags == ([False] if expected else [])
    assert hatchet.list_calls[0]["limit"] == 3
    # Window = schedule_timeout (10 min) + execution_timeout (2 * 300 s + 60 s) + 5 min margin.
    window = datetime.now(timezone.utc) - hatchet.list_calls[0]["since"]
    assert timedelta(seconds=1500) < window < timedelta(seconds=1620)
    assert hatchet.list_calls[0]["statuses"] == ["QUEUED", "RUNNING"]
    assert all(
        item["additional_metadata"] == {"gpu_fill_role": "medium"} for item in fill_task.enqueued
    )


def test_fill_run_writes_records_and_skips_on_latency_guard(fake_sdk, tmp_path, monkeypatch):
    corpus_dir = write_corpus(tmp_path)
    output_dir = tmp_path / "out"
    hatchet = FakeHatchet(in_flight=0)
    fill_task, _topup = fill_tasks.build_fill_tasks(hatchet, worker_config(corpus_dir, output_dir))

    monkeypatch.setattr(fill_tasks, "run_chat", lambda *_a, **_k: chat_reply(GOOD))
    written = fill_task.fn({"llm_role": "medium"}, None)
    assert written["status"] == "written"
    assert (output_dir / "medium").is_dir()

    def refuse(*_a, **_k):
        raise LatencyGuardError("blocked")

    monkeypatch.setattr(fill_tasks, "run_chat", refuse)
    skipped = fill_task.fn({"llm_role": "medium"}, None)
    assert skipped == {"status": "skipped", "reason": "latency_guard", "written": 0}


def test_fill_run_rejects_a_mismatched_role_and_fails_without_retry(fake_sdk, tmp_path, monkeypatch):
    corpus_dir = write_corpus(tmp_path)
    fill_task, _topup = fill_tasks.build_fill_tasks(
        FakeHatchet(in_flight=0), worker_config(corpus_dir, tmp_path / "out")
    )
    with pytest.raises(ValueError):
        fill_task.fn({"llm_role": "small"}, None)

    def broken(*_a, **_k):
        raise RuntimeError("router chat API returned HTTP 500")

    monkeypatch.setattr(fill_tasks, "run_chat", broken)
    with pytest.raises(fake_sdk.NonRetryableException, match="RuntimeError"):
        fill_task.fn({"llm_role": "medium"}, None)
