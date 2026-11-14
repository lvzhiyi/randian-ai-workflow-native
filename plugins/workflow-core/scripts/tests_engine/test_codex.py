"""严格模式钩子只展示权威状态，不把交付技能当作完成证据。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

GATE = Path(__file__).resolve().parents[1] / "workflow_gate.py"


class CodexTests(unittest.TestCase):
    def test_enabled_mode_without_binding_reports_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "project"
            root.mkdir()
            (root / "ai-workflow.yaml").write_text(
                "version: 1\nengine:\n  enabled: true\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(GATE)],
                input=json.dumps({"session_id": "s1", "cwd": str(root), "hook_event_name": "Stop"}),
                capture_output=True, text=True,
                env={**os.environ, "WORKFLOW_HOST": "codex", "WORKFLOW_ENGINE_HOME": folder})
            self.assertEqual(result.returncode, 0)
            self.assertIn("ENGINE_TASK_UNBOUND", result.stdout)
            self.assertNotIn("decision", result.stdout)


if __name__ == "__main__":
    unittest.main()
