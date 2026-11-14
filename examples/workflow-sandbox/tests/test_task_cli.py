"""真实子进程验证协议、跨进程持久化与敏感错误隔离。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

CLI = Path(__file__).resolve().parents[1] / "src/task_cli.py"


class CliTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CLI.is_file(), "CLI 尚未实现")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tasks.json"

    def run_cli(self, *args, code=0, file=True):
        command = [sys.executable, str(CLI)]
        if file:
            command += ["--file", str(self.path)]
        result = subprocess.run(command + list(args), capture_output=True, text=True,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=10)
        self.assertEqual(result.returncode, code, result.stderr)
        if code:
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr)
            self.assertNotIn("Traceback", result.stderr)
        else:
            self.assertEqual(result.stderr, "")
        return result

    def test_missing_list_and_invalid_commands_do_not_create_file(self):
        self.assertEqual(json.loads(self.run_cli("list").stdout), [])
        for args in (("add", " "), ("add", "字" * 81), ("complete", "0"),
                     ("complete", "abc"), ("undo", "1.0"), ("undo", "-1"),
                     ("complete", "1"), ("list", "--status", "bad"), ("unknown",), ()):
            self.run_cli(*args, code=1)
            self.assertFalse(self.path.exists())

    def test_process_roundtrip_duplicates_filters_and_idempotence(self):
        for identifier in (1, 2):
            task = json.loads(self.run_cli("add", "  同名  ").stdout)
            self.assertEqual(task, {"id": identifier, "title": "同名", "status": "pending"})
        for action, status in (("complete", "completed"), ("complete", "completed"),
                               ("undo", "pending"), ("undo", "pending")):
            task = json.loads(self.run_cli(action, "1").stdout)
            self.assertEqual(task["status"], status)
        self.run_cli("complete", "2")
        self.assertEqual([t["id"] for t in json.loads(self.run_cli("list").stdout)], [1, 2])
        for status, expected in (("pending", [1]), ("completed", [2]), ("all", [1, 2])):
            result = json.loads(self.run_cli("list", "--status", status).stdout)
            self.assertEqual([t["id"] for t in result], expected)
        before = self.path.read_bytes()
        self.run_cli("complete", "99", code=1)
        self.run_cli("add", " ", code=1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_corruption_is_not_disclosed_or_overwritten_and_recovery(self):
        for bad in (b"{private-secret", b"\xff", b'{"version":1,"next_id":1,"tasks":[{}]}'):
            self.path.write_bytes(bad)
            for args in (("list",), ("add", "新建"), ("complete", "1"), ("undo", "1")):
                result = self.run_cli(*args, code=2)
                self.assertNotIn("private-secret", result.stderr)
                self.assertEqual(self.path.read_bytes(), bad)
        self.path.write_text('{"version":1,"next_id":1,"tasks":[]}', encoding="utf-8")
        self.assertEqual(json.loads(self.run_cli("add", "恢复").stdout)["id"], 1)

    def test_help_argument_errors_and_missing_parent(self):
        self.assertIn("usage:", self.run_cli("--help", file=False).stdout)
        self.run_cli("list", file=False, code=1)
        self.run_cli("add", code=1)
        self.run_cli("list", "--unknown", code=1)
        self.path = self.path.parent / "missing/tasks.json"
        self.assertEqual(json.loads(self.run_cli("list").stdout), [])
        self.run_cli("add", "待办", code=2)
        self.assertFalse(self.path.parent.exists())

    def test_symlink_and_directory_are_storage_errors(self):
        target = self.path.parent / "target.json"
        target.write_text('{"version":1,"next_id":1,"tasks":[]}', encoding="utf-8")
        self.path.symlink_to(target)
        self.run_cli("list", code=2)
        self.run_cli("add", "待办", code=2)
        self.assertTrue(self.path.is_symlink())
        self.path = self.path.parent
        self.run_cli("list", code=2)
