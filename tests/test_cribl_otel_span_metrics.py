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
from test_cribl_otel_collector import context, outputs


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
    context.value = value;
    vm.runInContext('__e.' + entry.name + ' = value', context);
    Object.assign(context, event);
  }
}
process.stdout.write(JSON.stringify(event));
"""
FILTER_NODE = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const context = vm.createContext({__e: input.event, ...input.event});
process.stdout.write(JSON.stringify(vm.runInContext(input.filter, context)));
"""


def evaluate(event):
    result = subprocess.run(
        ["node", "-e", NODE],
        input=json.dumps({"pipeline": render(PIPELINE), "event": event}),
        text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


def filter_matches(event, predicate):
    result = subprocess.run(
        ["node", "-e", FILTER_NODE],
        input=json.dumps({
            "event": event, "filter": predicate,
        }),
        text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout)


def aggregation_filter(metric):
    return next(
        step["filter"]
        for step in render(PIPELINE)["functions"]
        if step["id"] == "aggregation"
        and any(f".as({metric})" in expression for expression in step["conf"]["aggregations"])
    )


def agent_run_aggregation_accepts(event):
    return filter_matches(event, aggregation_filter("agent_runs"))


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
    source = _render_inputs(namespace, cribl_stream_arize_enabled=True)["inputs"]["open_telemetry:in_otel"]
    splunk = "splunk_hec_" if namespace else "splunk_hec"
    assert source["extractSpans"] is True
    assert source["sendToRoutes"] is False
    assert source["pipeline"] == "ansi_csi_strip"
    assert source["connections"] == [
        {"output": "victoriametrics_rw", "pipeline": PIPELINE},
        {"output": "langfuse_otlp", "pipeline": "otel_traces"},
        {"output": "phoenix_otlp", "pipeline": "otel_traces_phoenix"},
        {"output": "arize_otlp", "pipeline": "otel_traces_arize"},
        {"output": splunk + ("otel_traces" if namespace else ""),
         "pipeline": "otel_traces_to_splunk"},
        {"output": splunk + ("ai_usage" if namespace else ""), "pipeline": "otel_logs"},
        {"output": splunk + ("llm" if namespace else ""), "pipeline": "otel_metrics_to_splunk"},
        {"output": "victoriametrics_otlp", "pipeline": "otel_metrics_to_victoriametrics"},
    ]


def test_registered_native_aggregation_contract():
    defaults = yaml.safe_load((ROLE / "defaults/main/00-install.yml").read_text())
    assert defaults["cribl_stream_base_pipelines"].count(PIPELINE) == 1
    pipeline = render(PIPELINE)
    assert pipeline["output"] == "victoriametrics_rw"
    assert [step["id"] for step in pipeline["functions"]] == [
        "eval", "drop", "drop", "eval", "eval", "eval", "aggregation", "aggregation", "drop",
    ]
    assert [entry["name"] for entry in pipeline["functions"][0]["conf"]["add"]] == [
        "agent_tag_present", "is_root_span",
    ]
    assert pipeline["functions"][2]["filter"] == (
        "!/(^|,)gen_ai\\./.test(Object.keys(__e.attributes || {}).join(',')) && "
        "!(agent_tag_present === true && is_root_span === true)"
    )
    aggregation = pipeline["functions"][6]["conf"]
    assert pipeline["functions"][6]["filter"] == (
        "__e.__otlp && __e.__otlp.type === 'traces' && "
        "/(^|,)gen_ai\\./.test(Object.keys(__e.attributes || {}).join(','))"
    )
    assert aggregation == {
        "passthrough": True, "preserveGroupBys": True, "metricsMode": True,
        "cumulative": False, "flushOnInputClose": False, "timeWindow": "10s", "groupbys": [
            "service_name", "agent", "tier", "privacy_class", "model", "accelerator",
            "system", "status",
        ],
        "aggregations": [
            "count().as(llm_span_calls)",
            "count().where(status === 'error').as(llm_span_errors)",
            "sum(input_tokens).where(Number.isFinite(input_tokens)).as(llm_span_input_tokens)",
            "sum(output_tokens).where(Number.isFinite(output_tokens)).as(llm_span_output_tokens)",
            f"histogram(duration_seconds, {BUCKETS}) "
            ".where(Number.isFinite(duration_seconds) && duration_seconds >= 0).as(llm_span_duration_seconds)",
        ],
    }
    run_aggregation = pipeline["functions"][7]
    assert run_aggregation["filter"] == (
        "__e.__otlp && __e.__otlp.type === 'traces' && "
        "agent_tag_present === true && is_root_span === true"
    )
    assert run_aggregation["conf"] == {
        "passthrough": False, "preserveGroupBys": True, "metricsMode": True,
        "cumulative": False, "flushOnInputClose": False, "timeWindow": "10s",
        "groupbys": ["agent", "tier", "status"],
        "aggregations": ["count().as(agent_runs)"],
    }
    assert pipeline["functions"][8]["filter"] == "__e.__otlp && __e.__otlp.type === 'traces'"


def test_remote_write_has_no_label_filter_or_post_processing_pipeline():
    pipeline = render(PIPELINE)
    assert [step['id'] for step in pipeline['functions'][-3:]] == [
        'aggregation', 'aggregation', 'drop',
    ]
    output = outputs(context())['outputs'][pipeline['output']]
    assert output['type'] == 'prometheus'
    # Only transport settings: no destination pipeline or dimension transforms.
    assert set(output) == {
        'id', 'type', 'disabled', 'url', 'concurrency', 'maxPayloadSizeKB',
        'maxPayloadEvents', 'rejectUnauthorized', 'timeoutSec', 'flushPeriodSec',
        'useRoundRobinDns', 'failedRequestLoggingMode', 'safeHeaders', 'onBackpressure',
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
    variables["cribl_stream_base_pipelines"] = variables["_cribl_stream_defaults"]["cribl_stream_base_pipelines"]
    variables["cribl_stream_otel_collector_enabled"] = False
    variables['cribl_stream_role_dir'] = str(ROLE)
    for path in (ROLE / 'defaults/main').glob('4[01]-*.yml'):
        variables.update(yaml.safe_load(path.read_text()))
    variables['cribl_stream_otel_run_tags'] = trust_as_template(variables['cribl_stream_otel_run_tags'])
    variables["_cribl_stream_defaults"]["cribl_stream_pipelines"] = trust_as_template(
        variables["_cribl_stream_defaults"]["cribl_stream_pipelines"])
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
def test_non_genai_untagged_spans_are_dropped_before_aggregation(event):
    assert evaluate(event) is None


def test_tagged_root_without_genai_reaches_agent_run_aggregation():
    actual = evaluate(span(attributes={"agent": "test-agent"}))

    assert actual is not None
    assert actual["agent_tag_present"] is True
    assert not any(name.startswith("gen_ai.") for name in actual["attributes"])
    assert not filter_matches(actual, aggregation_filter("llm_span_calls"))
    assert agent_run_aggregation_accepts(actual)


def test_plain_span_without_genai_or_agent_tag_is_dropped():
    assert evaluate(span(attributes={"http.method": "POST"})) is None


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
    assert all(actual["attributes"][key] == value for key, value in event["attributes"].items())


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
    assert actual['model'] == 'unknown'
    for key in ("input_tokens", "output_tokens", "duration_seconds", "service_name", "system"):
        assert key not in actual


def test_five_dimensions_survive_flattening_without_correlation_labels():
    tags = dict(agent='test-agent', tier=0, privacy_class='private',
                model='served-model', accelerator='gpu-primary')
    event = span()
    event['attributes'].update({f'litellm.metadata.{key}': value for key, value in tags.items()})
    event['attributes'].update(caller='test-caller', correlation_id='test-run')
    actual = evaluate(event)
    assert {key: actual[key] for key in tags} == tags
    groupbys = render(PIPELINE)['functions'][6]['conf']['groupbys']
    assert set(tags).issubset(groupbys)
    assert not {
        'traceId', 'spanId', 'parentSpanId', 'caller', 'correlation_id', 'run_id',
    }.intersection(groupbys)


@pytest.mark.parametrize(('carrier', 'expected'), [
    ('attribute', True), ('alias', True), ('event', True), ('missing', False), ('blank', False),
])
def test_agent_tag_presence_precedes_default_enrichment(carrier, expected):
    event = span()
    if carrier == 'attribute':
        event['attributes']['agent'] = 'test-agent'
    elif carrier == 'alias':
        event['attributes']['litellm.metadata.agent'] = 'test-agent'
    elif carrier == 'event':
        event['agent'] = 'test-agent'
    elif carrier == 'blank':
        event['attributes']['agent'] = '  '

    actual = evaluate(event)
    assert actual['agent_tag_present'] is expected


def test_agent_run_filter_accepts_only_explicitly_tagged_root_spans():
    attributes = {"agent": "test-agent", "gen_ai.request.model": "fixture-model"}
    root = evaluate(span(attributes=attributes.copy()))
    child = evaluate(span(attributes=attributes.copy(), parentSpanId="2" * 16))
    snake_case_child = evaluate(span(attributes=attributes.copy(), parent_span_id="2" * 16))
    untagged = evaluate(span())

    assert agent_run_aggregation_accepts(root)
    assert not agent_run_aggregation_accepts(child)
    assert not agent_run_aggregation_accepts(snake_case_child)
    assert not agent_run_aggregation_accepts(untagged)


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
