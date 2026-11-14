"""检查入口必须拒绝零测试，并显式区分缺工具与失败。"""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

CHECK = Path(__file__).resolve().parents[1] / "scripts/check.py"


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CHECK.is_file(), "检查入口尚未实现")
        spec = importlib.util.spec_from_file_location("sandbox_check", CHECK)
        self.check = importlib.util.module_from_spec(spec)
        stdout = contextlib.redirect_stdout(io.StringIO())
        stderr = contextlib.redirect_stderr(io.StringIO())
        stdout.__enter__()
        stderr.__enter__()
        self.addCleanup(stdout.__exit__, None, None, None)
        self.addCleanup(stderr.__exit__, None, None, None)
        spec.loader.exec_module(self.check)

    def test_empty_suite_is_failure(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self.check.run_tests(Path(root)), 1)

    def test_real_suite_runs_and_failures_propagate(self):
        with tempfile.TemporaryDirectory() as root:
            test = Path(root) / "test_example.py"
            test.write_text("import unittest\nclass Example(unittest.TestCase):\n    def test_example(self):\n        self.assertTrue(False)\n", encoding="utf-8")
            self.assertEqual(self.check.run_tests(Path(root)), 1)

    def test_missing_ruff_is_blocked(self):
        with patch.object(self.check.importlib.util, "find_spec", return_value=None):
            self.assertEqual(self.check.run_ruff("format"), 2)
            self.assertEqual(self.check.run_ruff("static"), 2)

    def test_installed_tool_error_is_failure_not_missing_tool(self):
        with patch.object(self.check.importlib.util, "find_spec", return_value=object()):
            with patch.object(self.check.subprocess, "run") as run:
                run.return_value.returncode = 2
                self.assertEqual(self.check.run_ruff("static"), 1)

    def test_failed_check_dominates_blocked(self):
        with patch.object(self.check, "run_check", side_effect=[2, 1, 0, 0]):
            self.assertEqual(self.check.main(["all"]), 1)
        with patch.object(self.check, "run_check", side_effect=[2, 2, 0, 0]):
            self.assertEqual(self.check.main(["all"]), 2)
