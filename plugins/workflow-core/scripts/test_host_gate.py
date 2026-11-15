"""双宿主模拟门禁测试，不代表真实宿主端到端验证。"""
import os
import json
import shlex
from pathlib import Path
import tempfile
import subprocess
import sys
import uuid
import unittest
from unittest.mock import patch

import host_gate


class HostGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "ai-workflow.yaml").write_text("version: 1\nengine:\n  enabled: false\n", encoding="utf-8")
        self.env = patch.dict(os.environ, {"WORKFLOW_TASK_ID": "T1", "WORKFLOW_ROUND_ID": "r1", "WORKFLOW_EXECUTOR": "agent"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def event(self, tool="Edit", **data):
        return {"cwd": str(self.root), "session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": data}

    def task(self, state="implementing", missing=None):
        return {"protocol_version": 2, "id": "T1", "version": 3, "current_round": "r1", "state": state, "scope": ["src"], "baseline": ["rules.md"], "missing": missing or [], "rounds": [{"id": "r1", "executor": "agent", "session_id": "s1", "binding_version": 1}]}

    def test_read_only_never_hashes_task(self):
        with patch.object(host_gate, "load_task", side_effect=AssertionError("不应查询全量哈希")):
            self.assertIsNone(host_gate.pre_tool(self.event("Read", file_path="rules.md")))
            self.assertIsNone(host_gate.pre_tool(self.event("Bash", command="git status --short")))

    def test_arbitrary_shell_and_mcp_are_writes(self):
        for tool, data in [("Bash", {"command": "python3 -c 'open(\"x\",\"w\")'"}), ("Bash", {"command": "git status; touch x"}), ("mcp__service__update", {})]:
            with self.subTest(tool=tool), patch.object(host_gate, "load_task", return_value=self.task(missing=["tier_confirmation"])):
                self.assertIn("tier_confirmation", host_gate.pre_tool(self.event(tool, **data)))

    def test_binding_state_and_baseline_are_required(self):
        (self.root / "rules.md").write_text("规范", encoding="utf-8")
        for state in ("review_passed", "created", "cancelled"):
            with patch.object(host_gate, "load_task", return_value=self.task(state)):
                self.assertIsNotNone(host_gate.pre_tool(self.event(file_path="src/a.py")))
        with patch.object(host_gate, "load_task", return_value=self.task()):
            self.assertIsNone(host_gate.pre_tool(self.event(file_path="src/a.py")))
            with patch.dict(os.environ, {"WORKFLOW_EXECUTOR": "other"}):
                self.assertIn("绑定", host_gate.pre_tool(self.event(file_path="src/a.py")))

    def test_config_baseline_cannot_be_omitted(self):
        (self.root / "ai-workflow.yaml").write_text("version: 1\nbaseline:\n  required:\n    - required.md\n", encoding="utf-8")
        with patch.object(host_gate, "load_task", return_value=self.task()):
            self.assertIn("required.md", host_gate.pre_tool(self.event(file_path="src/a.py")))

    def test_shell_read_allowlist_rejects_execution_features(self):
        for command in ("python -c pass", "rg --pre python x", "git -c alias.x='!touch x' x", "find . -exec touch x ;", "cat x > y", "env python -c pass", "git diff --output=x", "git diff --ext-diff"):
            self.assertFalse(host_gate.readonly_shell(command), command)
        for command in ("git status --short", "rg -n needle src", "pwd", "ls -la", "cat rules.md"):
            self.assertTrue(host_gate.readonly_shell(command), command)

    def test_scoped_baselines_cover_directory_and_real_target(self):
        (self.root / "ai-workflow.yaml").write_text("version: 1\nbaseline:\n  scoped:\n    - src/**/*.py => python.md\n    - other/** => other.md\n", encoding="utf-8")
        with patch.object(host_gate, "load_task", return_value=self.task()):
            self.assertIn("python.md", host_gate.pre_tool(self.event(file_path="src/new.py")))
            self.assertIn("other.md", host_gate.pre_tool(self.event(file_path="other/new.txt")))

    def test_full_tier_unapproved_and_other_session_are_denied(self):
        task = self.task(missing=["approval"])
        with patch.object(host_gate, "load_task", return_value=task):
            self.assertIn("approval", host_gate.pre_tool(self.event(file_path="src/a.py")))
            event = self.event(file_path="src/a.py")
            event["session_id"] = "s2"
            self.assertIn("绑定", host_gate.pre_tool(event))

    def test_plan_exception_only_explicit_document_paths(self):
        with patch.dict(os.environ, {"WORKFLOW_PLAN_PATHS": "docs/plan.md"}), patch.object(host_gate, "load_task", side_effect=ValueError("unbound")):
            self.assertIsNotNone(host_gate.pre_tool(self.event("Write", file_path="docs/plan.md")))
            self.assertIsNotNone(host_gate.pre_tool(self.event("Write", file_path="docs/source.py")))
            self.assertIsNotNone(host_gate.pre_tool(self.event("Write", file_path="docs/other.md")))

    def test_read_receipt_rejects_truncated_failed_and_unknown_schemas(self):
        (self.root / "ai-workflow.yaml").write_text("version: 1\nbaseline:\n  required:\n    - rules.md\n", encoding="utf-8")
        (self.root / "rules.md").write_text("完整规范", encoding="utf-8")
        for response in ({"error": "failed"}, "完整规范", {"file": {"content": "完整", "startLine": 1, "numLines": 1, "totalLines": 2}}):
            event = self.event("Read", file_path="rules.md")
            event["tool_response"] = response
            with patch.object(host_gate, "load_task", side_effect=AssertionError("失败读取不应登记")):
                self.assertIn("ENGINE_BASELINE_UNREAD", host_gate.post_tool(event))

    def test_read_receipt_registers_full_exact_content_with_binding(self):
        (self.root / "ai-workflow.yaml").write_text("version: 1\nbaseline:\n  required:\n    - rules.md\n", encoding="utf-8")
        (self.root / "rules.md").write_text("完整规范", encoding="utf-8")
        event = self.event("Read", file_path="rules.md")
        event["tool_response"] = {"file": {"content": "完整规范", "startLine": 1, "numLines": 1, "totalLines": 1}}
        with patch.object(host_gate, "load_task", return_value=self.task()), patch("workflow_engine.engine.Engine") as engine:
            self.assertIn("ENGINE_BASELINE_RECORDED", host_gate.post_tool(event))
            args = engine.return_value.register_baseline.call_args.args
            self.assertEqual(args[1], 3)
            self.assertEqual(args[3]["round_id"], "r1")
            self.assertEqual(args[3]["executor"], "agent")
            self.assertTrue(args[3]["complete"])

    def test_real_engine_binding_read_receipt_and_invalidation(self):
        from workflow_engine.engine import Engine
        from workflow_engine_cli import default_db
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "ai-workflow.yaml").write_text("version: 1\nbaseline:\n  required:\n    - rules.md\n", encoding="utf-8")
        (self.root / "rules.md").write_text("完整规范", encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src/a.py").write_text("pass", encoding="utf-8")
        engine_home = tempfile.TemporaryDirectory()
        self.addCleanup(engine_home.cleanup)
        with patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": engine_home.name}):
            engine = Engine(self.root, default_db(self.root))
            plan = {"version": 1, "checks": [{"id": "all", "argv": [sys.executable, "-c", "pass"], "cwd": ".", "timeout": 2, "covers": ["format", "analyze", "test"], "acceptance": ["A1"]}]}
            task = engine.create("T1", "light", ["A1"], plan, str(uuid.uuid4()), details={"goal": "目标", "scope": ["src"], "source": "用户", "dependencies": [], "baseline": ["rules.md"], "steps": [{"id": "s1", "title": "实现"}]})
            task = engine.confirm_tier("T1", task["version"], str(uuid.uuid4()), "用户")
            task = engine.bind_executor("T1", task["version"], str(uuid.uuid4()), "agent", "s1")
            with patch.dict(os.environ):
                for key in ("WORKFLOW_TASK_ID", "WORKFLOW_EXECUTOR", "WORKFLOW_ROUND_ID"):
                    os.environ.pop(key, None)
                self.assertIn("baseline", host_gate.pre_tool(self.event(file_path="src/a.py")))
                read = self.event("Read", file_path="rules.md")
                read["hook_event_name"] = "PostToolUse"
                read["tool_response"] = {"file": {"content": "完整规范", "startLine": 1, "numLines": 1, "totalLines": 1}}
                self.assertIn("RECORDED", host_gate.post_tool(read))
                task = engine.status("T1")
                engine.start("T1", task["version"], str(uuid.uuid4()))
                self.assertIsNone(host_gate.pre_tool(self.event(file_path="src/a.py")))
                wrong = self.event(file_path="src/a.py")
                wrong["session_id"] = "other-session"
                self.assertIsNotNone(host_gate.pre_tool(wrong))
                current = engine.status("T1")
                engine.return_task("T1", current["version"], str(uuid.uuid4()), "重新授权", "用户")
                self.assertIsNotNone(host_gate.pre_tool(self.event(file_path="src/a.py")))
                (self.root / "rules.md").write_text("已经变更的规范", encoding="utf-8")
                self.assertIsNotNone(host_gate.pre_tool(self.event(file_path="src/a.py")))

    def test_pending_confirmation_matches_task_round_digest_and_call(self):
        task = self.task()
        task["control_digest"] = "digest"
        question = "workflow-confirm:T1:r1:digest:tier_confirmation"
        event = self.event("AskUserQuestion", questions=[{"question": question, "options": [{"label": "确认"}, {"label": "拒绝"}]}])
        event["tool_use_id"] = "call1"
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": home, "WORKFLOW_HOST": "claude"}), patch.object(host_gate, "load_task", return_value=task), patch("workflow_engine.engine.Engine") as engine:
            self.assertIsNone(host_gate.pre_tool(event))
            event["tool_response"] = {"answers": {question: "确认"}}
            wrong = dict(event, tool_use_id="wrong")
            self.assertIn("UNSUPPORTED", host_gate.post_tool(wrong))
            engine.return_value.confirm_tier.assert_not_called()
            self.assertIn("RECORDED", host_gate.post_tool(event))
            engine.return_value.confirm_tier.assert_called_once()
            self.assertIn("UNSUPPORTED", host_gate.post_tool(event))
            event = dict(event, tool_name="ExitPlanMode", tool_use_id="call2", tool_input={"plan": "workflow-confirm:T1:r1:digest:approval"}, tool_response={"approved": True})
            self.assertIsNone(host_gate.pre_tool(event))
            self.assertIn("RECORDED", host_gate.post_tool(event))
            engine.return_value.approve_proposal.assert_called_once()

    def test_cli_inline_create_bind_read_start_without_parent_binding(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "rules.md").write_text("规范", encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src/a.py").write_text("pass", encoding="utf-8")
        cli = str(Path(host_gate.__file__).with_name("workflow_engine_cli.py"))
        plan = {"version": 1, "checks": [{"id": "all", "argv": [sys.executable, "-c", "pass"], "cwd": ".", "timeout": 2, "covers": ["format", "analyze", "test"], "acceptance": ["A1"]}]}
        details = {"goal": "含 $ 和 ; 的目标", "scope": ["src"], "source": "用户", "dependencies": [], "baseline": ["rules.md"], "steps": [{"id": "s1", "title": "实现"}]}
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": home}):
            for key in ("WORKFLOW_TASK_ID", "WORKFLOW_ROUND_ID", "WORKFLOW_EXECUTOR"):
                os.environ.pop(key, None)
            def run(action, *args):
                argv = ["python3", cli, "--root", str(self.root), action, "--task", "T1", *args]
                if action != "create":
                    current = run.current
                    argv += ["--version", str(current["version"])]
                argv += ["--request", str(uuid.uuid4())]
                self.assertIsNone(host_gate.pre_tool(self.event("exec_command", cmd=shlex.join(argv))))
                result = subprocess.run(argv, text=True, capture_output=True, env=os.environ.copy())
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                run.current = json.loads(result.stdout)["task"]
                return run.current
            run("create", "--tier", "轻量", "--acceptance", "A1", "--plan-json", json.dumps(plan), "--details-json", json.dumps(details, ensure_ascii=False))
            run("bind-executor", "--executor", "agent", "--session", "s1")
            task = run.current
            marker = "workflow-confirm:T1:" + task["current_round"] + ":" + task["control_digest"] + ":tier_confirmation"
            confirmation = self.event("AskUserQuestion", questions=[{"question": marker}])
            confirmation["tool_use_id"] = "native-confirm-call"
            with patch.dict(os.environ, {"WORKFLOW_HOST": "claude"}):
                self.assertIsNone(host_gate.pre_tool(confirmation))
                confirmation["tool_response"] = {"answers": {marker: "确认"}}
                self.assertIn("RECORDED", host_gate.post_tool(confirmation))
            host_gate.CURRENT_EVENT.set(self.event())
            run.current = host_gate.load_task(self.root)
            run("read-baseline", "--path", "rules.md", "--executor", "agent", "--session", "s1")
            run("start")
            self.assertIsNone(host_gate.pre_tool(self.event(file_path="src/a.py")))
            wrong = self.event(file_path="src/a.py")
            wrong["session_id"] = "wrong"
            self.assertIsNotNone(host_gate.pre_tool(wrong))

    def test_ordinary_questions_and_plans_do_not_require_binding_or_approve(self):
        for tool, data in (("AskUserQuestion", {"questions": [{"question": "需要什么功能？"}]}), ("ExitPlanMode", {"plan": "先调查需求"})):
            event = self.event(tool, **data)
            event["tool_response"] = {"approved": True, "answers": {"需要什么功能？": "确认"}}
            with patch.object(host_gate, "load_task", side_effect=AssertionError("普通澄清不查询任务")):
                self.assertIsNone(host_gate.pre_tool(event))
                self.assertIsNone(host_gate.post_tool(event))

    def test_malformed_confirmation_marker_never_becomes_approval(self):
        for text in ("workflow-confirm:", "workflow-confirm:wrong:round:digest:approval", "workflow-confirm:T1:r1:digest:tier_confirmation-extra"):
            event = self.event("AskUserQuestion", questions=[{"question": text}])
            event["tool_use_id"] = "bad-marker"
            event["tool_response"] = {"answers": {text: "确认"}}
            with patch.object(host_gate, "load_task", return_value={**self.task(), "control_digest": "digest"}), patch("workflow_engine.engine.Engine") as engine:
                self.assertIsNotNone(host_gate.pre_tool(event))
                self.assertNotIn("RECORDED", host_gate.post_tool(event) or "")
                engine.return_value.confirm_tier.assert_not_called()

    def test_session_lookup_ignores_terminal_tasks_and_bounds_resources(self):
        import sqlite3
        from session_binding import lookup
        database = self.root / "state.sqlite"
        def record(identifier, state):
            task = self.task(state)
            task.update(id=identifier, root=str(self.root.resolve()))
            return json.dumps(task)
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY, data TEXT)")
            db.executemany("INSERT INTO tasks VALUES(?,?)", [("old", record("old", "review_passed")), ("cancelled", record("cancelled", "cancelled")), ("active", record("active", "implementing"))])
        self.assertEqual(lookup(self.root, "s1", database), "active")
        with patch("session_binding.MAX_TASKS", 2):
            with self.assertRaisesRegex(ValueError, "LIMIT"):
                lookup(self.root, "s1", database)
        with patch("session_binding.MAX_TASK_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "LIMIT"):
                lookup(self.root, "s1", database)
        with patch("session_binding.MAX_TOTAL_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "LIMIT"):
                lookup(self.root, "s1", database)
        missing = self.root / "missing" / "state.sqlite"
        with self.assertRaises(ValueError):
            lookup(self.root, "s1", missing)
        self.assertFalse(missing.parent.exists())

    def test_stale_confirmation_cannot_approve(self):
        task = self.task()
        task["control_digest"] = "digest"
        question = "workflow-confirm:T1:r1:digest:tier_confirmation"
        event = self.event("AskUserQuestion", questions=[{"question": question}])
        event["tool_use_id"] = "call1"
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": home, "WORKFLOW_HOST": "claude"}), patch.object(host_gate, "load_task", return_value=task), patch("workflow_engine.engine.Engine") as engine:
            self.assertIsNone(host_gate.pre_tool(event))
            task["current_round"] = "different"
            event["tool_response"] = {"answers": {question: "确认"}}
            self.assertIn("REJECTED", host_gate.post_tool(event))
            engine.return_value.confirm_tier.assert_not_called()

    def test_explicit_mcp_allowlist_and_dashboard_status(self):
        command = "python3 " + str(Path(host_gate.__file__).with_name("dashboard_server.py"))
        self.assertTrue(host_gate.dashboard_command(command + " status --root /tmp"))
        self.assertTrue(host_gate.dashboard_command(command + " on"))
        with patch.dict(os.environ, {"WORKFLOW_READONLY_MCP_TOOLS": "mcp__known__read"}), patch.object(host_gate, "load_task", side_effect=ValueError("unbound")):
            self.assertIsNone(host_gate.pre_tool(self.event("mcp__known__read")))
            self.assertIsNotNone(host_gate.pre_tool(self.event("mcp__unknown__read")))

    def test_codex_real_shapes_and_quoted_inline_json(self):
        cli = Path(host_gate.__file__).with_name("workflow_engine_cli.py")
        command = "python3 " + str(cli) + " create --details-json '{\"goal\":\"$x; $(touch bad)\"}'"
        self.assertTrue(host_gate.engine_command(command))
        self.assertFalse(host_gate.engine_command("python3 " + str(cli) + ' create --details-json "$(touch bad)"'))
        for data in ({"cmd": "git status --short"}, {"command": ["bash", "-lc", "git status --short"]}):
            event = self.event("exec_command", **data)
            with patch.object(host_gate, "load_task", side_effect=AssertionError("不应哈希")):
                self.assertIsNone(host_gate.pre_tool(event))
        event = self.event("exec_command", cmd="git --no-pager diff src")
        self.assertIn("--no-ext-diff", host_gate.safe_shell_input(event)["cmd"])
        self.assertIn("--no-textconv", host_gate.safe_shell_input(event)["cmd"])

    def test_oversize_baseline_is_not_registered(self):
        (self.root / "ai-workflow.yaml").write_text("version: 1\nbaseline:\n  required:\n    - rules.md\n", encoding="utf-8")
        (self.root / "rules.md").write_bytes(b"x" * 1048577)
        event = self.event("Read", file_path="rules.md")
        event["tool_response"] = {"file": {"content": "x", "startLine": 1, "numLines": 1, "totalLines": 1}}
        self.assertIn("1MiB", host_gate.post_tool(event))

    def test_native_confirmation_has_no_unverified_auto_approval(self):
        with patch.object(host_gate, "load_task", side_effect=AssertionError("不能批准")):
            self.assertIsNone(host_gate.post_tool(self.event("AskUserQuestion")))
