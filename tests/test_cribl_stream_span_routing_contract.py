from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "cribl_stream"
SPLUNK_SPAN_DROP = (
    "sourcetype === 'otel:span' || !!(__otlp && __otlp.type === 'traces')"
)
SPLUNK_DROP_UNBOUNDED_SPANS = (
    f"({SPLUNK_SPAN_DROP}) && index !== 'otel_traces'"
)
TRACE_FILTER = """filter: "!__otlp || __otlp.type !== 'traces'"""


def _section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


class CriblSpanRoutingContract(unittest.TestCase):
    def test_s2s_spans_fan_out_to_trace_backends_and_drop_from_splunk(self):
        inputs = (ROLE / "templates" / "inputs.yml.j2").read_text()
        s2s_connections = _section(
            inputs, "  tcpjson:in_cribl_s2s:\n", "  tcpjson:in_cribl_s2s_metrics:\n"
        )
        self.assertIn(
            "- output: langfuse_otlp\n        pipeline: otel_traces",
            s2s_connections,
        )
        self.assertIn(
            "- output: phoenix_otlp\n        pipeline: otel_traces_phoenix",
            s2s_connections,
        )

        splunk_pipeline = (
            ROLE / "templates" / "pipelines" / "force_splunk_meta" / "conf.yml.j2"
        ).read_text()
        span_drop = f'filter: "{SPLUNK_SPAN_DROP}"'
        self.assertIn(span_drop, splunk_pipeline)
        self.assertLess(
            splunk_pipeline.index(span_drop), splunk_pipeline.index("- id: eval")
        )

    def test_otel_spans_have_a_bounded_splunk_hec_route(self):
        inputs = (ROLE / "templates" / "inputs" / "open_telemetry.yml.j2").read_text()
        self.assertIn(
            "- output: splunk_hec_otel_traces\n        pipeline: otel_traces_to_splunk",
            inputs,
        )
        self.assertIn(
            "- output: splunk_hec\n        pipeline: otel_traces_to_splunk",
            inputs,
        )

        splunk_route = (
            ROLE
            / "templates"
            / "pipelines"
            / "otel_traces_to_splunk"
            / "conf.yml.j2"
        ).read_text()
        self.assertIn(TRACE_FILTER, splunk_route)
        self.assertIn("value: \"'otel_traces'\"", splunk_route)
        self.assertIn("value: \"'otel:span'\"", splunk_route)

        redaction = (
            ROLE / "templates" / "pipelines" / "secret_redaction" / "conf.yml.j2"
        ).read_text()
        self.assertIn(f'filter: "{SPLUNK_DROP_UNBOUNDED_SPANS}"', redaction)
        self.assertIn("allowedFields", redaction)
        self.assertIn("allowedAttributes", redaction)

        defaults = (ROLE / "defaults" / "main" / "42-otel-splunk-export.yml").read_text()
        for body_attribute in (
            "gen_ai.prompt",
            "gen_ai.completion",
            "gen_ai.input.messages",
            "gen_ai.output.messages",
        ):
            self.assertNotIn(body_attribute, defaults)

        splunk_defaults = (
            ROLE / "defaults" / "main" / "20-splunk-hec-routing.yml"
        ).read_text()
        self.assertIn("'otel_traces'", splunk_defaults)

    def test_span_drop_is_limited_to_splunk_outputs(self):
        splunk_defaults = (
            ROLE / "defaults" / "main" / "20-splunk-hec-routing.yml"
        ).read_text()
        self.assertIn(
            "cribl_stream_splunk_hec_post_processing_pipeline: secret_redaction",
            splunk_defaults,
        )

        outputs = (ROLE / "templates" / "outputs.yml.j2").read_text()
        pipeline_ref = (
            'pipeline: "{{ cribl_stream_splunk_hec_'
            'post_processing_pipeline }}"'
        )
        base_splunk = _section(
            outputs, "  splunk_hec:\n", "{% if (cribl_stream_hec_namespace"
        )
        per_index_splunk = _section(
            outputs, "  splunk_hec_{{ idx }}:\n", "{% endfor %}"
        )
        self.assertIn(pipeline_ref, base_splunk)
        self.assertIn(pipeline_ref, per_index_splunk)
        self.assertNotIn("\n    pipeline:", outputs.split("  # Langfuse OTLP", 1)[1])

        redaction = (
            ROLE / "templates" / "pipelines" / "secret_redaction" / "conf.yml.j2"
        ).read_text()
        self.assertIn(f'filter: "{SPLUNK_DROP_UNBOUNDED_SPANS}"', redaction)

        inputs = (ROLE / "templates" / "inputs" / "open_telemetry.yml.j2").read_text()
        trace_connections = _section(
            inputs, "      # Trace destination", "      # OTLP log records"
        )
        self.assertIn(
            "- output: langfuse_otlp\n        pipeline: otel_traces", trace_connections
        )
        self.assertIn(
            "- output: phoenix_otlp\n        pipeline: otel_traces_phoenix",
            trace_connections,
        )

        for name in ("otel_traces", "otel_traces_phoenix"):
            trace_pipeline = (
                ROLE / "templates" / "pipelines" / name / "conf.yml.j2"
            ).read_text()
            self.assertIn(TRACE_FILTER, trace_pipeline)
            self.assertNotIn(SPLUNK_SPAN_DROP, trace_pipeline)


if __name__ == "__main__":
    unittest.main(verbosity=2)
