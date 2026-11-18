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


if __name__ == "__main__":
    unittest.main()
