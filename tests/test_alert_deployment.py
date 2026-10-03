import json
from pathlib import Path
import unittest

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


class DeploymentBoundaries(unittest.TestCase):
    def test_notification_compose_needs_no_ticket_or_model_credentials(self):
        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        env.filters['ternary'] = lambda value, yes, no: yes if value else no
        template = env.from_string((ROOT / 'roles/n8n_docker/templates/docker-compose.yml.j2').read_text())
        context = {
            'n8n_docker_app_service': 'n8n', 'n8n_docker_app_image': 'n8nio/n8n:fixture',
            'n8n_docker_container_name': 'n8n-notifications',
            'n8n_docker_memory_limit': '1g', 'n8n_docker_cpu_limit': '1.0',
            'n8n_docker_db_host': 'delivery-db.example.test', 'n8n_docker_postgres_port': 5432,
            'n8n_docker_db_name': 'n8n_notifications', 'n8n_docker_db_user': 'n8n_notifications',
            'n8n_docker_db_password': 'synthetic-db', 'n8n_docker_encryption_key': 'synthetic-notify-key',
            'n8n_docker_fqdn': 'n8n-notifications.example.test', 'n8n_docker_web_port': 5678,
            'n8n_docker_seed_workflow': False, 'n8n_docker_execution_concurrency': 2,
            'n8n_docker_execution_timeout': 120, 'n8n_docker_bind_address': '127.0.0.1',
            'n8n_docker_app_data_dir': '/opt/n8n-notifications/data',
            'n8n_docker_app_internal_data': '/home/node/.n8n',
            'n8n_docker_restart_policy': 'unless-stopped',
        }
        notification = yaml.safe_load(template.render(context))['services']['n8n']
        self.assertEqual(notification['ports'], ['127.0.0.1:5678:5678'])
        runtime_env = notification['environment']
        self.assertEqual(runtime_env['DB_POSTGRESDB_DATABASE'], 'n8n_notifications')
        self.assertEqual(runtime_env['N8N_BLOCK_ENV_ACCESS_IN_NODE'], 'true')
        self.assertEqual(runtime_env['N8N_CONCURRENCY_PRODUCTION_LIMIT'], '2')
        self.assertFalse(any('LITELLM' in key or 'ZAMMAD' in key for key in runtime_env))
        context.update(n8n_docker_seed_workflow=True, n8n_docker_llm_base_url='https://model.example.test/v1',
                       n8n_docker_llm_api_key='synthetic-ai', n8n_docker_seed_model='cheap')
        existing = yaml.safe_load(template.render(context))['services']['n8n']['environment']
        self.assertEqual(existing['LITELLM_ROUTER_KEY'], 'synthetic-ai')

    def test_credentials_and_databases_are_separate(self):
        values = load('playbooks/alert-delivery/vars.yml')
        notification_types = [row['type'] for row in values['alert_delivery_notification_credentials']
                              if isinstance(row, dict)]
        self.assertNotIn('zammadTokenAuthApi', notification_types)
        self.assertNotIn('openAiApi', notification_types)
        incident_types = [row['type'] for row in values['alert_delivery_incident_credentials']
                          if isinstance(row, dict)]
        self.assertIn('httpHeaderAuth', incident_types)
        self.assertIn('openAiApi', incident_types)
        zammad = next(row for row in values['alert_delivery_incident_credentials']
                      if isinstance(row, dict) and 'zammad' in row['id'])
        self.assertEqual(zammad['data']['name'], 'Authorization')
        self.assertTrue(zammad['data']['value'].startswith('Token token='))
        for node in json.loads((ROOT / 'roles/alert_delivery/files/tickets.json').read_text())['nodes']:
            if node['type'] == 'n8n-nodes-base.httpRequest':
                self.assertEqual(node['parameters']['authentication'], 'genericCredentialType')
                self.assertEqual(node['parameters']['genericAuthType'], 'httpHeaderAuth')
        databases = load('inventory/group_vars/postgres_ai_group.yml')
        self.assertEqual({d['name'] for d in databases['postgres_ai_alert_delivery_databases']},
                         {'n8n_notifications', 'alert_delivery'})
        self.assertEqual({d['name'] for d in databases['postgres_ai_base_databases']},
                         {'hindsight', 'litellm'})

    def test_normal_converge_uses_one_cutover_authority(self):
        settings = load('inventory/group_vars/all.yml')
        self.assertFalse(settings['alert_delivery_enabled'])
        self.assertFalse(settings['alert_delivery_cutover_verified'])
        values = load('playbooks/alert-delivery/vars.yml')
        self.assertNotIn('alert_delivery_enabled', values)
        self.assertNotIn('alert_delivery_cutover_verified', values)
        for key in ('ntfy_docker_slack_delivery_verified', 'ntfy_docker_zammad_manage_subscriber'):
            self.assertIn('alert_delivery_cutover_verified', settings[key])
        imports = [play.get('ansible.builtin.import_playbook', play.get('import_playbook'))
                   for play in load('playbooks/site.yml')]
        for stage in ('00-secrets', '05-databases', '10-notifications', '20-incidents', '30-cutover'):
            self.assertIn('alert-delivery/' + stage + '.yml', imports)

    def test_merge_gate_cannot_skip_delivery_contract(self):
        jobs = load('.github/workflows/ci-gate.yml')['jobs']
        self.assertNotIn('if', jobs['alert-delivery'])
        self.assertIn('alert-delivery', jobs['gate']['needs'])
        for step in jobs['gate']['steps']:
            self.assertNotIn('alert-delivery', step.get('with', {}).get('allowed-skips', ''))
            self.assertNotIn('alert-delivery', step.get('with', {}).get('allowed-failures', ''))
        contract = load('.github/workflows/_alert-delivery-contract.yml')['jobs']['alert-delivery']
        self.assertIn('postgres', contract['services'])
        commands = '\n'.join(step.get('run', '') for step in contract['steps'])
        self.assertIn('test_alert_delivery.py', commands)
        self.assertIn('test_alert_deployment.py', commands)

    def test_applied_revisions_follow_activation_readiness(self):
        tasks = load('roles/n8n_docker/tasks/main.yml')
        names = [task['name'] for task in tasks]
        self.assertLess(names.index('Activate managed workflow changes before reporting readiness'),
                        names.index('Record managed revisions after successful activation'))
        self.assertLess(names.index('Verify managed instance readiness after activation'),
                        names.index('Record managed revisions after successful activation'))
        for filename in ('managed_auth', 'managed_workflow'):
            encoded = json.dumps(load('roles/n8n_docker/tasks/' + filename + '.yml'))
            self.assertNotIn('ansible.builtin.copy', encoded)
            self.assertIn('/dev/stdin', encoded)


if __name__ == '__main__':
    unittest.main()
