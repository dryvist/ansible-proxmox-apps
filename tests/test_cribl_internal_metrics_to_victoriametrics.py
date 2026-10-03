"""Cribl's built-in internal source (cribl:CriblLogs / cribl:CriblMetrics)
must fan CriblMetrics -- and only CriblMetrics -- to victoriametrics_rw.

CriblMetrics events are native Cribl metrics (they carry __criblMetrics), so
they fit the Prometheus remote-write sink; CriblLogs events are raw log
lines and don't. The Splunk leg (cribl_internal pipeline, stamping
index/sourcetype) is unchanged for both inputs -- this only adds a second,
metrics-only connection.

Exact metric names in VictoriaMetrics (Cribl docs, docs.cribl.io/stream/
internal-metrics/ + destinations-prometheus/): the per-output counters are
`total.out_events` and `total.dropped_events` (dimension `output=<id>`,
e.g. `output=splunk_hec_cribl_internal`); the Prometheus destination's
default renaming expression replaces every `.` with `_`, so they arrive as
`total_out_events{output="..."}` and `total_dropped_events{output="..."}`.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
INPUTS_TEMPLATE = ROOT / "roles/cribl_stream/templates/inputs.yml.j2"

# Minimal variable set inputs.yml.j2 needs to render end to end (grep
# cribl_stream_ references in the template for the full list).
BASE_VARS = {
    "cribl_stream_hec_namespace": "",
    "cribl_stream_netflow_port": 2055,
    "cribl_stream_otel_port": 4318,
    "cribl_stream_pq_enabled": True,
    "cribl_stream_prometheus_rw_api_path": "/api/v1/write",
    "cribl_stream_prometheus_rw_port": 9090,
    "cribl_stream_pve_metrics_port": 2003,
    "cribl_stream_s2s_metrics_port": 10202,
    "cribl_stream_s2s_port": 10201,
    "cribl_stream_unpoller_poll_minutes": 1,
    "cribl_stream_unpoller_scrape_target": "unpoller.invalid:9130",
    "cribl_stream_ai_log_routing": {},
    "cribl_stream_ai_input_types": {},
}


def _render_inputs(hec_namespace: str = "") -> dict:
    variables = {**BASE_VARS, "cribl_stream_hec_namespace": hec_namespace}
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    rendered = templar.template(
        trust_as_template(INPUTS_TEMPLATE.read_text(encoding="utf-8"))
    )
    return yaml.safe_load(rendered)


def _connections(inputs: dict, input_id: str) -> list[dict]:
    return inputs["inputs"][input_id]["connections"]


def test_cribl_metrics_connects_to_victoriametrics_and_splunk():
    for hec_namespace in ("", "prod"):
        inputs = _render_inputs(hec_namespace)
        connections = _connections(inputs, "cribl:CriblMetrics")
        outputs = [c["output"] for c in connections]

        assert "victoriametrics_rw" in outputs
        vm_conn = next(c for c in connections if c["output"] == "victoriametrics_rw")
        assert "pipeline" not in vm_conn, (
            "CriblMetrics -> victoriametrics_rw must be a bare passthrough "
            "(no cribl_internal pipeline, which only stamps Splunk metadata)"
        )

        splunk_output = "splunk_hec_cribl_internal" if hec_namespace else "splunk_hec"
        splunk_conn = next(c for c in connections if c["output"] == splunk_output)
        assert splunk_conn["pipeline"] == "cribl_internal"


def test_cribl_logs_does_not_connect_to_victoriametrics():
    for hec_namespace in ("", "prod"):
        inputs = _render_inputs(hec_namespace)
        connections = _connections(inputs, "cribl:CriblLogs")
        outputs = [c["output"] for c in connections]

        assert "victoriametrics_rw" not in outputs, (
            "CriblLogs carries raw log lines, not metrics -- it must not "
            "gain a victoriametrics_rw leg"
        )
        assert len(connections) == 1

        splunk_output = "splunk_hec_cribl_internal" if hec_namespace else "splunk_hec"
        assert connections[0] == {"output": splunk_output, "pipeline": "cribl_internal"}


def test_cribl_logs_splunk_connection_is_unchanged():
    inputs = _render_inputs(hec_namespace="")
    assert _connections(inputs, "cribl:CriblLogs") == [
        {"output": "splunk_hec", "pipeline": "cribl_internal"}
    ]
