"""通过真实子进程验证 CLI 不会把缺失状态静默判为成功。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).resolve().parents[1] / "workflow_engine_cli.py"


class CliTests(unittest.TestCase):
    def test_missing_task_is_structured_rejection(self):
        self.assertTrue(CLI.is_file(), "CLI 尚未实现")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "project"
            root.mkdir()
            result = subprocess.run(
                [sys.executable, str(CLI), "--root", str(root), "--db",
                 str(Path(folder) / "state.sqlite"), "status", "--task", "missing"],
                capture_output=True, text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("code", payload)

    def test_create_maps_chinese_tier(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / "project"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            plan = base / "plan.json"
            plan.write_text(json.dumps({"version": 1, "checks": [{"id": "all",
                "argv": [sys.executable, "-c", "pass"], "cwd": ".", "timeout": 2,
                "covers": ["format", "analyze", "test"], "acceptance": ["A1"]}]}))
            details = base / 'details.json'
            details.write_text(json.dumps({'goal': '目标', 'scope': ['代码'], 'source': '需求', 'dependencies': [], 'baseline': ['baseline.md'], 'steps': [{'id': 's', 'title': '实施'}]}))
            result = subprocess.run([sys.executable, str(CLI), "--root", str(root),
                "--db", str(base / "state.sqlite"), "create", "--task", "one",
                "--tier", "轻量", "--acceptance", "A1", "--plan", str(plan),
                "--request", "create", "--details", str(details)], capture_output=True, text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(json.loads(result.stdout)["task"]["tier"], "light")

    def test_failed_run_returns_nonzero(self):
        sys.path.insert(0, str(CLI.parent))
        from workflow_engine import Engine
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / "project"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            engine = Engine(root, base / "state.sqlite")
            plan = {"version": 1, "checks": [{"id": "all",
                "argv": [sys.executable, "-c", "raise SystemExit(7)"],
                "cwd": ".", "timeout": 2, "covers": ["format", "analyze", "test"],
                "acceptance": ["A1"]}]}
            from test_protocol import ProtocolTests
            fixture = ProtocolTests()
            fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            task = fixture.implemented(code='raise SystemExit(7)')
            root = fixture.root
            base = fixture.e.db.parent
            # 此用例必须通过真实 v2 任务进入失败检查，不保留旧协议 CLI 通道。
            database = fixture.e.db
            result = subprocess.run([sys.executable, str(CLI), "--root", str(root),
                "--db", str(database), "run", "--task", "t",
                "--version", str(task["version"]), "--request", "run"],
                capture_output=True, text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertFalse(json.loads(result.stdout)["ok"])

    def test_protocol_cli_file_workflow(self):
        sys.path.insert(0, str(CLI.parent))
        from workflow_engine import Engine
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / 'repo'
            root.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'baseline.md').write_text('规范')
            plan = {'version': 1, 'checks': [{'id': 'a', 'argv': [sys.executable, '-c', 'pass'], 'cwd': '.', 'timeout': 2, 'covers': ['format', 'analyze', 'test'], 'acceptance': ['A1']}]}
            details = {'goal': '目标', 'scope': ['代码'], 'source': '需求', 'dependencies': [], 'baseline': ['baseline.md'], 'steps': [{'id': 's', 'title': '实施'}]}
            (base / 'plan.json').write_text(json.dumps(plan))
            (base / 'details.json').write_text(json.dumps(details))
            count = 0
            def cli(action, *args, version=None):
                nonlocal count
                count += 1
                command = [sys.executable, str(CLI), '--root', str(root), '--db', str(base / 'db'), action, '--task', 't']
                if action not in ('status', 'history', 'snapshot'):
                    command += ['--request', str(count)]
                if version is not None:
                    command += ['--version', str(version)]
                result = subprocess.run(command + list(args), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout)
                return json.loads(result.stdout)
            task = cli('create', '--tier', '轻量', '--acceptance', 'A1', '--plan', str(base / 'plan.json'), '--details', str(base / 'details.json'))['task']
            self.assertEqual(task['protocol_version'], 2)
            engine = Engine(root, base / 'db')
            task = engine.confirm_tier('t', task['version'], 'human', '人')
            task = engine.bind_executor('t', task['version'], 'binding', 'cli-reader', 'cli-session')
            baseline_output = cli('read-baseline', '--path', 'baseline.md', '--executor', 'cli-reader', '--session', 'cli-session', version=task['version'])
            self.assertEqual(baseline_output['document']['content'], '规范')
            task = baseline_output['task']
            task = cli('start', version=task['version'])['task']
            (base / 'tdd.json').write_text(json.dumps({'adopted': False, 'reason': '文档任务', 'alternative_validation': '真实检查'}))
            task = cli('record-tdd', '--file', str(base / 'tdd.json'), version=task['version'])['task']
            task = cli('finish-step', '--step', 's', '--summary', '完成', version=task['version'])['task']
            task = cli('finish-implementation', version=task['version'])['task']
            task = cli('run', version=task['version'])['task']
            report = {'snapshot': task['snapshot'], 'control_digest': task['control_digest'], 'round_id': task['current_round'], 'executor': 'reviewer', 'axes': {a: {'conclusion': 'pass', 'findings': []} for a in ['spec', 'standards']}}
            (base / 'report.json').write_text(json.dumps(report))
            task = cli('review', '--file', str(base / 'report.json'), version=task['version'])['task']
            self.assertEqual(task['state'], 'review_passed')
            self.assertTrue(cli('history')['history'])
            self.assertEqual(cli('snapshot')['task']['state'], 'review_passed')

    def test_no_arbitrary_pass_command(self):
        self.assertTrue(CLI.is_file(), "CLI 尚未实现")
        result = subprocess.run([sys.executable, str(CLI), "mark-passed"],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_batch_baseline_load_is_atomic_and_unblocks_start(self):
        from test_protocol import ProtocolTests

        fixture = ProtocolTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        task = fixture.create()
        paths = ['baseline.md', 'other.md', 'third.md']
        task = fixture.call('update_task', task, {'baseline': paths})
        task = fixture.call('confirm_tier', task, '人工')
        task = fixture.call('bind_executor', task, 'reader', 'session')
        (fixture.root / 'other.md').write_text('第二份规范', encoding='utf-8')
        last = fixture.root / 'third.md'
        command = [sys.executable, str(CLI), '--root', str(fixture.root),
                   '--db', str(fixture.e.db), 'read-baseline', '--task', 't',
                   '--version', str(task['version']), '--request', 'batch',
                   '--executor', 'reader', '--session', 'session', '--all']

        def load(*args):
            result = subprocess.run(command + list(args), capture_output=True, text=True)
            return result.returncode, json.loads(result.stdout)

        for contents, options, expected_code in (
            (None, (), 'BASELINE_INVALID'),
            (b'\xff', (), 'ARGUMENT'),
            ('第三份规范'.encode(), ('--max-bytes', '100'), 'BASELINE_BATCH_LIMIT'),
        ):
            with self.subTest(expected_code=expected_code):
                if contents is not None:
                    last.write_bytes(contents)
                code, output = load(*options)
                self.assertEqual(code, 2, output)
                self.assertEqual(output['code'], expected_code, output)
                latest = fixture.e.status('t')
                self.assertEqual(latest['version'], task['version'])
                self.assertEqual(latest['rounds'][-1]['evidence'], task['rounds'][-1]['evidence'])
                self.assertIn('baseline', latest['missing'])

        code, output = load()
        self.assertEqual(code, 0, output)
        self.assertEqual([(doc['path'], doc['content']) for doc in output['documents']],
                         list(zip(paths, ['工程规范全文', '第二份规范', '第三份规范'])))
        latest = fixture.e.status('t')
        self.assertEqual(output['version'], task['version'] + 1)
        receipts = [item['data']['path'] for item in latest['rounds'][-1]['evidence']
                    if item['kind'] == 'baseline']
        self.assertEqual(receipts, paths)
        self.assertEqual(load(), (code, output))
        self.assertEqual(fixture.call('start', latest)['state'], 'implementing')

        last.write_text('规范已更新', encoding='utf-8')
        refreshed = fixture.e.status('t')
        valid_paths = [item['data']['path'] for item in refreshed['rounds'][-1]['evidence']
                       if item['kind'] == 'baseline' and item['valid']]
        self.assertEqual(valid_paths, paths[:2])
        self.assertIn('baseline', refreshed['missing'])

    def test_prepare_and_begin_streamlined_lifecycle_preserves_all_gates(self):
        sys.path.insert(0, str(CLI.parent))
        from workflow_engine import Engine

        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / 'repo'
            root.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / 'rules.md').write_text('核心工程规范全文', encoding='utf-8')
            (root / 'ai-workflow.yaml').write_text(
                'version: 1\n'
                'baseline:\n'
                '  required:\n'
                '    - rules.md\n'
                'verify:\n'
                f'  light: {sys.executable} -c pass\n',
                encoding='utf-8',
            )
            db = base / 'state.sqlite'

            def run_cli(action, *args):
                proc = subprocess.run(
                    [sys.executable, str(CLI), '--root', str(root), '--db', str(db), action, '--task', 't1', *args],
                    capture_output=True, text=True,
                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
                )
                return proc.returncode, json.loads(proc.stdout)

            # 1. prepare：自动从 ai-workflow.yaml 派生 baseline 和 plan，省略 --request，绑定会话
            details = {'goal': '修复问题', 'scope': ['src'], 'source': '需求', 'dependencies': [], 'steps': [{'id': 's1', 'title': '实现'}]}
            code, prep = run_cli(
                'prepare', '--tier', '轻量', '--acceptance', 'A1',
                '--details-json', json.dumps(details),
                '--executor', 'agent', '--session', 'sess-1',
            )
            self.assertEqual(code, 0, prep)
            self.assertEqual(prep['task']['baseline'], ['rules.md'])
            self.assertEqual(prep['task']['rounds'][-1]['executor'], 'agent')
            self.assertEqual(prep['task']['rounds'][-1]['session_id'], 'sess-1')
            self.assertIn('progress', prep)

            # 2. 未人工定档前，begin 必须被硬门禁拒绝，不写入任何基线回执
            code, blocked = run_cli('begin', '--executor', 'agent', '--session', 'sess-1')
            self.assertEqual((code, blocked['code']), (2, 'NOT_READY'))
            self.assertEqual(Engine(root, db).status('t1')['version'], prep['task']['version'])

            # 人工定档
            engine = Engine(root, db)
            confirmed = engine.confirm_tier('t1', prep['task']['version'], 'human-tier', '用户')

            # 3. 基线超限时 begin 必须拒绝，不登记回执、不进入 implementing
            code, truncated = run_cli('begin', '--executor', 'agent', '--session', 'sess-1', '--max-bytes', '20')
            self.assertEqual((code, truncated['code']), (2, 'BASELINE_BATCH_LIMIT'))
            self.assertEqual(engine.status('t1')['state'], 'created')

            # 4. 正常 begin：一步吐出基线正文 + 登记 SHA-256 回执 + start + record-tdd + 返回 progress
            tdd = {'adopted': False, 'reason': '小修正', 'alternative_validation': '运行检查'}
            code, begun = run_cli(
                'begin', '--version', str(confirmed['version']),
                '--executor', 'agent', '--session', 'sess-1',
                '--tdd-json', json.dumps(tdd),
            )
            self.assertEqual(code, 0, begun)
            self.assertEqual(begun['task']['state'], 'implementing')
            self.assertEqual(begun['documents'][0]['path'], 'rules.md')
            self.assertEqual(begun['documents'][0]['content'], '核心工程规范全文')
            self.assertIn('progress', begun)

            # 5. finish-step --finish-implementation 一步收口进入 pending_verification
            code, finished = run_cli(
                'finish-step', '--version', str(begun['version']),
                '--step', 's1', '--summary', '已完成实现', '--finish-implementation',
            )
            self.assertEqual(code, 0, finished)
            self.assertEqual(finished['task']['state'], 'pending_verification')
            self.assertIn('progress', finished)

            # 6. run + review（省略 --request，均自带 progress 投影）
            code, verified = run_cli('run', '--version', str(finished['task']['version']))
            self.assertEqual(code, 0, verified)
            self.assertEqual(verified['task']['state'], 'passed')
            self.assertIn('progress', verified)

            report = {
                'snapshot': verified['task']['snapshot'],
                'control_digest': verified['task']['control_digest'],
                'round_id': verified['task']['current_round'],
                'executor': 'reviewer',
                'axes': {axis: {'conclusion': 'pass', 'findings': []} for axis in ('spec', 'standards')},
            }
            code, reviewed = run_cli(
                'review', '--version', str(verified['task']['version']),
                '--file-json', json.dumps(report),
            )
            self.assertEqual(code, 0, reviewed)
            self.assertEqual(reviewed['task']['state'], 'review_passed')
            self.assertIn('progress', reviewed)

    def test_list_reads_project_tasks_without_creating_database(self):
        sys.path.insert(0, str(CLI.parent))
        from workflow_engine import Engine

        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base / 'repo'
            other_root = base / 'other'
            for item in (root, other_root):
                item.mkdir()
                subprocess.run(['git', 'init', '-q', str(item)], check=True)
            db = base / 'state.sqlite'

            def run_list(*args):
                proc = subprocess.run(
                    [sys.executable, str(CLI), '--root', str(root), '--db', str(db), 'list', *args],
                    capture_output=True, text=True,
                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
                )
                return proc.returncode, json.loads(proc.stdout)

            code, empty = run_list()
            self.assertEqual(code, 0, empty)
            self.assertEqual(empty['tasks'], [])
            self.assertFalse(db.exists())

            plan = {'version': 1, 'checks': [{'id': 'c1', 'argv': ['true'], 'cwd': '.', 'timeout': 2, 'covers': ['format', 'analyze', 'test'], 'acceptance': ['A1']}]}
            details = {'goal': '任务目标', 'scope': ['src'], 'source': '需求', 'dependencies': [], 'baseline': [], 'steps': [{'id': 's1', 'title': '步骤'}]}
            engine = Engine(root, db)
            t1 = engine.create('T1', 'light', ['A1'], plan, 'c1', details=details)
            engine.bind_executor('T1', t1['version'], 'b1', 'agent', 'sess-1')
            t2 = engine.create('T2', 'light', ['A1'], plan, 'c2', details=details)
            engine.cancel('T2', t2['version'], 'x2')
            Engine(other_root, db).create('OTHER', 'light', ['A1'], plan, 'c3', details=details)

            code, listed = run_list()
            self.assertEqual(code, 0, listed)
            self.assertEqual([item['id'] for item in listed['tasks']], ['T1', 'T2'])
            self.assertEqual(listed['tasks'][0]['session_id'], 'sess-1')
            self.assertEqual(listed['tasks'][0]['executor'], 'agent')

            code, active = run_list('--active')
            self.assertEqual(code, 0, active)
            self.assertEqual([item['id'] for item in active['tasks']], ['T1'])

            link = base / 'link.sqlite'
            link.symlink_to(db)
            proc = subprocess.run(
                [sys.executable, str(CLI), '--root', str(root), '--db', str(link), 'list'],
                capture_output=True, text=True,
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
            )
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(json.loads(proc.stdout)['code'], 'DB_LOCATION')


if __name__ == "__main__":
    unittest.main()
