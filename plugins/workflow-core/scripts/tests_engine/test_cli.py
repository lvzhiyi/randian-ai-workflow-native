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
            result = subprocess.run([sys.executable, str(CLI), "--root", str(root),
                "--db", str(base / "state.sqlite"), "create", "--task", "one",
                "--tier", "轻量", "--acceptance", "A1", "--plan", str(plan),
                "--request", "create"], capture_output=True, text=True,
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
            task = engine.create("one", "light", ["A1"], plan, "create")
            task = engine.confirm_plan("one", task["version"], "confirm", task["plan_digest"])
            task = engine.start("one", task["version"], "start")
            result = subprocess.run([sys.executable, str(CLI), "--root", str(root),
                "--db", str(base / "state.sqlite"), "run", "--task", "one",
                "--version", str(task["version"]), "--request", "run"],
                capture_output=True, text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertFalse(json.loads(result.stdout)["ok"])

    def test_no_arbitrary_pass_command(self):
        self.assertTrue(CLI.is_file(), "CLI 尚未实现")
        result = subprocess.run([sys.executable, str(CLI), "mark-passed"],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
