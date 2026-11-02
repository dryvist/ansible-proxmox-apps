#!/usr/bin/env node
// Execute the Langfuse trace-hour Code function extracted from the pipeline.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const vm = require('node:vm');

const root = `${__dirname}/..`;
const defaultsPath = `${root}/roles/cribl_stream/defaults/main/40-otel-langfuse-pipeline.yml`;
const pipelinePath = `${root}/roles/cribl_stream/templates/pipelines/otel_traces/conf.yml.j2`;
const defaults = fs.readFileSync(defaultsPath, 'utf8');
const pipeline = fs.readFileSync(pipelinePath, 'utf8');

function readList(name) {
  const match = defaults.match(new RegExp(`^${name}:\\n((?:[ \\t]+- [^\\n]*\\n)+)`, 'm'));
  assert.ok(match, `${name} is a YAML list in the defaults`);
  return [...match[1].matchAll(/^[ \t]+- ([^\n]+)$/gm)].map((item) => item[1].trim());
}

function readNumber(name) {
  const match = defaults.match(new RegExp(`^${name}:\\s*(\\d+)\\s*$`, 'm'));
  assert.ok(match, `${name} is a number in the defaults`);
  return Number(match[1]);
}

const bucketSeconds = readNumber('cribl_stream_otel_trace_bucket_seconds');
const nanosecondsPerSecond = readNumber('cribl_stream_otel_ns_per_second');
const defaultBucketSources = readList('cribl_stream_otel_bucket_sources');
const sessionSources = readList('cribl_stream_otel_session_id_sources');
assert.ok(bucketSeconds > 0, 'the default bucket is enabled');

const stepStart = pipeline.indexOf('  # 3. Re-key Langfuse spans by clock hour');
const stepEnd = pipeline.indexOf('\n  # 4. Identity.', stepStart);
assert.notEqual(stepStart, -1, 'the trace-hour step is present in the template');
assert.notEqual(stepEnd, -1, 'the trace-hour step precedes identity normalization');
const stepTemplate = pipeline.slice(stepStart, stepEnd);
const codeMatch = stepTemplate.match(/^      code: >-\n((?:        .*(?:\n|$))+)/m);
assert.ok(codeMatch, 'the trace-hour step has a folded Code function body');
const codeTemplate = codeMatch[1].replace(/^ {8}/gm, '');

function compileCode(bucketSources = defaultBucketSources) {
  const rendered = codeTemplate
    .replaceAll('{{ cribl_stream_otel_bucket_sources | to_json }}', JSON.stringify(bucketSources))
    .replaceAll('{{ cribl_stream_otel_session_id_sources | to_json }}', JSON.stringify(sessionSources))
    .replaceAll('{{ cribl_stream_otel_ns_per_second }}', String(nanosecondsPerSecond))
    .replaceAll('{{ cribl_stream_otel_trace_bucket_seconds }}', String(bucketSeconds));
  assert.ok(!rendered.includes('{{'), 'default values resolve every template expression');
  return rendered;
}

function applyStep(event, code) {
  const context = {
    __e: event,
    C: {
      Mask: {
        md5: (value) => crypto.createHash('md5').update(String(value), 'utf8').digest('hex'),
      },
    },
  };
  vm.runInNewContext(code, context);
  return event;
}

function eventStream(shape, withSession = true) {
  const originalTraceId = '0123456789abcdef0123456789abcdef';
  const events = [];
  for (let hour = 0; hour < 5; hour += 1) {
    for (let span = 0; span < 3; span += 1) {
      const startSeconds = 1_700_006_400 + hour * bucketSeconds + 60 + span * 10;
      const attributes = withSession ? { 'session.id': 'coding-session-42' } : {};
      events.push({
        [shape.traceKey]: originalTraceId,
        [shape.timeKey]: String(BigInt(startSeconds) * BigInt(nanosecondsPerSecond)),
        spanId: `${hour.toString(16).padStart(8, '0')}${span.toString(16).padStart(8, '0')}`,
        parentSpanId: span === 0 ? undefined : `${hour.toString(16).padStart(8, '0')}00000000`,
        name: ['root', 'session', 'generation'][span],
        attributes,
      });
    }
  }
  return events;
}

const originalTraceId = '0123456789abcdef0123456789abcdef';
const shapes = [
  { name: 'camelCase', traceKey: 'traceId', timeKey: 'startTimeUnixNano' },
  { name: 'snake_case', traceKey: 'trace_id', timeKey: 'start_time_unix_nano' },
];

for (const shape of shapes) {
  const code = compileCode();
  const events = eventStream(shape);
  const originalTimes = events.map((event) => event[shape.timeKey]);
  const originalParents = events.map((event) => event.parentSpanId);
  const transformed = events.map((event) => applyStep(event, code));
  assert.equal(transformed.length, 15, `${shape.name}: all three span kinds pass through`);
  const traceIds = new Set(transformed.map((event) => event[shape.traceKey]));
  assert.equal(traceIds.size, 5, `${shape.name}: five clock hours produce five trace ids`);
  assert.ok([...traceIds].every((traceId) => /^[0-9a-f]{32}$/.test(traceId)),
    `${shape.name}: bucket ids are 32 hex characters`);
  assert.deepEqual([...new Set(transformed.map((event) => event.attributes['langfuse.session.id']))],
    ['coding-session-42'], `${shape.name}: all spans retain the emitted session id`);
  assert.ok(transformed.every((event) =>
    event.attributes['langfuse.trace.metadata.original_trace_id'] === originalTraceId),
  `${shape.name}: all spans preserve their original trace id`);
  assert.ok(transformed.every((event, index) => event.parentSpanId === originalParents[index]),
    `${shape.name}: parentSpanId remains unchanged`);
  assert.ok(transformed.every((event, index) => event[shape.timeKey] === originalTimes[index]),
    `${shape.name}: the start-time field remains unchanged`);
  assert.deepEqual([...new Set(transformed.map((event) => event.name))],
    ['root', 'session', 'generation']);

  if (shape.name === 'snake_case') {
    assert.ok(transformed.every((event) => event.trace_id !== originalTraceId),
      'snake_case: the new id is written to trace_id');
    assert.ok(transformed.every((event) => !Object.hasOwn(event, 'traceId')),
      'snake_case: no camelCase traceId field is added');
  }

  const noSessionEvents = eventStream(shape, false);
  const noSessionSnapshots = noSessionEvents.map((event) => JSON.stringify(event));
  for (const event of noSessionEvents) applyStep(event, code);
  assert.ok(noSessionEvents.every((event, index) =>
    JSON.stringify(event) === noSessionSnapshots[index]),
  `${shape.name}: spans without a bucket source stay untouched`);
  assert.ok(noSessionEvents.every((event) => event[shape.traceKey] === originalTraceId),
    `${shape.name}: spans without a bucket session source keep their original trace id`);
  assert.ok(noSessionEvents.every((event) => !('langfuse.session.id' in event.attributes)),
    `${shape.name}: spans without a bucket session source get no session id`);

  const precedenceEvent = {
    [shape.traceKey]: originalTraceId,
    [shape.timeKey]: String(BigInt(1_700_006_460) * BigInt(nanosecondsPerSecond)),
    attributes: {
      'litellm.metadata.session_id': 'bucket-session',
      'langfuse.session.id': 'existing-langfuse-session',
    },
  };
  applyStep(precedenceEvent, compileCode(['litellm.metadata.session_id']));
  assert.equal(precedenceEvent.attributes['langfuse.session.id'], 'existing-langfuse-session',
    `${shape.name}: existing Langfuse session id wins`);

  const customSourceEvent = {
    [shape.traceKey]: originalTraceId,
    [shape.timeKey]: String(BigInt(1_700_006_460) * BigInt(nanosecondsPerSecond)),
    attributes: { x: 'custom-bucket-source' },
  };
  applyStep(customSourceEvent, compileCode(['x']));
  assert.equal(customSourceEvent.attributes['langfuse.session.id'], originalTraceId,
    `${shape.name}: custom bucket source falls back to the original trace id as the session`);

  const deterministicA = eventStream(shape).map(
    (event) => applyStep(event, code)[shape.traceKey]);
  const deterministicB = eventStream(shape).map(
    (event) => applyStep(event, code)[shape.traceKey]);
  assert.deepEqual(deterministicA, deterministicB,
    `${shape.name}: the same span timestamps produce the same bucket ids`);
}

console.log('Cribl Langfuse trace-hour bucket tests passed for camelCase and snake_case events.');
