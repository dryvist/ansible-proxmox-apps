"""Contracts for the GPU fill worker's chat platform kind and its slot defaults."""

import json
import sys
from pathlib import Path

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
WORKER_PACKAGE = ROOT / "roles/hatchet_docker/files/gpu_fill_worker"
sys.path.insert(0, str(WORKER_PACKAGE))
sys.dont_write_bytecode = True

from adapter import LatencyGuardError  # noqa: E402
from adapter import run_agent  # noqa: E402
from config import load_config  # noqa: E402

DEFAULTS = yaml.safe_load((ROOT / "roles/hatchet_docker/defaults/main.yml").read_text())
CHAT_KEY = "sk-test-chat-key-7f3a"


def write_config(tmp_path, config):
    path = tmp_path / "gpu-fill-worker.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def base_config():
    return {
        "roles": {"medium": {"max_runs": 6}},
        "platforms": {"noop": {"run_url": None, "auth_env": None, "timeout_s": 30}},
    }


def valid_guard():
    return {
        "prometheus_url": "https://metrics.example.test",
        "query": "sum(rate(requests_total[5m]))",
        "max_ratio": 1.2,
    }


def prometheus_response(value):
    return json.dumps(
        {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [{"metric": {}, "value": [0, str(value)]}],
            },
        }
    ).encode()


def chat_platform(**overrides):
    platform = {
        "kind": "chat",
        "base_url": "https://router.example.test/v1",
        "model": "pro6000-direct",
        "max_tokens": 1024,
        "auth_env": "GPU_FILL_ROUTER_API_KEY",
        "timeout_s": 300,
    }
    platform.update(overrides)
    return platform


def chat_payload(**request):
    return {
        "agent": "filler",
        "llm_role": "medium",
        "privacy_class": "public",
        "payload": {"prompt": "hello", **request},
    }


def test_config_accepts_chat_kind_and_rejects_unknown_or_malformed_chat_platforms(tmp_path):
    config = base_config()
    config["platforms"]["chat"] = chat_platform()
    assert load_config(write_config(tmp_path, config)) == config

    rejected = [
        ({**chat_platform(), "kind": "stream"}, "invalid fields"),
        ({k: v for k, v in chat_platform().items() if k != "base_url"}, "invalid fields"),
        (chat_platform(base_url="https://user:pw@router.example.test/v1"), "base_url"),
        (chat_platform(max_tokens=0), "max_tokens"),
    ]
    for platform, message in rejected:
        config["platforms"]["chat"] = platform
        with pytest.raises(ValueError, match=message):
            load_config(write_config(tmp_path, config))


def test_role_defaults_keep_chat_inactive_and_inventory_opts_into_the_chat_routes():
    inventory = yaml.safe_load((ROOT / "inventory/group_vars/docker_ai_group.yml").read_text())
    assert DEFAULTS["hatchet_docker_worker_platforms"] == []
    assert "hatchet_docker_worker_chat_platforms" in inventory["hatchet_docker_worker_platforms"]
    assert "noop" in inventory["hatchet_docker_worker_platforms"]


def test_chat_request_carries_alias_bounded_tokens_stream_false_and_env_key(monkeypatch, capsys):
    monkeypatch.setenv("GPU_FILL_ROUTER_API_KEY", CHAT_KEY)
    calls = []

    def fake_http_post(url, body, headers, timeout_s):
        calls.append((url, json.loads(body), headers, timeout_s))
        return 200, json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

    result = run_agent(chat_platform(), chat_payload(max_tokens=64), fake_http_post)

    url, body, headers, timeout_s = calls[0]
    assert result == {"choices": [{"message": {"content": "ok"}}]}
    assert url == "https://router.example.test/v1/chat/completions"
    assert body == {
        "model": "pro6000-direct",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 64,
        "stream": False,
    }
    assert headers["Authorization"] == f"Bearer {CHAT_KEY}"
    assert timeout_s == 300
    captured = capsys.readouterr()
    assert CHAT_KEY not in captured.out + captured.err


@pytest.mark.parametrize(("requested", "expected"), [(None, 1024), (10, 10), (99999, 1024)])
def test_chat_max_tokens_defaults_to_platform_cap_and_never_exceeds_it(
    monkeypatch, requested, expected
):
    monkeypatch.setenv("GPU_FILL_ROUTER_API_KEY", CHAT_KEY)
    sent = []

    def fake_http_post(url, body, headers, timeout_s):
        sent.append(json.loads(body)["max_tokens"])
        return 200, b"{}"

    request = {} if requested is None else {"max_tokens": requested}
    run_agent(chat_platform(), chat_payload(**request), fake_http_post)

    assert sent == [expected]


def test_latency_guard_refuses_over_ratio_chat_run_before_any_post(monkeypatch):
    monkeypatch.setenv("GPU_FILL_ROUTER_API_KEY", CHAT_KEY)

    def fail_post(*_args):
        raise AssertionError("an over-ratio chat run must not reach the router")

    with pytest.raises(LatencyGuardError, match="exceeds"):
        run_agent(
            chat_platform(),
            chat_payload(),
            fail_post,
            latency_guard=valid_guard(),
            http_get=lambda url, timeout_s: (200, prometheus_response(1.5)),
        )


def test_chat_failures_name_the_env_var_or_status_and_never_the_key(monkeypatch):
    monkeypatch.delenv("GPU_FILL_ROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GPU_FILL_ROUTER_API_KEY is empty"):
        run_agent(chat_platform(), chat_payload(), lambda *_args: (200, b"{}"))

    monkeypatch.setenv("GPU_FILL_ROUTER_API_KEY", CHAT_KEY)
    with pytest.raises(RuntimeError) as failure:
        run_agent(chat_platform(), chat_payload(), lambda *_args: (503, b"echoed body"))
    assert "HTTP 503" in str(failure.value)
    assert CHAT_KEY not in str(failure.value)


def test_slot_max_runs_defaults_match_medium_6_agent_long_context_1_studio_direct_2():
    roles = DEFAULTS["hatchet_docker_worker_roles"]
    assert {name: role["max_runs"] for name, role in roles.items()} == {
        "medium": 6,
        "agent-long-context": 1,
        "studio-direct": 2,
    }


def test_worker_config_template_renders_chat_platforms_that_load_cleanly(tmp_path):
    template = (ROOT / "roles/hatchet_docker/templates/gpu_fill_worker_config.json.j2").read_text()
    platforms = [
        {**platform, "base_url": "https://router.example.test/v1"}
        for platform in DEFAULTS["hatchet_docker_worker_chat_platforms"]
    ]
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "hatchet_docker_worker_roles": DEFAULTS["hatchet_docker_worker_roles"],
        "hatchet_docker_worker_platforms": platforms,
        "hatchet_docker_worker_latency_guard_enabled": False,
        "hatchet_docker_eval_enabled": False,
    }

    rendered = templar.template(trust_as_template(template))
    config = json.loads(rendered)

    assert config["platforms"]["pro6000-direct"] == {
        "kind": "chat",
        "base_url": "https://router.example.test/v1",
        "model": "pro6000-direct",
        "max_tokens": 1024,
        "auth_env": "GPU_FILL_ROUTER_API_KEY",
        "timeout_s": 300,
    }
    assert config["roles"] == DEFAULTS["hatchet_docker_worker_roles"]
    assert load_config(write_config(tmp_path, config)) == config
