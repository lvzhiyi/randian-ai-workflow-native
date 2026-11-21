"""钩子进程双宿主模拟测试；不是实际宿主端到端测试。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).parent


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name) / "project"
        self.project.mkdir()
        (self.project / "ai-workflow.yaml").write_text("version: 1\nengine:\n  enabled: false\n", encoding="utf-8")
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir()
        (self.state / "disabled").touch()

    def hook(self, name, host="claude", raw=None, cwd=None, **extra):
        event = {"session_id": "s1", "cwd": str(cwd or self.project), "hook_event_name": name, **extra}
        env = {k: v for k, v in os.environ.items() if not k.startswith("WORKFLOW_")}
        env.update(WORKFLOW_HOST=host, WORKFLOW_GATE_DIR=str(self.state), WORKFLOW_ENGINE_HOME=self.tmp.name)
        return subprocess.run([sys.executable, str(HERE / "workflow_gate.py")], input=json.dumps(event) if raw is None else raw,
                              text=True, capture_output=True, env=env)

    def test_disabled_switches_do_not_bypass_pretool(self):
        for host in ("claude", "codex"):
            for tool, data in (("Edit", {"file_path": "src/a.py"}), ("Write", {"file_path": "a.py"}),
                               ("apply_patch", {"command": "*** Add File: x.py"}), ("Bash", {"command": "python3 -c pass"}),
                               ("mcp__example__update", {})):
                with self.subTest(host=host, tool=tool):
                    result = self.hook("PreToolUse", host, tool_name=tool, tool_input=data)
                    self.assertEqual(result.returncode, 0)
                    value = json.loads(result.stdout)["hookSpecificOutput"]
                    self.assertEqual(value["permissionDecision"], "deny")
                    self.assertIn("ENGINE_TASK_UNBOUND", value["permissionDecisionReason"])
                    self.assertNotIn('"ask"', result.stdout)

    def test_readonly_and_unconfigured_project_are_allowed(self):
        for tool, data in (("Read", {"file_path": "rules.md"}), ("Bash", {"command": "git status --short"})):
            self.assertEqual(self.hook("PreToolUse", tool_name=tool, tool_input=data).stdout, "")
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        self.assertEqual(self.hook("PreToolUse", cwd=other, tool_name="Write", tool_input={"file_path": "x.py"}).stdout, "")
        # 未接入的独立 .git 仓库（哪怕嵌套在已接入父目录下）也必须完全旁路门禁。
        for repo in (other / "git_repo", self.project / "nested_git_repo"):
            (repo / ".git").mkdir(parents=True)
            for host in ("claude", "codex"):
                for tool, data in (("Write", {"file_path": "x.py"}), ("Bash", {"command": "npm test"}), ("mcp__example__update", {})):
                    result = self.hook("PreToolUse", host, cwd=repo, tool_name=tool, tool_input=data)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                for event_name in ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"):
                    result = self.hook(event_name, host, cwd=repo)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")

    def test_malformed_json_is_explicit_nonzero(self):
        for payload in ("not json", "[]", "null"):
            result = self.hook("PreToolUse", raw=payload)
            self.assertEqual(result.returncode, 2)
            self.assertIn("ENGINE_GATE_ERROR", result.stderr)

    def test_invalid_pretool_input_fails_closed(self):
        result = self.hook("PreToolUse", tool_name="Write", tool_input=["invalid"])
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_stop_reports_task_missing_not_legacy_deliver(self):
        for host in ("claude", "codex"):
            result = self.hook("Stop", host)
            self.assertIn("ENGINE_TASK_UNBOUND", result.stdout)
            self.assertNotIn("workflow-core:deliver", result.stdout)

    def test_confirmation_callback_does_not_auto_approve(self):
        for tool in ("AskUserQuestion", "ExitPlanMode"):
            result = self.hook("PostToolUse", tool_name=tool, tool_input={}, tool_response={"answer": "approved"})
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")

    def test_native_tier_selection_is_bound_to_the_question_and_call(self):
        from workflow_engine.engine import Engine
        from workflow_engine_cli import default_db
        from unittest.mock import patch

        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        with patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": self.tmp.name}):
            engine = Engine(self.project, default_db(self.project))
        for host, tool in (("codex", "request_user_input"), ("claude", "AskUserQuestion")):
            with self.subTest(host=host):
                plan = {"version": 1, "checks": [{"id": "check", "argv": ["true"], "cwd": ".", "timeout": 2, "covers": ["format", "analyze", "test"], "acceptance": ["A"]}]}
                task = engine.create(host, "light", ["A"], plan, host + "-create", details={"goal": "目标", "scope": ["src"], "source": "用户", "steps": [{"id": "s1", "title": "修改"}]})
                session = "session-" + host
                task = engine.bind_executor(host, task["version"], host + "-bind", "agent", session)
                marker = f"workflow-confirm:{host}:{task['current_round']}:{task['control_digest']}:tier_confirmation"
                question = {"question": "选择档位 " + marker, "header": "工作档位", "options": [{"label": label, "description": label} for label in ("轻量档", "标准档", "完整档")]}
                if host == "codex":
                    question["id"] = "workflow_tier"
                    answer = json.dumps({"answers": {"workflow_tier": {"answers": ["完整档"]}}}, ensure_ascii=False)
                else:
                    question["multiSelect"] = False
                    answer = {"answers": {question["question"]: "完整档"}}
                event = dict(session_id=session, tool_name=tool, tool_input={"questions": [question]}, tool_use_id="call")
                self.assertEqual(self.hook("PreToolUse", host, **event).stdout, "")
                wrong = dict(event, tool_use_id="other")
                self.assertIn("UNSUPPORTED", self.hook("PostToolUse", host, **wrong, tool_response=answer).stdout)
                self.assertEqual(engine.status(host)["version"], task["version"])
                self.assertIn("RECORDED", self.hook("PostToolUse", host, **event, tool_response=answer).stdout)
                selected = engine.status(host)
                self.assertEqual(selected["tier"], "full")
                self.assertEqual(selected["version"], task["version"] + 1)
                self.assertNotIn("tier_confirmation", selected["missing"])
                self.assertIn("approval", selected["missing"])
                self.assertIn("REJECTED", self.hook("PostToolUse", host, **event, tool_response=answer).stdout)
                self.assertEqual(engine.status(host)["version"], selected["version"])

    def test_manifests_install_synchronous_wildcard_gate(self):
        for filename in ("hooks.json", "codex.json"):
            manifest = json.loads((HERE.parent / "hooks" / filename).read_text(encoding="utf-8"))
            for name in ("PreToolUse", "PostToolUse", "UserPromptSubmit"):
                groups = [g for g in manifest["hooks"][name] if any("workflow_gate.py" in str(h) for h in g["hooks"])]
                self.assertTrue(groups)
                self.assertNotIn("matcher", groups[0])
                self.assertTrue(all(not h.get("async") for g in groups for h in g["hooks"]))


if __name__ == "__main__":
    unittest.main()
