"""Faked API and Hatchet contracts for scheduled repository work-finding."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "roles/hatchet_docker/files/gpu_fill_worker"
sys.path.insert(0, str(WORKER))
sys.dont_write_bytecode = True

from config import load_config  # noqa: E402
from workfind import agent, repositories, tasks  # noqa: E402


def workfind_config(repo_dir):
    return {
        "cron": "17 3 * * *",
        "repos": [{"name": "sample", "url": "https://github.com/example/sample.git"}],
        "files_per_repo": 1,
        "max_file_bytes": 65536,
        "min_confidence": 0.8,
        "max_tasks_per_night": 1,
        "llm_role": "agent-long-context",
        "platform": "agent-long-context",
        "vikunja": {
            "base_url": "https://tasks.example.invalid/api/v1",
            "project_id": 55,
            "token_env": "VIKUNJA_WORKFIND_TOKEN",
        },
    }


def full_config(workfind):
    return {
        "roles": {"agent-long-context": {"max_runs": 1}},
        "platforms": {
            "agent-long-context": {
                "kind": "chat",
                "base_url": "https://router.example.invalid/v1",
                "model": "agent-long-context",
                "max_tokens": 4096,
                "auth_env": "ROUTER_TOKEN",
                "timeout_s": 60,
            }
        },
        "workfind": workfind,
    }


def finding(file_path="README.md", confidence=0.95):
    return {
        "kind": "todo_context",
        "title": "Add focused tests",
        "description": "This TODO has no linked work or completion condition.",
        "file": file_path,
        "line": 2,
        "evidence": "TODO: add tests",
        "confidence": confidence,
    }


def completion(value):
    return {"choices": [{"message": {"content": json.dumps({"findings": [value]})}}]}


def make_git_repo(path):
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.invalid"], check=True)
    (path / "README.md").write_text("# Sample\nTODO: add tests\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-qm", "initial"],
        check=True,
        env={**os.environ, "GIT_AUTHOR_DATE": "@1700000000 +0000", "GIT_COMMITTER_DATE": "@1700000000 +0000"},
    )
    return path


def test_config_accepts_and_rejects_workfind_contract(tmp_path):
    config = full_config(workfind_config(tmp_path))
    path = tmp_path / "worker.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    assert load_config(path) == config

    for edit, message in (
        (lambda value: value.update(cron="15 3 * * *"), "quarter-hour"),
        (lambda value: value.update(cron="*/15 3 * * *"), "quarter-hour"),
        (lambda value: value["repos"][0].update(url="https://user:pass@example.org/repo.git"), "without credentials"),
        (lambda value: value.update(min_confidence=1.1), "from 0 to 1"),
        (lambda value: value["vikunja"].update(project_id=0), "positive integer"),
        (lambda value: value.update(platform="missing"), "active chat platform"),
        (lambda value: value.update(llm_role="missing"), "LLM role must be configured"),
    ):
        broken = full_config(workfind_config(tmp_path))
        edit(broken["workfind"])
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            load_config(path)


def test_clone_uses_anonymous_shallow_default_branch_command(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

    repositories.clone_repo("https://github.com/example/repo.git", tmp_path / "repo", fake_run)
    command, options = calls[0]
    assert command == [
        "git",
        "clone",
        "--depth",
        "1000",
        "--single-branch",
        "--filter=blob:none",
        "--",
        "https://github.com/example/repo.git",
        str(tmp_path / "repo"),
    ]
    assert options["check"] is True and options["timeout"] == 180
    with pytest.raises(ValueError, match="without credentials"):
        repositories.clone_repo("https://user:pass@example.org/repo.git", tmp_path / "bad", fake_run)


def test_select_files_orders_recent_history_then_size_and_skips_symlinks(tmp_path):
    repo = make_git_repo(tmp_path / "repo")
    (repo / "old-large.md").write_text("old " * 100, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "old-large.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "older file"],
        check=True,
        env={**os.environ, "GIT_AUTHOR_DATE": "@1700000100 +0000", "GIT_COMMITTER_DATE": "@1700000100 +0000"},
    )
    (repo / "large.md").write_text("x " * 20, encoding="utf-8")
    (repo / "new.md").write_text("new\n", encoding="utf-8")
    (repo / "outside.md").symlink_to(repo / "README.md")
    subprocess.run(["git", "-C", str(repo), "add", "large.md", "new.md", "outside.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "recent"], check=True)

    selected = repositories.select_files(repo, 2, 65536)

    assert [item["path"] for item in selected] == ["large.md", "new.md"]
    assert selected[0]["committed_at"] >= 1700000000


def test_parse_requires_strict_json_and_verbatim_file_line_evidence():
    source = "# Sample\nTODO: add tests\n"
    assert agent.parse_findings(completion(finding()), "README.md", source) == [finding()]
    wrong_line = finding()
    wrong_line["line"] = 1
    assert agent.parse_findings(completion(wrong_line), "README.md", source) == []
    with pytest.raises(ValueError, match="strict JSON"):
        agent.parse_findings({"choices": [{"message": {"content": "```json{}"}}]}, "README.md", source)
    related = finding("docs/guide.md")
    related["kind"] = "docs_code_drift"
    related["line"] = 1
    context = {"docs/guide.md": "TODO: add tests; the old API returns a different result.\n"}
    assert agent.parse_findings(completion(related), "README.md", source, context) == [related]
    assert "the old API returns a different result." in agent.build_prompt(
        "sample", "README.md", source, context
    )


def test_task_list_paginates_until_the_vikunja_project_is_exhausted():
    pages = []

    def fake_request(method, url, _body, _token_env, _timeout_s):
        assert method == "GET"
        query = parse_qs(urlsplit(url).query)
        pages.append((query["page"][0], query["per_page"][0]))
        assert urlsplit(url).path.endswith("/tasks")
        if query["page"] == ["1"]:
            return 200, [
                {"title": str(index), "description": "", "project_id": 55}
                for index in range(50)
            ]
        if query["page"] == ["2"]:
            return 200, [
                {"title": "last task", "description": "", "project_id": 64},
                {"title": "target task", "description": "", "project_id": 55},
            ]
        return 200, []

    config = workfind_config(Path("/unused"))["vikunja"]
    existing = agent._task_list(
        config["base_url"], config["project_id"], config["token_env"], 30, fake_request
    )

    assert len(existing) == 51
    assert pages == [("1", "50"), ("2", "50"), ("3", "50")]


def test_vikunja_token_is_read_from_environment_and_added_only_as_bearer_header(monkeypatch):
    calls = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"[]"

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse()

    monkeypatch.setenv("VIKUNJA_WORKFIND_TOKEN", "test-only-token")
    monkeypatch.setattr(agent, "urlopen", fake_urlopen)
    status, body = agent._request(
        "GET", "https://tasks.example.invalid/api/v1/tasks", None, "VIKUNJA_WORKFIND_TOKEN", 30
    )

    assert status == 200 and body == []
    assert calls[0][1] == 30
    headers = dict((key.lower(), value) for key, value in calls[0][0].header_items())
    assert headers["authorization"] == "Bearer test-only-token"
    assert "test-only-token" not in repr(body)


def test_workfind_is_disabled_by_default_and_secret_is_not_rendered_into_json():
    defaults = (ROOT / "roles/hatchet_docker/defaults/main.yml").read_text(encoding="utf-8")
    config_template = (ROOT / "roles/hatchet_docker/templates/gpu_fill_worker_config.json.j2").read_text(encoding="utf-8")
    compose_template = (ROOT / "roles/hatchet_docker/templates/docker-compose.yml.j2").read_text(encoding="utf-8")

    assert "hatchet_docker_worker_workfind_enabled: false" in defaults
    assert 'hatchet_docker_worker_workfind_cron: "17 3 * * *"' in defaults
    assert '"token_env": {{ hatchet_docker_worker_workfind_vikunja_token_env | to_json }}' in config_template
    assert "vikunja_token_secret_key" not in config_template
    assert "bao_apps_secrets[hatchet_docker_worker_workfind_vikunja_token_secret_key]" in compose_template


def test_evidence_hash_and_title_similarity_dedupe():
    item = finding()
    digest = agent.evidence_hash("https://github.com/example/sample.git", "README.md", item)
    title = "[workfind] sample: Add focused tests"
    existing = [{"title": title, "description": f"<!-- workfind-evidence-sha256:{digest} -->"}]
    assert len(digest) == 64
    assert agent.is_duplicate(title, digest, existing)
    assert agent.is_duplicate("[workfind] sample: Add focused test", "f" * 64, existing)


def test_run_creates_once_and_dedupes_on_later_night(tmp_path):
    source = make_git_repo(tmp_path / "source")
    api_tasks = []
    calls = []

    def fake_clone(_url, destination):
        shutil.copytree(source, destination)

    def fake_chat(_platform, _payload, latency_guard=None):
        assert latency_guard is None
        return completion(finding())

    def fake_request(method, url, body, token_env, timeout_s):
        calls.append((method, url, body, token_env, timeout_s))
        if method == "GET":
            page = parse_qs(urlsplit(url).query)["page"][0]
            return 200, list(api_tasks) if page == "1" else []
        api_tasks.append({"title": body["title"], "description": body["description"], "project_id": 55})
        return 200, {"id": len(api_tasks)}

    config = workfind_config(tmp_path)
    platform = {"timeout_s": 60}
    first = agent.run_workfind(
        config, platform, chat=fake_chat, request_fn=fake_request, clone_fn=fake_clone
    )
    second = agent.run_workfind(
        config, platform, chat=fake_chat, request_fn=fake_request, clone_fn=fake_clone
    )

    assert first["created"] == 1
    assert second["created"] == 0 and second["duplicates"] == 1
    creates = [call for call in calls if call[0] == "PUT"]
    assert len(creates) == 1
    assert creates[0][2]["title"].startswith("[workfind] sample:")
    assert "README.md:2" in creates[0][2]["description"]
    assert agent.HASH_MARKER.search(creates[0][2]["description"])
    assert all(call[3] == "VIKUNJA_WORKFIND_TOKEN" for call in calls)


def test_low_confidence_is_not_published_and_task_cap_is_respected(tmp_path):
    source = make_git_repo(tmp_path / "source")
    (source / "src.py").write_text("# Source\nTODO: add tests\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "src.py"], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-qm", "second file"], check=True)
    creates = []

    def fake_request(method, _url, body, *_args):
        if method == "GET":
            return 200, []
        creates.append(body)
        return 200, {}

    config = workfind_config(tmp_path)
    config["files_per_repo"] = 2
    config["max_tasks_per_night"] = 1
    confidence = [0.4, 0.99]

    def fake_chat(_platform, payload, **_kwargs):
        file_path = re.search(r"Focus file '([^']+)' begins", payload["payload"]["prompt"]).group(1)
        return completion(finding(file_path=file_path, confidence=confidence.pop(0)))

    result = agent.run_workfind(
        config,
        {"timeout_s": 60},
        chat=fake_chat,
        request_fn=fake_request,
        clone_fn=lambda _url, destination: shutil.copytree(source, destination),
    )

    assert result["below_threshold"] == 1
    assert result["created"] == len(creates) == 1


def test_repo_order_rotates_by_utc_day_when_the_nightly_task_cap_is_reached(tmp_path):
    source = make_git_repo(tmp_path / "source")
    config = workfind_config(tmp_path)
    config["repos"].append({"name": "second", "url": "https://github.com/example/second.git"})
    visited = []

    def fake_clone(url, destination):
        visited.append(url)
        shutil.copytree(source, destination)

    def fake_chat(_platform, payload, **_kwargs):
        file_path = re.search(r"Focus file '([^']+)' begins", payload["payload"]["prompt"]).group(1)
        return completion(finding(file_path=file_path))

    def fake_request(method, _url, _body, *_args):
        return (200, []) if method == "GET" else (200, {})

    agent.run_workfind(
        config,
        {"timeout_s": 30},
        chat=fake_chat,
        request_fn=fake_request,
        clone_fn=fake_clone,
        today="2026-11-05",
    )
    first = visited[-1]
    agent.run_workfind(
        config,
        {"timeout_s": 30},
        chat=fake_chat,
        request_fn=fake_request,
        clone_fn=fake_clone,
        today="2026-11-06",
    )

    assert visited[-1] != first


class FakeHatchet:
    def __init__(self):
        self.registered = []

    def task(self, **options):
        return lambda handler: self.registered.append((options, handler)) or handler


def test_task_is_scheduled_low_priority_serialized_and_disabled_without_config(monkeypatch):
    sdk = ModuleType("hatchet_sdk")
    sdk.ConcurrencyExpression = lambda **values: SimpleNamespace(**values)
    sdk.ConcurrencyLimitStrategy = SimpleNamespace(GROUP_ROUND_ROBIN="round-robin")
    sdk.Context = type("Context", (), {})
    sdk.NonRetryableException = type("NonRetryableException", (Exception,), {})
    sdk.Priority = SimpleNamespace(LOW="low")
    monkeypatch.setitem(sys.modules, "hatchet_sdk", sdk)
    hatchet = FakeHatchet()
    assert tasks.build_tasks(hatchet, {}) == []
    assert tasks.workfind_slots({}) == 0
    worker_config = full_config(workfind_config(Path("/unused")))

    assert tasks.build_tasks(hatchet, worker_config) == [hatchet.registered[0][1]]
    options, _handler = hatchet.registered[0]
    assert options["name"] == "gpu-repo-workfind"
    assert options["on_crons"] == ["17 3 * * *"]
    assert options["concurrency"][0].max_runs == 1
    assert options["concurrency"][0].name == "gpu-agent-long-context"
    assert options["concurrency"][0].expression == "'agent-long-context'"
    assert options["default_priority"] == "low"
    assert tasks.workfind_slots(worker_config) == 1
