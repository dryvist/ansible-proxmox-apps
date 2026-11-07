"""Exercise AX projection with serialized SDK spans, without sink I/O."""
import json
import unittest

from google.protobuf.json_format import MessageToDict
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode

import test_cribl_agent_telemetry as telemetry
from test_cribl_litellm_trace_contract import enrich


def otlp_events(*records):
    """SDK spans -> OTLP protobuf bytes -> extracted Cribl source events.

    Models the source's extraction only, not a running Cribl receiver:
    https://docs.cribl.io/stream/sources-otel/#internal-fields
    """
    provider = TracerProvider(resource=Resource({'service.name': 'test-service', 'host.name': 'body-marker'}))
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer('test-telemetry')
    for attributes in records:
        with tracer.start_as_current_span('body-marker', attributes=attributes) as span:
            span.add_event('body-marker', {'input.value': 'body-marker'})
            span.set_status(Status(StatusCode.ERROR, 'body-marker'))
    request = encode_spans(exporter.get_finished_spans())
    decoded = ExportTraceServiceRequest.FromString(request.SerializeToString())
    provider.shutdown()

    def value(item):
        field = item.WhichOneof('value')
        if field == 'array_value':
            return [value(child) for child in item.array_value.values]
        return getattr(item, field)

    def attributes(items):
        return {item.key: value(item.value) for item in items}

    events = []
    for resource in decoded.resource_spans:
        for scope in resource.scope_spans:
            for span in scope.spans:
                event = MessageToDict(span, use_integers_for_enums=True)
                event.update(traceId=span.trace_id.hex(), spanId=span.span_id.hex(),
                             attributes=attributes(span.attributes),
                             resource={'attributes': attributes(resource.resource.attributes)},
                             scope=MessageToDict(scope.scope),
                             __otlp={'type': 'traces', 'extracted': True, 'version': '1.3.1'})
                if span.parent_span_id:
                    event['parentSpanId'] = span.parent_span_id.hex()
                events.append(event)
    return events


def project(event):
    return enrich('otel_traces_arize', event['attributes'],
                  **{key: value for key, value in event.items() if key != 'attributes'})


class AgentOTLP(unittest.TestCase):
    tags = telemetry.AgentTelemetry.tags

    def test_arize_projects_sdk_otlp_public_and_private_records(self):
        tags = {key: value for key, value in self.tags.items() if key not in ('caller', 'correlation_id')}
        records = otlp_events(tags, dict(tags, privacy_class='private'))
        for event in records:
            self.assertIs(type(event['attributes']['tier']), int)
            self.assertEqual(event['attributes']['tier'], 0)
            self.assertIn('body-marker', json.dumps(event))
        public = project(records[0])
        self.assertEqual(public['attributes'], tags)
        for field in ('traceId', 'spanId', 'startTimeUnixNano', 'endTimeUnixNano'):
            self.assertEqual(public[field], records[0][field])
        self.assertNotIn('body-marker', json.dumps(public))
        self.assertIsNone(project(records[1]))
        self.assertEqual(project(public), public)

    def test_arize_sdk_otlp_missing_and_unknown_privacy_fail_closed(self):
        missing = {key: value for key, value in self.tags.items() if key != 'privacy_class'}
        for event in otlp_events(missing, dict(self.tags, privacy_class='unknown')):
            self.assertIsNone(project(event))

    def test_arize_sdk_otlp_valid_values_survive(self):
        for event in otlp_events(*(dict(self.tags, tier=tier, accelerator=accelerator)
                                   for tier in (0, 1, 2)
                                   for accelerator in ('gpu-primary', 'gpu-secondary', 'mac-primary',
                                                       'mac-secondary', 'cloud', 'cpu'))):
            actual = project(event)['attributes']
            self.assertEqual(actual, {key: event['attributes'][key] for key in actual})
            self.assertEqual(set(actual), set(self.tags) - {'caller', 'correlation_id'})
            self.assertIs(type(actual['tier']), int)

    def test_arize_sdk_otlp_rejects_text_inside_every_allowed_tag(self):
        for tag in ('agent', 'tier', 'privacy_class', 'model', 'accelerator'):
            for text in ('free text', 'Summarize this prompt: private input and output.'):
                for prefix in ('', 'litellm.metadata.'):
                    attrs = {key: value for key, value in self.tags.items() if key != tag}
                    attrs[prefix + tag] = text
                    with self.subTest(tag=tag, text=text, prefix=prefix):
                        event, = otlp_events(attrs)
                        actual = project(event)
                        if tag == 'privacy_class':
                            self.assertIsNone(actual)
                        else:
                            self.assertEqual(actual['attributes'], {
                                key: value for key, value in self.tags.items()
                                if key not in (tag, 'caller', 'correlation_id')})
                            self.assertNotIn(text, json.dumps(actual))
                            self.assertEqual(project(actual), actual)
