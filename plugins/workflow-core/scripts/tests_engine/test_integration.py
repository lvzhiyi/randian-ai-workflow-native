"""最终集成门禁：配置、内联输入、会话查询和资源上限。"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
import test_protocol
from workflow_engine import EngineError
from workflow_engine.runner import run_checks


class IntegrationTests(unittest.TestCase):
    setUp = test_protocol.ProtocolTests.setUp
    call = test_protocol.ProtocolTests.call
    create = test_protocol.ProtocolTests.create
    ready = test_protocol.ProtocolTests.ready
    implemented = test_protocol.ProtocolTests.implemented
    report = test_protocol.ProtocolTests.report

    def config(self, command):
        (self.root / 'ai-workflow.yaml').write_text('version: 1\nverify:\n  light:\n    - ' + command + '\n')

    def test_config_checks_are_required_create_update_run(self):
        self.config(sys.executable + ' -c "raise SystemExit(7)"')
        with self.assertRaises(EngineError):
            self.create()
        (self.root / 'ai-workflow.yaml').unlink()
        task = self.implemented()
        self.config(sys.executable + ' -c "raise SystemExit(7)"')
        with self.assertRaises(EngineError):
            self.call('run', task)
        with self.assertRaises(EngineError):
            self.call('update_task', task, {'note': '不可绕过配置'})
        plan = task['plan']
        plan['checks'].append({'id': 'configured', 'argv': [sys.executable, '-c', 'raise SystemExit(7)'], 'cwd': '.', 'timeout': 2, 'covers': ['test'], 'acceptance': ['A1']})
        task = self.call('update_task', task, {'plan': plan})
        self.assertEqual(task['state'], 'created')

    def test_configured_docs_check_cannot_be_omitted(self):
        from workflow_engine.config_checks import enforce
        (self.root / 'ai-workflow.yaml').write_text('version: 1\nverify:\n  light: python3 -m unittest\n  docs: python3 scripts/check_docs.py\n', encoding='utf-8')
        plan = {'checks': [{'argv': ['python3', '-m', 'unittest'], 'cwd': '.'}]}
        with self.assertRaises(EngineError):
            enforce(self.root, 'light', plan)
        plan['checks'].append({'argv': ['python3', 'scripts/check_docs.py'], 'cwd': '.'})
        self.assertTrue(enforce(self.root, 'light', plan))

    def test_configured_command_really_runs_and_shell_rejected(self):
        command = sys.executable + ' -c "raise SystemExit(7)"'
        self.config(command)
        task = self.create(code='raise SystemExit(7)')
        self.assertTrue(task['verify_config_digest'])
        self.config(sys.executable + ' -c "pass" && echo bypass')
        with self.assertRaises(EngineError) as error:
            self.call('update_task', task, {'note': 'bad'})
        self.assertEqual(error.exception.code, 'VERIFY_CONFIG')

    def test_refine_steps_keeps_approval_and_done_history(self):
        task = self.ready('full')
        task = self.call('record_tdd', task, {'adopted': True})
        task = self.call('finish_step', task, '0', '已完成')
        old = task['control_digest']
        task = self.call('refine_steps', task, [{'id': 'detail-1', 'title': '原范围细化', 'parent_id': '0'}], '细化实现')
        self.assertEqual(task['control_digest'], old)
        self.assertNotIn('approval', task['missing'])
        self.assertEqual(task['rounds'][-1]['todos'][0]['status'], 'done')
        self.assertTrue(any(e['kind'] == 'steps_refined' for e in task['rounds'][-1]['evidence']))
        with self.assertRaises(EngineError):
            self.call('refine_steps', task, {'scope': ['扩大范围']}, '非法')
        with self.assertRaises(EngineError):
            self.call('refine_steps', task, [{'id': 'x', 'title': '越界', 'parent_id': 'missing'}], '非法')

    def test_baseline_limit_applies_to_registration_and_refresh(self):
        task = self.ready()
        data = b'x' * (1048576+1)
        (self.root / 'baseline.md').write_bytes(data)
        with self.assertRaises(EngineError):
            self.e._baseline_bytes('baseline.md')
        receipt = {'path': 'baseline.md', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes_read': len(data), 'complete': True, 'executor': 'reader-1', 'session_id': 'session-1', 'round_id': task['current_round']}
        with self.assertRaises(EngineError):
            self.call('register_baseline', task, receipt)
        self.assertIn('baseline', self.e.status('t')['missing'])

    def test_baseline_public_reader_rejects_negative_unbounded_limit(self):
        self.create()
        for limit in (-1, 0, True, 'bad'):
            with self.subTest(limit=limit):
                with self.assertRaises(EngineError):
                    self.e.read_baseline_bytes('baseline.md', limit)

    def test_readonly_session_lookup_unique_and_ambiguous(self):
        task = self.ready()
        before = self.e.db.read_bytes()
        self.assertEqual(self.e.task_for_session('session-1')['id'], 't')
        self.assertIsNone(self.e.task_for_session('missing'))
        self.assertEqual(self.e.db.read_bytes(), before)
        second = self.e.create('second', 'light', ['A1'], task['plan'], 'second-create', details={'goal': '其他', 'steps': [{'id': 's', 'title': '实施'}]})
        self.e.bind_executor('second', second['version'], 'second-bind', 'other', 'session-1')
        with self.assertRaises(EngineError) as error:
            self.e.task_for_session('session-1')
        self.assertEqual(error.exception.code, 'SESSION_AMBIGUOUS')

    def test_runner_deadline_includes_escaped_pipe_holder(self):
        code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time;time.sleep(.8)'], start_new_session=True); time.sleep(.05)"
        plan = {'checks': [{'id': 'escape', 'argv': [sys.executable, '-c', code], 'cwd': '.', 'timeout': .2}]}
        before = time.monotonic()
        result = run_checks(self.root.resolve(), plan)[0]
        elapsed = time.monotonic()-before
        self.assertEqual(result['reason'], 'timeout')
        self.assertLess(elapsed, .6)
        self.assertTrue(result['truncated'])

    def test_session_lookup_returns_stale_terminal_for_repair(self):
        task = self.implemented()
        task = self.call('run', task)
        task = self.call('review', task, self.report(task))
        self.assertIsNone(self.e.task_for_session('session-1'))
        (self.root / 'code.py').write_text('changed')
        task = self.e.task_for_session('session-1')
        self.assertIsNotNone(task)
        self.assertEqual(task['state'], 'stale')

    def test_config_valid_plan_runs_every_command_and_change_invalidates(self):
        command = sys.executable + ' -c "pass"'
        self.config(command)
        task = self.implemented()
        task = self.call('run', task)
        self.assertEqual(task['state'], 'passed')
        self.assertEqual(len(task['results']), 1)
        task = self.call('review', task, self.report(task))
        self.config(sys.executable + ' -c "raise SystemExit(4)"')
        before = self.e.db.read_bytes()
        task = self.e.status('t')
        self.assertEqual(task['state'], 'stale')
        self.assertIn('verify_config', task['missing'])
        self.assertEqual(before, self.e.db.read_bytes())

    def test_each_tier_config_rejects_missing_command_and_executes_failure(self):
        for tier in ('light', 'standard', 'full'):
            with self.subTest(tier=tier):
                (self.root / 'ai-workflow.yaml').write_text('version: 1\nverify:\n  ' + tier + ':\n    - ' + sys.executable + ' -c "raise SystemExit(7)"\n')
                with self.assertRaises(EngineError):
                    self.create(tier=tier)
        # 完整档沿用同一真实失败命令创建闭环，不能因为配置覆盖自报而判成功。
        task = self.implemented('full', 'raise SystemExit(7)')
        task = self.call('run', task)
        self.assertEqual(task['state'], 'failed')
        self.assertEqual(task['results'][0]['exit_code'], 7)

    def test_refinement_requires_completion_before_verify(self):
        task = self.ready('full')
        task = self.call('record_tdd', task, {'adopted': True})
        task = self.call('finish_step', task, '0', '完成原步骤')
        task = self.call('refine_steps', task, [{'id': 'detail', 'title': '细化', 'parent_id': '0'}], '原范围细化')
        with self.assertRaises(EngineError):
            self.call('finish_implementation', task)
        task = self.call('finish_step', task, 'detail', '细化完成')
        task = self.call('finish_implementation', task)
        task = self.call('run', task)
        task = self.call('review', task, self.report(task))
        self.assertEqual(task['state'], 'review_passed')

    def test_inline_file_and_file_json_are_mutually_exclusive(self):
        cli = Path(__file__).resolve().parents[1] / 'workflow_engine_cli.py'
        output = subprocess.run([sys.executable, str(cli), 'update-task', '--task', 'x', '--version', '1', '--request', 'x', '--file', 'x.json', '--file-json', '{}'], capture_output=True, text=True)
        self.assertEqual(output.returncode, 2)
        self.assertEqual(json.loads(output.stdout)['code'], 'ARGUMENT')

    def test_cli_inline_and_missing_db_read_does_not_create(self):
        cli = Path(__file__).resolve().parents[1] / 'workflow_engine_cli.py'
        missing = self.root.parent / 'absent' / 'state.sqlite'
        prefix = [sys.executable, str(cli), '--root', str(self.root), '--db', str(missing)]
        output = subprocess.run(prefix + ['status', '--task', 'missing'], capture_output=True, text=True)
        self.assertNotEqual(output.returncode, 0)
        self.assertFalse(missing.parent.exists())
        task = self.create()
        details = {'goal': '内联', 'scope': ['code.py'], 'source': '用户', 'dependencies': [], 'baseline': ['baseline.md'], 'steps': [{'id': 's', 'title': '实施'}]}
        prefix = [sys.executable, str(cli), '--root', str(self.root), '--db', str(self.e.db)]
        output = subprocess.run(prefix + ['create', '--task', 'inline', '--tier', '轻量', '--acceptance', 'A1', '--plan-json', json.dumps(task['plan']), '--details-json', json.dumps(details), '--request', 'inline'], capture_output=True, text=True)
        self.assertEqual(output.returncode, 0, output.stdout)
        task = json.loads(output.stdout)['task']
        output = subprocess.run(prefix + ['update-task', '--task', 'inline', '--version', str(task['version']), '--file-json', '{"note":"inline"}', '--request', 'inline-update'], capture_output=True, text=True)
        self.assertEqual(output.returncode, 0, output.stdout)
