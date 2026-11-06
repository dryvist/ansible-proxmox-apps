"""Contracts for the scheduled Hatchet GitHub release digest."""

import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
WORKER_PACKAGE = ROOT / "roles/hatchet_docker/files/gpu_fill_worker"
sys.path.insert(0, str(WORKER_PACKAGE))
sys.dont_write_bytecode = True

from adapter import run_agent  # noqa: E402
from config import load_config  # noqa: E402
from release_digest import digest  # noqa: E402
from release_digest import tasks as digest_tasks  # noqa: E402

DEFAULTS = yaml.safe_load((ROOT / "roles/hatchet_docker/defaults/main.yml").read_text())
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
PLATFORM = {
    "kind": "chat",
    "base_url": "https://router.example.invalid/v1",
    "model": "pro6000-direct",
    "max_tokens": 1024,
    "auth_env": "GPU_FILL_ROUTER_API_KEY",
    "timeout_s": 300,
}
RELEASE_CONFIG = {
    "cron": "23 11 * * *",
    "repositories": [{"owner": "example", "repo": "project", "interest_tag": "homelab"}],
    "chat_platform": "gpu",
    "auth_env": "SLACK_RELEASE_DIGEST_WEBHOOK",
}


def base_config():
    return {
        "roles": {"medium": {"max_runs": 1}},
        "platforms": {"gpu": PLATFORM},
    }


def write_config(tmp_path, config):
    path = tmp_path / "worker.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def release(tag, published_at, **overrides):
    return {
        "tag_name": tag,
        "name": f"Release {tag}",
        "html_url": f"https://github.com/example/project/releases/tag/{tag}",
        "published_at": published_at,
        "draft": False,
        "body": "Adds an upgrade and fixes a bug.",
        **overrides,
    }


def summary(level):
    return {
        "summary": ["Adds a feature", "Fixes a defect", "Updates dependencies"],
        "homelab_impact": "Check the service before upgrading.",
        "risk": {"level": level, "reason": f"{level} operational risk."},
    }


def completion(value):
    return {"choices": [{"message": {"content": json.dumps(value)}}]}


def test_defaults_keep_release_digest_off_and_repository_list_empty():
    assert DEFAULTS["hatchet_docker_worker_release_digest_enabled"] is False
    assert DEFAULTS["hatchet_docker_worker_release_digest_cron"] == "23 11 * * *"
    assert DEFAULTS["hatchet_docker_worker_release_digest_repositories"] == []


def test_config_accepts_release_digest_with_optional_interest_tag(tmp_path):
    config = base_config()
    config["release_digest"] = copy.deepcopy(RELEASE_CONFIG)

    assert load_config(write_config(tmp_path, config)) == config

    config["release_digest"]["repositories"] = [{"owner": "example", "repo": "project"}]
    assert load_config(write_config(tmp_path, config)) == config


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda value: value.update(cron="15 11 * * *"), "quarter-hour"),
        (lambda value: value.update(auth_env="bad-name"), "env var name"),
        (lambda value: value.update(chat_platform="missing"), "active chat platform"),
        (lambda value: value.update(repositories=[{"owner": "example"}]), "owner and repo"),
        (
            lambda value: value.update(repositories=[{"owner": "example", "repo": "project", "interest_tag": " "}]),
            "interest_tag",
        ),
    ],
)
def test_config_rejects_malformed_release_digest(tmp_path, change, message):
    config = base_config()
    config["release_digest"] = copy.deepcopy(RELEASE_CONFIG)
    change(config["release_digest"])

    with pytest.raises(ValueError, match=message):
        load_config(write_config(tmp_path, config))


def test_worker_config_template_renders_enabled_release_digest(tmp_path):
    template = (ROOT / "roles/hatchet_docker/templates/gpu_fill_worker_config.json.j2").read_text()
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "hatchet_docker_worker_roles": {"medium": {"max_runs": 1}},
        "hatchet_docker_worker_platforms": [{"name": "gpu", **PLATFORM}],
        "hatchet_docker_worker_latency_guard_enabled": False,
        "hatchet_docker_worker_fill_enabled": False,
        "hatchet_docker_eval_enabled": False,
        "hatchet_docker_worker_release_digest_enabled": True,
        "hatchet_docker_worker_release_digest_cron": RELEASE_CONFIG["cron"],
        "hatchet_docker_worker_release_digest_repositories": RELEASE_CONFIG["repositories"],
        "hatchet_docker_worker_release_digest_chat_platform": RELEASE_CONFIG["chat_platform"],
        "hatchet_docker_worker_release_digest_auth_env": RELEASE_CONFIG["auth_env"],
    }

    rendered = templar.template(trust_as_template(template))
    config = json.loads(rendered)

    assert config["release_digest"] == RELEASE_CONFIG
    assert load_config(write_config(tmp_path, config)) == config


def test_compose_template_injects_existing_slack_secret_under_auth_env():
    template = (ROOT / "roles/hatchet_docker/templates/docker-compose.yml.j2").read_text()
    render_vars = yaml.safe_load(
        (ROOT / "tests/hatchet_gpu_fill_worker/render_vars.yml").read_text()
    )
    render_vars.update(
        hatchet_docker_worker_enabled=True,
        hatchet_docker_worker_release_digest_enabled=True,
        hostvars={"localhost": {"hatchet_docker_worker_token_current": "render-token"}},
    )
    templar = Templar(loader=DataLoader())
    templar.available_variables = render_vars

    rendered = templar.template(trust_as_template(template))

    assert (
        'SLACK_RELEASE_DIGEST_WEBHOOK: "https://hooks.example.invalid/slack-digest-placeholder"'
        in rendered
    )
    render_vars["hatchet_docker_worker_release_digest_enabled"] = False
    templar.available_variables = render_vars
    rendered_off = templar.template(trust_as_template(template))
    assert "SLACK_RELEASE_DIGEST_WEBHOOK" not in rendered_off


def test_fetch_releases_filters_to_last_24_hours_and_reads_all_pages():
    older = release("old", (NOW - timedelta(hours=25)).isoformat())
    first_page = [older] * 100
    second_page = [
        release("recent", (NOW - timedelta(hours=3)).isoformat()),
        release("draft", (NOW - timedelta(hours=1)).isoformat(), draft=True),
        release("future", (NOW + timedelta(minutes=1)).isoformat()),
    ]
    urls = []

    def http_get(url, _timeout):
        urls.append(url)
        return 200, json.dumps(first_page if url.endswith("page=1") else second_page).encode()

    result = digest.fetch_releases(RELEASE_CONFIG["repositories"], now=NOW, http_get=http_get)

    assert [item["tag"] for item in result] == ["recent"]
    assert result[0]["interest_tag"] == "homelab"
    assert len(urls) == 2
    assert all("per_page=100" in url for url in urls)


def test_summarize_requests_json_mode_and_validates_the_three_bullets():
    captured = {}
    item = digest.fetch_releases(
        RELEASE_CONFIG["repositories"],
        now=NOW,
        http_get=lambda *_: (200, json.dumps([release("v1", NOW.isoformat())]).encode()),
    )[0]

    def chat(platform, request, latency_guard=None):
        captured.update(platform=platform, request=request, latency_guard=latency_guard)
        return completion(summary("medium"))

    result = digest.summarize_release(item, PLATFORM, latency_guard={"query": "x"}, chat=chat)

    assert result["analysis"] == summary("medium")
    assert captured["request"]["payload"]["response_format"] == {"type": "json_object"}
    assert captured["request"]["payload"]["max_tokens"] == 512
    assert "homelab" in captured["request"]["payload"]["prompt"]
    assert captured["latency_guard"] == {"query": "x"}


@pytest.mark.parametrize(
    "value",
    [
        {**summary("low"), "extra": True},
        {**summary("low"), "summary": ["one", "two"]},
        {**summary("low"), "risk": {"level": "critical", "reason": "bad"}},
    ],
)
def test_model_reply_must_match_the_strict_summary_contract(value):
    with pytest.raises(ValueError):
        digest._parse_summary(completion(value))


def test_empty_digest_does_not_read_webhook_or_call_model_or_slack(monkeypatch):
    monkeypatch.delenv(RELEASE_CONFIG["auth_env"], raising=False)

    def fail(*_args, **_kwargs):
        raise AssertionError("an empty digest must not do external work")

    config = {**RELEASE_CONFIG, "repositories": []}
    assert digest.run_digest(config, PLATFORM, chat=fail, http_post=fail) == {
        "status": "empty",
        "release_count": 0,
    }


def test_run_digest_posts_one_slack_message_grouped_by_risk(monkeypatch, capsys):
    webhook = "https://hooks.example.invalid/services/private-value"
    monkeypatch.setenv(RELEASE_CONFIG["auth_env"], webhook)
    releases = [
        release("v1", NOW.isoformat()),
        release("v2", (NOW - timedelta(hours=1)).isoformat()),
    ]
    posted = []
    model_results = iter((summary("low"), summary("high")))

    def chat(_platform, _request, **_kwargs):
        return completion(next(model_results))

    def http_post(url, body, headers, timeout_s):
        posted.append((url, json.loads(body), headers, timeout_s))
        return 200, b"ok"

    result = digest.run_digest(
        RELEASE_CONFIG,
        PLATFORM,
        now=NOW,
        http_get=lambda *_: (200, json.dumps(releases).encode()),
        chat=chat,
        http_post=http_post,
    )

    assert result == {"status": "posted", "release_count": 2}
    assert len(posted) == 1
    assert posted[0][0] == webhook
    message = posted[0][1]["text"]
    assert message.index("*High risk") < message.index("*Low risk")
    assert "• <https://github.com/example/project/releases/tag/v1|example/project v1>" in message
    assert webhook not in json.dumps(posted[0][1])
    assert webhook not in capsys.readouterr().out


def test_slack_post_failure_does_not_expose_webhook():
    webhook = "https://hooks.example.invalid/private-value"

    def fail_post(*_args):
        raise RuntimeError(webhook)

    with pytest.raises(digest.DigestPostError) as failure:
        digest.post_digest(webhook, "digest", http_post=fail_post)

    assert webhook not in str(failure.value)


def test_chat_adapter_forwards_json_object_response_format(monkeypatch):
    posted = []
    monkeypatch.setenv("GPU_FILL_ROUTER_API_KEY", "render-only-placeholder")

    def http_post(_url, body, _headers, _timeout):
        posted.append(json.loads(body))
        return 200, b"{}"

    run_agent(
        PLATFORM,
        {"payload": {"prompt": "Return JSON", "response_format": {"type": "json_object"}}},
        http_post=http_post,
    )

    assert posted[0]["response_format"] == {"type": "json_object"}


class FakeHatchet:
    def __init__(self):
        self.registered = []

    def task(self, **options):
        def decorate(handler):
            self.registered.append((options, handler))
            return SimpleNamespace(name=options["name"])

        return decorate


def test_task_builder_registers_low_priority_daily_cron(monkeypatch):
    sdk = ModuleType("hatchet_sdk")
    sdk.NonRetryableException = type("FakeNonRetryableException", (Exception,), {})
    sdk.Priority = SimpleNamespace(LOW="LOW")
    monkeypatch.setitem(sys.modules, "hatchet_sdk", sdk)
    hatchet = FakeHatchet()

    tasks = digest_tasks.build_tasks(hatchet, RELEASE_CONFIG, {"gpu": PLATFORM})

    options, _handler = hatchet.registered[0]
    assert [task.name for task in tasks] == ["release-digest"]
    assert options["on_crons"] == ["23 11 * * *"]
    assert options["default_priority"] == "LOW"
    assert options["retries"] == 6


def test_release_digest_role_defaults_name_the_existing_slack_webhook_path():
    compose = (ROOT / "roles/hatchet_docker/templates/docker-compose.yml.j2").read_text()

    assert "bao_ntfy_secrets[platform_alerts_slack_webhook_key]" in compose
    assert "hatchet_docker_worker_release_digest_auth_env" in compose
