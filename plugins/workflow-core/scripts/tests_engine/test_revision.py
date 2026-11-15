"""独立复核回归：验证真实边界，不以接口存在代替闭环。"""
import hashlib
import json
import subprocess
import sys
import time
import unittest
import test_protocol
from workflow_engine import EngineError
from workflow_engine.runner import run_checks


class RevisionTests(unittest.TestCase):
    setUp = test_protocol.ProtocolTests.setUp
    call = test_protocol.ProtocolTests.call
    create = test_protocol.ProtocolTests.create
    ready = test_protocol.ProtocolTests.ready
    implemented = test_protocol.ProtocolTests.implemented
    report = test_protocol.ProtocolTests.report

    def test_tdd_requires_alternative_and_step_scope(self):
        task = self.ready('standard')
        with self.assertRaises(EngineError):
            self.call('record_tdd', task, {'adopted': False, 'reason': '原因'})
        with self.assertRaises(EngineError):
            self.call('record_tdd', task, {'adopted': True, 'step_id': 'missing'})
        task = self.call('record_tdd', task, {'adopted': False, 'reason': '原因', 'alternative_validation': '真实测试', 'step_id': '0'})
        task = self.call('finish_step', task, '0', '完成')
        with self.assertRaises(EngineError):
            self.call('finish_step', task, '1', '不可借用上步决策')
        task = self.call('record_tdd', task, {'adopted': True})
        task = self.call('finish_step', task, '1', '任务级决策覆盖')
        self.assertEqual(task['rounds'][-1]['todos'][1]['status'], 'done')

    def test_update_uses_same_step_validation_as_create(self):
        task = self.create()
        for steps in [[{'id': 'x', 'title': 'a'}, {'id': 'x', 'title': 'b'}], [{'id': '', 'title': 'a'}], [{'id': 'x', 'title': []}], 'bad']:
            with self.subTest(steps=steps):
                with self.assertRaises(EngineError):
                    self.call('update_task', task, {'steps': steps})
        self.assertEqual(self.e.status('t')['version'], task['version'])

    def test_repair_same_round_keeps_approval_then_requires_verification(self):
        task = self.implemented('full')
        task = self.call('run', task)
        task = self.call('review', task, self.report(task, 'fail'))
        old_round, old_control = task['current_round'], task['control_digest']
        task = self.call('repair', task, [{'id': 'fix-1', 'title': '原范围内修复'}], '修复评审问题')
        self.assertEqual(task['state'], 'implementing')
        self.assertEqual(task['current_round'], old_round)
        self.assertEqual(task['control_digest'], old_control)
        self.assertNotIn('approval', task['missing'])
        with self.assertRaises(EngineError):
            self.call('run', task)
        task = self.call('record_tdd', task, {'adopted': True, 'step_id': 'fix-1'})
        (self.root / 'code.py').write_text('修复')
        task = self.call('finish_step', task, 'fix-1', '修复完成')
        task = self.call('finish_implementation', task)
        self.assertEqual(task['state'], 'pending_verification')
        task = self.call('run', task)
        task = self.call('review', task, self.report(task))
        self.assertEqual(task['state'], 'review_passed')
        self.assertTrue(any(a['stage'] == 'repair' for a in task['rounds'][-1]['attempts']))

    def test_switch_executor_requires_fresh_read_but_not_new_approval(self):
        task = self.ready('full')
        task = self.call('bind_executor', task, 'agent-B', 'session-B')
        self.assertEqual(task['rounds'][-1]['executor'], 'agent-B')
        self.assertEqual(task['rounds'][-1]['session_id'], 'session-B')
        self.assertIn('baseline', task['missing'])
        self.assertNotIn('approval', task['missing'])
        with self.assertRaises(EngineError):
            self.call('start', task)
        data = (self.root / 'baseline.md').read_bytes()
        receipt = {'path': 'baseline.md', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes_read': len(data), 'complete': True, 'executor': 'agent-B', 'session_id': 'session-B', 'round_id': task['current_round']}
        task = self.call('register_baseline', task, receipt)
        self.assertEqual(self.call('start', task)['state'], 'implementing')

    def test_runner_keeps_bounded_redacted_diagnostics_without_deadlock(self):
        plan = {'checks': [{'id': 'output', 'argv': [sys.executable, '-c', "import os; os.write(1,b'token=very-secret password=hidden\\n'); os.write(2,b'error-detail\\n'); os.write(1,b'x'*2000000); os.write(2,b'y'*2000000)"], 'cwd': '.', 'timeout': 3}]}
        before = time.monotonic()
        result = run_checks(self.root.resolve(), plan)[0]
        self.assertEqual(result['reason'], 'exit')
        self.assertLess(time.monotonic()-before, 5)
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['stdout'].encode()), 8192)
        self.assertLessEqual(len(result['stderr'].encode()), 8192)
        self.assertNotIn('very-secret', result['stdout'])
        self.assertNotIn('hidden', result['stdout'])
        self.assertIn('error-detail', result['stderr'])
        plan['checks'][0]['argv'] = [sys.executable, '-c', "import os,time; os.write(1,b'x'*2000000); os.write(2,b'y'*2000000); time.sleep(30)"]
        plan['checks'][0]['timeout'] = .2
        before = time.monotonic()
        result = run_checks(self.root.resolve(), plan)[0]
        self.assertEqual(result['reason'], 'timeout')
        self.assertTrue(result['truncated'])
        self.assertLess(time.monotonic()-before, 3)

    def test_cli_cannot_create_legacy_and_legacy_mutation_requires_adopt(self):
        from pathlib import Path
        cli = Path(__file__).resolve().parents[1] / 'workflow_engine_cli.py'
        plan = {'version': 1, 'checks': [{'id': 'a', 'argv': [sys.executable, '-c', 'pass'], 'cwd': '.', 'timeout': 2, 'covers': ['format', 'analyze', 'test'], 'acceptance': ['A1']}]}
        file = self.root.parent / 'plan.json'
        file.write_text(json.dumps(plan))
        prefix = [sys.executable, str(cli), '--root', str(self.root), '--db', str(self.e.db)]
        output = subprocess.run(prefix + ['create', '--task', 'new', '--tier', '轻量', '--acceptance', 'A1', '--plan', str(file), '--request', 'cli-create'], capture_output=True, text=True)
        self.assertEqual(output.returncode, 2)
        self.assertEqual(json.loads(output.stdout)['code'], 'ARGUMENT')
        task = self.e.create('old', 'light', ['A1'], plan, 'legacy')
        output = subprocess.run(prefix + ['cancel', '--task', 'old', '--version', str(task['version']), '--request', 'cli-cancel'], capture_output=True, text=True)
        self.assertEqual(output.returncode, 2)
        self.assertEqual(json.loads(output.stdout)['code'], 'PROTOCOL_REQUIRED')

    def test_cli_null_details_cannot_fall_back_to_legacy(self):
        from pathlib import Path
        cli = Path(__file__).resolve().parents[1] / 'workflow_engine_cli.py'
        task = self.create()
        plan = self.root.parent / 'checks.json'
        plan.write_text(json.dumps(task['plan']))
        details = self.root.parent / 'null.json'
        details.write_text('null')
        output = subprocess.run([sys.executable, str(cli), '--root', str(self.root), '--db', str(self.e.db), 'create', '--task', 'bypass', '--tier', '轻量', '--acceptance', 'A1', '--plan', str(plan), '--details', str(details), '--request', 'null-create'], capture_output=True, text=True)
        self.assertEqual(output.returncode, 2, output.stdout)
        with self.assertRaises(EngineError):
            self.e.status('bypass')

    def test_executor_returning_to_old_identity_still_requires_new_read(self):
        task = self.ready('full')
        task = self.call('bind_executor', task, 'agent-B', 'session-B')
        task = self.call('bind_executor', task, 'reader-1', 'session-1')
        self.assertIn('baseline', task['missing'])
        self.assertNotIn('approval', task['missing'])
        self.assertEqual(task['rounds'][-1]['binding_version'], 3)

    def test_failed_checks_repair_and_reverify_same_round(self):
        task = self.implemented(code="from pathlib import Path; raise SystemExit(0 if Path('code.py').read_text() == 'fixed' else 3)")
        task = self.call('run', task)
        self.assertEqual(task['state'], 'failed')
        old_round = task['current_round']
        task = self.call('repair', task, [{'id': 'fix-check', 'title': '修复验证失败'}], '原范围内修复')
        task = self.call('record_tdd', task, {'adopted': True, 'step_id': 'fix-check'})
        (self.root / 'code.py').write_text('fixed')
        task = self.call('finish_step', task, 'fix-check', '修复完成')
        task = self.call('finish_implementation', task)
        task = self.call('run', task)
        task = self.call('review', task, self.report(task))
        self.assertEqual(task['state'], 'review_passed')
        self.assertEqual(task['current_round'], old_round)
        attempts = [a for a in task['rounds'][-1]['attempts'] if a['stage'] == 'verification']
        self.assertEqual([a['status'] for a in attempts], ['failed', 'passed'])

    def test_repair_after_verification_failure_and_snapshot_stale(self):
        task = self.implemented()
        flag = self.root / 'code.py'
        flag.write_text('before')
        task = self.call('run', task)
        (self.root / 'code.py').write_text('after')
        task = self.e.status('t')
        self.assertEqual(task['state'], 'stale')
        control = task['control_digest']
        task = self.call('repair', task, [{'id': 'repair-stale', 'title': '修复失效'}], '原授权内修复')
        self.assertEqual(task['control_digest'], control)
        self.assertEqual(task['state'], 'implementing')
        with self.assertRaises(EngineError):
            self.call('repair', task, [{'id': 'repair-stale', 'title': '重复修复'}], '重复')

    def test_cli_invalid_utf8_does_not_claim_body_complete(self):
        from pathlib import Path
        cli = Path(__file__).resolve().parents[1] / 'workflow_engine_cli.py'
        task = self.ready()
        before = len(task['rounds'][-1]['evidence'])
        (self.root / 'baseline.md').write_bytes(b'invalid-utf8-' + bytes([255]))
        output = subprocess.run([sys.executable, str(cli), '--root', str(self.root), '--db', str(self.e.db), 'read-baseline', '--task', 't', '--path', 'baseline.md', '--executor', 'reader-1', '--session', 'session-1', '--version', str(task['version']), '--request', 'invalid-encoding'], capture_output=True, text=True)
        self.assertEqual(output.returncode, 2, output.stdout)
        self.assertEqual(len(self.e.status('t')['rounds'][-1]['evidence']), before)

    def test_repair_attempt_retains_executor_binding(self):
        task = self.implemented()
        task = self.call('run', task)
        task = self.call('review', task, self.report(task, 'fail'))
        task = self.call('repair', task, [{'id': 'fix-bound', 'title': '修复'}], '原范围修复')
        attempt = task['rounds'][-1]['attempts'][-1]
        self.assertEqual(attempt['executor'], 'reader-1')
        self.assertEqual(attempt['session_id'], 'session-1')
        self.assertEqual(attempt['binding_version'], 1)

    def test_cli_baseline_body_and_over_limit_not_registered(self):
        from pathlib import Path
        cli = Path(__file__).resolve().parents[1] / 'workflow_engine_cli.py'
        task = self.ready()
        prefix = [sys.executable, str(cli), '--root', str(self.root), '--db', str(self.e.db), 'read-baseline', '--task', 't', '--path', 'baseline.md', '--executor', 'reader-1', '--session', 'session-1']
        output = subprocess.run(prefix + ['--version', str(task['version']), '--request', 'body'], capture_output=True, text=True)
        self.assertEqual(output.returncode, 0, output.stdout)
        payload = json.loads(output.stdout)
        self.assertEqual(payload['document']['content'], '工程规范全文')
        task = payload['task']
        before = len(task['rounds'][-1]['evidence'])
        (self.root / 'baseline.md').write_text('长文本'*100)
        output = subprocess.run(prefix + ['--version', str(task['version']), '--request', 'truncated', '--max-bytes', '12'], capture_output=True, text=True)
        payload = json.loads(output.stdout)
        self.assertNotEqual(output.returncode, 0)
        self.assertTrue(payload['document']['truncated'])
        self.assertLessEqual(len(payload['document']['content'].encode()), 12)
        self.assertEqual(len(self.e.status('t')['rounds'][-1]['evidence']), before)
