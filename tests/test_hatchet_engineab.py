"""Engine comparison dispatch, public-data boundary, and Slack contracts."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

WORKER = Path(__file__).resolve().parents[1] / "roles/hatchet_docker/files/gpu_fill_worker"
sys.path.insert(0, str(WORKER))
from engineab.config import validate  # noqa: E402
from engineab.digest import merged_prs, run  # noqa: E402


def config():
    return {"repos": ["org/repo"], "slack_channel": "C123", "slack_auth_env": "SLACK",
            "engines": {name: {"run_url": f"https://192.0.2.1/{name}", "auth_env": name.upper()}
                        for name in ("dify", "langflow", "langgraph")}}


def test_comparison_uses_same_prompt_and_one_thread(monkeypatch):
    cfg = config()
    for env in ["SLACK", "DIFY", "LANGFLOW", "LANGGRAPH"]:
        monkeypatch.setenv(env, "test")
    prompts, posts = [], []

    def call(url, body=None, token=None, header=None):
        if "/repos/" in url:
            return {"private": False, "visibility": "public"}
        if "/search/" in url:
            assert "merged%3A2026-11-04" in url
            return {"total_count": 1, "items": [{"title": "Change", "number": 1, "html_url": "public-link"}]}
        if url.endswith("/dify"):
            prompts.append(body["inputs"]["prompt"])
            return {"data": {"status": "succeeded", "outputs": {"text": "D" * 3000}, "total_tokens": 40}}
        if url.endswith("/langflow"):
            assert header == "x-api-key"
            prompts.append(body["input_value"])
            return {"outputs": [{"outputs": [{"results": {"message": {"text": "flow"}}}]}]}
        if url.endswith("/langgraph"):
            prompts.append(body["input"]["prompt"])
            return {"text": "graph", "tokens": 20}
        posts.append(body)
        return {"ok": True, "ts": "123"}

    result = run(cfg, call, datetime(2026, 11, 5, tzinfo=timezone.utc))
    assert len(prompts) == 3 and len(set(prompts)) == 1
    assert len(posts) == 2 and posts[1]["thread_ts"] == "123"
    assert len(posts[1]["blocks"]) == 2  # Full output survives Slack field limit.
    assert result["engines"]["dify"]["output_length"] == 3000
    assert result["engines"]["langflow"]["tokens"] is None


@pytest.mark.parametrize("metadata", [{"private": True}, {"private": False}])
def test_non_public_repo_is_refused(metadata):
    with pytest.raises(ValueError, match="public"):
        merged_prs(["org/repo"], "2026-11-04", lambda url: metadata)


def test_incomplete_search_is_refused():
    def call(url):
        return ({"private": False, "visibility": "public"} if "/repos/" in url
                else {"total_count": 1001})
    with pytest.raises(ValueError, match="incomplete"):
        merged_prs(["org/repo"], "2026-11-04", call)


def test_config_requires_all_engines():
    cfg = config()
    validate(cfg)
    del cfg["engines"]["langflow"]
    with pytest.raises(ValueError, match="three"):
        validate(cfg)


def test_engine_failure_does_not_stop_other_engines(monkeypatch):
    cfg = config()
    for env in ["SLACK", "DIFY", "LANGFLOW", "LANGGRAPH"]:
        monkeypatch.setenv(env, "test")
    seen = []

    def call(url, body=None, *args):
        seen.append(url)
        if "/repos/" in url:
            return {"private": False, "visibility": "public"}
        if "/search/" in url:
            return {"total_count": 0, "items": []}
        if "slack.com" in url:
            return {"ok": True, "ts": "123"}
        raise RuntimeError("sensitive body")

    result = run(cfg, call)
    assert len([url for url in seen if "192.0.2.1" in url]) == 3
    assert "sensitive" not in str(result)
    assert all(r["status"] == "failed" for r in result["engines"].values())
