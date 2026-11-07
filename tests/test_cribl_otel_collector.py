"""Offline forwarding and output reconciliation contracts; no receiver I/O."""
import copy
import json
import subprocess

import pytest
import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import init_plugin_loader
from ansible.template import Templar, trust_as_template

from test_cribl_internal_metrics_to_victoriametrics import _render_inputs
from test_cribl_litellm_trace_contract import ROLE, fixture_vars, render


PIPELINE = "otel_traces_to_collector"
OUTPUT = "otel_metrics_collector"
ROOT = ROLE.parents[1]
init_plugin_loader()


def defaults():
    variables = {}
    for path in sorted((ROLE / "defaults/main").glob("*.yml")):
        variables.update(yaml.safe_load(path.read_text()) or {})
    return variables


def context(enabled=False, namespace=""):
    variables = defaults()
    variables.update(fixture_vars("cribl_stream"))
    variables.update({
        "cribl_stream_otel_collector_enabled": enabled,
        "cribl_stream_otel_collector_url": "http://collector.example.invalid:4318",
        "cribl_stream_hec_namespace": namespace,
        "cribl_stream_per_index_indexes": ["llm", "ai_usage", "otel_traces"],
        "cribl_stream_clickhouse_url": "",
        "cribl_stream_base_pipelines": yaml.safe_load(
            (ROLE / "defaults/main/00-install.yml").read_text())["cribl_stream_base_pipelines"],
    })
    return variables


def trusted(value):
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, dict):
        return {str(key): trusted(item) for key, item in value.items()}
    if isinstance(value, list):
        return [trusted(item) for item in value]
    return value


def templar(variables):
    loader = DataLoader()
    loader.set_basedir(str(ROLE / "templates"))
    return Templar(loader=loader, variables=trusted(variables))


def outputs(variables):
    return yaml.safe_load(templar(variables).template(trust_as_template(
        (ROLE / "templates/outputs.yml.j2").read_text())))


@pytest.mark.parametrize("namespace", ["", "11111111-2222-4333-8444-555555555555"])
def test_default_off_and_enabled_preserve_every_existing_leg(namespace):
    disabled = _render_inputs(namespace)
    enabled = _render_inputs(namespace, cribl_stream_otel_collector_enabled=True)
    connections = enabled["inputs"]["open_telemetry:in_otel"]["connections"]
    assert connections.pop(0) == {"output": OUTPUT, "pipeline": PIPELINE}
    assert enabled == disabled
    before = outputs(context(namespace=namespace))
    after = outputs(context(True, namespace))
    assert OUTPUT not in before["outputs"]
    collector = after["outputs"].pop(OUTPUT)
    assert after == before
    assert {key: collector[key] for key in (
        "id", "type", "disabled", "protocol", "endpoint", "otlpVersion", "systemFields"
    )} == {
        "id": OUTPUT, "type": "open_telemetry", "disabled": False,
        "protocol": "http", "endpoint": "http://collector.example.invalid:4318",
        "otlpVersion": "1.3.1", "systemFields": [],
    }
    for key, value in collector.items():
        if key.startswith("pq") or key in (
            "onBackpressure", "responseRetrySettings", "timeoutRetrySettings", "responseHonorRetryAfterHeader"
        ):
            assert value == before["outputs"]["phoenix_otlp"][key]


def test_registry_gates_only_collector_and_keeps_legacy_metrics():
    defaults = yaml.safe_load((ROLE / "defaults/main/43-otel-collector.yml").read_text())
    assert defaults["cribl_stream_otel_collector_enabled"] is False
    disabled = templar(context()).template(trust_as_template(context()["cribl_stream_pipelines"]))
    enabled = templar(context(True)).template(trust_as_template(context(True)["cribl_stream_pipelines"]))
    assert PIPELINE not in disabled
    assert enabled == disabled + [PIPELINE]
    assert disabled.count("otel_traces_to_metrics") == 1


@pytest.mark.parametrize("signal", [None, "logs", "metrics", "traces"])
def test_trace_only_pipeline_preserves_original_event(signal):
    pipeline = render(PIPELINE)
    assert pipeline["output"] == OUTPUT
    assert pipeline["functions"] == [{
        "id": "drop", "filter": "!__e.__otlp || __e.__otlp.type !== 'traces'",
        "disabled": False, "conf": {},
    }]
    event = {
        "traceId": "1" * 32, "spanId": "2" * 16, "parentSpanId": "3" * 16,
        "startTimeUnixNano": "1793923200000000001", "endTimeUnixNano": "1793923200050000001",
        "resource": {"attributes": {"service.name": "fixture-client"}},
        "attributes": {"gen_ai.request.model": "fixture-model"},
    }
    if signal is not None:
        event["__otlp"] = {"type": signal}
    result = subprocess.run([
        "node", "-e",
        "const input=JSON.parse(require('fs').readFileSync(0,'utf8'));"
        "const drop=new Function('__e','return ('+input.filter+');');"
        "process.stdout.write(JSON.stringify(drop(input.event)?null:input.event));",
    ], input=json.dumps({"event": event, "filter": pipeline["functions"][0]["filter"]}),
        capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == (event if signal == "traces" else None)


def test_inventory_endpoint_is_lazy_and_reaches_the_tagged_guest_by_name():
    value = yaml.safe_load((ROOT / "inventory/group_vars/cribl_stream_group.yml").read_text())[
        "cribl_stream_otel_collector_url"]
    assert templar({"cribl_stream_otel_collector_enabled": False}).template(trust_as_template(value)) == ""
    variables = {
        "cribl_stream_otel_collector_enabled": True,
        "tofu_data": {
            "domain": "lab.example.test",
            "containers": {
                "clickhouse": {"hostname": "clickhouse-fixture", "ip": "192.0.2.44", "tags": ["clickhouse"]},
                "other": {"hostname": "other-fixture", "ip": "192.0.2.45", "tags": ["web"]},
            },
            "constants": {"service_ports": {"otel_traces_http": 14318}},
        },
    }
    assert templar(variables).template(trust_as_template(value)) == "http://clickhouse-fixture.lab.example.test:14318"
    del variables["tofu_data"]["constants"]["service_ports"]["otel_traces_http"]
    with pytest.raises(Exception, match="otel_traces_http"):
        templar(variables).template(trust_as_template(value))


def reconcile(enabled, live):
    variables = context(enabled)
    variables["cribl_stream_outputs_live"] = {"stdout": yaml.safe_dump(live)}
    tasks = yaml.safe_load((ROLE / "tasks/outputs.yml").read_text())
    facts = next(task["ansible.builtin.set_fact"] for task in tasks
                 if task["name"] == "Extract live Splunk HEC output settings")
    variables.update(templar(variables).template(trusted(facts)))
    if enabled:
        expected = next(task["ansible.builtin.set_fact"] for task in tasks
                        if task["name"] == "Render the managed Collector output settings for drift detection")
        variables.update(templar(variables).template(trusted(expected)))
    guard = next(task["when"][1] for task in tasks
                 if task["name"] == "Deploy Cribl Stream outputs configuration")
    return templar(variables).evaluate_expression(trust_as_template(guard))


def test_reconcile_add_remove_move_and_unchanged_existing_outputs():
    disabled = outputs(context())
    enabled = outputs(context(True))
    assert reconcile(False, disabled) is False
    assert reconcile(True, enabled) is False
    assert reconcile(True, disabled) is True
    assert reconcile(False, enabled) is True
    enabled["outputs"][OUTPUT]["endpoint"] = "http://moved.example.invalid:4318"
    assert reconcile(True, enabled) is True


@pytest.mark.parametrize("field", [
    "type", "disabled", "protocol", "otlpVersion", "systemFields", "onBackpressure",
    "pqMode", "pqOnBackpressure", "pqPath", "pqMaxFileSize", "pqMaxSize", "pqCompress",
    "responseRetrySettings", "timeoutRetrySettings", "responseHonorRetryAfterHeader",
])
def test_reconcile_repairs_every_managed_collector_field(field):
    live = copy.deepcopy(outputs(context(True)))
    del live["outputs"][OUTPUT][field]
    assert reconcile(True, live) is True


def test_reconcile_tolerates_runtime_defaults_and_disabled_missing_url():
    live = outputs(context(True))
    live["outputs"][OUTPUT]["runtimeDefault"] = "ignored"
    assert reconcile(True, live) is False
    variables = context()
    del variables["cribl_stream_otel_collector_url"]
    assert OUTPUT not in outputs(variables)["outputs"]
    variables["cribl_stream_otel_collector_enabled"] = True
    with pytest.raises(Exception, match="Collector OTLP base URL"):
        outputs(variables)


@pytest.mark.parametrize("namespace", ["", "11111111-2222-4333-8444-555555555555"])
def test_template_render_assertions_without_local_rpc(namespace):
    variables = fixture_vars("cribl_stream")
    variables.update({
        "_cribl_stream_defaults": defaults(), "collector_namespace": namespace,
        "_template_dir": str(ROLE / "templates"),
        "cribl_stream_victoriametrics_otlp_endpoint": defaults()["cribl_stream_victoriametrics_otlp_endpoint"],
    })
    tasks = yaml.safe_load((ROOT / "tests/template_render/verify/cribl_stream/assertions_collector.yml").read_text())
    for task in tasks:
        scoped = {**variables, **task["vars"]}
        engine = templar(scoped)
        if "ansible.builtin.set_fact" in task:
            variables.update(engine.template(trusted(task["ansible.builtin.set_fact"])))
        else:
            for expression in task["ansible.builtin.assert"]["that"]:
                assert engine.evaluate_expression(trust_as_template(expression)), expression
