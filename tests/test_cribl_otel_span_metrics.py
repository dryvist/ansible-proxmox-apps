"""Render the native metrics leg and execute its filters/Eval expressions only.

Cribl's Aggregations engine and remote-write histogram encoding need live proof.
"""
import json
import subprocess

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from test_cribl_internal_metrics_to_victoriametrics import _render_inputs
from test_cribl_litellm_trace_contract import ROLE, render


PIPELINE = "otel_traces_to_metrics"
BUCKETS = "[0.05,0.1,0.25,0.5,1,2.5,5,10,30,60,120]"
NODE = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const event = input.event;
const context = vm.createContext({__e: event, ...event});
for (const step of input.pipeline.functions) {
  if (step.id === 'aggregation') break;
  if (!vm.runInContext(step.filter, context)) continue;
  if (step.id === 'drop') {
    process.stdout.write('null');
    process.exit(0);
  }
  if (step.id !== 'eval') throw new Error('Unexpected native function');
  for (const entry of step.conf.add) {
    const value = vm.runInContext(entry.value, context);
    event[entry.name] = context[entry.name] = value;
  }
}
process.stdout.write(JSON.stringify(event));
"""


def evaluate(event):
    result = subprocess.run(
        ["node", "-e", NODE],
        input=json.dumps({"pipeline": render(PIPELINE), "event": event}),
        text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


def span(**overrides):
    event = {
        "__otlp": {"type": "traces"},
        "attributes": {
            "service.name": "router",
            "gen_ai.request.model": "fixture-model",
            "gen_ai.system": "fixture-provider",
            "gen_ai.usage.input_tokens": 0,
            "gen_ai.usage.output_tokens": 9,
            "user.id": "excluded-user",
        },
        "startTimeUnixNano": "1793923200000000001",
        "endTimeUnixNano": "1793923200050000001",
        "traceId": "1" * 32,
        "status": {"code": 2},
    }
    event.update(overrides)
    return event


@pytest.mark.parametrize("namespace", ["", "fixture-namespace"])
def test_original_input_fans_to_metrics_before_unchanged_trace_legs(namespace):
    source = _render_inputs(namespace)["inputs"]["open_telemetry:in_otel"]
    splunk = "splunk_hec_" if namespace else "splunk_hec"
    assert source["extractSpans"] is True
    assert source["sendToRoutes"] is False
    assert source["pipeline"] == "ansi_csi_strip"
    assert source["connections"] == [
        {"output": "victoriametrics_rw", "pipeline": PIPELINE},
        {"output": "langfuse_otlp", "pipeline": "otel_traces"},
        {"output": "phoenix_otlp", "pipeline": "otel_traces_phoenix"},
        {"output": splunk + ("otel_traces" if namespace else ""),
         "pipeline": "otel_traces_to_splunk"},
        {"output": splunk + ("ai_usage" if namespace else ""), "pipeline": "otel_logs"},
        {"output": splunk + ("llm" if namespace else ""), "pipeline": "otel_metrics_to_splunk"},
        {"output": "victoriametrics_otlp", "pipeline": "otel_metrics_to_victoriametrics"},
    ]


def test_registered_native_aggregation_contract():
    defaults = yaml.safe_load((ROLE / "defaults/main/00-install.yml").read_text())
    assert defaults["cribl_stream_pipelines"].count(PIPELINE) == 1
    pipeline = render(PIPELINE)
    assert pipeline["output"] == "victoriametrics_rw"
    assert [step["id"] for step in pipeline["functions"]] == ["drop", "drop", "eval", "aggregation"]
    aggregation = pipeline["functions"][-1]["conf"]
    assert aggregation == {
        "metricsMode": True, "cumulative": True, "flushOnInputClose": False,
        "timeWindow": "10s", "groupbys": ["service_name", "model", "system", "status"],
        "aggregations": [
            "count().as(llm_span_calls)",
            "count().where(status === 'error').as(llm_span_errors)",
            "sum(input_tokens).where(Number.isFinite(input_tokens)).as(llm_span_input_tokens)",
            "sum(output_tokens).where(Number.isFinite(output_tokens)).as(llm_span_output_tokens)",
            f"histogram(duration_seconds, {BUCKETS}) "
            ".where(Number.isFinite(duration_seconds) && duration_seconds >= 0).as(llm_span_duration_seconds)",
        ],
    }


def test_ansible_render_assertions_evaluate_without_local_rpc():
    tasks = yaml.safe_load((ROLE.parents[1] / "tests/template_render/verify/cribl_stream/"
                            "assertions_span_metrics.yml").read_text())
    variables = {
        "_cribl_stream_span_metrics": render(PIPELINE),
        "_cribl_stream_inputs": yaml.safe_dump(_render_inputs()),
        "_cribl_stream_inputs_per_index": yaml.safe_dump(_render_inputs("fixture")),
        "_cribl_stream_defaults": yaml.safe_load((ROLE / "defaults/main/00-install.yml").read_text()),
    }
    for task in tasks[1:]:
        templar = Templar(loader=DataLoader(), variables={
            **variables, **{key: trust_as_template(value) if isinstance(value, str) else value
                            for key, value in task["vars"].items()},
        })
        for expression in task["ansible.builtin.assert"]["that"]:
            assert templar.evaluate_expression(trust_as_template(expression)), expression


@pytest.mark.parametrize("event", [
    {}, {"__otlp": {"type": "metrics"}}, {"__otlp": {"type": "logs"}},
    span(attributes={}), span(attributes={"http.method": "POST"}),
    span(attributes={"other_gen_ai.request.model": "fixture"}),
])
def test_only_genai_trace_spans_reach_aggregation(event):
    assert evaluate(event) is None


@pytest.mark.parametrize("snake_case", [False, True])
def test_flat_fields_and_exact_duration_preserve_zero_usage(snake_case):
    event = span()
    if snake_case:
        event["start_time_unix_nano"] = event.pop("startTimeUnixNano")
        event["end_time_unix_nano"] = event.pop("endTimeUnixNano")
    actual = evaluate(event)
    assert {key: actual[key] for key in (
        "service_name", "model", "system", "status", "input_tokens", "output_tokens", "duration_seconds"
    )} == {
        "service_name": "router", "model": "fixture-model", "system": "fixture-provider",
        "status": "error", "input_tokens": 0, "output_tokens": 9, "duration_seconds": 0.05,
    }
    assert actual["traceId"] == event["traceId"]
    assert actual["attributes"] == event["attributes"]


@pytest.mark.parametrize("code,expected", [
    (0, "unset"), (1, "ok"), (2, "error"), ("ERROR", "error"),
    ("STATUS_CODE_ERROR", "error"), ("OK", "ok"), ("STATUS_CODE_OK", "ok"),
])
def test_status_is_bounded_and_detects_otel_errors(code, expected):
    assert evaluate(span(status={"code": code}))["status"] == expected


def test_missing_measurements_are_not_invented_and_calls_still_count():
    event = span(attributes={"gen_ai.operation.name": "chat"}, status={})
    del event["endTimeUnixNano"]
    actual = evaluate(event)
    assert actual is not None
    assert actual["status"] == "unset"
    for key in ("input_tokens", "output_tokens", "duration_seconds", "service_name", "model", "system"):
        assert key not in actual


@pytest.mark.parametrize("value", [None, "", -1, "invalid", False])
def test_invalid_usage_is_absent(value):
    actual = evaluate(span(attributes={"gen_ai.usage.input_tokens": value}))
    assert "input_tokens" not in actual


def test_string_usage_is_numeric():
    actual = evaluate(span(attributes={"gen_ai.usage.input_tokens": "12"}))
    assert actual["input_tokens"] == 12


@pytest.mark.parametrize("value", [None, "", "invalid", -1])
def test_invalid_timestamps_do_not_invent_latency(value):
    actual = evaluate(span(endTimeUnixNano=value))
    assert actual is not None
    assert "duration_seconds" not in actual
