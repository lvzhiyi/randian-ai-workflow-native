"""Review card write-back through the engine and its CLI."""
import json
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_protocol
from workflow_engine import EngineError
from workflow_engine import review_card


CLI = Path(__file__).resolve().parents[1] / 'workflow_engine_cli.py'
CARD = 'docs/product/任务/我的模块.md'
ORIGINAL = (
    '## 我的模块\r\n'
    '### MOD-R1 当前任务\r\n'
    '- 协作状态：待验证与评审\r\n'
    '- [ ] 子需求人工验收/交付完成\r\n'
    '- 人工验收：未进行\r\n'
    '### MOD-R2 其他任务\r\n'
    '- 协作状态：待验证与评审\r\n'
)
PROJECTED = ORIGINAL.replace('待验证与评审', '评审通过，待人工验收', 1)
BINDING = {'path': CARD, 'id': 'MOD-R1'}


class ReviewCardTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_protocol.ProtocolTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.engine = self.fixture.e
        self.card = self.root / CARD
        self.card.parent.mkdir(parents=True)
        self.card.write_bytes(ORIGINAL.encode())
        (self.root / 'ai-workflow.yaml').write_text(
            'version: 1\ndocs:\n  cards_dir: docs/product/任务\n', encoding='utf-8')

    def cli(self, action, *args):
        process = subprocess.run(
            [sys.executable, str(CLI), '--root', str(self.root), '--db', str(self.engine.db),
             action, '--task', 't', *args], capture_output=True, text=True)
        return process.returncode, json.loads(process.stdout)

    def verified(self, *, bound=True, baseline=True):
        fixture = self.fixture
        task = fixture.create()
        changes = {'card': BINDING} if bound else {}
        if baseline:
            changes['baseline'] = [CARD]
        if changes:
            code, result = self.cli('update-task', '--version', str(task['version']),
                                    '--request', 'set-card', '--file-json', json.dumps(changes))
            self.assertEqual(code, 0, result)
            task = result['task']
        task = fixture.call('confirm_tier', task, '人工')
        task = fixture.call('bind_executor', task, 'agent', 'session')
        path = task['baseline'][0]
        data = (self.root / path).read_bytes()
        task = fixture.call('register_baseline', task, {
            'path': path, 'sha256': sha256(data).hexdigest(), 'bytes_read': len(data),
            'complete': True, 'executor': 'agent', 'session_id': 'session',
            'round_id': task['current_round'],
        })
        task = fixture.call('start', task)
        task = fixture.call('record_tdd', task, {
            'adopted': False, 'reason': '文档任务', 'alternative_validation': '真实检查',
        })
        task = fixture.call('finish_step', task, '0', '实施完成')
        task = fixture.call('finish_implementation', task)
        return fixture.call('run', task)

    def review(self, task, outcome='pass', request='review'):
        return self.cli('review', '--request', request, '--version', str(task['version']),
                        '--file-json', json.dumps(self.fixture.report(task, outcome)))

    def test_cli_projects_only_the_bound_status_and_keeps_original_evidence(self):
        task = self.verified()
        code, result = self.review(task)
        self.assertEqual(code, 0, result)
        self.assertEqual(self.card.read_bytes(), PROJECTED.encode())
        status = self.engine.status('t')
        self.assertEqual((status['state'], status['missing']), ('review_passed', []))
        self.assertEqual(status['card_sync'], 'synced')
        for attempt in status['rounds'][-1]['attempts']:
            if attempt['stage'] in ('verification', 'review'):
                self.assertEqual((attempt['status'], attempt['snapshot']), ('passed', task['snapshot']))
        self.assertEqual(self.review(task)[1]['task']['version'], status['version'])
        self.card.write_bytes(ORIGINAL.encode())
        restored = self.engine.status('t')
        self.assertEqual((restored['state'], restored['card_sync']), ('review_passed', 'diverged'))
        self.card.write_bytes(PROJECTED.replace('其他任务', '并发修改').encode())
        changed = self.engine.status('t')
        self.assertEqual(changed['state'], 'stale')

    def test_failed_axis_leaves_card_unchanged(self):
        task = self.verified()
        code, result = self.review(task, outcome='fail')
        self.assertEqual(code, 1, result)
        self.assertEqual(result['task']['state'], 'review_failed')
        self.assertEqual(self.card.read_bytes(), ORIGINAL.encode())

    def test_unresolved_required_finding_leaves_card_unchanged(self):
        task = self.verified()
        report = self.fixture.report(task)
        report['axes']['spec']['findings'] = [
            {'id': 'required', 'required': True, 'resolved': False, 'message': '待修复'}]
        result = self.engine.review('t', task['version'], 'required', report)
        self.assertEqual(result['state'], 'review_failed')
        self.assertEqual(self.card.read_bytes(), ORIGINAL.encode())

    def test_write_failure_can_resume_the_same_request(self):
        task = self.verified()
        report = self.fixture.report(task)
        with patch.object(review_card, 'atomic_replace', side_effect=PermissionError):
            with self.assertRaisesRegex(EngineError, '重试同一请求'):
                self.engine.review('t', task['version'], 'retry', report)
        self.assertEqual(self.card.read_bytes(), ORIGINAL.encode())
        status = self.engine.status('t')
        self.assertEqual((status['state'], status['card_sync']), ('passed', 'pending'))
        self.assertEqual(self.engine.task_for_session('session')['card_sync_request'],
                         {'action': 'review', 'request': 'retry'})
        with self.assertRaises(EngineError) as blocked:
            self.engine.run('t', task['version'], 'competing-run')
        self.assertEqual(blocked.exception.code, 'CARD_PENDING')
        code, result = self.review(task, request='retry')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.card.read_bytes(), PROJECTED.encode())

    def test_interrupted_database_commit_resumes_with_card_already_written(self):
        task = self.verified()
        with patch.object(self.engine.store, 'finish_card_write', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.engine.review('t', task['version'], 'resume', self.fixture.report(task))
        self.assertEqual(self.card.read_bytes(), PROJECTED.encode())
        self.assertEqual(self.engine.status('t')['state'], 'passed')
        code, result = self.review(task, request='resume')
        self.assertEqual(code, 0, result)
        reviewed = result['task']
        self.assertEqual((reviewed['state'], reviewed['version']), ('review_passed', task['version'] + 1))
        self.assertEqual(reviewed['card_sync'], 'synced')
        self.assertEqual(len([event for event in self.engine.history('t') if event['action'] == 'review']), 1)

    def test_interrupted_temporary_file_is_removed_when_retry_detects_config_change(self):
        task = self.verified()
        report = json.dumps(self.fixture.report(task))
        script = (
            'import os, sys\n'
            'sys.path.insert(0, sys.argv.pop(1))\n'
            'from workflow_engine import review_card\n'
            'from workflow_engine_cli import main\n'
            'review_card.os.replace = lambda *args, **kwargs: os._exit(73)\n'
            'sys.exit(main())'
        )
        interrupted = subprocess.run(
            [sys.executable, '-B', '-c', script, str(CLI.parent), '--root', str(self.root),
             '--db', str(self.engine.db), 'review', '--task', 't', '--request', 'interrupted',
             '--version', str(task['version']), '--file-json', report], capture_output=True, text=True)
        self.assertEqual(interrupted.returncode, 73, interrupted.stdout)
        self.assertEqual(len(list(self.card.parent.glob('.workflow-review-*.tmp'))), 1)
        self.assertEqual(self.engine.status('t')['card_sync_request']['request'], 'interrupted')
        config = self.root / 'ai-workflow.yaml'
        with config.open('a', encoding='utf-8') as handle:
            handle.write('verify:\n  light: python3 other.py\n')

        code, result = self.review(task, request='interrupted')
        self.assertEqual(code, 2, result)
        self.assertEqual(list(self.card.parent.glob('.workflow-review-*.tmp')), [])
        self.assertEqual(self.card.read_bytes(), ORIGINAL.encode())
        self.assertEqual(self.engine.status('t')['state'], 'stale')

    def test_other_section_change_during_review_is_preserved_and_invalidates_evidence(self):
        task = self.verified(baseline=False)
        changed = ORIGINAL.replace('其他任务', '并发改动').encode()
        apply = review_card.apply

        def concurrent_edit(*args):
            self.card.write_bytes(changed)
            return apply(*args)

        with patch.object(review_card, 'apply', side_effect=concurrent_edit):
            with self.assertRaises(EngineError) as failure:
                self.engine.review('t', task['version'], 'conflict', self.fixture.report(task))
        self.assertEqual(failure.exception.code, 'CARD_CONFLICT')
        self.assertEqual(self.card.read_bytes(), changed)
        self.assertEqual(self.engine.status('t')['state'], 'stale')
        self.assertEqual(self.fixture.call('run', task)['state'], 'passed')

    def test_changed_ignored_baseline_blocks_write_before_replacement(self):
        (self.root / '.gitignore').write_text('baseline.md\n')
        task = self.verified(baseline=False)
        finish = self.engine._finish_card_write

        def concurrent_edit(*args):
            (self.root / 'baseline.md').write_text('更新的基线')
            return finish(*args)

        with patch.object(self.engine, '_finish_card_write', side_effect=concurrent_edit):
            with self.assertRaises(EngineError) as failure:
                self.engine.review('t', task['version'], 'stale-baseline', self.fixture.report(task))
        self.assertEqual(failure.exception.code, 'CARD_CONFLICT')
        self.assertEqual(self.card.read_bytes(), ORIGINAL.encode())
        self.assertEqual(self.engine.status('t')['state'], 'stale')

    def test_legacy_status_keeps_other_fields_on_the_line(self):
        original = ORIGINAL.replace('- 协作状态：待验证与评审', '- 状态：待验证；人工验收：未进行；负责人：待指定', 1)
        self.card.write_bytes(original.encode())
        task = self.verified()
        code, result = self.review(task)
        self.assertEqual(code, 0, result)
        self.assertEqual(self.card.read_bytes(), original.replace('待验证；', '评审通过，待人工验收；', 1).encode())

    def test_inline_comment_is_preserved(self):
        original = ORIGINAL.replace('待验证与评审', '待验证与评审 <!-- 保留说明 -->', 1)
        self.card.write_bytes(original.encode())
        task = self.verified()
        code, result = self.review(task)
        self.assertEqual(code, 0, result)
        self.assertEqual(self.card.read_bytes(), original.replace('待验证与评审', '评审通过，待人工验收', 1).encode())

    def test_existing_review_can_be_synced_using_its_current_evidence(self):
        task = self.verified(bound=False)
        code, result = self.review(task)
        self.assertEqual(code, 0, result)
        reviewed = result['task']
        self.assertEqual(reviewed['card_sync'], 'unbound')
        self.assertEqual(self.card.read_bytes(), ORIGINAL.encode())
        code, result = self.cli(
            'sync-review-card', '--request', 'backfill', '--version', str(reviewed['version']),
            '--round', reviewed['current_round'], '--card-path', CARD, '--card-id', 'MOD-R1')
        self.assertEqual(code, 0, result)
        self.assertEqual(self.card.read_bytes(), PROJECTED.encode())
        synced = result['task']
        self.assertEqual((synced['state'], synced['snapshot']), ('review_passed', task['snapshot']))
        self.assertEqual(synced['rounds'][-1]['attempts'], reviewed['rounds'][-1]['attempts'])

    def test_backfill_rejects_stale_review_without_writing(self):
        task = self.verified(bound=False)
        code, result = self.review(task)
        self.assertEqual(code, 0, result)
        reviewed = result['task']
        (self.root / 'code.py').write_text('updated')
        code, result = self.cli(
            'sync-review-card', '--request', 'stale-backfill', '--version', str(reviewed['version']),
            '--round', reviewed['current_round'], '--card-path', CARD, '--card-id', 'MOD-R1')
        self.assertEqual((code, result['code']), (2, 'CHECKS_REQUIRED'))
        self.assertEqual(self.card.read_bytes(), ORIGINAL.encode())

    def test_backfill_requires_an_explicit_binding(self):
        task = self.verified(bound=False)
        code, result = self.review(task)
        self.assertEqual(code, 0, result)
        reviewed = result['task']
        with self.assertRaises(EngineError) as invalid:
            self.engine.sync_review_card('t', reviewed['version'], 'missing-card', reviewed['current_round'], {})
        self.assertEqual(invalid.exception.code, 'CARD_INVALID')
        self.assertEqual(self.engine.status('t')['version'], reviewed['version'])

    def test_duplicate_card_heading_is_rejected_without_writing(self):
        original = ORIGINAL.replace('MOD-R2', 'MOD-R1').encode()
        self.card.write_bytes(original)
        task = self.verified()
        code, result = self.review(task)
        self.assertEqual((code, result['code']), (2, 'CARD_INVALID'))
        self.assertEqual(self.card.read_bytes(), original)
        self.assertEqual(self.engine.status('t')['state'], 'passed')
