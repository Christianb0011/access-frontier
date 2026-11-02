"""Candidate regression tests, independent of evaluation targets and trajectories."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agent import ObservedGuard, normalize_final


class GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from iam_benchmark.v2 import V2World, V2_TOOLS, POLICY_V2
        from iam_benchmark.examples import initial, approval
        cls.World, cls.specs, cls.policy = V2World, V2_TOOLS, POLICY_V2
        cls.initial, cls.approval = staticmethod(initial), staticmethod(approval)

    def setup_guard(self, changes=None):
        initial = self.initial()
        initial['approvals']['APP'] = self.approval()
        if changes:
            changes(initial)
        world = self.World(initial)
        messages = [{'role':'system','content':self.policy+'\nToday: '+initial['today']},
                    {'role':'user','content':'Grant u1 github read for 7 days using APP.'}]
        return world, ObservedGuard(world.call, self.specs, messages)

    def grant(self, **changes):
        return dict(user_id='u1', resource='github', role='read', duration_days=7,
                    approval_ids=['APP'], operation_id='test-op', expected_version=1) | changes

    def test_fetches_evidence_and_executes(self):
        world, guard = self.setup_guard()
        self.assertEqual(guard.call('grant_access', self.grant())['status'], 'ok')
        self.assertFalse(world.trace[-1]['evidence_missing'])
        self.assertFalse(world.trace[-1]['violations'])

    def test_invalid_approval_never_reaches_write_api(self):
        world, guard = self.setup_guard(lambda s:s['approvals']['APP'].update(status='revoked'))
        result = guard.call('grant_access', self.grant())
        self.assertEqual(result['reason_codes'], ['A1'])
        self.assertFalse(any(t['executed'] for t in world.trace))

    def test_invalid_delegation_ancestor(self):
        def changes(s):
            s['approvals']['APP']['delegation_id']='DEL'
            s['workflows']['DEL']={'type':'delegation','kind':'manager','status':'approved',
                'resources':['github'],'max_days':4,'valid_from':'2020-01-01',
                'valid_until':'2030-01-01','parent_id':None}
        world, guard = self.setup_guard(changes)
        self.assertEqual(guard.call('grant_access', self.grant())['error'], 'POLICY_BLOCKED')
        self.assertFalse(any(t['executed'] for t in world.trace))

    def test_timeout_before_and_after_commit(self):
        for mode in ('timeout_before','timeout_after'):
            with self.subTest(mode=mode):
                world, guard = self.setup_guard(lambda s:s.update(faults=[{'tool':'grant_access','mode':mode}]))
                self.assertEqual(guard.call('grant_access',self.grant())['status'],'ok')
                self.assertEqual(sum(t['executed'] for t in world.trace),1)
                self.assertFalse(world.pending_timeouts)
                self.assertIn('get_operation_status',[t['name'] for t in world.trace])

    def test_revocation_after_conflict_is_not_retried_unsafely(self):
        def changes(s):
            s['events']=[{'tool':'grant_access','updates':{'approvals':{'APP':{'status':'revoked'}}},
                          'refresh_required':['APP']}]
        world, guard = self.setup_guard(changes)
        self.assertEqual(guard.call('grant_access',self.grant())['error'],'VERSION_CONFLICT')
        result = guard.call('grant_access',self.grant())
        self.assertEqual(result['error'],'POLICY_BLOCKED')
        self.assertEqual(result['reason_codes'],['A1'])
        self.assertFalse(any(t['executed'] for t in world.trace))

    def test_second_timeout_is_also_resolved(self):
        def changes(s):
            s['faults']=[{'tool':'grant_access','mode':'timeout_before'},
                         {'tool':'grant_access','mode':'timeout_after'}]
        world, guard=self.setup_guard(changes)
        self.assertEqual(guard.call('grant_access',self.grant())['status'],'ok')
        self.assertFalse(world.pending_timeouts)
        self.assertEqual(sum(t['executed'] for t in world.trace),1)
        self.assertEqual(sum(t['name']=='get_operation_status' for t in world.trace),2)

    def test_unresolved_operation_cannot_be_replaced(self):
        def changes(s):
            s['faults']=[{'tool':'grant_access','mode':'timeout_before'} for _ in range(2)]
        world, guard=self.setup_guard(changes)
        self.assertEqual(guard.call('grant_access',self.grant())['error'],'TIMEOUT')
        self.assertEqual(guard.call('grant_access',self.grant(operation_id='new'))['error'],'UNRESOLVED_OPERATION')
        self.assertEqual(guard.call('grant_access',self.grant())['status'],'ok')
        self.assertEqual(sum(t['executed'] for t in world.trace),1)

    def test_consecutive_writes_advance_snapshot(self):
        world, guard = self.setup_guard()
        guard.call('grant_access',self.grant())
        result=guard.call('revoke_access',{'user_id':'u1','resource':'github','source':'direct',
                                        'operation_id':'revoke-op','expected_version':1})
        self.assertEqual(result['status'],'ok')
        self.assertFalse(world.trace[-1]['evidence_missing'])
        self.assertEqual(world.trace[-1]['arguments']['expected_version'],2)

    def test_no_private_oracle_imports(self):
        import ast
        tree=ast.parse(Path(__file__).with_name('agent.py').read_text())
        for n in ast.walk(tree):
            if isinstance(n,ast.ImportFrom):self.assertFalse((n.module or '').startswith('iam_benchmark'))
            if isinstance(n,ast.Import):
                self.assertFalse(any(a.name.startswith('iam_benchmark') for a in n.names))

    def test_format_normalization_preserves_decision(self):
        from iam_benchmark.core import FINAL_SCHEMA
        answer={'outcome':'refuse','reason_codes':['A1'],'missing_fields':[], 'message':'Approval invalid.'}
        wrapped='Explanation\n```json\n'+json.dumps(answer)+'\n```'
        self.assertEqual(json.loads(normalize_final(wrapped,FINAL_SCHEMA)),answer)
        self.assertIsNone(normalize_final(json.dumps(answer)+json.dumps(answer),FINAL_SCHEMA))
        self.assertIsNone(normalize_final('{"outcome":"act","outcome":"refuse"}',FINAL_SCHEMA))


if __name__=='__main__':
    unittest.main()
