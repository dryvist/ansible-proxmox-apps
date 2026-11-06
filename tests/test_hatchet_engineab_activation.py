"""Render opt-in deployment artifacts and exercise worker registration offline."""

import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/hatchet_docker"
WORKER = ROLE / "files/gpu_fill_worker"
sys.path.insert(0, str(WORKER))
from config import load_config  # noqa: E402
from engineab import tasks  # noqa: E402


@pytest.fixture
def variables():
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    values = {key: "test" if isinstance(value, str) and "{{" in value else value
              for key, value in defaults.items()}
    values.update({
        "hatchet_docker_worker_enabled": True,
        "hatchet_docker_worker_roles": {"medium": {"max_runs": 2}},
        "hatchet_docker_worker_platforms": [
            {"name": "agent", "run_url": "https://192.0.2.1/run", "auth_env": None, "timeout_s": 30}
        ],
        "hatchet_docker_worker_latency_guard_enabled": False,
        "hatchet_docker_worker_fill_enabled": False,
        "hatchet_docker_eval_enabled": False,
        "hatchet_docker_db_host": "192.0.2.2",
        "hatchet_docker_db_password": "test",
        "hatchet_docker_server_auth_cookie_secrets": "test",
        "hatchet_docker_server_encryption_master_keyset": "test",
        "hatchet_docker_server_encryption_jwt_private_keyset": "test",
        "hatchet_docker_server_encryption_jwt_public_keyset": "test",
        "hatchet_docker_admin_password": "test",
        "hostvars": defaultdict(lambda: {"hatchet_docker_worker_token_current": "test"}),
        "bao_apps_secrets": {},
    })
    return values


def render(name, variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(trust_as_template((ROLE / "templates" / name).read_text()))


def enable(variables):
    engines = {name: {"run_url": f"https://192.0.2.1/{name}", "auth_env": name.upper()}
               for name in ("dify", "langflow", "langgraph")}
    envs = [engine["auth_env"] for engine in engines.values()] + ["ENGINEAB_SLACK_BOT_TOKEN"]
    variables.update({
        "hatchet_docker_worker_engineab_enabled": True,
        "hatchet_docker_worker_engineab_repos": ["org/repo"],
        "hatchet_docker_worker_engineab_engines": engines,
        "hatchet_docker_worker_engineab_slack_channel": "C123",
        "hatchet_docker_worker_engineab_credentials": [
            {"name": env, "secret_key": env.lower()} for env in envs
        ],
        "bao_apps_secrets": {env.lower(): f"test-${env}" for env in envs},
    })
    return envs


@pytest.mark.parametrize("enabled", [False, True])
def test_templates_activate_only_when_enabled(variables, tmp_path, enabled):
    assert variables["hatchet_docker_worker_engineab_enabled"] is False
    envs = enable(variables) if enabled else []
    source = render("gpu_fill_worker_config.json.j2", variables)
    path = tmp_path / "worker.json"
    path.write_text(source)
    config = load_config(path)
    assert ("engineab" in config) is enabled
    assert "test-$" not in source
    if enabled:
        assert config["engineab"] == {
            "repos": ["org/repo"], "engines": variables["hatchet_docker_worker_engineab_engines"],
            "slack_channel": "C123", "slack_auth_env": "ENGINEAB_SLACK_BOT_TOKEN",
        }
    compose = yaml.safe_load(render("docker-compose.yml.j2", variables))
    worker = compose["services"]["hatchet-worker"]
    environment = worker["environment"]
    assert {key for key in environment if key in {"DIFY", "LANGFLOW", "LANGGRAPH", "ENGINEAB_SLACK_BOT_TOKEN"}} == set(envs)
    for env in envs:
        assert environment[env] == f"test-$${env}"
        assert all(env not in service["environment"] for name, service in compose["services"].items()
                   if name != "hatchet-worker")
    assert worker["command"][-1].endswith("python /app/gpu_fill_worker/worker.py")
    assert any(":/app/gpu_fill_worker:ro" in volume for volume in worker["volumes"])


def test_disabled_templates_do_not_resolve_engine_credentials(variables):
    enable(variables)
    variables["hatchet_docker_worker_engineab_enabled"] = False
    variables["bao_apps_secrets"] = {}
    assert "ENGINEAB_SLACK_BOT_TOKEN" not in render("docker-compose.yml.j2", variables)


def test_enabled_template_requires_credentials(variables):
    enable(variables)
    variables["bao_apps_secrets"] = {}
    with pytest.raises(Exception, match="required for engineab"):
        render("docker-compose.yml.j2", variables)


@pytest.mark.parametrize("enabled", [False, True])
def test_worker_registers_daily_task_and_adds_slot(variables, tmp_path, monkeypatch, enabled):
    if enabled:
        enable(variables)
    path = tmp_path / "worker.json"
    path.write_text(render("gpu_fill_worker_config.json.j2", variables))
    monkeypatch.setenv("GPU_FILL_WORKER_CONFIG", str(path))
    sdk = ModuleType("hatchet_sdk")
    sdk.Context = object
    sdk.NonRetryableException = type("NonRetryableException", (Exception,), {})
    sdk.Priority = SimpleNamespace(LOW=3)
    sdk.ConcurrencyExpression = lambda **kwargs: kwargs
    sdk.ConcurrencyLimitStrategy = SimpleNamespace(GROUP_ROUND_ROBIN=1)
    registered, workers, started = [], [], []

    class Hatchet:
        def task(self, **options):
            def decorate(fn):
                task = SimpleNamespace(fn=fn, options=options)
                registered.append(task)
                return task
            return decorate

        def worker(self, name, **options):
            workers.append(options)
            return SimpleNamespace(start=lambda: started.append(name))

    sdk.Hatchet = Hatchet
    monkeypatch.setitem(sys.modules, "hatchet_sdk", sdk)
    spec = importlib.util.spec_from_file_location("engineab_worker_test", WORKER / "worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    worker.main()
    assert started == ["gpu-fill-worker"]
    assert workers[0]["slots"] == 2 + int(enabled)
    assert workers[0]["workflows"] == registered
    daily = [task for task in registered if task.options["name"] == "engineab-pr-digest"]
    assert len(daily) == int(enabled)
    if enabled:
        task = daily[0]
        assert task.options["on_crons"] == ["29 7 * * *"]
        assert task.options["retries"] == 0
        assert task.options["default_priority"] == sdk.Priority.LOW
        assert task.options["execution_timeout"].total_seconds() == 1800
        calls = []
        monkeypatch.setattr(tasks, "run", lambda cfg: calls.append(cfg) or {"prs": 0})
        assert task.fn(None, None) == {"prs": 0}
        assert calls == [json.loads(path.read_text())["engineab"]]
