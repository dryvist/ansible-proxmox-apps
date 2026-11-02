"""Contracts for the Hatchet GPU fill worker's config and HTTP adapter."""

import ast
import base64
import json
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


def test_token_renewal_decision_renders_absent_far_and_near_expiry():
    decision = next(
        task for task in TOKEN_TASKS
        if task["name"] == "Decide whether the Hatchet worker token needs minting"
    )
    expression = decision["ansible.builtin.set_fact"]["hatchet_docker_worker_token_needs_mint"]
    padding = next(
        task
        for task in TOKEN_TASKS
        if task["name"] == "Pad the existing Hatchet token payload for base64 decoding"
    )
    decode = next(task for task in TOKEN_TASKS if task["name"] == "Decode the existing Hatchet token expiry")
    decode_expression = decode["ansible.builtin.set_fact"]["hatchet_docker_worker_token_exp"]
    padding_expression = padding["ansible.builtin.set_fact"]["hatchet_docker_worker_token_payload_padded"]
    renew_days = DEFAULTS["hatchet_docker_worker_token_renew_days"]

    def needs_mint(token):
        expiry = 0
        if len(token.split(".")) == 3:
            padded_payload = _render_task_expression(
                padding_expression,
                {"hatchet_docker_worker_token_payload_segment": token.split(".")[1]},
            )
            expiry = _render_task_expression(
                decode_expression,
                {"hatchet_docker_worker_token_payload_padded": padded_payload},
            )
        return _render_task_expression(
            expression,
            {
                "hatchet_docker_worker_token_current": token,
                "hatchet_docker_worker_token_renew_days": renew_days,
                "hatchet_docker_worker_token_exp": expiry,
            },
        )

    now = int(time.time())
    assert needs_mint("") is True
    assert needs_mint(_signed_token(now + (renew_days + 5) * 86400)) is False
    assert needs_mint(_signed_token(now + (renew_days - 5) * 86400)) is True


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


def test_token_publisher_is_opt_in_tagged_and_reuses_shared_kv_seed_role():
    main_tasks = yaml.safe_load((ROOT / "roles/hatchet_docker/tasks/main.yml").read_text())
    publish_include = next(task for task in main_tasks if "worker_token_publish.yml" in str(task))
    assert publish_include["when"] == "hatchet_docker_worker_token_publish | bool"
    assert "hatchet_worker_token" in publish_include["tags"]
    assert DEFAULTS["hatchet_docker_worker_token_publish"] is False
    site = (ROOT / "playbooks/site/03-notifications-and-core-apps.yml").read_text()
    assert "- hatchet_worker_token" in site

    gate = next(task for task in TOKEN_TASKS if "human-unlocked publisher token" in task["name"])
    assert gate["ansible.builtin.assert"]["that"] == ["lookup('env', 'BAO_TOKEN') | length > 0"]
    mint = next(task for task in TOKEN_TASKS if task["name"] == "Mint the Hatchet GPU fill worker token")
    assert mint["run_once"] is True
    assert mint["no_log"] is True
    assert mint["community.docker.docker_container"]["image"] == "{{ hatchet_docker_admin_image }}"
    assert mint["community.docker.docker_container"]["command"] == [
        "token",
        "create",
        "--tenant-id",
        "{{ hatchet_docker_tenant_id }}",
        "--name",
        "gpu-fill-worker",
        "--expiresIn",
        "{{ hatchet_docker_worker_token_expires_in }}",
    ]

    publisher = next(
        task
        for task in TOKEN_TASKS
        if task["name"] == "Publish the Hatchet worker token to the apps secret"
    )
    include = publisher["block"][0]
    assert include["ansible.builtin.include_role"]["name"] == "dryvist.homelab.openbao_secrets"
    assert include["ansible.builtin.include_role"]["tasks_from"] == "seed_generated.yml"
    assert include["vars"]["openbao_secrets_seed_path"] == "apps/hatchet/worker-token"
    assert include["vars"]["openbao_secrets_seed_check_capabilities"] is True
    assert include["vars"]["openbao_secrets_seed_token"] == "{{ lookup('env', 'BAO_TOKEN') }}"


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
