#!/usr/bin/env node
// Execute the plumbing span-drop filter expression extracted from each trace leg.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const root = `${__dirname}/..`;
const defaultsPath = `${root}/roles/cribl_stream/defaults/main/40-otel-langfuse-pipeline.yml`;
const templatePaths = [
  `${root}/roles/cribl_stream/templates/pipelines/otel_traces/conf.yml.j2`,
  `${root}/roles/cribl_stream/templates/pipelines/otel_traces_phoenix/conf.yml.j2`,
  `${root}/roles/cribl_stream/templates/pipelines/otel_traces_to_splunk/conf.yml.j2`,
];
const defaults = fs.readFileSync(defaultsPath, 'utf8');

function readList(name) {
  const match = defaults.match(new RegExp(`^${name}:\\n((?:[ \\t]+- [^\\n]*\\n)+)`, 'm'));
  assert.ok(match, `${name} is a YAML list in the defaults`);
  return [...match[1].matchAll(/^[ \t]+- ([^\n]+)$/gm)].map((item) => item[1].trim());
}

const dropNames = readList('cribl_stream_otel_drop_span_names');
const dropPrefixes = readList('cribl_stream_otel_drop_span_prefixes');

function compileFilter(template, emptyPrefixes = false) {
  const line = template.match(/^ *filter: '\{\{ cribl_stream_otel_drop_span_names \| to_json \}\}.*'$/m);
  assert.ok(line, 'the plumbing drop filter is one single-quoted line');
  const rendered = line[0]
    .replace(/^ *filter: '/, '')
    .replace(/'$/, '')
    .replace('{{ cribl_stream_otel_drop_span_names | to_json }}', () => JSON.stringify(dropNames))
    .replace('{{ cribl_stream_otel_drop_span_prefixes | to_json }}', () =>
      JSON.stringify(emptyPrefixes ? [] : dropPrefixes));
  assert.ok(!rendered.includes('{{'), 'default values resolve every template expression');
  return rendered;
}

function drops(renderedFilter, name) {
  return vm.runInNewContext(renderedFilter, { name });
}

for (const templatePath of templatePaths) {
  const template = fs.readFileSync(templatePath, 'utf8');
  const leg = templatePath.match(/pipelines\/([^/]+)\//)[1];
  const filter = compileFilter(template);
  const filterWithoutPrefixes = compileFilter(template, true);

  for (const name of ['redis.mget router_budgets', 'cache.set llm_response',
    'dispatch_tool_call_with_state', 'auth /metrics/', 'auth', 'transport_worker']) {
    assert.equal(drops(filter, name), true, `${leg}: drops "${name}"`);
  }
  for (const name of ['litellm_request', 'redis', 'my.redis.get']) {
    assert.equal(drops(filter, name), false, `${leg}: keeps "${name}"`);
  }
  assert.equal(drops(filter, undefined), false, `${leg}: keeps spans with no name`);
  assert.equal(drops(filterWithoutPrefixes, 'redis.get auth_objects'), false,
    `${leg}: an empty prefix list drops nothing extra`);
}

console.log('Cribl span-drop filter tests passed for the Langfuse, Phoenix and Splunk legs.');
