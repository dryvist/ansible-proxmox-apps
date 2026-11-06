"""Contracts for the Hatchet GPU fill worker's config and HTTP adapter."""

import ast
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
WORKER_PACKAGE = ROOT / "roles/hatchet_docker/files/gpu_fill_worker"
sys.path.insert(0, str(WORKER_PACKAGE))
sys.dont_write_bytecode = True

from adapter import run_agent  # noqa: E402
from adapter import LatencyGuardError  # noqa: E402
from config import load_config  # noqa: E402

DEFAULTS = yaml.safe_load((ROOT / "roles/hatchet_docker/defaults/main.yml").read_text())
TOKEN_TASKS = yaml.safe_load((ROOT / "roles/hatchet_docker/tasks/worker_token_publish.yml").read_text())
TOKEN_READ_TASKS = yaml.safe_load((ROOT / "roles/hatchet_docker/tasks/worker_token_read.yml").read_text())


def valid_guard():
    return {
        "prometheus_url": "http://192.0.2.10:9090",
        "query": "sum(rate(requests_total[5m]))",
        "max_ratio": 1.2,
    }


def valid_config():
    return {
        "roles": {"medium": {"max_runs": 3}},
        "platforms": {
            "hermes": {
                "run_url": "https://192.0.2.11/run",
                "auth_env": "HERMES_TOKEN",
                "timeout_s": 120,
            }
        },
        "latency_guard": valid_guard(),
    }


def write_config(tmp_path, config):
    path = tmp_path / "worker.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_config_loads_expected_role_and_platform_shape(tmp_path):
    config = valid_config()

    assert load_config(write_config(tmp_path, config)) == config


def test_config_allows_omitting_the_optional_latency_guard(tmp_path):
    config = valid_config()
    config.pop("latency_guard")

    assert load_config(write_config(tmp_path, config)) == config


@pytest.mark.parametrize(
    ("edit", "error"),
    [
        (lambda cfg: cfg["roles"]["medium"].update(max_runs=True), "positive integer"),
        (lambda cfg: cfg["platforms"]["hermes"].update(timeout_s=0), "positive integer"),
        (lambda cfg: cfg["platforms"]["hermes"].update(auth_env="bad-name"), "env var name"),
        (
            lambda cfg: cfg["platforms"]["hermes"].update(
                run_url="https://user:password@192.0.2.11/run"
            ),
            "absolute HTTP(S) URL",
        ),
        (
            lambda cfg: cfg["latency_guard"].update(prometheus_url="/api/v1/query"),
            "latency_guard prometheus_url",
        ),
        (
            lambda cfg: cfg["latency_guard"].update(query=" "),
            "latency_guard query",
        ),
        (
            lambda cfg: cfg["latency_guard"].update(max_ratio=float("nan")),
            "finite positive number",
        ),
    ],
)
def test_config_rejects_invalid_fields(tmp_path, edit, error):
    config = valid_config()
    edit(config)

    with pytest.raises(ValueError, match=re.escape(error)):
        load_config(write_config(tmp_path, config))


def test_adapter_posts_payload_and_bearer_token(monkeypatch):
    monkeypatch.setenv("HERMES_TOKEN", "test-only-token")
    payload = {"agent": "reviewer", "payload": {"prompt": "review this"}}
    calls = []

    def fake_http_post(url, body, headers, timeout_s):
        calls.append((url, body, headers, timeout_s))
        return 201, b'{"run_id":"run-123"}'

    result = run_agent(
        {
            "run_url": "https://192.0.2.11/run",
            "auth_env": "HERMES_TOKEN",
            "timeout_s": 300,
        },
        payload,
        fake_http_post,
    )

    assert result == {"run_id": "run-123"}
    assert len(calls) == 1
    assert calls[0][0] == "https://192.0.2.11/run"
    assert json.loads(calls[0][1]) == payload
    assert calls[0][2] == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": "Bearer test-only-token",
    }
    assert calls[0][3] == 300


def test_adapter_omits_bearer_header_without_auth_env(monkeypatch):
    monkeypatch.delenv("UNUSED_PLATFORM_TOKEN", raising=False)
    calls = []

    def fake_http_post(url, body, headers, timeout_s):
        calls.append((url, body, headers, timeout_s))
        return 200, b'{"ok":true}'

    result = run_agent(
        {
            "run_url": "https://192.0.2.11/run",
            "auth_env": None,
            "timeout_s": 30,
        },
        {"agent": "planner"},
        fake_http_post,
    )

    assert result == {"ok": True}
    assert json.loads(calls[0][1]) == {"agent": "planner"}
    assert "Authorization" not in calls[0][2]


def test_noop_platform_loads_and_completes_without_http_or_guard(tmp_path):
    config = valid_config()
    config["platforms"]["noop"] = {"run_url": None, "auth_env": None, "timeout_s": 30}
    assert load_config(write_config(tmp_path, config)) == config

    def fail(*_args):
        raise AssertionError("a noop platform must not make HTTP calls")

    result = run_agent(
        config["platforms"]["noop"],
        {"agent": "planner"},
        fail,
        latency_guard={"prometheus_url": "unused-by-noop", "query": "q", "max_ratio": 1.2},
        http_get=fail,
    )

    assert result == {"noop": True, "agent": "planner"}


def test_adapter_raises_for_non_success_status():
    def fake_http_post(url, body, headers, timeout_s):
        return 500, b"server error"

    with pytest.raises(RuntimeError, match="HTTP 500"):
        run_agent(
            {
                "run_url": "https://192.0.2.11/run",
                "auth_env": None,
                "timeout_s": 30,
            },
            {"agent": "planner"},
            fake_http_post,
        )


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


def test_latency_guard_passes_and_posts_after_one_instant_query():
    get_calls = []
    post_calls = []

    def fake_http_get(url, timeout_s):
        get_calls.append((url, timeout_s))
        return 200, prometheus_response(1.0)

    def fake_http_post(url, body, headers, timeout_s):
        post_calls.append(url)
        return 200, b'{"ok":true}'

    result = run_agent(
        {"run_url": "https://192.0.2.11/run", "auth_env": None, "timeout_s": 30},
        {"agent": "planner"},
        http_post=fake_http_post,
        latency_guard=valid_guard(),
        http_get=fake_http_get,
    )

    assert result == {"ok": True}
    assert len(get_calls) == 1
    assert get_calls[0][0].startswith("http://192.0.2.10:9090/api/v1/query?")
    assert len(post_calls) == 1


def test_latency_guard_blocks_regressed_interactive_latency_before_post():
    post_calls = []

    with pytest.raises(LatencyGuardError, match="exceeds"):
        run_agent(
            {"run_url": "https://192.0.2.11/run", "auth_env": None, "timeout_s": 30},
            {"agent": "planner"},
            http_post=lambda *args: post_calls.append(args),
            latency_guard=valid_guard(),
            http_get=lambda *_: (200, prometheus_response(1.5)),
        )

    assert post_calls == []


def test_latency_guard_allows_nan_when_no_interactive_traffic_exists():
    post_calls = []
    result = run_agent(
        {"run_url": "https://192.0.2.11/run", "auth_env": None, "timeout_s": 30},
        {"agent": "planner"},
        http_post=lambda *args: (post_calls.append(args) or (200, b'{"ok":true}')),
        latency_guard=valid_guard(),
        http_get=lambda *_: (200, prometheus_response("NaN")),
    )

    assert result == {"ok": True}
    assert len(post_calls) == 1


def test_latency_guard_query_error_fails_closed_before_post():
    post_calls = []

    with pytest.raises(LatencyGuardError, match="query failed"):
        run_agent(
            {"run_url": "https://192.0.2.11/run", "auth_env": None, "timeout_s": 30},
            {"agent": "planner"},
            http_post=lambda *args: post_calls.append(args),
            latency_guard=valid_guard(),
            http_get=lambda *_: (503, b"unavailable"),
        )

    assert post_calls == []


def test_worker_uses_hatchet_limits_without_local_retry_or_queue_loops():
    package_sources = [path.read_text(encoding="utf-8") for path in WORKER_PACKAGE.glob("*.py")]
    source = "\n".join(package_sources)
    syntax_trees = [ast.parse(source_text) for source_text in package_sources]

    assert "time.sleep" not in source
    assert not any(
        isinstance(node, ast.While)
        for syntax_tree in syntax_trees
        for node in ast.walk(syntax_tree)
    )
    assert not re.search(r"\bfor\s+(?:retry|attempt)\b", source)
    assert not re.search(r"\bqueue\b", source, re.IGNORECASE)
    assert len((WORKER_PACKAGE / "worker.py").read_text().splitlines()) < 120
    assert "default_priority=Priority.LOW" in source
    assert "retries=6" in source
    assert "backoff_factor=2.0" in source
    assert "backoff_max_seconds=300" in source
    # Only a latency hold retries; any other failure must not re-run an agent.
    assert "except LatencyGuardError:" in source
    assert "raise NonRetryableException(" in source


def _render_task_expression(expression, variables):
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(expression))


def _signed_token(exp):
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def test_default_latency_query_joins_the_interactive_aliases():
    query = DEFAULTS["hatchet_docker_worker_latency_guard_query"]
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "hatchet_docker_worker_interactive_key_aliases": DEFAULTS[
            "hatchet_docker_worker_interactive_key_aliases"
        ]
    }

    rendered = templar.template(trust_as_template(query))

    assert 'api_key_alias=~"hermes-default|litellm-local-workstation"' in rendered
    assert "[30m]" in rendered
    assert "[7d] offset 1d" in rendered


def test_compose_and_worker_config_templates_render_on_and_off():
    ansible_playbook = shutil.which("ansible-playbook")
    if ansible_playbook is None:
        pytest.skip("ansible-playbook is not installed")

    for name in ("render_templates.yml", "render_fill_templates.yml"):
        env = os.environ.copy()
        env["SLACK_WEBHOOK_URL"] = "render-slack-webhook-placeholder"
        result = subprocess.run(
            [
                ansible_playbook,
                str(ROOT / "tests/hatchet_gpu_fill_worker" / name),
                "-i",
                "localhost,",
                "-c",
                "local",
                "--extra-vars",
                '{"hatchet_docker_worker_token_current":"render-worker-token-placeholder"}',
            ],
            capture_output=True,
            check=False,
            text=True,
            env=env,
        )
        assert result.returncode == 0, f"{name}\n{result.stdout}\n{result.stderr}"
