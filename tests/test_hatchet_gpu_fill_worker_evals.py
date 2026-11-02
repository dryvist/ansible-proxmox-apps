"""Contracts for scheduled Hatchet evaluations."""

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKER_PACKAGE = ROOT / "roles/hatchet_docker/files/gpu_fill_worker"
if str(WORKER_PACKAGE) not in sys.path:
    sys.path.insert(0, str(WORKER_PACKAGE))
sys.dont_write_bytecode = True

from adapter import LatencyGuardError  # noqa: E402
from config import load_config  # noqa: E402
from evals.parse_experiment import (  # noqa: E402
    make_expected_fields_evaluator,
    make_schema_evaluator,
)
from evals.sync_judges import sync  # noqa: E402
import evals.tasks as eval_tasks  # noqa: E402


def base_config():
    return {
        "roles": {"medium": {"max_runs": 2}},
        "platforms": {"agent": {"run_url": "https://192.0.2.10/run", "auth_env": None, "timeout_s": 30}},
    }


def eval_config(cron="0 */6 * * *", judges_sync_cron="15 3 * * *"):
    return {
        "cron": cron,
        "judges_sync_cron": judges_sync_cron,
        "prompts_dir": "/app/ai-llm-prompts",
        "roles": [{"role": "small", "dataset": "vikunja-clerk-evals"}],
    }


def test_config_accepts_strict_eval_section(tmp_path):
    config = base_config()
    config["evals"] = eval_config()
    path = tmp_path / "worker.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    assert load_config(path) == config


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.update(extra=True), "evals must contain"),
        (lambda value: value.update(cron="hourly"), "five-field cron"),
        (lambda value: value.update(prompts_dir="relative"), "absolute path"),
        (
            lambda value: value.update(roles=[{"role": "small", "dataset": "vikunja"}] * 2),
            "duplicate eval role",
        ),
    ],
)
def test_config_rejects_malformed_eval_section(tmp_path, change, message):
    config = base_config()
    config["evals"] = eval_config()
    change(config["evals"])
    path = tmp_path / "worker.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_config(path)


def test_sync_skips_code_and_posts_only_llm_as_judge(tmp_path):
    judges_dir = tmp_path / "judges"
    judges_dir.mkdir()
    (judges_dir / "00-code.yaml").write_text(
        "name: parse-json-schema\ntype: code\nsource: missing.py\nlanguage: PYTHON\n",
        encoding="utf-8",
    )
    definition = {
        "name": "parse-faithful",
        "description": "Checks one parse reply.",
        "type": "llm_as_judge",
        "connection": "litellm-local-small",
        "model": "small",
        "prompt_header": "Reply: {{output}}",
        "criteria": ["one JSON object", "no tool claims"],
        "variable_mapping": {"input": "input", "output": "output"},
        "output": {"data_type": "BOOLEAN", "reasoning_instructions": "Explain the first failure."},
    }
    (judges_dir / "99-judge.yaml").write_text(yaml.safe_dump(definition), encoding="utf-8")
    calls = []

    def fake_request(method, path, body=None):
        calls.append((method, path, body))
        return {"data": []} if method == "GET" else {"id": "created-id"}

    report = sync(judges_dir, request_fn=fake_request)

    assert report == [
        "skipped parse-json-schema: hosted code evaluators off",
        "created parse-faithful id=created-id",
    ]
    assert [call[0] for call in calls] == ["GET", "POST"]
    assert calls[1][1] == "/api/public/v2/evaluators"
    assert calls[1][2] == {
        "name": "parse-faithful",
        "description": "Checks one parse reply.",
        "type": "llm_as_judge",
        "prompt": "Reply: {{output}}\nCriteria:\n- one JSON object\n- no tool claims\n",
        "modelConfig": {"provider": "litellm-local-small", "model": "small"},
        "variableMapping": [
            {"variable": "input", "source": "input"},
            {"variable": "output", "source": "output"},
        ],
        "outputDefinition": {
            "dataType": "BOOLEAN",
            "scoreReasoningInstructions": "Explain the first failure.",
        },
    }


class FakeEvaluation:
    def __init__(self, **values):
        self.__dict__.update(values)


def install_fake_langfuse(monkeypatch):
    module = ModuleType("langfuse")
    module.Evaluation = FakeEvaluation
    monkeypatch.setitem(sys.modules, "langfuse", module)


def test_expected_fields_evaluator_scores_match_and_mismatch(monkeypatch):
    install_fake_langfuse(monkeypatch)
    evaluator = make_expected_fields_evaluator()
    expected_output = {
        "structured_fields": {"operation": "create", "title": "Add a task", "project_id": "ignored"}
    }

    matched = evaluator(
        output='{"operation":"CREATE","title":" Add a task ","project_id":"other"}',
        expected_output=expected_output,
    )
    mismatched = evaluator(
        output='{"operation":"list","title":"Add a task"}',
        expected_output=expected_output,
    )

    assert matched.value == 1.0
    assert matched.comment == "2 fields matched"
    assert mismatched.value == 0.0
    assert "operation: want 'create' got 'list'" in mismatched.comment


def test_schema_evaluator_scores_valid_and_invalid_replies(monkeypatch):
    install_fake_langfuse(monkeypatch)
    evaluator = make_schema_evaluator(lambda output: None if output == "valid" else "project_id must not appear")

    valid = evaluator(output="valid")
    invalid = evaluator(output='{"project_id":"forbidden"}')

    assert (valid.value, valid.comment) == (1.0, "valid")
    assert (invalid.value, invalid.comment) == (0.0, "project_id must not appear")


class FakeNonRetryableException(Exception):
    pass


class FakeConcurrencyExpression:
    def __init__(self, **values):
        self.__dict__.update(values)


class FakeHatchet:
    def __init__(self):
        self.registered = []

    def task(self, **options):
        def decorate(handler):
            self.registered.append((options, handler))
            return SimpleNamespace(name=options["name"])

        return decorate


def install_fake_hatchet_sdk(monkeypatch):
    module = ModuleType("hatchet_sdk")
    module.ConcurrencyExpression = FakeConcurrencyExpression
    module.ConcurrencyLimitStrategy = SimpleNamespace(GROUP_ROUND_ROBIN="GROUP_ROUND_ROBIN")
    module.Context = type("Context", (), {})
    module.NonRetryableException = FakeNonRetryableException
    module.Priority = SimpleNamespace(LOW="LOW")
    monkeypatch.setitem(sys.modules, "hatchet_sdk", module)


def test_task_builder_sets_priority_crons_concurrency_and_nonretryable(monkeypatch):
    install_fake_hatchet_sdk(monkeypatch)
    hatchet = FakeHatchet()
    monkeypatch.setenv("LITELLM_BASE_URL", "https://192.0.2.20/v1")
    monkeypatch.setenv("LITELLM_API_KEY", "render-only-placeholder")
    monkeypatch.setattr(eval_tasks, "_check_latency_guard", lambda *_: None)

    def fail_experiment(**_kwargs):
        raise RuntimeError("hidden failure detail")

    monkeypatch.setattr(
        eval_tasks,
        "run_parse_experiment",
        fail_experiment,
    )

    built = eval_tasks.build_tasks(hatchet, eval_config(), latency_guard={"prometheus_url": "x"})
    sync_options, _ = hatchet.registered[0]
    parse_options, parse_handler = hatchet.registered[1]

    assert [task.name for task in built] == ["eval-sync-judges", "eval-parse-small"]
    assert sync_options["default_priority"] == "LOW"
    assert sync_options["on_crons"] == ["15 3 * * *"]
    assert parse_options["default_priority"] == "LOW"
    assert parse_options["on_crons"] == ["0 */6 * * *"]
    assert parse_options["retries"] == 6
    assert parse_options["backoff_factor"] == 2.0
    assert parse_options["backoff_max_seconds"] == 300
    assert parse_options["concurrency"][0].expression == "'small'"
    assert parse_options["concurrency"][0].max_runs == 1
    assert parse_options["concurrency"][0].limit_strategy == "GROUP_ROUND_ROBIN"

    with pytest.raises(FakeNonRetryableException, match="parse experiment failed"):
        parse_handler({}, None)

    def fail_guard(*_args):
        raise LatencyGuardError("latency hold")

    monkeypatch.setattr(eval_tasks, "_check_latency_guard", fail_guard)
    with pytest.raises(LatencyGuardError, match="latency hold"):
        parse_handler({}, None)


def test_task_builder_disables_empty_crons(monkeypatch):
    install_fake_hatchet_sdk(monkeypatch)
    hatchet = FakeHatchet()

    eval_tasks.build_tasks(hatchet, eval_config(cron="", judges_sync_cron=""))

    assert [options["on_crons"] for options, _ in hatchet.registered] == [[], []]


def test_worker_imports_eval_tasks_only_for_eval_config():
    source = (WORKER_PACKAGE / "worker.py").read_text(encoding="utf-8")

    assert 'if "evals" in worker_config:' in source
    assert "from evals import build_tasks as build_eval_tasks" in source


def test_worker_adds_eval_slots_beyond_gpu_fill_slots():
    source = (Path(__file__).resolve().parent.parent
              / "roles/hatchet_docker/files/gpu_fill_worker/worker.py").read_text(encoding="utf-8")
    assert 'slots += len(worker_config["evals"]["roles"]) + 1 if "evals" in worker_config else 0' in source
