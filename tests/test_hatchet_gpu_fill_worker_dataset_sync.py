"""Contracts for creating missing Langfuse eval datasets at worker start."""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKER_PACKAGE = ROOT / "roles/hatchet_docker/files/gpu_fill_worker"
if str(WORKER_PACKAGE) not in sys.path:
    sys.path.insert(0, str(WORKER_PACKAGE))
sys.dont_write_bytecode = True

from evals.sync_datasets import case_payload, sync_datasets  # noqa: E402


def write_eval_set(evals_dir: Path, agent: str, cases: list[dict]) -> None:
    evals_dir.mkdir(parents=True, exist_ok=True)
    definition = {"agent": agent, "cases": cases}
    (evals_dir / f"{agent}.yaml").write_text(
        yaml.safe_dump(definition), encoding="utf-8"
    )


class FakeLangfuse:
    """Answers the list and create calls the sync makes, and records every call."""

    def __init__(self, datasets=(), items=None):
        self.datasets = list(datasets)
        self.items = dict(items or {})
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("/api/public/v2/datasets"):
            page = int(path.split("page=")[1].split("&")[0])
            start = (page - 1) * 100
            return {
                "data": [{"name": name} for name in self.datasets[start : start + 100]]
            }
        if method == "GET" and path.startswith("/api/public/dataset-items"):
            dataset = path.split("datasetName=")[1].split("&")[0]
            ids = self.items.get(dataset, [])
            page = int(path.split("page=")[1].split("&")[0])
            start = (page - 1) * 100
            return {"data": [{"id": item_id} for item_id in ids[start : start + 100]]}
        if method == "POST":
            return {"id": "created"}
        raise AssertionError(f"unexpected call {method} {path}")


def test_case_payload_splits_input_from_expected_fields():
    case = {
        "id": "c1",
        "input_event_summary": {"repo": "dryvist/example"},
        "expected_output": {"decision": "commit"},
        "expected_behavior": "commits the fix",
    }

    inputs, expected = case_payload(case)

    assert inputs == {"input_event_summary": {"repo": "dryvist/example"}}
    assert expected == {
        "expected_output": {"decision": "commit"},
        "expected_behavior": "commits the fix",
    }


def test_missing_dataset_is_created_with_its_items(tmp_path):
    write_eval_set(
        tmp_path, "ci-fixer", [{"id": "c1", "expected_output": {"decision": "commit"}}]
    )
    fake = FakeLangfuse(datasets=[])

    report = sync_datasets(tmp_path, request_fn=fake)

    assert report == [
        "created dataset ci-fixer",
        "ci-fixer: created 1 items, 0 already present",
    ]
    assert fake.calls[1] == (
        "POST",
        "/api/public/v2/datasets",
        {"name": "ci-fixer", "description": "Eval set from agents/evals/ci-fixer.yaml"},
    )
    assert fake.calls[-1] == (
        "POST",
        "/api/public/dataset-items",
        {
            "datasetName": "ci-fixer",
            "id": "ci-fixer:c1",
            "input": {},
            "expectedOutput": {"expected_output": {"decision": "commit"}},
        },
    )


def test_existing_dataset_and_items_are_neither_recreated_nor_overwritten(tmp_path):
    write_eval_set(
        tmp_path,
        "ci-fixer",
        [{"id": "c1", "expected_output": {}}, {"id": "c2", "expected_output": {}}],
    )
    fake = FakeLangfuse(datasets=["ci-fixer"], items={"ci-fixer": ["ci-fixer:c1"]})

    report = sync_datasets(tmp_path, request_fn=fake)

    assert report == ["ci-fixer: created 1 items, 1 already present"]
    posts = [call for call in fake.calls if call[0] == "POST"]
    assert [call[1] for call in posts] == ["/api/public/dataset-items"]
    assert posts[0][2]["id"] == "ci-fixer:c2"


def test_items_listed_across_pages_are_all_seen_before_creating(tmp_path):
    cases = [{"id": f"c{index}", "expected_output": {}} for index in range(101)]
    write_eval_set(tmp_path, "docs-updater", cases)
    existing = [f"docs-updater:c{index}" for index in range(101)]
    fake = FakeLangfuse(datasets=["docs-updater"], items={"docs-updater": existing})

    report = sync_datasets(tmp_path, request_fn=fake)

    assert report == ["docs-updater: created 0 items, 101 already present"]
    assert [call for call in fake.calls if call[0] == "POST"] == []


def test_sync_never_sends_delete_or_put(tmp_path):
    write_eval_set(tmp_path, "ci-fixer", [{"id": "c1", "expected_output": {}}])
    fake = FakeLangfuse(datasets=["ci-fixer"])

    sync_datasets(tmp_path, request_fn=fake)

    assert {method for method, _, _ in fake.calls} <= {"GET", "POST"}


def install_fake_hatchet_sdk(monkeypatch):
    class FakeConcurrencyExpression:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    module = ModuleType("hatchet_sdk")
    module.ConcurrencyExpression = FakeConcurrencyExpression
    module.ConcurrencyLimitStrategy = SimpleNamespace(
        GROUP_ROUND_ROBIN="GROUP_ROUND_ROBIN"
    )
    module.Context = type("Context", (), {})
    module.Hatchet = type("Hatchet", (), {})
    module.NonRetryableException = type("NonRetryableException", (Exception,), {})
    module.Priority = SimpleNamespace(LOW="LOW")
    monkeypatch.setitem(sys.modules, "hatchet_sdk", module)
    pydantic = ModuleType("pydantic")
    pydantic.BaseModel = object
    monkeypatch.setitem(sys.modules, "pydantic", pydantic)


def test_worker_sync_failure_prints_exception_type_only(monkeypatch, capsys):
    install_fake_hatchet_sdk(monkeypatch)
    sys.modules.pop("worker", None)
    import worker

    def failing_sync(_evals_dir):
        raise RuntimeError(
            "POST /api/public/v2/datasets -> HTTP 500: secret-looking detail"
        )

    monkeypatch.setattr("evals.sync_datasets.sync_datasets", failing_sync)

    worker._sync_eval_datasets("/tmp/prompts")

    output = capsys.readouterr().out
    assert output == "eval dataset sync failed: RuntimeError\n"
    assert "secret-looking detail" not in output
