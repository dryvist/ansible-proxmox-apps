"""Run sanitized Hermes log samples through the rendered Cribl Eval expressions."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.hermes_cron_pipeline_samples import (  # noqa: E402
    BASE_OUTCOMES,
    FAILED_OUTCOMES,
    FAILED_SAMPLES,
    SAMPLES,
)

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_TEMPLATE = (
    ROOT / "roles/cribl_stream/templates/pipelines/hermes_cron_to_metrics/conf.yml.j2"
)

NODE_EVAL = r"""
const payload = JSON.parse(process.argv[1]);
const events = payload.samples.map(raw => {
  const event = {_raw: raw};
  for (const add of payload.evalAdds) {
    event[add.name] = Function('_raw', 'event', `with (event) { return (${add.value}); }`)(raw, event);
  }
  return event;
});
const dropped = Function('event', `with (event) { return (${payload.dropFilter}); }`);
const accepted = events.filter(event => !dropped(event));
const unique = [];
const seen = new Set();
for (const event of accepted) {
  const key = `${event.hermes_host}:${event.hermes_timestamp}:${event.hermes_message}`;
  if (seen.has(key)) continue;
  seen.add(key);
  unique.push(event);
}
"""

# The dedupe and second suppress run after the eval/drop stages, so they live in a
# second literal to keep this module under the per-file token budget.
NODE_TAIL = r"""
// Second suppress: one outcome per host, job and outcome inside its window.
const seenOutcomes = new Set();
const perRun = unique.filter(event => {
  if (event.hermes_metric_event !== 'outcome') return true;
  const key = `${event.hermes_host}:${event.job}:${event.outcome}`;
  if (seenOutcomes.has(key)) return false;
  seenOutcomes.add(key);
  return true;
});
console.log(JSON.stringify({
  events,
  unique: perRun.map(({agent, job, job_id, job_name, outcome, profile, hermes_metric_event}) =>
    ({agent, job, job_id, job_name, outcome, profile, hermes_metric_event}))
}));
"""


def _pipeline() -> dict:
    templar = Templar(loader=DataLoader())
    templar.available_variables = {
        "cribl_stream_hermes_cron_suppress_seconds": 600,
        "cribl_stream_hermes_cron_outcome_suppress_seconds": 30,
    }
    rendered = templar.template(trust_as_template(PIPELINE_TEMPLATE.read_text(encoding="utf-8")))
    return yaml.safe_load(rendered)


def test_pipeline_is_native_and_exports_only_the_contract_labels():
    pipeline = _pipeline()
    functions = pipeline["functions"]
    assert pipeline["output"] == "victoriametrics_rw"
    assert [function["id"] for function in functions] == [
        "eval",
        "eval",
        "eval",
        "drop",
        "suppress",
        "suppress",
        "publish_metrics",
        "publish_metrics",
        "publish_metrics",
    ]

    suppress = functions[4]["conf"]
    assert suppress["keyExpr"] == "`${hermes_host}:${hermes_timestamp}:${hermes_message}`"
    assert suppress["numAllowed"] == 1
    assert suppress["dropEvents"] is True
    per_run = functions[5]
    assert per_run["filter"] == "hermes_metric_event === 'outcome'"
    assert per_run["conf"]["keyExpr"] == "`${hermes_host}:${job}:${outcome}`"
    assert per_run["conf"]["numAllowed"] == 1
    assert per_run["conf"]["suppressPeriodSec"] == 30
    assert per_run["conf"]["dropEvents"] is True
    outcome = functions[6]
    assert outcome["filter"] == "hermes_metric_event === 'outcome'"
    assert outcome["conf"]["fields"] == [
        {"inFieldName": "hermes_info_value", "outFieldExpr": "'hermes_cron_run_outcome'", "metricType": "gauge"}
    ]
    assert outcome["conf"]["dimensions"] == ["agent", "job", "outcome"]
    assert "hermes_cron_runs_total" not in PIPELINE_TEMPLATE.read_text(encoding="utf-8")
    info = functions[7]["conf"]
    assert info["fields"] == [
        {"inFieldName": "hermes_info_value", "outFieldExpr": "'hermes_cron_job_info'", "metricType": "gauge"}
    ]
    assert info["dimensions"] == ["agent", "job_id", "job_name"]
    profile = functions[8]
    assert profile["filter"] == "hermes_metric_event === 'profile'"
    assert profile["conf"]["fields"] == [
        {"inFieldName": "hermes_info_value", "outFieldExpr": "'hermes_cron_job_profile'", "metricType": "gauge"}
    ]
    assert profile["conf"]["dimensions"] == ["agent", "job_id", "profile"]


def test_sanitized_hermes_lines_produce_contract_events_after_native_suppress():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to evaluate the exact rendered Cribl Eval expressions")

    pipeline = _pipeline()
    eval_adds = [
        add
        for function in pipeline["functions"]
        if function["id"] == "eval"
        for add in function["conf"]["add"]
    ]
    result = subprocess.run(
        [
            node,
            "-e",
            NODE_EVAL + NODE_TAIL,
            json.dumps({"evalAdds": eval_adds, "dropFilter": pipeline["functions"][3]["filter"], "samples": SAMPLES + FAILED_SAMPLES}),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(result.stdout)
    unique = output["unique"]
    outcomes = [event for event in unique if event["hermes_metric_event"] == "outcome"]
    starts = [event for event in unique if event["hermes_metric_event"] == "start"]
    profiles = [event for event in unique if event["hermes_metric_event"] == "profile"]
    profile_copies = [event for event in output["events"] if event["hermes_metric_event"] == "profile"]

    # All 19 expected outcomes live in the samples module so this assertion stays
    # inside the per-file token budget.
    assert Counter((event["agent"], event["job"], event["outcome"]) for event in outcomes) == BASE_OUTCOMES + FAILED_OUTCOMES
    assert len(outcomes) == 19
    assert len(starts) == 2
    assert {
        (event["agent"], event["job_id"], event["job_name"])
        for event in starts
    } == {
        ("hermes-example/root", "abcdef012345", "job-example"),
        ("hermes-example/unknown", "bcdef0123456", "health-example"),
    }
    assert Counter(event["hermes_source"] for event in profile_copies) == {
        "hermes-file": 2,
        "hermes-profile": 2,
    }
    assert Counter(event["job_id"] for event in profiles) == {
        "abcdef012345": 1,
        "bcdef0123456": 1,
    }
    assert {
        (event["agent"], event["job_id"], event["profile"])
        for event in profiles
    } == {
        ("hermes-example/root", "abcdef012345", "root"),
        ("hermes-example/profile-example", "bcdef0123456", "profile-example"),
    }
    assert all(event["hermes_info_value"] == 1 for event in profile_copies)

    ignored = [
        event
        for event in output["events"]
        if "completed successfully" in event["hermes_message"]
        or "session ended without a final assistant message" in event["hermes_message"]
        or "handed to restart-safe worker" in event["hermes_message"]
        or event["hermes_message"].startswith("Traceback")
        or event["hermes_message"].startswith("RuntimeError:")
    ]
    assert all(event["hermes_metric_event"] == "" for event in ignored)
    assert len(ignored) == 5


def test_every_template_key_expression_is_a_javascript_template_literal():
    """Cribl evaluates keyExpr as JavaScript, so a ${field} key needs backticks or the function fails to load."""
    pipelines = ROOT / "roles/cribl_stream/templates/pipelines"
    keys = [
        (path.parent.name, line.split("keyExpr:", 1)[1].strip().strip("\"'"))
        for path in pipelines.glob("*/conf.yml.j2")
        for line in path.read_text().splitlines()
        if "keyExpr:" in line and "${" in line
    ]
    assert keys
    for pipeline, key in keys:
        assert key.startswith("`") and key.endswith("`"), (pipeline, key)
