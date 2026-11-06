"""Documentation drift contracts, with no live model or tracker calls."""

import base64
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "roles/hatchet_docker/files/gpu_fill_worker"))
from docsdrift import build_tasks  # noqa: E402
from docsdrift.source import pairs, public_snapshot  # noqa: E402
from docsdrift.sweep import evidence_hash, findings, sweep  # noqa: E402

ITEM = {"doc_claim": "Retries are 3", "code_line": "retries: 0",
        "suggested_fix": "Document zero retries", "confidence": 0.95}
FILES = {"README.md": "Retries are 3", ".github/workflows/test.yml": "retries: 0"}


def reply(items):
    return {"choices": [{"message": {"content": json.dumps({"findings": items})}}]}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("DOCSDRIFT_VIKUNJA_API_URL", "https://tracker.example/api/v1")
    monkeypatch.setenv("DOCSDRIFT_VIKUNJA_TOKEN", "fake")


class Tracker:
    def __init__(self):
        self.tasks = []
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert kwargs["token"] == "fake"
        if kwargs.get("method") == "PUT":
            task = dict(kwargs["body"], id=len(self.tasks) + 1)
            self.tasks.append(task)
            return task
        return self.tasks if "page=1&" in url else []


def test_sweep_cap_dedupe_and_restart(env):
    tracker = Tracker()
    config = {"repos": ["example/repo", "example/other"], "project_id": 7, "max_findings": 1}
    kwargs = dict(snapshot=lambda _: ("abc", FILES), api=tracker,
                  chat=lambda *_a, **_k: reply([ITEM, ITEM]))
    assert sweep(config, {}, **kwargs) == {"created": 1}
    assert sweep(config, {}, **kwargs) == {"created": 1}
    assert sweep(config, {}, **kwargs) == {"created": 0}
    assert len(tracker.tasks) == 2
    assert "Confidence: 0.95" in tracker.tasks[0]["description"]
    assert ".github/workflows/test.yml:1" in tracker.tasks[0]["description"]
    assert evidence_hash("example/repo", "README.md", "x", ITEM) == evidence_hash(
        "example/repo", "README.md", "x", dict(ITEM, confidence=0.8, suggested_fix="new"))


@pytest.mark.parametrize("change", [
    {"confidence": True}, {"confidence": 2}, {"confidence": float("nan")},
    {"code_line": "retries: 3"}, {"doc_claim": "invented"},
    {"extra": "unexpected"}, {"suggested_fix": ""},
])
def test_strict_grounded_findings(change):
    with pytest.raises(ValueError):
        findings(reply([dict(ITEM, **change)]), FILES["README.md"], "retries: 0")


def test_fenced_json_rejected():
    with pytest.raises(ValueError):
        findings({"choices": [{"message": {"content": '```json\n{}\n```'}}]}, "", "")


def test_pair_role_docs_and_general_guides():
    files = dict(FILES, **{"roles/app/README.md": "", "roles/app/defaults/main.yml": "",
                          "roles/other/defaults/main.yml": "", "docs/config.mdx": "", "flake.nix": ""})
    result = list(pairs(files))
    assert ("roles/app/README.md", "roles/app/defaults/main.yml") in result
    assert ("roles/app/README.md", "roles/other/defaults/main.yml") not in result
    assert ("docs/config.mdx", "flake.nix") in result


def test_public_snapshot_pins_and_decodes():
    calls = []

    def get(url):
        calls.append(url)
        if url.endswith("/example/repo"):
            return {"private": False, "default_branch": "main"}
        if "/commits/" in url:
            return {"sha": "abc"}
        if "/git/trees/" in url:
            return {"tree": [{"path": "README.md", "mode": "100644", "sha": "def", "size": 5}]}
        return {"encoding": "base64", "content": base64.b64encode(b"hello").decode()}

    assert public_snapshot("example/repo", get) == ("abc", {"README.md": "hello"})
    assert any("/git/trees/abc?" in url for url in calls)
    with pytest.raises(ValueError, match="public"):
        public_snapshot("example/repo", lambda _: {"private": True})
    with pytest.raises(ValueError, match="owner/name"):
        public_snapshot("../private", get)


def test_tracker_failure_stops_without_model(env):
    def fail(*_a, **_k):
        raise RuntimeError("unavailable")

    with pytest.raises(RuntimeError):
        sweep({"project_id": 7}, {}, api=fail)


def test_schedule_disabled_and_serialized(monkeypatch):
    sdk = ModuleType("hatchet_sdk")
    sdk.ConcurrencyExpression = lambda **kw: SimpleNamespace(**kw)
    sdk.ConcurrencyLimitStrategy = SimpleNamespace(GROUP_ROUND_ROBIN="round-robin")
    sdk.Priority = SimpleNamespace(LOW=3)
    monkeypatch.setitem(sys.modules, "hatchet_sdk", sdk)
    options = []
    hatchet = SimpleNamespace(task=lambda **kw: (options.append(kw) or (lambda fn: fn)))
    assert build_tasks(hatchet, {}) == []
    assert len(build_tasks(hatchet, {"docsdrift": {}})) == 1
    assert options[0]["on_crons"] == ["41 5 * * 0"]
    assert options[0]["retries"] == 0
    assert options[0]["concurrency"][0].max_runs == 1
