from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "roles" / "cribl_stream" / "tasks" / "main.yml"


def _task_named(name: str):
    tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    return next(task for task in tasks if task.get("name") == name)


def test_output_reconcile_when_victoriametrics_destination_is_missing() -> None:
    facts = _task_named("Extract live Splunk HEC output settings")[
        "ansible.builtin.set_fact"
    ]
    guard = _task_named("Deploy Cribl Stream outputs configuration")["when"][1]

    assert "cribl_stream_victoriametrics_live" in facts
    assert "'victoriametrics_rw' not in cribl_stream_outputs_live_ids" in guard


def test_output_reconcile_when_victoriametrics_destination_url_drifts() -> None:
    guard = _task_named("Deploy Cribl Stream outputs configuration")["when"][1]

    assert "cribl_stream_victoriametrics_live.get('url', '')" in guard
    assert "cribl_stream_victoriametrics_rw_url" in guard


def test_validation_requires_live_victoriametrics_output() -> None:
    validation = (
        ROOT / "playbooks" / "validate-pipeline" / "cribl_stream.yml"
    ).read_text(encoding="utf-8")

    assert "Read live Cribl Stream outputs configuration" in validation
    assert "Assert VictoriaMetrics remote-write output is configured" in validation
    assert "cribl_stream_victoriametrics_rw_url" in validation
