"""Offline workflow contracts and opt-in real PostgreSQL queue scenarios.

Run: python3 -m unittest discover -s tests -p 'test_alert_delivery.py' -v
Set ALERT_DELIVERY_TEST_DSN to an isolated disposable database for SQL scenarios.
The PostgreSQL tests drop only the alert_delivery schema in that test database.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / 'roles/alert_delivery/files'


def workflow(name):
    return json.loads((FILES / (name + '.json')).read_text())


class WorkflowContracts(unittest.TestCase):
    def test_ticket_worker_absent_from_notification_graph(self):
        for name in ('ingest', 'slack'):
            data = workflow(name)
            encoded = json.dumps(data).lower()
            self.assertNotIn('zammad', encoded)
            self.assertNotIn('alert_delivery.ticket', encoded)
            self.assertNotIn('alert_delivery.enrichment', encoded)
            self.assertNotIn('hypotheses', encoded)
        # Removing the entire incident runtime leaves the notification graph intact.
        self.assertNotIn('search.messages', json.dumps(workflow('slack')))
        self.assertEqual(workflow('slack')['connections']['Uncertain retry']['main'][1][0]['node'], 'Post Slack')

    def test_all_graph_edges_resolve_and_native_nodes_only(self):
        for name in ('ingest', 'slack', 'tickets', 'enrichment'):
            data = workflow(name)
            names = {n['name'] for n in data['nodes']}
            self.assertEqual(len(names), len(data['nodes']))
            for n in data['nodes']:
                self.assertIn(n['type'], {'n8n-nodes-base.scheduleTrigger', 'n8n-nodes-base.postgres',
                                         'n8n-nodes-base.httpRequest', 'n8n-nodes-base.if', 'n8n-nodes-base.set', 'n8n-nodes-base.aggregate'})
            for source, outputs in data['connections'].items():
                self.assertIn(source, names)
                for branch in outputs['main']:
                    for target in branch:
                        self.assertIn(target['node'], names)

    def test_deadman_publisher_preserves_entity_and_explicit_recovery(self):
        source = (ROOT / 'roles/service_deadman/templates/service-deadman-validate.sh.j2').read_text()
        function = source[source.index('ntfy_publish() {'):source.index('# Healthy:')]
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / 'payload.txt'
            script = 'curl() { printf "%s\\n" "$@" > "$PAYLOAD_CAPTURE"; }\n' + function + '\nntfy_publish example urgent rotating_light "Synthetic observation" "$STATUS"\n'
            payloads = []
            for host, status in [('host-a','firing'),('host-a','resolved'),('host-b','firing')]:
                env = {**os.environ, 'PAYLOAD_CAPTURE': str(capture), 'SOURCE_HOST': host,
                       'NTFY_URL':'https://example.invalid/fixture', 'STATUS':status}
                result = subprocess.run(['bash','-c',script], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = capture.read_text().splitlines()
                payloads.append(json.loads(args[args.index('--data-binary')+1]))
            self.assertEqual(payloads[0]['entity'], payloads[1]['entity'])
            self.assertNotEqual(payloads[0]['entity'], payloads[2]['entity'])
            self.assertEqual(payloads[1]['status'], 'resolved')
            self.assertEqual(payloads[0]['source'], 'service_deadman')
            self.assertEqual(payloads[0]['impact'], 'service_unavailable')
            print('deadman producer: stable same-host identity, distinct cross-host identity, explicit recovery')

    def test_expressions_parse_as_javascript(self):
        if not shutil.which('node'):
            self.skipTest('node not installed')
        expressions = []
        def visit(value):
            if isinstance(value, dict):
                for v in value.values():
                    visit(v)
            elif isinstance(value, list):
                for v in value:
                    visit(v)
            elif isinstance(value, str) and value.startswith('={{'):
                expressions.append(value[3:-2].replace('__IMPACTS__', '[]').replace('__CRITICAL_RULES__', '[]').replace('__ZAMMAD_CUSTOMER_ID__', '1'))
        for name in ('ingest', 'slack', 'tickets', 'enrichment'):
            visit(workflow(name))
        result = subprocess.run(['node', '-e', 'for (const x of JSON.parse(process.argv[1])) new Function("return ("+x+")"); console.log("parsed "+JSON.parse(process.argv[1]).length+" expressions")', json.dumps(expressions)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        print(result.stdout.strip())

    def test_topic_and_channel_http_errors_do_not_abort_other_items(self):
        ingest = workflow('ingest')
        poll = next(node for node in ingest['nodes'] if node['name'] == 'Poll ntfy')
        self.assertEqual(poll['onError'], 'continueErrorOutput')
        self.assertEqual(ingest['connections']['Poll ntfy']['main'][1], [])
        slack = workflow('slack')
        for name in ('Find prior Slack delivery', 'Post Slack'):
            node = next(node for node in slack['nodes'] if node['name'] == name)
            self.assertEqual(node['onError'], 'continueRegularOutput')

    def test_zammad_pending_and_closed_fixtures(self):
        if not shutil.which('node'):
            self.skipTest('node not installed')
        resolve = next(n for n in workflow('tickets')['nodes'] if n['name'] == 'Resolve active ticket')
        expression = resolve['parameters']['assignments']['assignments'][0]['value'][3:-2]
        script = r'''
const assert = require('node:assert/strict');
const states=[{id:1,name:'open',state_type_id:1},{id:2,name:'pending reminder',state_type_id:2},{id:3,name:'resolved',state_type_id:3}];
const $=name=>({item:{json:name==='Ticket states'?{body:states}:name==='Ticket state types'?{body:[{id:1,name:'open'},{id:2,name:'pending reminder'},{id:3,name:'closed'}]}:{incident_key:'abc'}}});
let $json={pages:[{body:[{id:10,state_id:2,title:'example [incident:abc]'}]}]};
let resolve=()=>eval(process.argv[1]);
assert.equal(resolve().active.id,10);
$json={pages:[{body:[{id:10,state_id:3,title:'example [incident:abc]'}]}]};
assert.equal(resolve().active,null); assert.equal(resolve().previous,10);
$json={pages:[{body:[{id:11,state_id:1,title:'example [incident:other]'}]}]};
assert.equal(resolve().active,null);
$json={pages:[{body:Array.from({length:100},(_,id)=>({id,state_id:3,title:'example [incident:abc]'}))},{body:[{id:101,state_id:2,title:'example [incident:abc]'}]}]};
assert.equal(resolve().active.id,101);
console.log('pending retained; closed recurrence; unrelated identity rejected; active match on second search page');
'''
        result = subprocess.run(['node', '-e', script, expression], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        print(result.stdout.strip())


@unittest.skipUnless(os.environ.get('ALERT_DELIVERY_TEST_DSN') and shutil.which('psql'),
                     'requires psql and isolated ALERT_DELIVERY_TEST_DSN')
class PostgreSQLBehavior(unittest.TestCase):
    def sql(self, sql):
        result = subprocess.run(['psql', os.environ['ALERT_DELIVERY_TEST_DSN'], '-X', '-At', '-v', 'ON_ERROR_STOP=1'], input=sql, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def setUp(self):
        self.sql('DROP SCHEMA IF EXISTS alert_delivery CASCADE;\n' + (FILES / 'ledger.sql').read_text())

    def ingest(self, identifier='one', entity='service-a', impact='widespread_outage', canonical=True, status='firing'):
        body = json.dumps({'source':'fixture','rule':'availability','entity':entity,'impact':impact,'summary':'Synthetic observation','status':status,'details_url':'https://example.invalid/observations'}) if canonical else 'legacy unknown entity'
        event = json.dumps({'event':'message','topic':'fixture','id':identifier,'time':1700000120,'message':body})
        return self.sql("SELECT alert_delivery.ingest($fixture$" + event + "$fixture$, ARRAY['widespread_outage'], ARRAY['fixture:availability']);")

    def test_ticket_worker_killed_notification_still_ready(self):
        self.ingest()
        self.sql('SELECT id FROM alert_delivery.claim_ticket();')
        # Ticket lease is deliberately abandoned, modelling worker death/HTTP500.
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.claim_notification('general');"), '1')
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.claim_notification('critical');"), '1')
        self.assertEqual(self.sql('SELECT count(*) FROM alert_delivery.ticket WHERE acknowledged_at IS NULL;'), '1')

    def test_replay_duplicate_and_cursor_overlap(self):
        self.assertEqual(self.ingest(), '1')
        self.assertEqual(self.ingest(), '0')
        self.assertEqual(self.sql('SELECT count(*) FROM alert_delivery.ticket;'), '1')
        self.assertEqual(self.sql('SELECT seen-120 FROM alert_delivery.cursor;'), '1700000000')
        self.assertEqual(self.sql("SELECT alert_delivery.ingest('{\"event\":\"keepalive\"}', ARRAY[]::text[], ARRAY[]::text[]);"), '0')

    def test_unknown_identity_and_strict_impact(self):
        self.ingest('unknown-a', canonical=False)
        self.ingest('unknown-b', canonical=False)
        self.ingest('benign', impact='service_unavailable')
        self.assertEqual(self.sql('SELECT count(*) FROM alert_delivery.incident;'), '3')
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.notification WHERE channel='critical';"), '0')

    def test_storm_is_grouped_and_ticket_operations_retained(self):
        for i in range(8):
            self.ingest(str(i), 'entity-'+str(i))
        self.assertEqual(self.sql("SELECT kind FROM alert_delivery.claim_notification('general');"), 'overflow')
        self.assertEqual(self.sql('SELECT count(*) FROM alert_delivery.ticket;'), '8')
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.notification WHERE channel='general' AND acknowledged_at IS NULL;"), '9')

    def test_recovery_stops_reminders_without_closing_ticket(self):
        self.ingest('firing')
        self.ingest('recovery', status='resolved')
        self.assertEqual(self.sql('SELECT active FROM alert_delivery.incident;'), 'f')
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.notification WHERE channel='critical' AND kind='escalation' AND cancelled_at IS NULL;"), '1')
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.notification WHERE channel='critical' AND kind='recovery' AND body NOT LIKE '%<!channel>%';"), '1')
        self.assertEqual(self.sql('SELECT count(*) FROM alert_delivery.ticket WHERE acknowledged_at IS NULL;'), '2')
        self.ingest('recurrence')
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.notification WHERE channel='general' AND kind='initial';"), '2')

    def test_attachment_evidence_link_survives_legacy_payload(self):
        event = json.dumps({'event': 'message', 'topic': 'fixture', 'id': 'attachment',
                            'time': 1700000120, 'title': 'Synthetic attachment',
                            'message': 'You received a file: evidence.json',
                            'attachment': {'url': 'https://evidence.example.test/file.json'}})
        self.sql("SELECT alert_delivery.ingest($fixture$" + event + "$fixture$, ARRAY[]::text[], ARRAY[]::text[]);")
        self.assertEqual(self.sql('SELECT details_url FROM alert_delivery.incident;'),
                         'https://evidence.example.test/file.json')
        self.assertIn('https://evidence.example.test/file.json',
                      self.sql("SELECT body FROM alert_delivery.notification WHERE channel='general';"))
        self.assertIn('https://evidence.example.test/file.json',
                      self.sql('SELECT body FROM alert_delivery.ticket;'))

    def test_digest_reminder_and_escalation(self):
        self.ingest('low', impact='unknown')
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.notification WHERE channel='critical';"), '0')
        self.ingest('escalation')
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.notification WHERE channel='critical';"), '1')
        self.sql("UPDATE alert_delivery.incident SET last_general=now()-interval '31 minutes',last_critical=now()-interval '31 minutes'; SELECT alert_delivery.periodic();")
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.notification WHERE kind IN ('digest','reminder');"), '2')

    def test_critical_reminder_until_explicit_recovery_without_new_input(self):
        self.ingest()
        self.sql("UPDATE alert_delivery.incident SET last_seen=now()-interval '2 hours',last_critical=now()-interval '31 minutes',last_general=now()-interval '31 minutes'; SELECT alert_delivery.periodic();")
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.notification WHERE kind='reminder';"), '1')
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.notification WHERE kind='digest';"), '0')
        self.ingest('recovery', status='resolved')
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.notification WHERE kind='reminder' AND cancelled_at IS NOT NULL;"), '1')
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.notification WHERE kind='escalation' AND cancelled_at IS NULL;"), '1')

    def test_channel_new_post_budget(self):
        self.ingest()
        self.sql("UPDATE alert_delivery.budget SET used=0;")
        self.sql("INSERT INTO alert_delivery.budget VALUES('general',now(),5) ON CONFLICT(channel) DO UPDATE SET used=5,window_started=now();")
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.claim_notification('general');"), '0')
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.claim_notification('critical');"), '1')

    def test_poison_line_does_not_block_valid_following_events(self):
        event = json.dumps({'event':'message','topic':'fixture','id':'valid-after-poison','time':1700000120,'message':'plain event'})
        batch = 'not json\n' + json.dumps({'event':'message','id':'missing-topic'}) + '\n' + event
        result = self.sql("SELECT alert_delivery.ingest($fixture$" + batch + "$fixture$, ARRAY[]::text[], ARRAY[]::text[]);")
        self.assertEqual(result, '1')
        self.assertEqual(self.sql('SELECT count(*) FROM alert_delivery.quarantine;'), '2')
        self.assertEqual(self.sql('SELECT count(*) FROM alert_delivery.ticket;'), '1')

    def test_native_splunk_envelope_keeps_host_identity(self):
        for identifier, host in [('a','one'),('b','one'),('c','two')]:
            payload = {'search_name':'synthetic-search','sid':identifier,'results_link':'https://example.invalid/results','result':{'host':host,'summary':'Synthetic observation'}}
            event = json.dumps({'event':'message','topic':'fixture','id':identifier,'time':1700000120,'message':json.dumps(payload)})
            self.sql("SELECT alert_delivery.ingest($fixture$" + event + "$fixture$, ARRAY[]::text[], ARRAY[]::text[]);")
        self.assertEqual(self.sql("SELECT count(*) FROM alert_delivery.incident WHERE source='splunk';"), '2')

    def test_retry_backoff_and_additive_upgrade(self):
        self.ingest()
        self.sql('SELECT id FROM alert_delivery.claim_ticket();')
        self.assertEqual(self.sql("SELECT available_at >= now()+interval '290 seconds' FROM alert_delivery.ticket;"), 't')
        self.sql((FILES / 'ledger.sql').read_text())
        self.assertEqual(self.sql('SELECT count(*) FROM alert_delivery.ticket;'), '1')

    def test_retention_preserves_undelivered_work(self):
        self.ingest()
        self.sql('SELECT alert_delivery.periodic();')
        self.assertEqual(self.sql('SELECT count(*) FROM alert_delivery.message;'), '0')
        self.assertEqual(self.sql('SELECT count(*) FROM alert_delivery.ticket WHERE acknowledged_at IS NULL;'), '1')
        self.assertEqual(self.sql('SELECT count(*) FROM alert_delivery.notification WHERE acknowledged_at IS NULL;'), '2')

    def test_ticket_lease_expiry_and_same_incident_serialization(self):
        self.ingest('first')
        self.ingest('second')
        self.assertEqual(self.sql('SELECT count(*) FROM alert_delivery.claim_ticket();'), '1')
        self.assertEqual(self.sql('SELECT count(*) FROM alert_delivery.claim_ticket();'), '0')
        self.sql("UPDATE alert_delivery.ticket SET lease_until=now()-interval '1 second',available_at=now()-interval '1 second' WHERE attempts=1;")
        self.assertEqual(self.sql('SELECT attempts FROM alert_delivery.claim_ticket();'), '2')


if __name__ == '__main__':
    unittest.main()
