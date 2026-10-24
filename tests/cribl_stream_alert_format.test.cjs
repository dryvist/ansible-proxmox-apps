#!/usr/bin/env node
// Run the rendered Cribl formatter code against representative Grafana HEC
// events. This tests the deployed Code function, not a second formatter.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const root = `${__dirname}/..`;
const renderedOutputsPath = process.argv[2];
assert.ok(renderedOutputsPath, 'pass the rendered outputs.yml fixture path');
const pipelinePath = `${root}/roles/cribl_stream/templates/pipelines/grafana_alerts_ntfy/conf.yml.j2`;
const pipeline = fs.readFileSync(pipelinePath, 'utf8');
const codeMarker = '      code: |\n';
const formatterOffset = pipeline.indexOf('        const byteLength =');
const codeStart = pipeline.lastIndexOf(codeMarker, formatterOffset);
assert.notEqual(formatterOffset, -1, 'Grafana formatter Code function exists');
const bodyStart = codeStart + codeMarker.length;
const bodyEnd = pipeline.indexOf('\n  - id: unroll', bodyStart);
assert.notEqual(bodyEnd, -1, 'Grafana formatter is followed by native Unroll');
const code = pipeline.slice(bodyStart, bodyEnd)
  .split('\n')
  .map((line) => line.startsWith('        ') ? line.slice(8) : line)
  .join('\n')
  .replaceAll('{{ cribl_stream_alerts_splunk_search_url }}',
    'https://splunk.example.test/en-US/app/search/search?q=search%20sourcetype%3Dgrafana%3Aalert%2A');

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
  return __e.ntfy_parts;
}

const unroll = pipeline.match(/  - id: unroll\n([\s\S]*?)\n  - id: code\n/);
assert.ok(unroll, 'Grafana ntfy pipeline has a native Unroll function');
const unrollSource = unroll[1].match(/^\s+srcExpr: (\S+)$/m)?.[1];
const unrollDestination = unroll[1].match(/^\s+dstField: (\S+)$/m)?.[1];
assert.ok(unrollSource && unrollDestination, 'Unroll source and destination fields are configured');
assert.ok(!unrollSource.startsWith('__') && !unrollDestination.startsWith('__'),
  'the Unroll srcExpr and dstField use no __-prefixed fields');

const pipelineTemplatesDirectory = `${root}/roles/cribl_stream/templates/pipelines`;
const pipelineTemplates = fs.readdirSync(pipelineTemplatesDirectory, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => `${pipelineTemplatesDirectory}/${entry.name}/conf.yml.j2`)
  .filter((path) => fs.existsSync(path));
assert.ok(pipelineTemplates.length > 0, 'Cribl pipeline templates exist');
for (const templatePath of pipelineTemplates) {
  const template = fs.readFileSync(templatePath, 'utf8');
  const functions = template.split(/^  - id: /m).slice(1);
  for (const block of functions) {
    const [id, ...bodyLines] = block.split('\n');
    const body = bodyLines.join('\n');
    assert.notEqual(id, 'parser', `${templatePath} uses the serde id, not parser`);
    if (id === 'unroll') {
      assert.match(body, /^      srcExpr: /m, `${templatePath} Unroll has srcExpr`);
      assert.match(body, /^      dstField: /m, `${templatePath} Unroll has dstField`);
      assert.doesNotMatch(body, /^      (?:srcField|destField): /m,
        `${templatePath} Unroll has no Parser field keys`);
    }
    if (id === 'serde') {
      assert.match(body, /^      srcField: /m, `${templatePath} serde has srcField`);
      assert.match(body, /^      dstField: /m, `${templatePath} serde has dstField`);
      assert.doesNotMatch(body, /^      destField: /m,
        `${templatePath} serde has no destField key`);
    }
  }
}

function classifierCode(source) {
  const marker = '          const payload = JSON.parse(__e._raw);';
  const markerOffset = source.indexOf(marker);
  assert.notEqual(markerOffset, -1, 'Grafana ntfy label classifier exists');
  const start = source.lastIndexOf(codeMarker, markerOffset) + codeMarker.length;
  const end = source.indexOf('\n  - id: drop', start);
  assert.notEqual(end, -1, 'Grafana ntfy label classifier precedes route selection');
  return source.slice(start, end)
    .split('\n')
    .map((line) => line.startsWith('        ') ? line.slice(8) : line)
    .join('\n');
}

const slackPipeline = fs.readFileSync(
  `${root}/roles/cribl_stream/templates/pipelines/grafana_alerts_slack/conf.yml.j2`, 'utf8');
const ntfyClassifier = classifierCode(pipeline);
assert.equal(classifierCode(slackPipeline), ntfyClassifier,
  'direct Slack and ntfy pipelines select the same Grafana alerts');
function routesToNtfy(payload) {
  const __e = {
    sourcetype: 'grafana:alert',
    _raw: typeof payload === 'string' ? payload : JSON.stringify(payload),
  };
  vm.runInNewContext(ntfyClassifier, { __e });
  return __e.github_actions_ntfy;
}
assert.equal(routesToNtfy({ alerts: [{ labels: { ntfy: 'true' } }] }), true,
  'alerts with the ntfy route label use the ntfy path');
assert.equal(routesToNtfy({ alerts: [{ labels: { severity: 'warning' } }] }), false,
  'unlabeled alerts stay on the existing direct path');
assert.equal(routesToNtfy('{"alerts":['), false,
  'malformed envelopes remain on the existing direct path');

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
const rendered = contents(over4k);
assert.ok(rendered.includes('[shortened; full event link below]'), 'oversized summaries get an explicit marker');
const sourceEvidence = rendered.match(/Evidence \(source\): `([^`\n]+)`/);
assert.ok(sourceEvidence, 'source evidence link remains visible');
const sourceEvidenceUrl = new URL(sourceEvidence[1]);
assert.equal(sourceEvidenceUrl.protocol, 'https:');
assert.equal(sourceEvidenceUrl.hostname, 'grafana.example.test');
assert.equal(sourceEvidenceUrl.pathname, '/alert/1');
const fullEventSearch = rendered.match(/Full event search: (\S+)/);
assert.ok(fullEventSearch, 'full event search link remains visible');
const fullEventSearchUrl = new URL(fullEventSearch[1]);
assert.equal(fullEventSearchUrl.protocol, 'https:');
assert.equal(fullEventSearchUrl.hostname, 'splunk.example.test');
assert.equal(over4k[0].priority, 3, 'warnings use the ntfy default priority and reach Zammad');
assert.equal(over4k[0].title, 'Grafana alerts', 'formatted alert title reaches the ntfy part');
assert.equal(over4k[0].click, 'https://splunk.example.test/en-US/app/search/search?q=search%20sourcetype%3Dgrafana%3Aalert%2A',
  'notification click uses the derived trusted full-event search, not an incoming alert URL');
assert.match(contents(over4k), /Evidence \(source\): `https:\/\/grafana\.example\.test\/alert\/1`/,
  'incoming evidence URLs remain visible without becoming active Slack links');

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

const summaryReason = format({ alerts: [{ labels: { alertname: 'SummaryReason' },
  annotations: { summary: 'x' } }] });
assert.match(summaryReason[0].message, /Reason: x/);

const linkless = format({ status: 'firing', alerts: [{ labels: { alertname: 'NoLink', severity: 'warning' },
  annotations: { summary: 'still retained' } }] });
assert.match(linkless[0].message, /no source URL in this alert/);
assert.match(linkless[0].message, /Full event search:/);
assert.match(linkless[0].click, /^https:\/\/splunk\.example\.test/);

const maliciousLink = format({ status: 'firing', alerts: [{
  labels: { alertname: 'UntrustedLink', severity: 'warning' },
  annotations: { summary: 'link is displayed as code' },
  generatorURL: 'https://evil.example.test/<@everyone>',
}] });
assert.equal(maliciousLink[0].click, over4k[0].click, 'untrusted links never control the notification click target');
assert.match(contents(maliciousLink), /`https:\/\/evil\.example\.test\/&lt;@everyone&gt;`/,
  'untrusted evidence is escaped and rendered as inert inline code');

const unknown = format({ status: 'firing', alerts: [{ labels: { alertname: 'UnknownSeverity' }, annotations: {} }] });
assert.equal(unknown[0].priority, 4, 'unknown severity uses conservative priority');
const info = format({ status: 'firing', alerts: [{ labels: { alertname: 'Informational', severity: 'info' }, annotations: {} }] });
assert.equal(info[0].priority, 3, 'informational severity remains on the noncritical ntfy priority');

const inputTemplate = fs.readFileSync(`${root}/roles/cribl_stream/templates/inputs.yml.j2`, 'utf8');
assert.match(inputTemplate, /output: ntfy_grafana_alerts[\s\S]*?pipeline: grafana_alerts_ntfy/);
assert.match(inputTemplate, /output: slack_grafana_alerts[\s\S]*?pipeline: grafana_alerts_slack/);
assert.equal((inputTemplate.match(/output: slack_grafana_alerts/g) || []).length, 1,
  'the required critical destination is connected exactly once');
assert.match(pipeline, /grafana:alert:canary/,
  'canary alert delivery stays available before the flag is set');
assert.match(pipeline, /labels\.ntfy === 'true'/,
  'selected Grafana alerts can use ntfy before the global cutover');
assert.match(pipeline, /cribl_stream_grafana_ntfy_cutover_verified/,
  'the global cutover still controls all other production alerts');
assert.match(slackPipeline, /github_actions_ntfy/,
  'selected alerts leave the direct Slack path to avoid duplicate delivery');
const nautobotPipeline = slackPipeline;
assert.match(nautobotPipeline, /severity === 'critical'/);
assert.match(nautobotPipeline, /sourcetype === 'grafana:alert'/,
  'Grafana remains on its current direct delivery by default');
assert.match(nautobotPipeline, /cribl_stream_grafana_ntfy_cutover_verified/,
  'the existing direct Grafana leg is retired only when cutover is verified');
const roleTasks = fs.readFileSync(`${root}/roles/cribl_stream/tasks/main.yml`, 'utf8');
assert.match(roleTasks, /Require the ntfy destination for Grafana alert delivery/);
assert.match(roleTasks, /cribl_stream_alerts_ntfy_publish_url/,
  'Grafana alert delivery requires both ntfy endpoint URLs');
assert.match(fs.readFileSync(`${root}/roles/cribl_stream/templates/outputs.yml.j2`, 'utf8'),
  /typeof message === 'string'[\s\S]*?typeof priority === 'number'[\s\S]*?: null/,
  'the ntfy webhook only serializes explicitly formatted fields');

const renderedOutputs = fs.readFileSync(renderedOutputsPath, 'utf8');
const outputSections = new Map();
for (const outputId of ['ntfy_grafana_alerts', 'slack_grafana_alerts']) {
  const section = renderedOutputs.match(
    new RegExp(`  ${outputId}:\\n([\\s\\S]*?)(?=\\n  [a-zA-Z0-9_]+:|$)`),
  );
  assert.ok(section, `the rendered ${outputId} output exists`);
  assert.match(section[1], /^    customPayloadExpression: "`\$\{events\}`"$/m,
    `${outputId} renders the Cribl batch payload expression`);
  assert.match(section[1], /^    customEventDelimiter: "\\n"$/m,
    `${outputId} renders the newline event delimiter`);
  outputSections.set(outputId, section[1]);
}
const ntfySection = outputSections.get('ntfy_grafana_alerts');
const publishUrl = ntfySection.match(/^    url: "([^"]+)"$/m)?.[1];
assert.equal(publishUrl, 'https://ntfy.example.invalid/', 'ntfy publishes to the configured root URL');
const expressionLines = ntfySection.match(/^    customSourceExpression: >-\n((?:      .*\n)+)/m)?.[1];
assert.ok(expressionLines, 'the rendered custom webhook expression exists');
const customSourceExpression = expressionLines.split('\n').filter(Boolean).map((line) => line.trim()).join(' ');
const webhookEvent = {
  message: 'compact Grafana summary',
  title: 'Grafana alerts',
  priority: 4,
  tags: ['warning'],
  click: 'https://splunk.example.test/search',
  _raw: '{"alerts":["full event remains in Splunk"]}',
  secret: 'must not be serialized',
};
const webhookBody = vm.runInNewContext(customSourceExpression, webhookEvent);
assert.deepEqual(JSON.parse(webhookBody), {
  topic: 'observability',
  message: 'compact Grafana summary',
  title: 'Grafana alerts',
  priority: 4,
  tags: ['warning'],
  click: 'https://splunk.example.test/search',
}, 'the rendered webhook JSON contains only the ntfy fields, never _raw or other event data');
assert.equal(vm.runInNewContext(customSourceExpression, { ...webhookEvent, message: '' }), null,
  'empty summaries are dropped instead of emitting a topic-only JSON payload');
assert.equal(vm.runInNewContext(customSourceExpression, { ...webhookEvent, message: null }), null,
  'invalid summaries are dropped instead of emitting raw-event fallbacks');

process.stdout.write('Grafana alert formatter acceptance checks passed.\n');
