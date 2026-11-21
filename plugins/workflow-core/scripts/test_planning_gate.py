"""真实无任务项目的规划授权与严格命令边界回归。"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import host_gate


class PlanningGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / "project"
        self.root.mkdir()
        (self.root / "ai-workflow.yaml").write_text("version: 1\ndocs:\n  product_root: docs/product\n  cards_dir: docs/product/任务\n  overview: docs/product/任务/版本任务总览.md\n  home: README.md\n", encoding="utf-8")
        self.env = patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": str(Path(self.tmp.name) / "state")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.cli = Path(host_gate.__file__).with_name("workflow_planning_cli.py")

    def event(self, tool="Write", **data):
        return {"cwd": str(self.root), "session_id": "s1", "tool_name": tool, "tool_input": data}

    def run_cli(self, action="open", *extra):
        argv = ["python3", str(self.cli), action, "--root", str(self.root), "--session", "s1", *extra]
        self.assertIsNone(host_gate.pre_tool(self.event("Shell", command=shlex.join(argv))))
        result = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def grant(self):
        self.run_cli("open", "--operation", "prd-breakdown", "--path", "docs/product/任务/账户.md", "--path", "docs/product/任务/版本任务总览.md", "--path", "README.md")

    def test_real_no_task_open_write_close_and_mixed_denied(self):
        self.grant()
        for path in ("docs/product/任务/账户.md", "docs/product/任务/版本任务总览.md", "README.md"):
            self.assertIsNone(host_gate.pre_tool(self.event(file_path=path)))
        patch_text = "*** Begin Patch\n*** Update File: README.md\n@@\n-x\n+y\n*** Add File: src/test.py\n+pass\n*** End Patch"
        self.assertIsNotNone(host_gate.pre_tool(self.event("apply_patch", patch=patch_text)))
        valid_patch = "*** Begin Patch\n*** Add File: docs/product/任务/账户.md\n+文档\n*** End Patch"
        self.assertIsNone(host_gate.pre_tool(self.event("apply_patch", patch=valid_patch)))
        self.assertIsNone(host_gate.pre_tool(self.event("Edit", file_path=str(self.root / "README.md"))))
        for tool, data in [("Shell", {"command": "printf x > README.md"}), ("mcp__update", {"path": "README.md"})]:
            event = self.event(tool, **data)
            self.assertIn("ENGINE_PLANNING_TOOL_UNSUPPORTED", host_gate.pre_tool(event))
            self.assertIn("ENGINE_TASK_UNBOUND", host_gate.pre_tool(dict(event, session_id="other")))
        self.assertIn("ENGINE_PLANNING_TARGET_DENIED", host_gate.pre_tool(self.event("Write", file_path="docs/product/任意.md")))
        self.run_cli("close")
        self.assertIn("ENGINE_TASK_UNBOUND", host_gate.pre_tool(self.event(file_path="README.md")))

    def test_planning_help_is_narrow_and_has_no_side_effects(self):
        from workflow_planning_cli import session_path
        record = session_path(self.root, "s1")
        for host in ("cursor", "codex", "claude"):
            for suffix in ("--help", "-h", "open --help", "close -h", "status --help"):
                command = f"WORKFLOW_HOST={host} python3 {self.cli} {suffix}"
                self.assertIsNone(host_gate.pre_tool(self.event("Shell", command=command)))
        self.assertFalse(record.exists())
        for command in (f"python3 /tmp/workflow_planning_cli.py open --help", f"python3 {self.cli} open --help --path README.md", f"python3 {self.cli} open --help && touch x", f"env WORKFLOW_HOST=cursor python3 {self.cli} --help"):
            self.assertIsNotNone(host_gate.pre_tool(self.event("Shell", command=command)), command)
        self.assertIsNotNone(host_gate.pre_tool(self.event(file_path="README.md")))

    def test_session_root_expiry_and_paths_fail_closed(self):
        self.grant()
        event = self.event(file_path="README.md")
        self.assertIsNotNone(host_gate.pre_tool(dict(event, session_id="wrong")))
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        (other / "ai-workflow.yaml").write_text("version: 1\n")
        self.assertIsNotNone(host_gate.pre_tool(dict(event, cwd=str(other))))
        with patch("workflow_planning_cli.time.time", return_value=10**12):
            self.assertIsNotNone(host_gate.pre_tool(event))
        for path in ("docs/product/任务/../任务/账户.md", "docs/product/任务/test.py", "README.md/evil.py", str(Path(self.tmp.name) / "README.md")):
            self.assertIsNotNone(host_gate.pre_tool(self.event(file_path=path)), path)
        (self.root / "docs").symlink_to(other, target_is_directory=True)
        self.assertIsNotNone(host_gate.pre_tool(self.event(file_path="docs/product/任务/账户.md")))

    def test_dashboard_strict_actions_all_hosts(self):
        script = Path(host_gate.__file__).with_name("dashboard_server.py")
        for host in ("cursor", "codex", "claude"):
            for action in ("on", "off", "status"):
                command = f"WORKFLOW_HOST={host} python3 {script} {action} --root {self.root} --task T1"
                self.assertIsNone(host_gate.pre_tool(self.event("Shell", command=command)))
        self.assertFalse(host_gate.dashboard_command("python3 /tmp/dashboard_server.py on"))
        for suffix in ("", "--root /tmp", "serve", "on --port 1", "on --root /tmp --root /", "on; touch x", "on --task --root", "on --task x extra"):
            self.assertFalse(host_gate.dashboard_command(f"python3 {script} {suffix}"), suffix)
        self.assertFalse(host_gate.dashboard_command("WORKFLOW_HOST=bad python3 " + str(script) + " on"))

    def test_init_bootstrap_without_configuration(self):
        (self.root / "ai-workflow.yaml").unlink()
        (self.root / ".git").mkdir()
        self.assertIsNone(host_gate.pre_tool(self.event(file_path="src/test.py")))
        self.run_cli("open", "--operation", "init", "--path", "ai-workflow.yaml", "--path", "AGENTS.md", "--path", "docs/product/项目首页.md")
        for path in ("ai-workflow.yaml", "AGENTS.md", "docs/product/项目首页.md"):
            self.assertIsNone(host_gate.pre_tool(self.event(file_path=path)))
        self.assertIsNotNone(host_gate.pre_tool(self.event(file_path="src/test.py")))
        self.run_cli("close")
        self.assertIsNone(host_gate.pre_tool(self.event(file_path="src/test.py")))

    def test_registration_rejects_arbitrary_or_disguised_targets(self):
        for path in ("src/test.py", "docs/product/任意.md", "docs/product/任务/test.py.md", "docs/product/任务/../other.md", "AGENTS.md"):
            argv = ["python3", str(self.cli), "open", "--root", str(self.root), "--session", "s1", "--operation", "prd-breakdown", "--path", path]
            result = subprocess.run(argv, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, path)
        self.grant()
        self.run_cli("close")
        from workflow_planning_cli import session_path
        audit = session_path(self.root, "s1").with_suffix(".jsonl")
        entries = [json.loads(line) for line in audit.read_text().splitlines()]
        self.assertEqual(len(entries), 2)
        self.assertIn("closed_at", entries[-1])

    def test_planning_cli_cannot_register_other_session_or_project(self):
        base = ["python3", str(self.cli), "status", "--root", str(self.root), "--session", "wrong"]
        self.assertIsNotNone(host_gate.pre_tool(self.event("Shell", command=shlex.join(base))))
        for argv in (["python3", str(self.cli), "status", "--root", "/tmp", "--session", "s1"],
                     ["python3", str(self.cli), "status", "--root", str(self.root), "--session", "s1", "--evil", "x"]):
            self.assertIsNotNone(host_gate.pre_tool(self.event("Shell", command=shlex.join(argv))))

    def test_custom_init_draft_and_product_root_defaults(self):
        draft = json.dumps({"version": "1", "docs": {"product_root": "product", "cards_dir": "product/cards"}})
        self.run_cli("open", "--operation", "init", "--config-json", draft, "--path", "product/项目首页.md", "--path", "ai-workflow.yaml")
        self.assertIsNone(host_gate.pre_tool(self.event(file_path="product/项目首页.md")))
        self.assertIsNotNone(host_gate.pre_tool(self.event(file_path="docs/product/项目首页.md")))

    @unittest.skipUnless(os.sys.platform == "darwin" and Path("/var").is_symlink(), "仅 macOS 系统路径别名")
    def test_macos_system_alias_preserves_internal_symlink_evidence(self):
        self.grant()
        from workflow_planning_cli import safe_path
        alias_root = Path("/var") / self.root.relative_to("/private/var")
        alias_readme = alias_root / "README.md"
        self.assertEqual(safe_path(self.root, str(alias_readme)), "README.md")
        self.assertIsNone(host_gate.pre_tool(self.event(file_path=str(alias_readme))))
        (self.root / "real.md").write_text("文档")
        (self.root / "README.md").symlink_to("real.md")
        self.assertIsNotNone(host_gate.pre_tool(self.event(file_path=str(alias_readme))))
        with self.assertRaisesRegex(ValueError, "符号链接"):
            safe_path(self.root, str(alias_readme))
        external = self.root.parent / "project-alias"
        external.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            safe_path(self.root, str(external / "real.md"))
        (self.root / "docs").symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            safe_path(self.root, str(alias_root / "docs" / "new.md"))

    def test_plugin_targets_cannot_be_granted_by_config(self):
        for operation, draft in (("init", True), ("prd-breakdown", False)):
            config = {"version": "1", "docs": {"home": "plugins/workflow-core/templates/task-card.md", "cards_dir": "plugins/workflow-core/templates"}}
            if not draft:
                (self.root / "ai-workflow.yaml").write_text("version: 1\ndocs:\n  home: plugins/workflow-core/templates/task-card.md\n  cards_dir: plugins/workflow-core/templates\n")
            for target in ("plugins/workflow-core/templates/task-card.md", "plugins/workflow-core/templates/new.md"):
                argv = ["python3", str(self.cli), "open", "--root", str(self.root), "--session", "s1", "--operation", operation, "--path", target]
                if draft:
                    argv += ["--config-json", json.dumps(config)]
                result = subprocess.run(argv, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stdout)
        (self.root / "plugins").mkdir()
        (self.root / "ai-workflow.yaml").write_text("version: 1\n")
        self.run_cli("open", "--operation", "init", "--path", "docs/product/项目首页.md")

    def test_option_order_and_fixed_init_helpers(self):
        script = Path(host_gate.__file__).with_name("dashboard_server.py")
        self.assertTrue(host_gate.dashboard_command(f"python3 {script} --root {self.root} status"))
        argv = ["python3", str(self.cli), "--root", str(self.root), "--session", "s1", "status"]
        self.assertIsNone(host_gate.pre_tool(self.event("Shell", command=shlex.join(argv))))
        plugin = script.parent.parent
        commands = [f"bash {plugin}/skills/init/detect.sh {self.root}", f"git check-ignore -v ai-workflow.yaml AGENTS.md docs/", f"python3 {plugin}/scripts/check_docs.py --root {self.root} --check-config"]
        for command in commands:
            self.assertIsNone(host_gate.pre_tool(self.event("Shell", command=command)), command)
        for command in (f"bash /tmp/detect.sh {self.root}", f"python3 {plugin}/scripts/check_docs.py --root /tmp --check-config", "git check-ignore -v --stdin", f"python3 {plugin}/scripts/check_docs.py --root {self.root} --check-config --evil x"):
            self.assertIsNotNone(host_gate.pre_tool(self.event("Shell", command=command)), command)

    def test_planning_context_does_not_request_implementation(self):
        text = host_gate.context(self.event())
        self.assertIn("init", text)
        self.assertNotIn("再 start", text)
        self.grant()
        text = host_gate.context(self.event())
        self.assertIn("ENGINE_PLANNING", text)
        self.assertIn("README.md", text)
        self.assertIn("close", text)

    def test_init_config_landing_preserves_skeleton_and_check_access(self):
        (self.root / "ai-workflow.yaml").unlink()
        (self.root / ".git").mkdir()
        self.run_cli("open", "--operation", "init", "--path", "ai-workflow.yaml", "--path", "docs/product/项目首页.md")
        (self.root / "ai-workflow.yaml").write_text("version: 1\ndocs:\n  home: docs/product/项目首页.md\n")
        self.assertIsNone(host_gate.pre_tool(self.event("Write", file_path="docs/product/项目首页.md")))
        target = self.root / "docs/product/项目首页.md"
        target.parent.mkdir(parents=True)
        target.write_text("# 项目首页\n")
        check = self.cli.with_name("check_docs.py")
        argv = ["python3", str(check), "--root", str(self.root), "--check-config"]
        self.assertIsNone(host_gate.pre_tool(self.event("Shell", command=shlex.join(argv))))
        result = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.run_cli("close")
        self.assertIsNotNone(host_gate.pre_tool(self.event("Write", file_path="docs/product/项目首页.md")))

    def test_init_allows_single_file_standards_skeleton(self):
        self.run_cli("open", "--operation", "init", "--path", "docs/development/standards.md")
        self.assertIsNone(host_gate.pre_tool(self.event("Write", file_path="docs/development/standards.md")))
        self.assertIsNotNone(host_gate.pre_tool(self.event("Write", file_path="docs/development/random.md")))
        self.run_cli("close")
