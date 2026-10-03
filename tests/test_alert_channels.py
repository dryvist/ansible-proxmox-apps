"""Exercise native Ansible control flow with a local Slack transport fixture.

The fixture replaces only uri calls: no sockets, credentials, or Slack writes.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/alert_delivery_channels"
EVIDENCE = Path(os.environ.get("ALERT_CHANNELS_EVIDENCE", ROOT / ".omo/evidence/alert-channels"))
FIXTURE_ACTION = '''
import json
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from ansible.plugins.action import ActionBase

class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        args = self._task.args
        assert args['headers']['Authorization'] == 'Bearer fixture-only'
        url = urlparse(args['url'])
        assert url.netloc == 'fixture.invalid'
        operation = url.path.rsplit('/', 1)[-1]
        path = Path(os.environ['ALERT_CHANNEL_FIXTURE'])
        state = json.loads(path.read_text())
        state['calls'].append({'operation': operation, 'body': args.get('body'), 'query': url.query})
        result = {'ok': True}
        if state.get('fail') == operation:
            result = {'ok': False, 'error': 'missing_scope'}
        elif operation == 'conversations.list':
            assert args.get('method', 'GET') == 'GET'
            assert parse_qs(url.query) == {'types': ['public_channel'], 'limit': ['1000'], 'exclude_archived': ['true']}
            result.update(channels=list(state['channels'].values()), response_metadata={'next_cursor': state.get('cursor', '')})
        elif operation == 'conversations.create':
            assert args['method'] == 'POST' and args['body_format'] == 'json'
            assert args['body']['is_private'] is False
            name = args['body']['name']
            assert not any(c['name'] == name for c in state['channels'].values())
            ident = 'CCRITICAL' if name.endswith('-critical') else 'CGENERAL'
            channel = {'id': ident, 'name': name, 'is_archived': False, 'is_private': False, 'is_member': True}
            state['channels'][ident] = channel
            result['channel'] = channel
        elif operation == 'conversations.info':
            ident = parse_qs(url.query)['channel'][0]
            result['channel'] = state['channels'][ident]
        elif operation == 'conversations.join':
            assert args['method'] == 'POST' and args['body_format'] == 'json'
            ident = args['body']['channel']
            state['channels'][ident]['is_member'] = True
            result['channel'] = state['channels'][ident]
        else:
            raise AssertionError(operation)
        path.write_text(json.dumps(state))
        return {'changed': False, 'json': result, 'status': 200}
'''


def channel(ident, name, **overrides):
    return {"id": ident, "name": name, "is_archived": False, "is_private": False,
            "is_member": True, **overrides}


class AlertChannels(unittest.TestCase):
    def test_native_channel_lifecycle(self):
        ansible = os.environ.get("ANSIBLE_PLAYBOOK") or shutil.which("ansible-playbook")
        self.assertTrue(ansible, "ANSIBLE_PLAYBOOK must identify an installed ansible-playbook")
        assert isinstance(ansible, str)
        self.assertIs(yaml.safe_load((ROLE / "defaults/main.yml").read_text())["alert_delivery_channels_enabled"], False)
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture_role = root / "roles/alert_delivery_channels"
            shutil.copytree(ROLE, fixture_role)
            # Preserve role control flow; substitute the network boundary only.
            for path in (fixture_role / "tasks").glob("*.yml"):
                def substitute(tasks, inherited_no_log=False):
                    for task in tasks:
                        no_log = task.get("no_log", inherited_no_log)
                        if "ansible.builtin.uri" in task:
                            self.assertTrue(no_log, task["name"])
                            task["fixture_slack"] = task.pop("ansible.builtin.uri")
                        if "block" in task:
                            substitute(task["block"], no_log)
                tasks = yaml.safe_load(path.read_text())
                substitute(tasks)
                path.write_text(yaml.safe_dump(tasks, sort_keys=False))
            plugins = root / "action_plugins"
            plugins.mkdir()
            (plugins / "fixture_slack.py").write_text(FIXTURE_ACTION)
            initial = {"CGENERAL": channel("CGENERAL", "homelab-alerts"),
                       "CCRITICAL": channel("CCRITICAL", "homelab-alerts-critical")}
            cases = [
                ("disabled", {}, {"alert_delivery_channels_enabled": False}, True, []),
                ("create", {}, {}, True, ["conversations.list", "conversations.create", "conversations.info",
                                          "conversations.create", "conversations.info"]),
                ("reuse-and-join", {"channels": {**initial, "CGENERAL": channel("CGENERAL", "homelab-alerts", is_member=False)}}, {}, True,
                 ["conversations.list", "conversations.info", "conversations.join", "conversations.info"]),
                ("explicit-ids", {"channels": initial}, {"alert_delivery_channels_general_id": "CGENERAL", "alert_delivery_channels_critical_id": "CCRITICAL"}, True,
                 ["conversations.info", "conversations.info"]),
                ("missing-token", {}, {"alert_delivery_channels_token": ""}, False, []),
                ("read-scope-refused", {"fail": "conversations.list"}, {}, False, ["conversations.list"]),
                ("partial-list", {"cursor": "next-page"}, {}, False, ["conversations.list"]),
                ("missing-scope", {"fail": "conversations.create"}, {}, False, ["conversations.list", "conversations.create"]),
                ("wrong-id-name", {"channels": initial}, {"alert_delivery_channels_general_id": "CCRITICAL", "alert_delivery_channels_critical_id": "CGENERAL"}, False,
                 ["conversations.info"]),
                ("archived", {"channels": {**initial, "CGENERAL": channel("CGENERAL", "homelab-alerts", is_archived=True)}},
                 {"alert_delivery_channels_general_id": "CGENERAL", "alert_delivery_channels_critical_id": "CCRITICAL"}, False, ["conversations.info"]),
                ("private", {"channels": {**initial, "CGENERAL": channel("CGENERAL", "homelab-alerts", is_private=True)}},
                 {"alert_delivery_channels_general_id": "CGENERAL", "alert_delivery_channels_critical_id": "CCRITICAL"}, False, ["conversations.info"]),
            ]
            for name, state_overrides, variables, success, expected_calls in cases:
                with self.subTest(scenario=name):
                    state = {"channels": {}, "calls": [], **state_overrides}
                    state_path = root / "state.json"
                    state_path.write_text(json.dumps(state))
                    values = {"alert_delivery_channels_enabled": True, "alert_delivery_channels_token": "fixture-only",
                              "alert_delivery_channels_api_url": "https://fixture.invalid/api", **variables}
                    play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
                             "tasks": [{"ansible.builtin.include_role": {"name": "alert_delivery_channels"}, "vars": values}]}]
                    if success and name != "disabled":
                        play[0]["tasks"].append({"ansible.builtin.assert": {"that": [
                            "alert_delivery_channels_general_id == 'CGENERAL'", "alert_delivery_channels_critical_id == 'CCRITICAL'"]}})
                    play_path = root / "play.yml"
                    play_path.write_text(yaml.safe_dump(play))
                    env = {**os.environ, "ANSIBLE_ACTION_PLUGINS": str(plugins), "ANSIBLE_ROLES_PATH": str(root / "roles"),
                           "ANSIBLE_LOCAL_TEMP": str(root / "local"), "ANSIBLE_REMOTE_TEMP": str(root / "remote"),
                           "ALERT_CHANNEL_FIXTURE": str(state_path)}
                    result = subprocess.run([ansible, "-i", "localhost,", str(play_path)], cwd=root,
                                            env=env, capture_output=True, text=True)
                    output = result.stdout + result.stderr
                    (EVIDENCE / f"{name}.log").write_text(output)
                    observed = json.loads(state_path.read_text())
                    (EVIDENCE / f"{name}.json").write_text(json.dumps(observed, indent=2))
                    self.assertEqual(result.returncode == 0, success, output)
                    self.assertNotIn("fixture-only", output)
                    self.assertEqual([c["operation"] for c in observed["calls"]], expected_calls)
                    if name == "create":
                        observed["calls"] = []
                        state_path.write_text(json.dumps(observed))
                        again = subprocess.run([ansible, "-i", "localhost,", str(play_path)], cwd=root,
                                               env=env, capture_output=True, text=True)
                        (EVIDENCE / "idempotence.log").write_text(again.stdout + again.stderr)
                        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
                        self.assertIn("changed=0", again.stdout)
                        self.assertEqual([c["operation"] for c in json.loads(state_path.read_text())["calls"]],
                                         ["conversations.list", "conversations.info", "conversations.info"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
