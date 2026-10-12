#!/usr/bin/env node
// Run the rendered Cribl formatter code against representative Grafana HEC
// events. This tests the deployed Code function, not a second formatter.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const root = `${__dirname}/..`;
const pipelinePath = `${root}/roles/cribl_stream/templates/pipelines/grafana_alerts_ntfy/conf.yml.j2`;
const pipeline = fs.readFileSync(pipelinePath, 'utf8');
const codeMarker = '      code: |\n';
const codeStart = pipeline.indexOf(codeMarker);
assert.notEqual(codeStart, -1, 'Grafana formatter Code function exists');
const bodyStart = codeStart + codeMarker.length;
const bodyEnd = pipeline.indexOf('\n  - id: unroll', bodyStart);
assert.notEqual(bodyEnd, -1, 'Grafana formatter is followed by native Unroll');
const code = pipeline.slice(bodyStart, bodyEnd)
  .split('\n')
  .map((line) => line.startsWith('        ') ? line.slice(8) : line)
  .join('\n')
  .replaceAll('{{ cribl_stream_alerts_splunk_search_url }}',
    'https://splunk.example.test/en-US/app/search/search?q=search%20sourcetype%3Dgrafana%3Aalert');

function format(payload, extra = {}) {
  const __e = {
    sourcetype: 'grafana:alert',
    index: 'ansible',
    _raw: typeof payload === 'string' ? payload : JSON.stringify(payload),
    ...extra,
  };
  vm.runInNewContext(code, { __e, C: { Encode: {
    base64: (value) => Buffer.from(String(value), 'utf8').toString('base64'),
  } } });
  return __e.__ntfyParts;
}

function contents(parts) {
  for (const part of parts) {
    assert.ok(Buffer.byteLength(part.message + part.title, 'utf8') <= 3500);
  }
  return parts.map((part) => part.message.replace(/^Grafana alert report \([^\n]*\)\n/, '')).join('');
}

const longSummary = 'A'.repeat(4500);
const over4k = format({
  status: 'firing',
  alerts: [{ labels: { alertname: 'LongSummary', severity: 'warning', instance: 'node-a' },
    annotations: { summary: longSummary }, generatorURL: 'https://grafana.example.test/alert/1' }],
});
assert.equal(over4k.length, 1, 'one compact alert record stays whole');
assert.ok(contents(over4k).includes('[shortened; full event link below]'), 'oversized summaries get an explicit marker');
assert.ok(contents(over4k).includes('https://grafana.example.test/alert/1'), 'source evidence link remains visible');
assert.ok(contents(over4k).includes('https://splunk.example.test/'), 'full event search link remains visible');
assert.equal(over4k[0].priority, 3, 'warnings use the ntfy default priority and reach Zammad');
assert.equal(over4k[0].click, 'https://grafana.example.test/alert/1');

const manyAlerts = Array.from({ length: 14 }, (_, index) => ({
  labels: { alertname: `Many${index}`, severity: 'warning', instance: `entity-${index}` },
  annotations: { summary: `finding-marker-${index}-${'b'.repeat(2700)}` },
}));
const over32k = format({ status: 'firing', alerts: manyAlerts });
const largeBody = contents(over32k);
assert.ok(over32k.length > 1, 'an envelope with many alerts becomes bounded continuations');
for (let index = 0; index < manyAlerts.length; index += 1) {
  const message = over32k.find((part) => part.message.includes(`alert=Many${index}`));
  assert.ok(message, `alert ${index} remains present`);
  assert.ok(message.message.includes(`finding-marker-${index}-`), `alert ${index} summary stays with its record`);
}
assert.ok(!largeBody.includes('...and '), 'no alert count cutoff is used');

const unicode = '火🔥é'.repeat(1600);
const unicodeParts = format({
  status: 'firing',
  alerts: [{ labels: { alertname: 'Unicode', severity: 'warning' }, annotations: { summary: unicode } }],
});
assert.equal(unicodeParts.length, 1, 'Unicode alert record remains whole');
assert.ok(contents(unicodeParts).includes('[shortened; full event link below]'), 'Unicode summary receives byte-safe compaction');
assert.ok(!contents(unicodeParts).includes('\uFFFD'), 'Unicode compaction does not introduce replacement characters');

const malformed = format('{"alerts":[', { index: 'ansible' });
assert.equal(malformed.length, 1);
assert.match(malformed[0].message, /could not be parsed/);
assert.match(malformed[0].message, /https:\/\/splunk\.example\.test/);
assert.ok(!malformed[0].message.includes('{"alerts"'), 'malformed raw JSON is not sent');
assert.equal(malformed[0].priority, 4, 'malformed data fails conservatively');
const malformedEntry = format({ status: 'firing', alerts: [null] });
assert.match(contents(malformedEntry), /malformed alert entry 1/);
assert.equal(malformedEntry[0].priority, 4, 'malformed alert entries fail conservatively');

const resolved = format({ status: 'resolved', alerts: [{ status: 'resolved',
  labels: { alertname: 'Recovered', severity: 'critical' }, annotations: { summary: 'recovered' } }] });
assert.match(resolved[0].message, /RESOLVED/);
assert.match(resolved[0].message, /recovered/);
assert.equal(resolved[0].priority, 4, 'critical recovery is preserved at high priority');

const noData = format({ status: 'firing', alerts: [{ status: 'firing', value: null,
  labels: { alertname: 'DatasourceNoData', severity: 'critical' },
  annotations: { grafana_state_reason: 'NoData' } }] });
assert.match(noData[0].message, /Reason: NoData/);
assert.match(noData[0].message, /Summary: \(not provided\)/);
assert.match(noData[0].message, /Value: \(not provided\)/);
const queryError = format({ status: 'firing', alerts: [{ status: 'firing', value: null,
  labels: { alertname: 'DatasourceError', severity: 'critical' },
  annotations: { grafana_state_reason: 'Error' }, values: { A: { value: null } } }] });
assert.match(queryError[0].message, /Reason: Error/);
assert.match(queryError[0].message, /Value: A=null/);

const linkless = format({ status: 'firing', alerts: [{ labels: { alertname: 'NoLink', severity: 'warning' },
  annotations: { summary: 'still retained' } }] });
assert.match(linkless[0].message, /no source URL in this alert/);
assert.match(linkless[0].message, /Full event search:/);
assert.match(linkless[0].click, /^https:\/\/splunk\.example\.test/);

const unknown = format({ status: 'firing', alerts: [{ labels: { alertname: 'UnknownSeverity' }, annotations: {} }] });
assert.equal(unknown[0].priority, 4, 'unknown severity uses conservative priority');

const inputTemplate = fs.readFileSync(`${root}/roles/cribl_stream/templates/inputs.yml.j2`, 'utf8');
assert.match(inputTemplate, /output: ntfy_grafana_alerts[\s\S]*?pipeline: grafana_alerts_ntfy/);
assert.match(inputTemplate, /output: slack_grafana_alerts[\s\S]*?pipeline: grafana_alerts_slack/);
assert.equal((inputTemplate.match(/output: slack_grafana_alerts/g) || []).length, 1,
  'the existing critical Nautobot output is connected exactly once');
assert.match(pipeline, /filter: "sourcetype !== 'grafana:alert'"/,
  'non-Grafana HEC events are dropped before ntfy output');
const nautobotPipeline = fs.readFileSync(
  `${root}/roles/cribl_stream/templates/pipelines/grafana_alerts_slack/conf.yml.j2`, 'utf8');
assert.match(nautobotPipeline, /severity === 'critical'/);
assert.doesNotMatch(nautobotPipeline, /sourcetype === 'grafana:alert'/);
assert.match(fs.readFileSync(`${root}/roles/cribl_stream/templates/outputs.yml.j2`, 'utf8'),
  /typeof message === 'string'[\s\S]*?typeof priority === 'number'[\s\S]*?: null/,
  'the ntfy webhook only serializes explicitly formatted fields');

process.stdout.write('Grafana alert formatter acceptance checks passed.\n');
