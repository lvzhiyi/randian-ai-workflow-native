"""archive_change.py 变更归档与断链检测回归测试。"""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import archive_change


class ArchiveChangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = archive_change.main(['--root', str(self.root), *argv])
        return code, out.getvalue()

    def test_dry_run_does_not_move_files(self):
        self.write('docs/development/changes/T1/proposal.md', '# T1\n')
        code, output = self.run_cli('--task', 'T1', '--month', '2026-11', '--dry-run')
        self.assertEqual(code, 0, output)
        self.assertIn('dry-run: docs/development/changes/T1 -> docs/development/changes/archive/2026-11-T1', output)
        self.assertTrue((self.root / 'docs/development/changes/T1/proposal.md').is_file())

    def test_archive_moves_directory_and_passes_link_check(self):
        self.write('docs/development/changes/T1/proposal.md', '# T1\n\n[设计](design.md)\n')
        self.write('docs/development/changes/T1/design.md', '# 设计\n')
        code, output = self.run_cli('--task', 'T1', '--month', '2026-11')
        self.assertEqual(code, 0, output)
        self.assertFalse((self.root / 'docs/development/changes/T1').exists())
        self.assertTrue((self.root / 'docs/development/changes/archive/2026-11-T1/proposal.md').is_file())

    def test_archive_reports_broken_links_after_move(self):
        self.write('docs/development/changes/T1/proposal.md', '# T1\n')
        self.write('docs/product/任务/模块.md', '[提案](../../development/changes/T1/proposal.md)\n')
        code, output = self.run_cli('--task', 'T1', '--month', '2026-11')
        self.assertEqual(code, 1, output)
        self.assertIn('链接目标不存在', output)

    def test_rejects_traversal_and_reserved_names(self):
        self.write('docs/development/changes/T1/proposal.md', '# T1\n')
        for bad in ('../T1', 'archive', 'a/b'):
            code, _ = self.run_cli('--task', bad, '--month', '2026-11')
            self.assertEqual(code, 1, bad)

    def test_custom_changes_dir_supports_legacy_openspec_archive(self):
        self.write('openspec/changes/add-login/proposal.md', '# Login\n')
        code, output = self.run_cli('--changes-dir', 'openspec/changes', '--task', 'add-login', '--month', '2026-11')
        self.assertEqual(code, 0, output)
        self.assertTrue((self.root / 'openspec/changes/archive/2026-11-add-login/proposal.md').is_file())


if __name__ == '__main__':
    unittest.main()
