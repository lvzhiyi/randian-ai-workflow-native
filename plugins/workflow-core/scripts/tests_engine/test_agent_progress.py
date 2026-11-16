"""进度仅投影当前轮次；真实 CLI 读取不初始化数据库或改变任务。"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_progress import project_progress
from workflow_engine.model import EngineError

CLI = Path(__file__).resolve().parents[1] / 'workflow_engine_cli.py'


class AgentProgressTests(unittest.TestCase):
    def task(self, state='implementing'):
        return {'id': 'task/a', 'current_round': 'round/1', 'state': state,
                'phase': 'implementation', 'version': 3, 'control_digest': 'digest',
                'rounds': [{'id': 'round/1', 'todos': [
                    {'id': 'one', 'title': '已完成', 'status': 'done'},
                    {'id': 'two', 'title': '当前步骤', 'status': 'pending'},
                    {'id': 'three', 'title': '后续步骤', 'status': 'pending'}]},
                    {'id': 'other', 'todos': [{'id': 'old', 'title': '禁止混入', 'status': 'done'}]}]}

    def test_current_round_is_not_last_and_projection_is_pure(self):
        task = self.task()
        before = copy.deepcopy(task)
        progress = project_progress(task)
        self.assertEqual([t['step_id'] for t in progress['todos']], ['one', 'two', 'three'])
        self.assertEqual([t['status'] for t in progress['todos']], ['completed', 'in_progress', 'pending'])
        self.assertEqual(progress['current'], progress['todos'][1]['id'])
        self.assertEqual(task, before)
        self.assertEqual(progress, project_progress(task))

    def test_non_implementation_never_claims_running(self):
        for state in ('failed', 'stale', 'review_failed', 'cancelled', 'running', 'created'):
            with self.subTest(state=state):
                progress = project_progress(self.task(state))
                self.assertNotIn('in_progress', [t['status'] for t in progress['todos']])
                self.assertEqual(progress['current'], progress['todos'][1]['id'])
        self.assertIn('待修复', project_progress(self.task('failed'))['text'])
        self.assertIn('失效', project_progress(self.task('stale'))['text'])

    def test_all_done_is_not_review_or_delivery(self):
        for state, label in [('implementing', '待进入验证'), ('pending_verification', '待验证'),
                             ('passed', '待评审'), ('review_failed', '待修复'),
                             ('review_passed', '不等于人工验收或交付')]:
            task = self.task(state)
            for todo in task['rounds'][0]['todos']:
                todo['status'] = 'done'
            progress = project_progress(task)
            self.assertIsNone(progress['current'])
            self.assertEqual(progress['state'], state)
            self.assertIn(label, progress['text'])

    def test_repair_refinement_and_new_round_preserve_identity(self):
        task = self.task()
        first = project_progress(task)
        task['rounds'][0]['todos'].append({'id': 'repair', 'title': '修复', 'status': 'pending', 'repair': True})
        second = project_progress(task)
        self.assertEqual(first['todos'], second['todos'][:3])
        self.assertEqual(second['todos'][-1]['status'], 'pending')
        task['rounds'][0]['todos'][1]['title'] = '细化标题'
        self.assertEqual(project_progress(task)['todos'][1]['id'], first['todos'][1]['id'])
        task['rounds'][0]['id'] = task['current_round'] = 'round/2'
        self.assertNotEqual(project_progress(task)['todos'][0]['id'], first['todos'][0]['id'])
        task['id'] = 'another'
        self.assertNotEqual(project_progress(task)['todos'][0]['id'], first['todos'][0]['id'])

    def test_real_repair_and_refinement_rebuild_current_step(self):
        from test_protocol import ProtocolTests
        fixture = ProtocolTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        task = fixture.implemented(code='raise SystemExit(1)')
        task = fixture.call('run', task)
        failed = project_progress(task)
        self.assertEqual(failed['state'], 'failed')
        self.assertIsNone(failed['current'])
        task = fixture.call('repair', task, [{'id': 'fix', 'title': '修复回归'}], '原范围修复')
        repaired = project_progress(task)
        self.assertEqual(repaired['todos'][0], failed['todos'][0])
        self.assertEqual(repaired['todos'][-1]['status'], 'in_progress')
        task = fixture.call('refine_steps', task, [{'id': 'fix-child', 'title': '细化修复', 'parent_id': 'fix'}], '细化边界')
        self.assertEqual(project_progress(task)['todos'][:2], repaired['todos'])
        task = fixture.call('record_tdd', task, {'adopted': False, 'reason': '回归检查', 'alternative_validation': '真实验证'})
        task = fixture.call('finish_step', task, 'fix', '已修复')
        advanced = project_progress(task)
        self.assertEqual(advanced['todos'][1]['status'], 'completed')
        self.assertEqual(advanced['todos'][2]['status'], 'in_progress')
        task = fixture.call('resume', task)
        resumed = project_progress(task)
        self.assertEqual(advanced['todos'], resumed['todos'])
        self.assertEqual(advanced['current'], resumed['current'])

    def test_encoded_ids_do_not_collide_at_component_boundaries(self):
        task = self.task()
        task['id'] = 'a/b'
        first = project_progress(task)['todos'][0]['id']
        task['id'] = 'a'
        task['rounds'][0]['id'] = task['current_round'] = 'b/round/1'
        self.assertNotEqual(first, project_progress(task)['todos'][0]['id'])

    def test_missing_round_rejects_instead_of_falling_back(self):
        task = self.task()
        task['current_round'] = 'missing'
        with self.assertRaises(EngineError):
            project_progress(task)

    def test_missing_db_cli_does_not_create_parent_or_database(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'absent' / 'state.sqlite'
            result = subprocess.run([sys.executable, str(CLI), '--root', folder, '--db', str(database),
                                     'progress', '--task', 'missing'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertEqual(json.loads(result.stdout)['code'], 'NOT_FOUND')
            self.assertFalse(database.parent.exists())

    def test_cli_reads_status_without_writing_even_when_stale(self):
        from test_protocol import ProtocolTests
        fixture = ProtocolTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        task = fixture.implemented()
        task = fixture.call('run', task)
        (fixture.root / 'code.py').write_text('changed')
        before = fixture.e.db.read_bytes()
        result = subprocess.run([sys.executable, str(CLI), '--root', str(fixture.root), '--db', str(fixture.e.db),
                                 'progress', '--task', 't'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        output = json.loads(result.stdout)
        self.assertTrue(output['ok'])
        self.assertEqual(output['progress']['state'], 'stale')
        self.assertEqual(output['progress']['version'], task['version'])
        self.assertNotIn('in_progress', [t['status'] for t in output['progress']['todos']])
        self.assertEqual(before, fixture.e.db.read_bytes())


if __name__ == '__main__':
    unittest.main()
