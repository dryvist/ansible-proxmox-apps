"""Render and execute the Langfuse pipeline with router caller attributes."""
import unittest

from test_cribl_litellm_trace_contract import enrich


class CallerAttribution(unittest.TestCase):
    def router_turn(self, caller, profile, session, turn):
        return enrich('otel_traces', {
            'litellm.metadata.client': caller,
            'litellm.metadata.profile': profile,
            'litellm.metadata.trace_user_id': caller,
            'litellm.metadata.trace_name': f'{caller}-chat',
            'litellm.metadata.session_id': session,
            'litellm.metadata.generation_name': f'turn-{turn}',
            'gen_ai.request.model': 'shared-model',
            'gen_ai.operation.name': 'chat',
            'langfuse.trace.tags': ['existing'],
        }, traceId=f'{turn:032x}',
            startTimeUnixNano=str((1700006400 + turn * 3600) * 1000000000))

    def test_two_agents_keep_distinct_names_users_sessions_and_tags(self):
        first = self.router_turn('agent-a', 'interactive', 'session-a', 1)['attributes']
        second = self.router_turn('agent-b', 'batch', 'session-b', 2)['attributes']
        for actual, caller, profile, session in (
                (first, 'agent-a', 'interactive', 'session-a'),
                (second, 'agent-b', 'batch', 'session-b')):
            self.assertEqual(actual['langfuse.trace.name'], f'{caller}-chat')
            self.assertEqual(actual['langfuse.user.id'], caller)
            self.assertEqual(actual['langfuse.session.id'], session)
            self.assertCountEqual(actual['langfuse.trace.tags'], ['existing', caller, profile])
            self.assertEqual(actual['langfuse.trace.metadata.client'], caller)
            self.assertEqual(actual['langfuse.trace.metadata.profile'], profile)

    def test_multi_turn_session_groups_distinct_requests_across_hours(self):
        turns = [self.router_turn('agent-a', 'interactive', 'session-a', turn)
                 for turn in (1, 2, 3)]
        self.assertEqual(len({event['traceId'] for event in turns}), 3)
        self.assertEqual([event['name'] for event in turns], ['turn-1', 'turn-2', 'turn-3'])
        for event in turns:
            attrs = event['attributes']
            self.assertEqual(attrs['langfuse.session.id'], 'session-a')
            self.assertEqual(attrs['langfuse.trace.name'], 'agent-a-chat')
            self.assertEqual(attrs['langfuse.user.id'], 'agent-a')
            self.assertCountEqual(attrs['langfuse.trace.tags'],
                                  ['existing', 'agent-a', 'interactive'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
