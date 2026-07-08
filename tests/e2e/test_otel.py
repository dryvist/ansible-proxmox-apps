"""OTel routes fan-out tests (Cribl Edge 4.12+).

The Edge otel input sends to the routes table: a non-final otel_langfuse
route feeds Langfuse (traces only) and a final otel_splunk route stamps
index=otel / sourcetype=otel:span and ships the same stream to Splunk. This
suite drives the Splunk leg end-to-end: OTLP/HTTP JSON trace in at the Edge
otel port, span event out in index=otel.

Skips when the inventory predates the otel_traces_http service port.
"""

import json
import time
import urllib.error
import urllib.request
import uuid

import pytest

from .helpers import query_splunk


def _otel_port(constants):
    port = constants.get("service_ports", {}).get("otel_traces_http")
    if not port:
        pytest.skip("No otel_traces_http in constants.service_ports")
    return port


def _make_otlp_trace_payload(sentinel):
    """Minimal OTLP/HTTP JSON traces export with a sentinel span name."""
    now_ns = int(time.time() * 1e9)
    return json.dumps(
        {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": "e2e-otel-test"},
                            }
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "e2e"},
                            "spans": [
                                {
                                    "traceId": uuid.uuid4().hex,
                                    "spanId": uuid.uuid4().hex[:16],
                                    "name": sentinel,
                                    "kind": 1,
                                    "startTimeUnixNano": str(now_ns),
                                    "endTimeUnixNano": str(now_ns + 1_000_000),
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    ).encode("utf-8")


def _post_otlp_traces(host, port, payload):
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/traces",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as e:
        return e.code


class TestOtelSplunkFanout:
    """Validate the otel_splunk route leg lands spans in index=otel."""

    def test_otlp_trace_reaches_otel_index(
        self,
        cribl_edge_ips,
        constants,
        splunk_creds,
        pipeline_poll_timeout,
        pipeline_poll_interval,
    ):
        """POST an OTLP trace to the first Edge and find it in index=otel."""
        port = _otel_port(constants)
        mgmt_url, user, password = splunk_creds
        sentinel = f"e2e-otel-{uuid.uuid4().hex[:10]}-{int(time.time())}"

        status = _post_otlp_traces(
            cribl_edge_ips[0], port, _make_otlp_trace_payload(sentinel)
        )
        assert status in (200, 202), f"OTLP POST returned HTTP {status}"

        search_str = f'index=otel sourcetype="otel:span" "{sentinel}" | head 5'
        deadline = time.time() + pipeline_poll_timeout
        results = []
        while time.time() < deadline:
            results = query_splunk(
                mgmt_url, user, password, search_str, earliest="-5m", timeout=30
            )
            if results:
                break
            time.sleep(pipeline_poll_interval)

        assert results, (
            f"OTel sentinel span {sentinel} did not reach Splunk with "
            f"index=otel sourcetype=otel:span — check the otel_splunk route "
            f"and the splunk_hec_otel output on the Edge"
        )
