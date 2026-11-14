"""用原始 PRD 的稳定场景编号核对引擎拒绝路径，不伪造真实宿主验收。"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        from workflow_engine.engine import Engine
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / "project"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "source.py").write_text("value = 1\n", encoding="utf-8")
        self.engine = Engine(self.root, base / "state.sqlite")
        self.plan = {"version": 1, "checks": [{"id": "check", "argv": [sys.executable, "-c", "pass"],
            "cwd": ".", "timeout": 5, "covers": ["format", "analyze", "test"], "acceptance": ["A1"]}]}
        # 此处仅测试内核协议，空命令不代表真实项目检查；项目验收另跑真实测试。

    def test_s04_missing_verification_rejected(self):
        from workflow_engine.model import EngineError
        task = self.engine.create("S04", "light", ["A1"], self.plan, "create")
        with self.assertRaises(EngineError):
            self.engine.complete("S04", task["version"], "complete")

    def test_s03_full_task_requires_approval(self):
        from workflow_engine.model import EngineError
        task = self.engine.create("S03", "full", ["A1"], self.plan, "create")
        with self.assertRaises(EngineError):
            self.engine.start("S03", task["version"], "start")

    def test_s07_loading_skill_does_not_change_engine(self):
        task = self.engine.create("S07", "light", ["A1"], self.plan, "create")
        state = self.engine.status("S07")
        self.assertNotEqual(state["state"], "completed")
        self.assertEqual(state["version"], task["version"])


if __name__ == "__main__":
    unittest.main()
