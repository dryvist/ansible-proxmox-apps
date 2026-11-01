"""Contracts for the Hatchet GPU fill worker's config and HTTP adapter."""

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKER_PACKAGE = ROOT / "roles/hatchet_docker/files/gpu_fill_worker"
sys.path.insert(0, str(WORKER_PACKAGE))
sys.dont_write_bytecode = True

from adapter import run_agent  # noqa: E402
from config import load_config  # noqa: E402


def valid_config():
    return {
        "roles": {"medium": {"max_runs": 3}},
        "platforms": {
            "hermes": {
                "run_url": "https://agents.example.invalid/run",
                "auth_env": "HERMES_TOKEN",
                "timeout_s": 120,
            }
        },
    }


def write_config(tmp_path, config):
    path = tmp_path / "worker.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_config_loads_expected_role_and_platform_shape(tmp_path):
    config = valid_config()

    assert load_config(write_config(tmp_path, config)) == config


@pytest.mark.parametrize(
    ("edit", "error"),
    [
        (lambda cfg: cfg["roles"]["medium"].update(max_runs=True), "positive integer"),
        (lambda cfg: cfg["platforms"]["hermes"].update(timeout_s=0), "positive integer"),
        (lambda cfg: cfg["platforms"]["hermes"].update(auth_env="bad-name"), "env var name"),
        (
            lambda cfg: cfg["platforms"]["hermes"].update(
                run_url="https://user:password@agents.example.invalid/run"
            ),
            "absolute HTTP(S) URL",
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
            "run_url": "https://agents.example.invalid/run",
            "auth_env": "HERMES_TOKEN",
            "timeout_s": 300,
        },
        payload,
        fake_http_post,
    )

    assert result == {"run_id": "run-123"}
    assert len(calls) == 1
    assert calls[0][0] == "https://agents.example.invalid/run"
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
            "run_url": "https://agents.example.invalid/run",
            "auth_env": None,
            "timeout_s": 30,
        },
        {"agent": "planner"},
        fake_http_post,
    )

    assert result == {"ok": True}
    assert json.loads(calls[0][1]) == {"agent": "planner"}
    assert "Authorization" not in calls[0][2]


def test_adapter_raises_for_non_success_status():
    def fake_http_post(url, body, headers, timeout_s):
        return 500, b"server error"

    with pytest.raises(RuntimeError, match="HTTP 500"):
        run_agent(
            {
                "run_url": "https://agents.example.invalid/run",
                "auth_env": None,
                "timeout_s": 30,
            },
            {"agent": "planner"},
            fake_http_post,
        )


def test_worker_uses_hatchet_limits_without_local_retry_or_queue_loops():
    source = (WORKER_PACKAGE / "worker.py").read_text(encoding="utf-8")
    syntax_tree = ast.parse(source)

    assert "time.sleep" not in source
    assert not any(isinstance(node, ast.While) for node in ast.walk(syntax_tree))
    assert not re.search(r"\bfor\s+(?:retry|attempt)\b", source)
    assert not re.search(r"\bqueue\b", source, re.IGNORECASE)
    assert "retries=1" in source


def test_compose_and_worker_config_templates_render_on_and_off():
    ansible_playbook = shutil.which("ansible-playbook")
    if ansible_playbook is None:
        pytest.skip("ansible-playbook is not installed")

    playbook = ROOT / "tests/hatchet_gpu_fill_worker/render_templates.yml"
    result = subprocess.run(
        [ansible_playbook, str(playbook), "-i", "localhost,", "-c", "local"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
