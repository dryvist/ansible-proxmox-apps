"""Fake-based contracts for nightly incremental indexing; no external services."""

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "roles/hatchet_docker/files/gpu_fill_worker"))
sys.dont_write_bytecode = True

from reindex import build_tasks  # noqa: E402
from reindex.api import APIs  # noqa: E402
from reindex.config import validate  # noqa: E402
from reindex.runner import run  # noqa: E402
from reindex.sources import documents  # noqa: E402


def config(tmp_path):
    return {"repos": [{"url": "https://192.0.2.1/org/repo.git", "collection": "docs"}],
            "hindsight_export": "", "hindsight_collection": "memories",
            "router_url": "https://192.0.2.2/v1", "qdrant_url": "https://192.0.2.3",
            "output_dir": str(tmp_path / "output"), "smoke_query": ""}


class FakeAPI:
    def __init__(self):
        self.embedded, self.upserts, self.deletes, self.smokes = [], [], [], []
        self.fail = False

    def embed(self, text):
        self.embedded.append(text)
        return [0.25, 0.75]

    def upsert(self, collection, point):
        if self.fail:
            raise RuntimeError("write failed")
        self.upserts.append((collection, point))

    def delete(self, collection, ids):
        self.deletes.append((collection, ids))

    def smoke(self, collection, query):
        self.smokes.append((collection, query))
        return 2


def test_incremental_updates_and_cleanup(tmp_path):
    cfg, api = config(tmp_path), FakeAPI()
    source = [("docs", "a#0", "first"), ("docs", "b#0", "second")]
    assert run(cfg, api=api, source=source)["collections"]["docs"]["changed"] == 2
    assert run(cfg, api=api, source=source)["collections"]["docs"]["unchanged"] == 2
    assert len(api.embedded) == 2
    source[0] = ("docs", "a#0", "changed")
    cfg["smoke_query"] = "test"
    result = run(cfg, api=api, source=source[:1])
    assert result["collections"]["docs"]["changed"] == 1
    assert result["collections"]["docs"]["deleted"] == 1
    assert api.upserts[0][1]["id"] == api.upserts[-1][1]["id"]
    assert api.smokes == [("docs", "test")]
    root = Path(cfg["output_dir"])
    assert json.loads((root / "results.json").read_text())["status"] == "completed"
    assert 'gpu_fill_reindex_changed{collection="docs"} 1' in (root / "reindex.prom").read_text()


def test_failed_writes_preserve_checkpoint_and_publish_failure(tmp_path):
    cfg, api = config(tmp_path), FakeAPI()
    run(cfg, api=api, source=[("docs", "a", "old")])
    checkpoint = Path(cfg["output_dir"]) / "checkpoint.json"
    previous = checkpoint.read_bytes()
    api.fail = True
    with pytest.raises(RuntimeError, match="write failed"):
        run(cfg, api=api, source=[("docs", "a", "new")])
    assert checkpoint.read_bytes() == previous
    assert json.loads(checkpoint.with_name("results.json").read_text())["status"] == "failed"
    assert "gpu_fill_reindex_success 0" in checkpoint.with_name("reindex.prom").read_text()


def test_failed_source_never_deletes_points(tmp_path):
    cfg, api = config(tmp_path), FakeAPI()
    run(cfg, api=api, source=[("docs", "a", "old")])

    def broken():
        raise ValueError("incomplete export")
        yield

    with pytest.raises(ValueError, match="incomplete export"):
        run(cfg, api=api, source=broken())
    assert api.deletes == []


def test_changed_target_reembeds(tmp_path):
    cfg, api = config(tmp_path), FakeAPI()
    source = [("docs", "a", "old")]
    run(cfg, api=api, source=source)
    cfg["qdrant_url"] += "/new"
    run(cfg, api=api, source=source)
    assert len(api.embedded) == 2


def test_sources_skip_hidden_binary_and_symlinks_and_load_memories(tmp_path):
    cfg = config(tmp_path)
    export = tmp_path / "export.json"
    export.write_text(json.dumps([{"id": "memory-1", "text": "remember"}]))
    cfg["hindsight_export"] = str(export)

    def clone(url, directory):
        assert url == cfg["repos"][0]["url"]
        root = Path(directory)
        (root / "guide.md").write_text("hello")
        (root / "app.py").write_text("print('hello')")
        (root / ".hidden.md").write_text("hidden")
        (root / "binary.txt").write_bytes(b"\xff")
        (root / "link.md").symlink_to(export)

    rows = list(documents(cfg, clone))
    assert {row[2] for row in rows} == {"hello", "print('hello')", "remember"}
    assert rows[-1][:2] == ("memories", "hindsight/memory-1#0")
    export.write_text(json.dumps([{"id": "same", "text": "a"}, {"id": "same", "text": "b"}]))
    with pytest.raises(ValueError, match="unique"):
        list(documents(cfg, clone))


def test_nightly_registration_is_optional_and_serialized(monkeypatch, tmp_path):
    assert build_tasks(None, {}) == []
    sdk = ModuleType("hatchet_sdk")
    sdk.ConcurrencyExpression = lambda **kw: kw
    sdk.ConcurrencyLimitStrategy = SimpleNamespace(GROUP_ROUND_ROBIN="round_robin")
    sdk.Priority = SimpleNamespace(LOW=3)
    monkeypatch.setitem(sys.modules, "hatchet_sdk", sdk)
    calls = []

    def task(**options):
        calls.append(options)
        return lambda fn: fn

    assert len(build_tasks(SimpleNamespace(task=task), {"reindex": config(tmp_path)})) == 1
    assert calls[0]["on_crons"] == ["37 1 * * *"]
    assert calls[0]["concurrency"][0]["max_runs"] == 1
    assert calls[0]["concurrency"][0]["is_tenant_scoped"]
    assert calls[0]["default_priority"] == 3


def test_api_routes_embed_and_confirmed_qdrant_writes(monkeypatch, tmp_path):
    monkeypatch.setenv("GPU_FILL_ROUTER_API_KEY", "fake-router")
    monkeypatch.setenv("GPU_FILL_REINDEX_QDRANT_API_KEY", "fake-qdrant")
    api = APIs(config(tmp_path))
    calls = []

    def call(service, path, body, method="POST"):
        calls.append((service, path, body, method))
        if path == "/embeddings":
            return {"data": [{"embedding": [0.1, 0.2]}]}
        if path.endswith("/query"):
            return {"result": {"points": [{"payload": {"text": "doc"}}]}}
        if path == "/rerank":
            return {"results": [{"index": 0, "relevance_score": 0.9}]}
        return {"status": "ok", "result": {"status": "completed"}}

    monkeypatch.setattr(api, "call", call)
    assert api.embed("document") == [0.1, 0.2]
    assert calls[0][2] == {"model": "embed", "input": ["document"]}
    api.upsert("docs", {"id": "fake"})
    assert calls[-1][1:] == ("/collections/docs/points?wait=true", {"points": [{"id": "fake"}]}, "PUT")
    assert api.smoke("docs", "query") == 1
    with pytest.raises(ValueError, match="completed"):
        api.completed({"status": "ok", "result": {"status": "acknowledged"}})


@pytest.mark.parametrize("field,value", [
    ("output_dir", "relative"), ("hindsight_export", "relative"),
    ("smoke_query", None), ("qdrant_url", "file:///tmp/db"),
    ("hindsight_collection", 'bad"label'),
])
def test_invalid_config_rejected(tmp_path, field, value):
    cfg = config(tmp_path)
    cfg[field] = value
    with pytest.raises(ValueError):
        validate(cfg)


def test_config_accepts_public_source_and_rejects_credentials(tmp_path):
    cfg = config(tmp_path)
    cfg["repos"][0]["url"] = "https://github.com/org/repo.git"
    validate(cfg)
    cfg["repos"][0]["url"] = "https://token@github.com/org/repo.git"
    with pytest.raises(ValueError, match="public HTTPS"):
        validate(cfg)


def test_templates_render_opt_in_with_durable_volume_and_env_secrets(tmp_path):
    import yaml
    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar, trust_as_template
    from config import load_config

    role = ROOT / "roles/hatchet_docker"
    defaults = yaml.safe_load((role / "defaults/main.yml").read_text())
    fixtures = yaml.safe_load((ROOT / "tests/hatchet_gpu_fill_worker/render_vars.yml").read_text())
    variables = {**defaults, **fixtures, "_hatchet_role_defaults": defaults}
    variables.update(
        hatchet_docker_worker_enabled=True,
        hatchet_docker_worker_reindex_enabled=True,
        hatchet_docker_worker_reindex_repos=[{"url": "https://github.com/org/repo.git", "collection": "docs"}],
        hatchet_docker_worker_reindex_qdrant_url="https://192.0.2.3",
        hatchet_docker_worker_reindex_router_url="https://192.0.2.2/v1",
        hatchet_docker_worker_latency_guard_enabled=False,
        hostvars={"localhost": {"hatchet_docker_worker_token_current": "fake-worker"}},
    )
    variables["bao_apps_secrets"].update(
        hatchet_reindex_qdrant_api_key="fake-db", gpu_fill_llm_router_key="fake-router")
    variables["hatchet_docker_worker_reindex_output_host_dir"] = trust_as_template(
        defaults["hatchet_docker_worker_reindex_output_host_dir"])
    templar = Templar(loader=DataLoader(), variables=variables)

    def render(name):
        return templar.template(trust_as_template((role / "templates" / name).read_text()))

    worker_json = render("gpu_fill_worker_config.json.j2")
    path = tmp_path / "worker.json"
    path.write_text(worker_json)
    loaded = load_config(path)
    assert loaded["reindex"]["output_dir"] == "/reindex"
    assert "fake-db" not in worker_json
    compose = yaml.safe_load(render("docker-compose.yml.j2"))
    worker = compose["services"]["hatchet-worker"]
    assert worker["environment"]["GPU_FILL_REINDEX_QDRANT_API_KEY"] == "fake-db"
    assert worker["environment"]["GPU_FILL_ROUTER_API_KEY"] == "fake-router"
    assert "/tmp/hatchet/reindex:/reindex" in worker["volumes"]
    assert "git ca-certificates" in worker["command"][-1]
    variables["hatchet_docker_worker_reindex_enabled"] = False
    templar.available_variables = variables
    assert "reindex" not in json.loads(render("gpu_fill_worker_config.json.j2"))
    worker = yaml.safe_load(render("docker-compose.yml.j2"))["services"]["hatchet-worker"]
    assert "GPU_FILL_REINDEX_QDRANT_API_KEY" not in worker["environment"]
