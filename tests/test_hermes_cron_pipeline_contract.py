"""Run sanitized Hermes log samples through the rendered Cribl Eval expressions."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_TEMPLATE = (
    ROOT / "roles/cribl_stream/templates/pipelines/hermes_cron_to_metrics/conf.yml.j2"
)

SAMPLES = [
    "<133>Nov 20 00:20:38 hermes-example hermes-file 2026-11-20 00:20:37,472 INFO cron.scheduler: Running job 'job-example' (ID: abcdef012345)",
    "<133>Nov 20 00:20:38 hermes-example hermes-profile 2026-11-20 00:20:37,472 INFO cron.scheduler: Running job 'job-example' (ID: abcdef012345)",
    "<133>Nov 20 00:01:39 hermes-example hermes-profile 2026-11-20 00:01:38,873 INFO cron.scheduler: Running job 'health-example' (ID: bcdef0123456)",
    "<133>Nov 20 00:01:40 hermes-example hermes-file 2026-11-20 00:01:38,900 INFO cron.scheduler: Job 'bcdef0123456': using task-scoped workdir /var/lib/hermes/.hermes/profiles/profile-example",
    "<133>Nov 20 00:01:40 hermes-example hermes-profile 2026-11-20 00:01:38,900 INFO cron.scheduler: Job 'bcdef0123456': using task-scoped workdir /var/lib/hermes/.hermes/profiles/profile-example",
    "<133>Nov 20 00:20:38 hermes-example hermes-file 2026-11-20 00:20:37,688 INFO cron.scheduler: Job 'abcdef012345': using task-scoped workdir /var/lib/hermes/.hermes",
    "<133>Nov 20 00:20:38 hermes-example hermes-profile 2026-11-20 00:20:37,688 INFO cron.scheduler: Job 'abcdef012345': using task-scoped workdir /var/lib/hermes/.hermes",
    "<133>Nov 20 00:22:42 hermes-example hermes-file 2026-11-20 00:22:42,053 INFO cron.scheduler: Job 'cdef01234567': delivered to slack:C0EXAMPLE via live adapter thread=- message_id=1234567890.000001",
    "<133>Nov 20 00:22:42 hermes-example hermes-file 2026-11-20 00:22:42,053 INFO cron.scheduler: Job 'cdef01234567': delivered to slack:C0EXAMPLE via live adapter thread=- message_id=1234567890.000001",
    "<133>Nov 20 00:30:42 hermes-example hermes-file 2026-11-20 00:30:42,695 INFO __main__: Job 'def012345678': agent returned [SILENT] — skipping delivery",
    "<133>Nov 20 00:30:39 hermes-example hermes-profile 2026-11-20 00:30:39,787 INFO __main__: Job 'ef0123456789' (no_agent): empty stdout — silent run",
    "<30>Nov 20 00:13:40 hermes-example hermes[123456]: 2026-11-20 00:13:40,222 WARNING cron.scheduler: Job 'f0123456789a': platform 'slack' not configured/enabled",
    "<133>Nov 20 00:13:40 hermes-example hermes-profile 2026-11-20 00:13:40,222 WARNING cron.scheduler: Job 'f0123456789a': platform 'slack' not configured/enabled",
    "<133>Nov 20 00:13:40 hermes-example hermes-profile 2026-11-20 00:13:40,222 WARNING cron.scheduler: Job 'f0123456789a': platform 'slack' not configured/enabled",
    "<30>Nov 20 00:20:38 hermes-example hermes[123456]: 2026-11-20 00:20:37,688 ERROR cron.scheduler: Job 'job-example' failed: TypeError: helper() missing 1 required positional argument: 'job_name'",
    "<133>Nov 20 00:20:38 hermes-example hermes-file 2026-11-20 00:20:37,688 ERROR cron.scheduler: Job 'job-example' failed: TypeError: helper() missing 1 required positional argument: 'job_name'",
    "<133>Nov 20 00:20:38 hermes-example hermes-file 2026-11-20 00:20:37,689 INFO cron.scheduler: Job 'job-example' completed successfully",
    "<133>Nov 20 00:20:38 hermes-example hermes-file 2026-11-20 00:20:37,690 ERROR cron.scheduler: Job 'job-example' session ended without a final assistant message (lifecycle=empty) — booking run as cron_incomplete_no_delivery",
    "<133>Nov 20 00:20:38 hermes-example hermes-file 2026-11-20 00:20:37,691 INFO cron.scheduler: Cron job 'job-example' handed to restart-safe worker pid=1234 execution=abcdef012345 dispatch=scoped",
    "<133>Nov 20 00:20:38 hermes-example hermes-file 2026-11-20 00:20:37,692 ERROR cron.scheduler: Traceback (most recent call last):",
    "<133>Nov 20 00:20:38 hermes-example hermes-file 2026-11-20 00:20:37,693 ERROR __main__: RuntimeError: TypeError: timeout configuration failed",
]

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
console.log(JSON.stringify({
  events,
  unique: unique.map(({agent, job, job_id, job_name, outcome, profile, hermes_metric_event}) =>
    ({agent, job, job_id, job_name, outcome, profile, hermes_metric_event}))
}));
"""


def _pipeline() -> dict:
    templar = Templar(loader=DataLoader())
    templar.available_variables = {"cribl_stream_hermes_cron_suppress_seconds": 600}
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
        "aggregation",
        "publish_metrics",
        "publish_metrics",
        "publish_metrics",
    ]

    suppress = functions[4]["conf"]
    assert suppress["keyExpr"] == "${hermes_host}:${hermes_timestamp}:${hermes_message}"
    assert suppress["numAllowed"] == 1
    assert suppress["dropEvents"] is True
    assert functions[5]["conf"]["groupByFields"] == ["agent", "job", "outcome", "hermes_metric_event"]
    assert functions[5]["filter"] == "hermes_metric_event === 'outcome'"
    counter = functions[6]["conf"]
    assert counter["metrics"] == [
        {"field": "value", "metricName": "'hermes_cron_runs_total'", "type": "counter"}
    ]
    assert counter["dimensions"] == ["agent", "job", "outcome"]
    info = functions[7]["conf"]
    assert info["metrics"] == [
        {"field": "hermes_info_value", "metricName": "'hermes_cron_job_info'", "type": "gauge"}
    ]
    assert info["dimensions"] == ["agent", "job_id", "job_name"]
    profile = functions[8]
    assert profile["filter"] == "hermes_metric_event === 'profile'"
    assert profile["conf"]["metrics"] == [
        {"field": "hermes_info_value", "metricName": "'hermes_cron_job_profile'", "type": "gauge"}
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
            NODE_EVAL,
            json.dumps({"evalAdds": eval_adds, "dropFilter": pipeline["functions"][3]["filter"], "samples": SAMPLES}),
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

    assert Counter((event["agent"], event["job"], event["outcome"]) for event in outcomes) == {
        ("hermes-example/root", "cdef01234567", "delivered"): 1,
        ("hermes-example/root", "def012345678", "silent"): 1,
        ("hermes-example/unknown", "ef0123456789", "silent"): 1,
        ("hermes-example/unknown", "f0123456789a", "undeliverable"): 1,
        ("hermes-example/root", "job-example", "failed"): 1,
    }
    assert len(outcomes) == 5
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
