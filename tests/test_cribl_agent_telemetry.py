"""Execute rendered native Eval/Drop functions at the trace export boundary."""
import json
import subprocess
import unittest

from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, FileSystemLoader, StrictUndefined
import yaml

from test_cribl_litellm_trace_contract import NODE, ROLE, enrich, fixture_vars, render
from test_cribl_stream_hec_pipeline_reconcile import _task_named


class AgentTelemetry(unittest.TestCase):
    tags = dict(agent='test-agent', tier=0, privacy_class='public', model='test-model',
                accelerator='test-accelerator', caller='test-caller', correlation_id='test-request')

    def test_defaults_and_explicit_tags_reach_every_trace_leg(self):
        for leg in ('otel_traces', 'otel_traces_phoenix', 'otel_traces_to_splunk'):
            with self.subTest(leg=leg):
                self.assertEqual({k: enrich(leg, {})['attributes'][k] for k in self.tags},
                                 dict(agent='unknown', tier=2, privacy_class='private', model='unknown',
                                      accelerator='unknown', caller='unknown', correlation_id='unknown'))
                actual = enrich(leg, self.tags)['attributes']
                self.assertEqual({k: actual[k] for k in self.tags}, self.tags)
                aliases = {f'litellm.metadata.{k}': v for k, v in self.tags.items()}
                actual = enrich(leg, aliases)['attributes']
                self.assertEqual({k: actual[k] for k in self.tags}, self.tags)

    def test_log_and_metric_legs_preserve_canonical_tags(self):
        for leg, signal in (('otel_logs', 'logs'), ('otel_metrics_to_splunk', 'metrics'),
                            ('otel_metrics_to_victoriametrics', 'metrics')):
            actual = enrich(leg, self.tags, __otlp={'type': signal})['attributes']
            self.assertEqual({k: actual[k] for k in self.tags}, self.tags)
            defaults = enrich(leg, None, __otlp={'type': signal})['attributes']
            self.assertEqual(set(defaults), set(self.tags))
            self.assertEqual(defaults['privacy_class'], 'private')

    def test_agent_run_facets_keep_zero_trace_identity_and_every_phoenix_span(self):
        run_tags = {key: value for key, value in self.tags.items()
                    if key not in ('caller', 'correlation_id')}
        for carrier in ('canonical', 'aliases', 'event'):
            for snake_case in (False, True):
                attrs = {'session.id': 'test-session', 'metadata': '{"other":"keep","tier":2}'}
                fields = {('trace_id' if snake_case else 'traceId'): 'a' * 31 + '1',
                          ('span_id' if snake_case else 'spanId'): 'b' * 16,
                          ('parent_span_id' if snake_case else 'parentSpanId'): 'c' * 16,
                          'startTimeUnixNano': '1793923200000000000'}
                if carrier == 'event':
                    fields.update(self.tags)
                else:
                    prefix = 'litellm.metadata.' if carrier == 'aliases' else ''
                    attrs.update({prefix + key: value for key, value in self.tags.items()})
                for leg in ('otel_traces', 'otel_traces_phoenix'):
                    with self.subTest(carrier=carrier, snake_case=snake_case, leg=leg):
                        event = enrich(leg, attrs, **fields)
                        self.assertIsNotNone(event)
                        for key, value in fields.items():
                            self.assertEqual(event[key], value)
                        actual = event['attributes']
                        if leg == 'otel_traces':
                            for level in ('trace', 'observation'):
                                self.assertEqual({key: actual[f'langfuse.{level}.metadata.{key}']
                                                  for key in run_tags}, run_tags)
                            self.assertTrue({f'{key}:{value}' for key, value in run_tags.items()}
                                            .issubset(actual['langfuse.trace.tags']))
                        else:
                            metadata = json.loads(actual['metadata'])
                            self.assertEqual({key: metadata[key] for key in run_tags}, run_tags)
                            self.assertEqual(metadata['other'], 'keep')
                        self.assertIs(type(actual['tier']), int)

    def test_arize_privacy_gate_fails_closed(self):
        for privacy in (None, '', 'private', 'zdr', 'PUBLIC', True, ['public'], {'value': 'public'}):
            with self.subTest(privacy=privacy):
                self.assertIsNone(enrich('otel_traces_arize', {'privacy_class': privacy},
                                        __otlp={'type': 'traces', 'extracted': True}))
        for signal in ('logs', 'metrics', 'traces'):
            self.assertIsNone(enrich('otel_traces_arize', self.tags, __otlp={'type': signal}))

    def test_tag_defaults_handle_empty_and_malformed_attributes(self):
        for attrs in (None, [], 'text', {tag: '' for tag in self.tags}):
            actual = enrich('otel_traces_to_splunk', attrs)['attributes']
            self.assertEqual(actual['privacy_class'], 'private')
            self.assertEqual(actual['agent'], 'unknown')
            self.assertEqual(actual['tier'], 2)
        for tier in (0, 1, 2, '0', '1', '2', False, 3):
            actual = enrich('otel_traces_to_splunk', {'tier': tier})['attributes']['tier']
            self.assertEqual(actual, int(tier) if type(tier) is not bool and str(tier) in '012' else 2)
        actual = enrich('otel_traces_to_splunk', {'gen_ai.request.model': 'test-model'})['attributes']
        self.assertEqual(actual['model'], 'test-model')

    def test_arize_removes_all_unlisted_content_and_resource_identity(self):
        attrs = dict(self.tags, **{key: 'body-marker' for key in (
            'gen_ai.prompt', 'gen_ai.completion', 'gen_ai.input.messages', 'gen_ai.output.messages',
            'llm.input_messages.0.message.content', 'input.value', 'output.value', 'metadata',
            'host.name', 'host.ip', 'service.instance.id', 'cloud.resource_id', 'custom.future.body')})
        event = enrich('otel_traces_arize', attrs,
                       __otlp={'type': 'traces', 'extracted': True, 'resource': 'body-marker'},
                       resource={'attributes': {'host.name': 'body-marker'}},
                       scope={'name': 'body-marker', 'attributes': {'identity': 'body-marker'}},
                       status={'code': 2, 'message': 'body-marker'}, events=[{'name': 'body-marker'}],
                       links=[{'attributes': {'message': 'body-marker'}}], name='body-marker',
                       trace_id='a' * 32, span_id='b' * 16, start_time_unix_nano='123',
                       startTime=123, endTime=456, duration=333,
                       _raw='body-marker', host='body-marker', __headers={'authorization': 'body-marker'})
        self.assertEqual(event['attributes'], self.tags)
        self.assertEqual(event['resource'], {'attributes': {}})
        self.assertEqual(event['scope'], {})
        self.assertEqual(event['status'], {'code': 2})
        self.assertEqual(event['trace_id'], 'a' * 32)
        self.assertEqual(event['span_id'], 'b' * 16)
        self.assertEqual((event['startTime'], event['endTime'], event['duration']), (123, 456, 333))
        self.assertNotIn('body-marker', json.dumps(event))
        # Running the output's post-processor a second time is idempotent.
        result = subprocess.run(['node', '-e', NODE], text=True, capture_output=True, check=True,
                                input=json.dumps({'event': event, 'pipeline': render('otel_traces_arize')}))
        self.assertEqual(json.loads(result.stdout), event)

    def test_splunk_final_projection_preserves_schema_and_drops_bodies(self):
        event = enrich('otel_traces_to_splunk', dict(self.tags, **{'gen_ai.prompt': 'body-marker'}))
        result = subprocess.run(['node', '-e', NODE], text=True, capture_output=True, check=True,
                                input=json.dumps({'event': event, 'pipeline': render('secret_redaction')}))
        actual = json.loads(result.stdout)
        self.assertEqual({k: actual['attributes'][k] for k in self.tags}, self.tags)
        self.assertNotIn('body-marker', json.dumps(actual))

    def test_otlp_and_s2s_inputs_connect_all_four_trace_destinations(self):
        for path in ('inputs.yml.j2', 'inputs/open_telemetry.yml.j2'):
            source = (ROLE / 'templates' / path).read_text()
            for output, pipeline in (('langfuse_otlp', 'otel_traces'), ('phoenix_otlp', 'otel_traces_phoenix'),
                                     ('arize_otlp', 'otel_traces_arize'), ('splunk_hec', 'otel_traces_to_splunk')):
                self.assertIn(f'- output: {output}\n        pipeline: {pipeline}', source)

    def test_arize_output_uses_parameters_and_enforces_projection(self):
        fixture = fixture_vars('cribl_stream_phoenix')
        env = Environment(undefined=StrictUndefined, loader=FileSystemLoader(ROLE / 'templates'))
        env.filters['bool'] = to_bool
        env.filters['to_uuid'] = lambda value, namespace: 'fixture-token'
        output = yaml.safe_load(env.get_template('outputs.yml.j2').render(fixture))['outputs']['arize_otlp']
        self.assertEqual(output['endpoint'], fixture['cribl_stream_arize_url'])
        self.assertEqual(output['pipeline'], 'otel_traces_arize')
        self.assertEqual(output['systemFields'], [])
        self.assertTrue(output['rejectUnauthorized'])
        self.assertEqual(output['failedRequestLoggingMode'], 'none')
        self.assertEqual(output['extraHttpHeaders'], [
            {'name': 'arize-api-key', 'value': fixture['cribl_stream_arize_api_key']},
            {'name': 'arize-space-id', 'value': fixture['cribl_stream_arize_space_id']}])
        guard = _task_named('Deploy Cribl Stream outputs configuration')['when'][1]
        for field in ('endpoint', 'extraHttpHeaders', 'pipeline', 'systemFields', 'rejectUnauthorized',
                      'failedRequestLoggingMode', 'safeHeaders'):
            self.assertIn(f"cribl_stream_arize_live.get('{field}'", guard)


if __name__ == '__main__':
    unittest.main(verbosity=2)
