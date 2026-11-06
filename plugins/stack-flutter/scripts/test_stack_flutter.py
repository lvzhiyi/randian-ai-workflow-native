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
