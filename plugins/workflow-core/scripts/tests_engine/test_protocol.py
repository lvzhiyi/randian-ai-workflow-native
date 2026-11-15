"""任务级协议：使用真实子进程验证闭环和历史隔离。"""
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow_engine import Engine, EngineError


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / 'repo'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / 'baseline.md').write_text('工程规范全文', encoding='utf-8')
        (self.root / 'code.py').write_text('pass')
        self.e = Engine(self.root, base / 'db.sqlite')
        self.counter = 0

    def call(self, method, task, *args):
        self.counter += 1
        return getattr(self.e, method)('t', task['version'], str(self.counter), *args)

    def create(self, tier='light', code='pass'):
        plan = {'version': 1, 'checks': [{'id': 'all', 'argv': [sys.executable, '-c', code], 'cwd': '.', 'timeout': 2, 'covers': ['format', 'analyze', 'test'], 'acceptance': ['A1']}]}
        details = {'goal': '目标', 'scope': ['code.py'], 'source': '用户需求', 'dependencies': [], 'baseline': ['baseline.md'], 'steps': [{'id': str(i), 'title': '步骤'+str(i)} for i in range(3 if tier == 'standard' else 1)]}
        if tier == 'full':
            details['proposal'] = {key: '内容' for key in ['goal', 'scope', 'impact', 'risk', 'rollback', 'acceptance']}
        return self.e.create('t', tier, ['A1'], plan, 'create', details=details)

    def ready(self, tier='light', code='pass'):
        task = self.create(tier, code)
        task = self.call('confirm_tier', task, '人工操作者')
        if tier == 'full':
            task = self.call('approve_proposal', task, '人工操作者', task['control_digest'])
        task = self.call('bind_executor', task, 'reader-1', 'session-1')
        data = (self.root / 'baseline.md').read_bytes()
        task = self.call('register_baseline', task, {'path': 'baseline.md', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes_read': len(data), 'complete': True, 'executor': 'reader-1', 'session_id': 'session-1', 'round_id': task['current_round']})
        return self.call('start', task)

    def implemented(self, tier='light', code='pass'):
        task = self.ready(tier, code)
        task = self.call('record_tdd', task, {'adopted': False, 'reason': '纯文档任务，验证由真实检查执行', 'alternative_validation': '真实检查计划'})
        for todo in task['rounds'][-1]['todos']:
            task = self.call('finish_step', task, todo['id'], '实施完成')
        return self.call('finish_implementation', task)

    def report(self, task, outcome='pass'):
        return {'snapshot': task['snapshot'], 'control_digest': task['control_digest'], 'round_id': task['current_round'], 'axes': {axis: {'conclusion': outcome, 'findings': []} for axis in ['spec', 'standards']}, 'executor': 'reviewer'}

    def test_three_tiers_reach_agent_terminal(self):
        for tier in ['light', 'standard', 'full']:
            with self.subTest(tier=tier):
                if tier != 'light':
                    self.setUp()
                task = self.implemented(tier)
                self.assertEqual(task['state'], 'pending_verification')
                task = self.call('run', task)
                self.assertEqual(task['state'], 'passed')
                task = self.call('review', task, self.report(task))
                self.assertEqual(task['state'], 'review_passed')
                self.assertEqual(task['missing'], [])
                self.assertEqual(task['rounds'][-1]['attempts'][-1]['status'], 'passed')

    def test_baseline_and_approval_are_required(self):
        task = self.create('full')
        with self.assertRaises(EngineError):
            self.call('start', task)
        task = self.call('confirm_tier', task, '人')
        with self.assertRaises(EngineError):
            self.call('start', task)
        task = self.call('approve_proposal', task, '人', task['control_digest'])
        with self.assertRaises(EngineError):
            self.call('register_baseline', task, {'path': 'baseline.md', 'complete': False})
        with self.assertRaises(EngineError):
            self.call('start', task)

    def test_review_failure_retry_and_read_only_invalidation(self):
        task = self.implemented()
        task = self.call('run', task)
        report = self.report(task)
        report['axes']['spec']['findings'] = [{'id': 'f1', 'required': True, 'resolved': False, 'message': '遗漏'}]
        task = self.call('review', task, report)
        self.assertEqual(task['state'], 'review_failed')
        resolved = self.report(task)
        resolved['axes']['spec']['findings'] = [{'id': 'f1', 'required': True, 'resolved': True, 'message': '已修复遗漏'}]
        task = self.call('review', task, resolved)
        self.assertEqual(task['state'], 'review_passed')
        before = self.e.db.read_bytes()
        (self.root / 'code.py').write_text('changed')
        observed = self.e.status('t')
        self.assertEqual(observed['state'], 'stale')
        self.assertEqual(before, self.e.db.read_bytes())
        self.assertEqual(observed['version'], task['version'])
        task = self.call('run', observed)
        task = self.call('review', task, self.report(task))
        attempts = task['rounds'][-1]['attempts']
        self.assertGreaterEqual(len([a for a in attempts if a['stage'] == 'verification']), 2)
        self.assertTrue(any(a['status'] == 'invalidated' for a in attempts))

    def test_cancel_return_new_round_cas_and_history(self):
        task = self.ready()
        task = self.call('cancel', task)
        with self.assertRaises(EngineError):
            self.call('start', task)
        with self.assertRaises(EngineError):
            self.call('run', task)
        task = self.call('return_task', task, '人工退回', '人')
        self.assertEqual(len(task['rounds']), 2)
        self.assertEqual(task['rounds'][0]['state'], 'cancelled')
        self.assertEqual(task['rounds'][1]['evidence'], [])
        with self.assertRaises(EngineError):
            self.e.confirm_tier('t', task['version']-1, 'cas', '人')
        history = self.e.history('t')
        self.assertEqual(history[0]['action'], 'create')
        self.assertEqual(history[-2]['action'], 'cancel')
        self.assertEqual(history[-1]['action'], 'return_task')
        self.assertEqual(history[-2]['task']['current_round'], task['rounds'][0]['id'])
        self.assertEqual(history[-1]['task']['current_round'], task['current_round'])
        self.assertEqual([h['task']['version'] for h in history], list(range(1, task['version']+1)))

    def test_failure_is_attempt_and_no_review_before_checks(self):
        task = self.implemented(code='raise SystemExit(8)')
        with self.assertRaises(EngineError):
            self.call('review', task, self.report(task))
        task = self.call('run', task)
        self.assertEqual(task['state'], 'failed')
        self.assertEqual(task['rounds'][-1]['attempts'][-1]['status'], 'failed')
        first = task['rounds'][-1]['attempts'][-1]['id']
        task = self.call('run', task)
        self.assertNotEqual(first, task['rounds'][-1]['attempts'][-1]['id'])

    def test_old_request_cannot_replay_terminal_across_rounds(self):
        task = self.implemented()
        old_version = task['version']
        task = self.e.run('t', old_version, 'verify-original')
        task = self.call('review', task, self.report(task))
        task = self.call('return_task', task, '重新实施', '人')
        replay = self.e.run('t', old_version, 'verify-original')
        self.assertEqual(replay['current_round'], task['current_round'])
        self.assertEqual(replay['state'], 'created')

    def test_dependency_incomplete_blocks_and_explicit_resume(self):
        task = self.create()
        task = self.call('update_task', task, {'dependencies': [{'id': 'upstream', 'status': 'pending'}]})
        self.assertIn('dependencies', task['missing'])
        task = self.call('update_task', task, {'dependencies': [{'id': 'upstream', 'status': 'done'}]})
        self.assertNotIn('dependencies', task['missing'])

    def test_baseline_changed_invalidates_terminal_and_truncated_receipt(self):
        task = self.implemented()
        task = self.call('run', task)
        task = self.call('review', task, self.report(task))
        (self.root / 'baseline.md').write_text('新规范')
        task = self.e.status('t')
        self.assertIn('baseline', task['missing'])
        with self.assertRaises(EngineError):
            self.call('run', task)
        task = self.call('bind_executor', task, 'reader-1', 'session-1')
        data = (self.root / 'baseline.md').read_bytes()
        receipt = {'path': 'baseline.md', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes_read': len(data)-1, 'complete': True, 'executor': 'reader-1', 'session_id': 'session-1', 'round_id': task['current_round']}
        with self.assertRaises(EngineError):
            self.call('register_baseline', task, receipt)

    def test_explicit_resume_same_round_and_stale_review_rejected(self):
        task = self.ready()
        same = self.call('resume', task)
        self.assertEqual(same['current_round'], task['current_round'])
        self.assertEqual(same['state'], 'implementing')
        same = self.call('cancel', same)
        with self.assertRaises(EngineError):
            self.call('resume', same)

    def test_readiness_missing_and_wrong_round_receipt(self):
        task = self.create()
        task = self.call('update_task', task, {'goal': '', 'scope': [], 'source': '', 'dependencies': None})
        for field in ['goal', 'scope', 'source', 'dependencies']:
            self.assertIn(field, task['missing'])
        task = self.call('bind_executor', task, 'reader-1', 'session-1')
        data = (self.root / 'baseline.md').read_bytes()
        with self.assertRaises(EngineError):
            self.call('register_baseline', task, {'path': 'baseline.md', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes_read': len(data), 'complete': True, 'executor': 'reader-1', 'session_id': 'session-1', 'round_id': 'other'})

    def test_required_findings_cannot_disappear_on_retry(self):
        task = self.implemented()
        task = self.call('run', task)
        report = self.report(task)
        report['axes']['standards']['findings'] = [{'id': 'required-1', 'required': True, 'resolved': False, 'message': '必修'}]
        task = self.call('review', task, report)
        task = self.call('review', task, self.report(task))
        self.assertEqual(task['state'], 'review_failed')

    def test_non_tdd_reason_does_not_substitute_real_checks(self):
        task = self.ready()
        with self.assertRaises(EngineError):
            self.call('finish_step', task, '0', '完成')
        with self.assertRaises(EngineError):
            self.call('record_tdd', task, {'adopted': False})
        task = self.call('record_tdd', task, {'adopted': False, 'reason': '文档变更', 'alternative_validation': '真实检查计划'})
        with self.assertRaises(EngineError):
            self.call('finish_implementation', task)
        task = self.call('finish_step', task, '0', '完成')
        task = self.call('finish_implementation', task)
        with self.assertRaises(EngineError):
            self.call('review', task, self.report(task))

    def test_standard_short_plan_rejects_wrong_size(self):
        task = self.create('standard')
        task = self.call('update_task', task, {'steps': [{'id': 'only', 'title': '不足三步'}]})
        self.assertIn('steps', task['missing'])

    def test_v2_cancel_cannot_be_bypassed_by_legacy_complete(self):
        task = self.implemented()
        task = self.call('run', task)
        task = self.call('review', task, self.report(task))
        task = self.call('cancel', task)
        with self.assertRaises(EngineError):
            self.call('complete', task)

    def test_runner_exception_becomes_error_attempt(self):
        from unittest.mock import patch
        task = self.implemented()
        with patch('workflow_engine.engine.run_checks', side_effect=RuntimeError('unexpected')):
            task = self.call('run', task)
        self.assertEqual(task['state'], 'failed')
        self.assertEqual(task['rounds'][-1]['attempts'][-1]['status'], 'error')
        self.assertNotIn('operation', task)

    def test_review_report_bound_to_snapshot_and_control(self):
        task = self.implemented()
        task = self.call('run', task)
        report = self.report(task)
        report['snapshot'] = 'old'
        with self.assertRaises(EngineError):
            self.call('review', task, report)
        (self.root / 'code.py').write_text('changed')
        with self.assertRaises(EngineError):
            self.call('review', task, self.report(task))

    def test_adopt_legacy_task_has_real_full_path(self):
        plan = {'version': 1, 'checks': [{'id': 'a', 'argv': [sys.executable, '-c', 'pass'], 'cwd': '.', 'timeout': 2, 'covers': ['format', 'analyze', 'test'], 'acceptance': ['A1']}]}
        task = self.e.create('t', 'full', ['A1'], plan, 'old-create')
        details = {'goal': '目标', 'scope': ['代码'], 'source': '需求', 'dependencies': [], 'baseline': ['baseline.md'], 'steps': [{'id': 's', 'title': '实施'}], 'proposal': {key: '内容' for key in ['goal', 'scope', 'impact', 'risk', 'rollback', 'acceptance']}}
        task = self.call('adopt_protocol', task, details)
        self.assertEqual(task['protocol_version'], 2)
        task = self.call('confirm_tier', task, '人')
        task = self.call('approve_proposal', task, '人', task['control_digest'])
        task = self.call('bind_executor', task, 'reader-1', 'session-1')
        data = (self.root / 'baseline.md').read_bytes()
        task = self.call('register_baseline', task, {'path': 'baseline.md', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes_read': len(data), 'complete': True, 'executor': 'reader-1', 'session_id': 'session-1', 'round_id': task['current_round']})
        self.assertEqual(self.call('start', task)['state'], 'implementing')

    def test_status_via_new_engine_does_not_write_database(self):
        self.ready()
        before = self.e.db.read_bytes()
        Engine(self.root, self.e.db).status('t')
        self.assertEqual(before, self.e.db.read_bytes())

    def test_control_update_invalidates_approval_but_wording_does_not(self):
        task = self.ready('full')
        old = task['control_digest']
        task = self.call('update_task', task, {'note': '只改说明措辞'})
        self.assertEqual(old, task['control_digest'])
        task = self.call('update_task', task, {'scope': ['new.py']})
        self.assertNotEqual(old, task['control_digest'])
        self.assertIn('tier_confirmation', task['missing'])
        self.assertIn('approval', task['missing'])


if __name__ == '__main__':
    unittest.main()
