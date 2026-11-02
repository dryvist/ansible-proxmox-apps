"""The Hatchet one-shot report prints only an exit code and a masked output tail."""

from __future__ import annotations

from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROLE = Path(__file__).resolve().parent.parent / "roles/hatchet_docker"
REPORT = yaml.safe_load((ROLE / "tasks/oneshot_report.yml").read_text(encoding="utf-8"))
MAIN = yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))


def _tail(result):
    task_vars = REPORT[0]["vars"]
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "hatchet_docker_oneshot_result": result,
        "hatchet_docker_oneshot_output": trust_as_template(task_vars["hatchet_docker_oneshot_output"]),
    }
    return templar.template(trust_as_template(task_vars["hatchet_docker_oneshot_tail"]))


def test_failed_output_masks_url_credentials_and_secret_assignments():
    tail = _tail({
        "status": 1,
        "msg": "\n".join([
            "dial postgres://hatchet:hunter2@db.example.test:5432/hatchet failed",
            "ADMIN_PASSWORD=hunter2 SERVER_AUTH_COOKIE_SECRETS=abc token=xyz secret=s3",
            "migration 42 failed",
        ]),
    })
    joined = "\n".join(tail)
    for secret in ("hunter2", "abc", "xyz", "s3"):
        assert secret not in joined
    assert "postgres://****@db.example.test:5432/hatchet" in joined
    assert "ADMIN_PASSWORD=****" in joined
    assert "SERVER_AUTH_COOKIE_SECRETS=****" in joined
    assert tail[-1] == "migration 42 failed"


def test_success_output_comes_from_the_container_and_keeps_the_last_20_lines():
    lines = [f"line {index}" for index in range(30)]
    tail = _tail({"status": 0, "container": {"Output": "\n".join(lines)}})
    assert tail == lines[-20:]


def test_report_prints_and_fails_on_non_zero_exit():
    assert REPORT[0]["no_log"] is False
    assert "hatchet_docker_oneshot_result.status" in REPORT[1]["when"]


def test_both_one_shot_containers_register_and_report():
    names = [task["name"] for task in MAIN]
    for container, label in (("Migrate Hatchet PostgreSQL schema", "migrate"),
                             ("Seed Hatchet database with shared credentials", "seed")):
        task = MAIN[names.index(container)]
        report = MAIN[names.index(container) + 1]
        assert task["no_log"] is True
        assert task["failed_when"] is False
        assert task["register"] == f"hatchet_docker_{label}_result"
        assert report["ansible.builtin.include_tasks"] == "oneshot_report.yml"
        assert report["vars"]["hatchet_docker_oneshot_result"] == f"{{{{ hatchet_docker_{label}_result }}}}"


def test_failed_compose_deploy_reports_the_masked_engine_log_tail():
    deploy = next(task for task in MAIN if task["name"] == "Deploy Hatchet and report the engine log tail on failure")
    assert deploy["block"][0]["no_log"] is True
    read_logs, report = deploy["rescue"]
    assert read_logs["no_log"] is True
    assert read_logs["failed_when"] is False
    assert "logs" in read_logs["ansible.builtin.command"]["cmd"]
    assert "hatchet-engine" in read_logs["ansible.builtin.command"]["cmd"]
    assert report["ansible.builtin.include_tasks"] == "oneshot_report.yml"
    assert report["vars"]["hatchet_docker_oneshot_result"]["status"] == 1
    tail = _tail({"status": 1, "msg": "dial postgres://hatchet:hunter2@db.example.test/hatchet: refused\n"})
    assert "hunter2" not in "\n".join(tail)
