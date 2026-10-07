"""Execute the rendered trace enrichment expressions, without sink I/O."""
import json
from pathlib import Path
import subprocess
import unittest

from jinja2 import Environment, StrictUndefined
import yaml

ROLE = Path(__file__).resolve().parents[1] / 'roles' / 'cribl_stream'
NODE = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const event = input.event;
for (const step of input.pipeline.functions) {
  const applies = new Function('attributes', 'name', '__otlp', 'return (' + step.filter + ');');
  if (!applies(event.attributes, event.name, event.__otlp)) continue;
  if (step.id === 'drop') { process.stdout.write('null'); process.exit(0); }
  if (step.id === 'eval') {
    for (const entry of step.conf.add || []) {
      const value = new Function('attributes', 'name', 'return (' + entry.value + ');')(event.attributes, event.name);
      new Function('event', 'value', 'event.' + entry.name + ' = value;')(event, value);
    }
    for (const field of step.conf.remove || []) new Function('event', 'delete event.' + field + ';')(event);
  }
  if (step.id === 'code') new Function('__e', step.conf.code)(event);
}
process.stdout.write(JSON.stringify(event));
"""


def render(name):
    context = {}
    for path in sorted((ROLE / 'defaults' / 'main').glob('*.yml')):
        context.update(yaml.safe_load(path.read_text()) or {})
    env = Environment(undefined=StrictUndefined)
    env.filters['to_json'] = json.dumps
    text = (ROLE / 'templates' / 'pipelines' / name / 'conf.yml.j2').read_text()
    return yaml.safe_load(env.from_string(text).render(context))


def enrich(name, attrs):
    event = {'name': 'inference', '__otlp': {'type': 'traces'}, 'attributes': attrs}
    result = subprocess.run(['node', '-e', NODE], input=json.dumps({'event': event, 'pipeline': render(name)}),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


class TraceContract(unittest.TestCase):
    def test_scalar_contract_reaches_native_fields_and_false_zero_survive(self):
        attrs = {'gen_ai.request.model': 'test-model', 'litellm.metadata.runner': 'test-runner',
                 'litellm.metadata.purpose': 'benchmark', 'litellm.metadata.session_id': 'run-1',
                 'litellm.metadata.trace_user_id': 'consumer', 'litellm.metadata.trace_name': 'run-trace',
                 'litellm.metadata.generation_name': 'run-generation', 'litellm.metadata.release': 'test-release',
                 'litellm.metadata.trace_release': 'app-release', 'litellm.metadata.trace_version': 'component-version',
                 'litellm.metadata.thinking': False, 'litellm.metadata.power_limit': 0}
        lf = enrich('otel_traces', attrs)['attributes']
        self.assertEqual(lf['langfuse.session.id'], 'run-1')
        self.assertEqual(lf['langfuse.user.id'], 'consumer')
        self.assertEqual(lf['langfuse.trace.name'], 'run-trace')
        self.assertEqual(lf['langfuse.release'], 'app-release')
        self.assertEqual(lf['langfuse.version'], 'component-version')
        self.assertIs(lf['langfuse.trace.metadata.thinking'], False)
        self.assertEqual(lf['langfuse.trace.metadata.power_limit'], 0)
        self.assertEqual(enrich('otel_traces', attrs)['name'], 'run-generation')
        px = enrich('otel_traces_phoenix', attrs)['attributes']
        self.assertEqual(px['session.id'], 'run-1')
        self.assertEqual(px['user.id'], 'consumer')
        self.assertEqual(px['tag.tags'], ['test-runner', 'benchmark'])
        metadata = json.loads(px['metadata'])
        self.assertEqual(metadata['session_id'], 'run-1')
        self.assertIs(metadata['thinking'], False)
        self.assertEqual(metadata['power_limit'], 0)

    def test_native_controls_and_metadata_survive_enrichment(self):
        attrs = {'langfuse.user.id': 'native-user', 'langfuse.session.id': 'native-session',
                 'langfuse.trace.name': 'native-trace', 'langfuse.trace.tags': ['native-tag'],
                 'langfuse.environment': 'native-env', 'langfuse.release': 'native-release',
                 'litellm.metadata.runner': 'runner', 'user.id': 'native-user', 'session.id': 'native-session',
                 'tag.tags': ['native-tag'], 'metadata': json.dumps({'other': 'keep'})}
        lf = enrich('otel_traces', attrs)['attributes']
        for field in ['user.id', 'session.id', 'trace.name', 'environment', 'release']:
            self.assertEqual(lf['langfuse.' + field], attrs['langfuse.' + field])
        self.assertIn('native-tag', lf['langfuse.trace.tags'])
        px = enrich('otel_traces_phoenix', attrs)['attributes']
        self.assertEqual(px['session.id'], 'native-session')
        self.assertEqual(px['tag.tags'], ['native-tag', 'runner'])
        self.assertEqual(json.loads(px['metadata']), {'other': 'keep', 'runner': 'runner'})

    def test_native_langfuse_metadata_survives_without_scalar_sources(self):
        attrs = {'langfuse.trace.metadata.runner': 'native-runner',
                 'langfuse.trace.metadata.run_id': 'native-run',
                 'langfuse.trace.metadata.thinking': False,
                 'langfuse.trace.metadata.power_limit': 0}
        actual = enrich('otel_traces', attrs)['attributes']
        for field, value in attrs.items():
            self.assertEqual(actual[field], value)

    def test_benchmark_generic_metadata_projects_stage0_contract_and_hardware(self):
        attrs = {
            'metadata.environment': 'benchmark',
            'metadata.client': 'stage0-client',
            'metadata.runtime': 'stage0-runtime',
            'metadata.runner': 'stage0-runner',
            'metadata.purpose': 'stage0-purpose',
            'metadata.tier': 'stage0-tier',
            'metadata.user': 'stage0-user',
            'metadata.trace_user_id': 'stage0-user-id',
            'metadata.session_id': 'stage0-session',
            'metadata.trace_name': 'stage0-trace',
            'metadata.generation_name': 'stage0-generation',
            'metadata.tags': ['stage0-tag'],
            'metadata.release': 'stage0-release',
            'metadata.trace_release': 'stage0-trace-release',
            'metadata.trace_version': 'stage0-version',
            'metadata.model_task': 'feature-extraction',
            'metadata.host': 'fixture-mac',
            'metadata.chip': 'fixture-chip',
            'metadata.unified_memory_gb': 128,
            'metadata.power_source': 'ac',
            'metadata.power_mode': 'normal',
            'metadata.macos_version': 'fixture-os',
            'model': 'fixture-model',
            'gen_ai.request.model': 'fixture-model',
            'gen_ai.system': 'fixture-provider',
        }
        actual = enrich('otel_traces', attrs)
        lf = actual['attributes']

        self.assertEqual(lf['langfuse.environment'], 'benchmark')
        self.assertEqual(lf['langfuse.user.id'], 'stage0-user')
        self.assertEqual(lf['langfuse.session.id'], 'stage0-session')
        self.assertEqual(lf['langfuse.trace.name'], 'stage0-trace')
        self.assertEqual(lf['langfuse.release'], 'stage0-trace-release')
        self.assertEqual(lf['langfuse.version'], 'stage0-version')
        self.assertEqual(actual['name'], 'stage0-generation')
        self.assertEqual(lf['langfuse.trace.metadata.model_task'], 'feature-extraction')
        self.assertEqual(lf['langfuse.trace.metadata.host'], 'fixture-mac')
        self.assertEqual(lf['langfuse.trace.metadata.chip'], 'fixture-chip')
        self.assertEqual(lf['langfuse.trace.metadata.unified_memory_gb'], 128)
        self.assertEqual(lf['langfuse.trace.metadata.power_source'], 'ac')
        self.assertEqual(lf['langfuse.trace.metadata.power_mode'], 'normal')
        self.assertEqual(lf['langfuse.trace.metadata.macos_version'], 'fixture-os')
        self.assertEqual(lf['gen_ai.request.model'], 'fixture-model')
        self.assertEqual(lf['gen_ai.system'], 'fixture-provider')
        self.assertTrue({'stage0-tag', 'stage0-runner', 'stage0-purpose'}.issubset(
            lf['langfuse.trace.tags']))
        for field in ('client', 'runtime', 'runner', 'purpose', 'tier', 'session_id',
                      'trace_user_id', 'trace_name', 'generation_name', 'release',
                      'trace_release', 'trace_version'):
            self.assertEqual(lf[f'langfuse.trace.metadata.{field}'], attrs[f'metadata.{field}'])

    def test_generic_fallback_preserves_litellm_precedence_and_default(self):
        attrs = {
            'metadata.environment': 'benchmark',
            'litellm.metadata.environment': 'legacy-environment',
            'deployment.environment': 'resource-environment',
            'metadata.client': 'generic-client',
            'litellm.metadata.client': 'legacy-client',
            'metadata.session_id': 'generic-session',
            'litellm.metadata.session_id': 'legacy-session',
            'metadata.trace_name': 'generic-trace',
            'litellm.metadata.trace_name': 'legacy-trace',
            'metadata.release': 'generic-release',
            'litellm.metadata.release': 'legacy-release',
        }
        lf = enrich('otel_traces', attrs)['attributes']
        self.assertEqual(lf['langfuse.environment'], 'legacy-environment')
        self.assertEqual(lf['langfuse.session.id'], 'legacy-session')
        self.assertEqual(lf['langfuse.trace.name'], 'legacy-trace')
        self.assertEqual(lf['langfuse.release'], 'legacy-release')
        self.assertEqual(lf['langfuse.trace.metadata.client'], 'legacy-client')
        self.assertEqual(lf['langfuse.trace.metadata.session_id'], 'legacy-session')

        production = enrich('otel_traces', {
            'metadata.environment': 'production',
            'metadata.client': 'generic-client',
            'metadata.session_id': 'generic-session',
            'metadata.user': 'generic-user',
            'metadata.tags': ['generic-tag'],
            'metadata.model_task': 'generic-task',
            'metadata.host': 'fixture-mac',
        })['attributes']
        self.assertEqual(production['langfuse.environment'], 'homelab')
        for field in ('client', 'session_id', 'model_task', 'host'):
            self.assertNotIn(f'langfuse.trace.metadata.{field}', production)
        self.assertNotIn('langfuse.session.id', production)
        self.assertNotIn('langfuse.user.id', production)
        self.assertNotIn('generic-tag', production.get('langfuse.trace.tags', []))

    def test_zero_usage_counts_survive_native_and_alias_sources(self):
        for attrs in [{'gen_ai.usage.input_tokens': 0, 'input_tokens': 99},
                      {'input_tokens': 0}]:
            actual = enrich('otel_traces', attrs)['attributes']
            self.assertEqual(actual['gen_ai.usage.input_tokens'], 0)

    def test_invalid_metadata_is_marked_and_unset_fields_are_removed(self):
        for value in ['malformed', '[]', 'null']:
            px = enrich('otel_traces_phoenix', {'metadata': value})['attributes']
            self.assertTrue(px['litellm.metadata.invalid_json'])
            self.assertEqual(json.loads(px['metadata']), {})
            self.assertNotIn('session.id', px)
            self.assertNotIn('user.id', px)
        for name in ['otel_traces', 'otel_traces_phoenix']:
            pipeline = render(name)
            self.assertEqual(pipeline['functions'][0]['id'], 'drop')
            self.assertTrue(any(step['id'] == 'mask' and step['conf']['rules'] for step in pipeline['functions']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
