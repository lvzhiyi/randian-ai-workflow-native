"""stack-flutter 脚本回归测试：python3 -m unittest discover -s plugins/stack-flutter/scripts -p 'test_*.py'"""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flutter_check  # noqa: E402
import stop_analyze  # noqa: E402


def git(root, *args):
    subprocess.run(['git', *args], cwd=root, check=True, capture_output=True,
                   env={**flutter_check.clean_env(), 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
                        'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'})


class RepoTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.metrics = tempfile.TemporaryDirectory()
        self.addCleanup(self.metrics.cleanup)
        env = patch.dict(os.environ, {'WORKFLOW_METRICS_DIR': self.metrics.name})
        env.start()
        self.addCleanup(env.stop)
        git(self.root, 'init', '-q')
        self.write('pubspec.yaml', 'name: demo\n')
        self.write('lib/a.dart', 'void a() {}\n')
        self.write('lib/a.g.dart', 'void g() {}\n')
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'init')

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')


class ChangedFilesTests(RepoTestCase):
    def test_clean_repo_has_no_changes(self):
        self.assertEqual(flutter_check.changed_dart_files(self.root), [])

    def test_modified_and_untracked_handwritten_files_only(self):
        self.write('lib/a.dart', 'void a() { }\n')
        self.write('lib/a.g.dart', 'void g() { }\n')
        self.write('test/b_test.dart', 'void main() {}\n')
        self.write('lib/c.freezed.dart', '')
        self.write('README.md', 'x')
        self.assertEqual(flutter_check.changed_dart_files(self.root), ['lib/a.dart', 'test/b_test.dart'])

    def test_deleted_file_is_excluded(self):
        (self.root / 'lib/a.dart').unlink()
        self.assertEqual(flutter_check.changed_dart_files(self.root), [])

    def test_git_hook_variables_are_removed(self):
        with patch.dict(os.environ, {'GIT_DIR': '/x', 'GIT_INDEX_FILE': '/y', 'KEEP': '1'}):
            env = flutter_check.clean_env()
        self.assertNotIn('GIT_DIR', env)
        self.assertNotIn('GIT_INDEX_FILE', env)
        self.assertEqual(env['KEEP'], '1')


class FlutterCheckMainTests(RepoTestCase):
    def run_main(self, *argv, results=()):
        calls = []
        outcomes = iter(results)

        def fake_run(label, command, root):
            calls.append((label, command))
            return next(outcomes, 0)

        out = io.StringIO()
        with patch.object(flutter_check, 'run', side_effect=fake_run), contextlib.redirect_stdout(out):
            code = flutter_check.main(['--root', str(self.root), *argv])
        return code, calls, out.getvalue()

    def test_not_flutter_project_is_blocked(self):
        (self.root / 'pubspec.yaml').unlink()
        code, calls, output = self.run_main()
        self.assertEqual(code, 2)
        self.assertEqual(calls, [])

    def test_formats_only_changed_files_and_skips_tests_without_test_dir(self):
        self.write('lib/a.dart', 'void a() { }\n')
        code, calls, output = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual([label for label, _ in calls], ['format', 'analyze'])
        self.assertEqual(calls[0][1][-1], 'lib/a.dart')
        self.assertIn('[test] status=SKIPPED', output)

    def test_no_changes_skips_format_but_still_analyzes(self):
        code, calls, output = self.run_main('--no-test')
        self.assertEqual([label for label, _ in calls], ['analyze'])
        self.assertIn('[format] status=SKIPPED', output)

    def test_blocked_takes_priority_over_failure(self):
        self.write('test/x_test.dart', '')
        code, calls, output = self.run_main(results=(1, 2, 0))
        self.assertEqual(code, 2)
        self.assertIn('Result: BLOCKED', output)

    def test_explicit_tests_are_passed_through(self):
        code, calls, _ = self.run_main('test/x_test.dart')
        self.assertEqual(calls[-1][1][-1], 'test/x_test.dart')


class AnalyzeErrorsTests(unittest.TestCase):
    def test_nonzero_without_machine_diagnostics_is_unknown(self):
        root = Path('/project')
        for output in ('', 'Analyzer crashed', 'ERROR|bad',
                       'ERROR|COMPILE_TIME_ERROR|BAD|lib/a.dart|x|1|1|bad'):
            with self.subTest(output=output), patch.object(stop_analyze.shutil, 'which', return_value='/dart'), patch.object(
                stop_analyze.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', output)
            ):
                self.assertIsNone(stop_analyze.analyze_errors(root, ['lib/a.dart']))

    def test_nonzero_warning_and_hint_diagnostics_have_no_errors(self):
        for severity in ('WARNING', 'INFO', 'HINT'):
            for stream in ('stdout', 'stderr'):
                diagnostic = f'{severity}|HINT|CODE|lib/a.dart|1|2|3|message'
                result = subprocess.CompletedProcess([], 1, diagnostic if stream == 'stdout' else '',
                                                     diagnostic if stream == 'stderr' else '')
                with self.subTest(severity=severity, stream=stream), patch.object(
                    stop_analyze.shutil, 'which', return_value='/dart'
                ), patch.object(stop_analyze.subprocess, 'run', return_value=result):
                    self.assertEqual(stop_analyze.analyze_errors(Path('/project'), ['lib/a.dart']), [])

    def test_machine_error_and_clean_exit(self):
        for result, expected in (
            (subprocess.CompletedProcess([], 0, '', ''), []),
            (subprocess.CompletedProcess([], 3,
             'ERROR|COMPILE_TIME_ERROR|BAD|/project/lib/a.dart|1|2|3|bad', ''),
             ['lib/a.dart:1:2 bad (bad)']),
        ):
            with self.subTest(result=result), patch.object(stop_analyze.shutil, 'which', return_value='/dart'), patch.object(
                stop_analyze.subprocess, 'run', return_value=result
            ):
                self.assertEqual(stop_analyze.analyze_errors(Path('/project'), ['lib/a.dart']), expected)


class StopHookTests(RepoTestCase):
    def hook(self, event, errors=None):
        out = io.StringIO()
        with patch.object(stop_analyze, 'analyze_errors', return_value=errors) as analyzer, patch(
            'sys.stdin', io.StringIO(json.dumps(event))
        ), contextlib.redirect_stdout(out):
            self.assertEqual(stop_analyze.main(), 0)
        text = out.getvalue().strip()
        return (json.loads(text) if text else None), analyzer

    def test_no_dart_changes_skips_analysis(self):
        result, analyzer = self.hook({'cwd': str(self.root)})
        self.assertIsNone(result)
        analyzer.assert_not_called()

    def test_non_flutter_project_is_ignored(self):
        (self.root / 'pubspec.yaml').unlink()
        self.write('lib/a.dart', 'broken(')
        result, analyzer = self.hook({'cwd': str(self.root)})
        self.assertIsNone(result)
        analyzer.assert_not_called()

    def outcomes(self):
        path = Path(self.metrics.name) / 'records.jsonl'
        return [json.loads(l)['outcome'] for l in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def test_metrics_record_block_and_retry_outcomes(self):
        self.write('lib/a.dart', 'broken(')
        self.hook({'cwd': str(self.root), 'session_id': 's'}, ['e'])
        self.hook({'cwd': str(self.root), 'session_id': 's', 'stop_hook_active': True}, ['e'])
        self.hook({'cwd': str(self.root), 'session_id': 's', 'stop_hook_active': True}, [])
        self.assertEqual(self.outcomes(), ['blocked', 'unresolved', 'fixed'])

    def test_metrics_skip_clean_pass_analyzer_failure_and_disabled(self):
        self.write('lib/a.dart', 'void a2() {}')
        self.hook({'cwd': str(self.root)}, [])
        self.hook({'cwd': str(self.root), 'stop_hook_active': True}, None)
        self.assertEqual(self.outcomes(), [])
        (Path(self.metrics.name) / 'disabled').touch()
        self.hook({'cwd': str(self.root)}, ['e'])
        self.assertEqual(self.outcomes(), [])

    def test_analyzer_failure_on_retry_does_not_record_fixed(self):
        self.write('lib/a.dart', 'broken(')
        event = {'cwd': str(self.root), 'stop_hook_active': True}
        out = io.StringIO()
        with patch.object(stop_analyze, 'project_root', return_value=self.root), patch.object(
            stop_analyze, 'changed_dart_files', return_value=['lib/a.dart']
        ), patch.object(stop_analyze.shutil, 'which', return_value='/dart'), patch.object(
            stop_analyze.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'Analyzer crashed')
        ), patch('sys.stdin', io.StringIO(json.dumps(event))), contextlib.redirect_stdout(out):
            self.assertEqual(stop_analyze.main(), 0)
        self.assertEqual(out.getvalue(), '')
        self.assertEqual(self.outcomes(), [])

    def test_errors_ask_claude_to_continue(self):
        self.write('lib/a.dart', 'broken(')
        result, analyzer = self.hook({'cwd': str(self.root / 'lib')}, ['lib/a.dart:1:1 bad (code)'])
        analyzer.assert_called_once_with(self.root, ['lib/a.dart'])
        context = result['hookSpecificOutput']['additionalContext']
        self.assertEqual(result['hookSpecificOutput']['hookEventName'], 'Stop')
        self.assertIn('lib/a.dart:1:1 bad', context)

    def test_second_round_only_warns_user(self):
        self.write('lib/a.dart', 'broken(')
        result, _ = self.hook({'cwd': str(self.root), 'stop_hook_active': True}, ['x'])
        self.assertNotIn('hookSpecificOutput', result)
        self.assertIn('systemMessage', result)

    def test_codex_stop_requests_one_continuation(self):
        self.write('lib/a.dart', 'broken(')
        event = {'cwd': str(self.root), 'turn_id': 't1'}
        with patch.dict(os.environ, {'WORKFLOW_HOST': 'codex'}):
            blocked, _ = self.hook(event, ['lib/a.dart:1:1 bad'])
            retried, _ = self.hook({**event, 'stop_hook_active': True}, ['lib/a.dart:1:1 bad'])
        self.assertEqual(blocked['decision'], 'block')
        self.assertIn('lib/a.dart:1:1 bad', blocked['reason'])
        self.assertEqual(list(retried), ['systemMessage'])

    def test_clean_analysis_and_unavailable_analyzer_allow_stop(self):
        self.write('lib/a.dart', 'void a() { }\n')
        for errors in ([], None):
            result, _ = self.hook({'cwd': str(self.root)}, errors)
            self.assertIsNone(result)

    def test_invalid_stdin_allows_stop(self):
        out = io.StringIO()
        with patch('sys.stdin', io.StringIO('not json')), contextlib.redirect_stdout(out):
            self.assertEqual(stop_analyze.main(), 0)
        self.assertEqual(out.getvalue(), '')

    def test_report_is_truncated(self):
        self.write('lib/a.dart', 'broken(')
        errors = [f'e{i}' for i in range(stop_analyze.MAX_REPORTED + 5)]
        result, _ = self.hook({'cwd': str(self.root)}, errors)
        self.assertIn('另有 5 条未列出', result['hookSpecificOutput']['additionalContext'])


if __name__ == '__main__':
    unittest.main()
