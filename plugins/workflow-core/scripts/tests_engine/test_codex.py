"""双宿主边界状态的模拟适配测试，不代表真实宿主端到端覆盖。"""
import os
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import patch

import engine_codex
import host_gate


class CodexTests(unittest.TestCase):
    def test_disabled_engine_still_reports_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "ai-workflow.yaml").write_text("version: 1\nengine:\n  enabled: false\n", encoding="utf-8")
            with patch.dict(os.environ, {"WORKFLOW_TASK_ID": ""}):
                result = engine_codex.context({"cwd": str(root), "session_id": "s1", "hook_event_name": "Stop"})
            self.assertIn("ENGINE_TASK_UNBOUND", result)

    def test_review_passed_is_not_human_acceptance(self):
        task = {"protocol_version": 2, "id": "T1", "current_round": "r1", "state": "review_passed", "missing": [],
                "rounds": [{"id": "r1", "executor": "agent", "session_id": "s1"}]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "ai-workflow.yaml").write_text("version: 1\n", encoding="utf-8")
            with patch.dict(os.environ, {"WORKFLOW_TASK_ID": "T1", "WORKFLOW_ROUND_ID": "r1", "WORKFLOW_EXECUTOR": "agent"}), patch.object(host_gate, "load_task", return_value=task):
                result = engine_codex.context({"cwd": str(root), "session_id": "s1", "hook_event_name": "Stop"})
            self.assertIn("待人工验收", result)
            self.assertIn("review_passed", result)


if __name__ == "__main__":
    unittest.main()
