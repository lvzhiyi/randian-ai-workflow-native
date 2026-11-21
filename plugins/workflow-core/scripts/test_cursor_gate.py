"""Cursor 官方回调形状的适配回归；不代表真实客户端端到端验证。"""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

SCRIPTS = Path(__file__).parent


class CursorGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project"
        self.root.mkdir()
        (self.root / "ai-workflow.yaml").write_text("version: 1\n", encoding="utf-8")
        self.env = patch.dict(os.environ, {"HOME": self.tmp.name, "WORKFLOW_HOST": "cursor", "WORKFLOW_ENGINE_HOME": str(Path(self.tmp.name) / "engine")})
        self.env.start()
        self.addCleanup(self.env.stop)
        for key in ("WORKFLOW_TASK_ID", "WORKFLOW_ROUND_ID", "WORKFLOW_EXECUTOR", "CURSOR_PROJECT_DIR"):
            old = os.environ.pop(key, None)
            if old is not None:
                self.addCleanup(os.environ.__setitem__, key, old)

    def event(self, tool="Write", *, conversation_id="conv-1", **data):
        return dict(conversation_id=conversation_id, generation_id="gen-1", workspace_roots=[str(self.root)], cwd=str(SCRIPTS.parent), hook_event_name="preToolUse", tool_name=tool, tool_input=data, tool_use_id="call-1")

    def call(self, event):
        result = subprocess.run([sys.executable, str(SCRIPTS / "cursor_gate.py")], input=json.dumps(event) if not isinstance(event, str) else event, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_adapter_exists(self):
        self.assertIsNotNone(importlib.util.find_spec("cursor_gate"), "缺少 Cursor 同步适配器")

    def test_no_task_and_readonly(self):
        for tool, data in (("Write", {"file_path": "x"}), ("Shell", {"command": "touch x"}), ("Task", {"subagent_type": "explore"}), ("MCP:service:write", {})):
            self.assertEqual(self.call(self.event(tool, **data))["permission"], "deny")
        for tool in ("Read", "Glob", "Grep", "rg", "AskQuestion"):
            self.assertEqual(self.call(self.event(tool))["permission"], "allow")

    def test_planning_help_without_task(self):
        cli = str(SCRIPTS / "workflow_planning_cli.py")
        for suffix in ("--help", "-h", "open --help", "status -h", "close --help"):
            command = "WORKFLOW_HOST=cursor python3 " + cli + " " + suffix
            self.assertEqual(self.call(self.event("Shell", command=command))["permission"], "allow", command)
        for suffix in ("open --help --evil", "open --help; touch x", "open --help && touch x"):
            self.assertEqual(self.call(self.event("Shell", command="python3 " + cli + " " + suffix))["permission"], "deny")

    def test_readonly_chain_and_git_safety(self):
        command = "git status --short && git remote -v && git symbolic-ref --short refs/remotes/origin/HEAD && git log --merges --format=%s origin/develop -10"
        result = self.call(self.event("Shell", command=command, working_directory=str(self.root)))
        self.assertEqual(result["permission"], "allow")
        self.assertIn("--no-ext-diff", result["updated_input"]["command"])
        self.assertIn("--no-textconv", result["updated_input"]["command"])
        for command in ("git status && touch x", "git remote add x y", "git symbolic-ref HEAD refs/heads/x", "git status || pwd", "git status &&", "pwd && git diff --output=x", "pwd && git diff --ext-diff", "pwd && git show --textconv"):
            self.assertEqual(self.call(self.event("Shell", command=command))["permission"], "deny", command)

    def test_planning_lifecycle_without_implementation_task(self):
        import shlex
        cli = str(SCRIPTS / "workflow_planning_cli.py")
        conversation = {"conversation_id": "planning-" + uuid.uuid4().hex}
        start = self.call(dict(self.event(**conversation), hook_event_name="sessionStart"))
        context = start.get("additional_context", "")
        match = re.search(r"^Cursor conversation_id: ([A-Za-z0-9_.-]+)$", context, re.MULTILINE)
        self.assertIsNotNone(match, context)
        session = match.group(1)
        self.assertEqual(session, conversation["conversation_id"])
        self.assertIn("--session", context)

        other_root = Path(self.tmp.name) / "other"
        other_root.mkdir()
        (other_root / "ai-workflow.yaml").write_text("version: 1\n", encoding="utf-8")
        for operation in ("init", "prd-breakdown"):
            target = "docs/product/项目首页.md" if operation == "init" else "docs/product/任务/账户.md"
            argv = ["python3", cli, "open", "--root", str(self.root), "--session", session, "--operation", operation, "--path", target]
            for option, value in (("--session", "other"), ("--root", str(other_root))):
                invalid = argv.copy()
                invalid[invalid.index(option) + 1] = value
                self.assertEqual(self.call(self.event("Shell", command=shlex.join(invalid), **conversation))["permission"], "deny")
            command = "WORKFLOW_HOST=cursor " + shlex.join(argv)
            self.assertEqual(self.call(self.event("Shell", command=command, **conversation))["permission"], "allow")
            result = subprocess.run(argv, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            document = self.root / target
            document.parent.mkdir(parents=True, exist_ok=True)
            document.write_text("待确认\n", encoding="utf-8")
            self.assertEqual(self.call(self.event("Edit", path=target, **conversation))["permission"], "allow")
            document.write_text("已确认\n", encoding="utf-8")
            self.assertEqual(self.call(self.event("Edit", path=target, conversation_id="other"))["permission"], "deny")
            for path in (str(document.with_name("未登记.md")), "src/a.py"):
                self.assertEqual(self.call(self.event("Edit", path=path, **conversation))["permission"], "deny")
            close = ["python3", cli, "close", "--root", str(self.root), "--session", session]
            self.assertEqual(self.call(self.event("Shell", command=shlex.join(close), **conversation))["permission"], "allow")
            self.assertEqual(subprocess.run(close, capture_output=True).returncode, 0)
            self.assertEqual(self.call(self.event("Edit", path=target, **conversation))["permission"], "deny")
            self.assertEqual(document.read_text(encoding="utf-8"), "已确认\n")

    def test_git_updates_preserve_input(self):
        result = self.call(self.event("Shell", command="git diff src", working_directory=str(self.root), timeout=42))
        self.assertEqual(result["permission"], "allow")
        self.assertEqual(result["updated_input"]["timeout"], 42)
        self.assertIn("--no-ext-diff", result["updated_input"]["command"])

    def test_roots_are_unambiguous(self):
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        (other / "ai-workflow.yaml").write_text("version: 1\n")
        event = self.event("Shell", command="pwd")
        event["workspace_roots"].append(str(other))
        self.assertEqual(self.call(event)["permission"], "deny")
        event["tool_input"]["working_directory"] = str(self.root)
        self.assertEqual(self.call(event)["permission"], "allow")
        event["tool_input"]["working_directory"] = str(Path(self.tmp.name))
        self.assertEqual(self.call(event)["permission"], "deny")
        with patch.dict(os.environ, {"CURSOR_PROJECT_DIR": str(other)}):
            self.assertEqual(self.call(self.event("Read"))["permission"], "deny")

    def test_actual_shell_directory_selects_nearest_project(self):
        import cursor_gate
        child = self.root / "child"
        child.mkdir()
        (child / "ai-workflow.yaml").write_text("version: 1\n")
        event = self.event("Shell", command="touch x", working_directory=str(child))
        self.assertEqual(cursor_gate.normalize(event)["cwd"], str(child.resolve()))
        with patch.dict(os.environ, {"CURSOR_PROJECT_DIR": str(self.root)}):
            self.assertEqual(cursor_gate.normalize(event)["cwd"], str(child.resolve()))
            event["workspace_roots"].append(str(child))
            self.assertEqual(cursor_gate.normalize(event)["cwd"], str(child.resolve()))
        # 父项目授权不能泄露给带独立配置的子项目。
        import host_gate
        with patch.object(host_gate, "pre_tool", side_effect=lambda value: "child denied" if host_gate.project_root(value["cwd"]) == child.resolve() else None):
            self.assertEqual(cursor_gate.handle(event)["permission"], "deny")
        sibling = self.root / "sibling"
        sibling.mkdir()
        with patch.dict(os.environ, {"CURSOR_PROJECT_DIR": str(sibling)}):
            self.assertEqual(self.call(event)["permission"], "deny")

    def test_unconfigured_workspace_bypasses_gate(self):
        (self.root / "ai-workflow.yaml").unlink()
        for tool in ("Shell", "Write", "WebSearch", "Task"):
            self.assertEqual(self.call(self.event(tool, command="python3 init.py")), {"permission": "allow"})
        for name in ("sessionStart", "postToolUse"):
            self.assertEqual(self.call(dict(self.event(), hook_event_name=name)), {})
        self.assertEqual(self.call(dict(self.event(), hook_event_name="subagentStart")), {"permission": "allow"})

    def test_configured_errors_never_bypass(self):
        (self.root / "ai-workflow.yaml").write_text("version: 999\n")
        self.assertEqual(self.call(self.event("Shell", command="touch x"))["permission"], "deny")

    def test_cursor_cli_prefix_is_narrow(self):
        cli = str(SCRIPTS / "workflow_engine_cli.py")
        for command in ("WORKFLOW_HOST=cursor python3 /tmp/other.py status", "WORKFLOW_HOST=cursor python3 " + cli + " status; touch x", "WORKFLOW_HOST=cursor", "env WORKFLOW_HOST=cursor python3 " + cli + " status"):
            import host_gate
            self.assertFalse(host_gate.engine_command(command))

    def test_malformed_fails_closed(self):
        for event in ("{", [], self.event("Write", path=3), dict(self.event(), tool_input="bad"), dict(self.event(), conversation_id="")):
            self.assertEqual(self.call(event)["permission"], "deny")

    def test_lifecycle_outputs(self):
        result = self.call(dict(self.event(), hook_event_name="sessionStart", tool_input=None))
        self.assertEqual(result["env"], {"WORKFLOW_HOST": "cursor"})
        self.assertIn("additional_context", result)
        self.assertIn(str((SCRIPTS / "workflow_engine_cli.py").resolve()), result["additional_context"])
        self.assertIn("prepare", result["additional_context"])
        result = self.call(dict(self.event("Task"), hook_event_name="subagentStart"))
        self.assertEqual(result["permission"], "allow")
        self.assertEqual(set(result), {"permission", "user_message"})
        self.assertIn("独立写入授权", result["user_message"])
        malformed = self.call(dict(self.event(), hook_event_name="subagentStart", conversation_id=""))
        self.assertEqual(set(malformed), {"permission", "user_message"})
        self.assertEqual(malformed["permission"], "deny")

    def test_post_does_not_consume_claude_receipts(self):
        read_output = json.dumps({"file": {"content": "规范", "startLine": 1, "numLines": 1, "totalLines": 1}})
        for tool in ("Read", "ReadFile"):
            self.assertEqual(self.call(dict(self.event(tool, path="rules.md"), hook_event_name="postToolUse", tool_output=read_output)), {})
        approval = json.dumps({"approved": True, "answers": {"workflow-confirm:x": "确认"}})
        self.assertEqual(self.call(dict(self.event("AskQuestion"), hook_event_name="postToolUse", tool_output=approval)), {})
        context = self.call(dict(self.event("AskQuestion", question="workflow-confirm:x"), hook_event_name="postToolUse", tool_output=approval))["additional_context"]
        self.assertIn("request-confirmation", context)
        self.assertNotIn("RECORDED", context)

    def test_real_engine_and_cross_session_isolation(self):
        from workflow_engine.engine import Engine
        from workflow_engine_cli import default_db
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "src").mkdir()
        (self.root / "rules.md").write_text("规范", encoding="utf-8")
        engine = Engine(self.root, default_db(self.root))
        plan = {"version": 1, "checks": [{"id": "all", "argv": [sys.executable, "-c", "pass"], "cwd": ".", "timeout": 2, "covers": ["format", "analyze", "test"], "acceptance": ["A1"]}]}
        task = engine.create("T1", "light", ["A1"], plan, str(uuid.uuid4()), details={"goal": "适配", "scope": ["src"], "source": "用户", "dependencies": [], "baseline": ["rules.md"], "steps": [{"id": "s1", "title": "实现"}]})
        task = engine.confirm_tier("T1", task["version"], str(uuid.uuid4()), "用户")
        task = engine.bind_executor("T1", task["version"], str(uuid.uuid4()), "agent", "conv-1")
        before_baseline = self.call(self.event("Write", path="src/a.py"))
        self.assertEqual(before_baseline["permission"], "deny")
        self.assertIn("read-baseline", before_baseline["agent_message"])
        cli = [sys.executable, str(SCRIPTS / "workflow_engine_cli.py"), "--root", str(self.root), "read-baseline", "--task", "T1", "--version", str(task["version"]), "--request", str(uuid.uuid4()), "--path", "rules.md", "--executor", "agent", "--session", "conv-1"]
        self.assertEqual(subprocess.run(cli, capture_output=True).returncode, 0)
        task = engine.status("T1")
        engine.start("T1", task["version"], str(uuid.uuid4()))
        child = self.root / "child"
        child.mkdir()
        (child / "ai-workflow.yaml").write_text("version: 1\n")
        with patch.dict(os.environ, {"CURSOR_PROJECT_DIR": str(self.root)}):
            self.assertEqual(self.call(self.event("Shell", command="touch x", working_directory=str(child)))["permission"], "deny")
        before = engine.status("T1")["version"]
        self.call(dict(self.event("AskQuestion", question="workflow-confirm:T1:fake:digest:approval"), hook_event_name="postToolUse", tool_output=json.dumps({"approved": True})))
        self.call(dict(self.event("Read", path="rules.md"), hook_event_name="postToolUse", tool_output=json.dumps({"file": {"content": "规范", "startLine": 1, "numLines": 1, "totalLines": 1}})))
        self.assertEqual(engine.status("T1")["version"], before)
        for key in ("path", "file_path", "target_file"):
            self.assertEqual(self.call(self.event("Write", **{key: "src/a.py"}))["permission"], "allow")
            self.assertEqual(self.call(self.event("Delete", **{key: "outside.py"}))["permission"], "deny")
        self.assertEqual(self.call(self.event("Write"))["permission"], "deny")
        self.assertEqual(self.call(dict(self.event("Write", path="src/a.py"), conversation_id="other"))["permission"], "deny")
        self.assertEqual(self.call(self.event("Task", subagent_type="generalPurpose"))["permission"], "allow")
        second = engine.create("T2", "light", ["A1"], plan, str(uuid.uuid4()), details={"goal": "另一任务", "scope": ["other"], "source": "用户", "dependencies": [], "baseline": ["rules.md"], "steps": [{"id": "s1", "title": "实现"}]})
        engine.bind_executor("T2", second["version"], str(uuid.uuid4()), "agent", "conv-2")
        isolated = dict(self.event("Write", path="src/a.py"), conversation_id="conv-2")
        self.assertEqual(self.call(isolated)["permission"], "deny")

    def test_chat_selects_tier_then_approves_current_full_proposal(self):
        from workflow_engine.engine import Engine
        from workflow_engine_cli import default_db

        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "ai-workflow.yaml").write_text("version: 1\nverify:\n  light: 'true'\n  full: git status --short\n", encoding="utf-8")
        engine = Engine(self.root, default_db(self.root))
        check = {"id": "all", "argv": ["true"], "cwd": ".", "timeout": 2, "covers": ["format", "analyze", "test"], "acceptance": ["A1"]}
        plan = {"version": 1, "checks": [check]}
        task = engine.create("T1", "light", ["A1"], plan, "create", details={"goal": "目标", "scope": ["src"], "source": "用户", "steps": [{"id": "s1", "title": "修改"}]})
        task = engine.bind_executor("T1", task["version"], "bind", "agent", "conv-1")

        def request(task, action):
            cli = [sys.executable, str(SCRIPTS / "workflow_engine_cli.py"), "--root", str(self.root), "request-confirmation", "--task", "T1", "--version", str(task["version"]), "--request", uuid.uuid4().hex, "--session", "conv-1", "--kind", action]
            result = subprocess.run(cli, text=True, capture_output=True)
            return json.loads(result.stdout)

        def reply(message, session="conv-1", event_name="beforeSubmitPrompt", **extra):
            return self.call(dict(self.event(conversation_id=session), hook_event_name=event_name, prompt=message, **extra))

        prepared = request(task, "tier_confirmation")
        self.assertTrue(prepared["ok"], prepared)
        self.assertEqual(prepared["confirmation"]["replies"], ["选轻量档", "选标准档", "选完整档"])
        reply("选完整档", "other")
        reply("我建议选完整档")
        reply("选完整档", event_name="postToolUse")
        self.assertEqual(engine.status("T1")["version"], task["version"])
        task = engine.update_task("T1", task["version"], "note", {"note": "说明更新"})
        reply("选完整档")
        self.assertEqual(engine.status("T1")["version"], task["version"])
        self.assertTrue(request(task, "tier_confirmation")["ok"])
        self.assertEqual(reply("选完整档", tool_input=None), {"continue": True})
        selected = engine.status("T1")
        self.assertEqual(selected["tier"], "full")
        self.assertTrue({"approval", "proposal", "verify_config"} <= set(selected["missing"]))
        self.assertNotIn("tier_confirmation", selected["missing"])
        self.assertFalse(request(selected, "approval")["ok"])

        proposal = {key: "内容" for key in ("goal", "scope", "impact", "risk", "rollback", "acceptance")}
        full_plan = dict(plan, checks=[dict(check, argv=["git", "status", "--short"])])
        ready = engine.update_task("T1", selected["version"], "proposal", {"plan": full_plan, "proposal": proposal})
        self.assertNotIn("tier_confirmation", ready["missing"])
        self.assertEqual(request(ready, "approval")["confirmation"]["replies"], ["批准方案"])
        self.assertEqual(reply("批准方案"), {"continue": True})
        approved = engine.status("T1")
        self.assertNotIn("approval", approved["missing"])
        reply("批准方案")
        self.assertEqual(engine.status("T1")["version"], approved["version"])

    def test_manifest_contract(self):
        manifest = json.loads((SCRIPTS.parent / ".cursor-plugin/plugin.json").read_text())
        self.assertEqual(manifest["version"], json.loads((SCRIPTS.parent / ".codex-plugin" / "plugin.json").read_text())["version"])
        self.assertEqual(manifest["hooks"], "./hooks/cursor.json")
        self.assertEqual(manifest["skills"], "./skills/")
        hooks = json.loads((SCRIPTS.parent / "hooks/cursor.json").read_text())["hooks"]
        self.assertIn("beforeSubmitPrompt", hooks)
        for name, entries in hooks.items():
            for entry in entries:
                self.assertIs(entry["failClosed"], name != "beforeSubmitPrompt")
                self.assertEqual(entry["timeout"], 10 if name == "beforeSubmitPrompt" else 30)
                self.assertNotIn("hooks", entry)
        marketplace = json.loads((SCRIPTS.parents[2] / ".cursor-plugin/marketplace.json").read_text())
        self.assertEqual([p["name"] for p in marketplace["plugins"]], ["workflow-core"])

    def test_shared_host_never_reads_cursor_receipts(self):
        import host_gate
        with patch.object(host_gate, "load_task", side_effect=AssertionError("不能自动批准或登记")):
            event = dict(cwd=str(self.root), session_id="conv-1", tool_name="AskUserQuestion", tool_input={"question": "workflow-confirm:x"}, tool_response={"approved": True})
            self.assertIn("UNSUPPORTED", host_gate.post_tool(event))
            event["tool_name"] = "Read"
            self.assertIsNone(host_gate.post_tool(event))
        cli = str(SCRIPTS / "workflow_engine_cli.py")
        self.assertTrue(host_gate.engine_command("WORKFLOW_HOST=cursor python3 " + cli + " status"))
        self.assertTrue(host_gate.engine_command("WORKFLOW_HOST=claude python3 " + cli + " status"))
        self.assertFalse(host_gate.engine_command("WORKFLOW_HOST=unknown python3 " + cli + " status"))
        self.assertFalse(host_gate.engine_command("OTHER=value python3 " + cli + " status"))
        dashboard = str(SCRIPTS / "dashboard_server.py")
        self.assertTrue(host_gate.dashboard_command("WORKFLOW_HOST=cursor python3 " + dashboard + " status"))
        self.assertTrue(host_gate.dashboard_command("WORKFLOW_HOST=cursor python3 " + dashboard + " on"))
        self.assertFalse(host_gate.dashboard_command("WORKFLOW_HOST=cursor python3 " + dashboard + " on; touch injected"))


if __name__ == "__main__":
    unittest.main()
