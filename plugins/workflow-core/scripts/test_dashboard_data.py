"""只读看板的数据、安全边界与引擎降级回归。"""
import importlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


class DashboardDataTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "project"
        self.root.mkdir()
        self.db = Path(self.temp.name).resolve() / "state.sqlite"
        self.api = importlib.import_module("dashboard_data")
        self.env = patch.dict(os.environ, {"WORKFLOW_ENGINE_HOME": str(Path(self.temp.name) / "engine")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def config(self, enabled=False, extra=""):
        self.write("ai-workflow.yaml", "version: 1\nengine:\n  enabled: " + str(enabled).lower() + "\n" + extra)

    def database(self, tasks):
        with sqlite3.connect(str(self.db)) as db:
            db.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY, data TEXT)")
            db.executemany("INSERT INTO tasks VALUES(?,?)", [(t["id"], json.dumps(t)) for t in tasks])

    def build(self, task_id=None):
        with patch("workflow_engine_cli.default_db", return_value=self.db):
            return self.api.build_dashboard(self.root, task_id)

    def test_missing_configuration_and_documents_are_unknown(self):
        data = self.build()
        self.assertEqual(set(data), {"project", "mode", "stages", "tasks", "pending", "documents", "issues", "trace"})
        self.assertEqual([s["id"] for s in data["stages"]], ["prd", "breakdown", "kickoff", "proposal", "implementation", "verification", "review", "delivery"])
        self.assertTrue(all(s["state"] == "unknown" for s in data["stages"]))
        self.assertFalse(self.db.exists())

    def test_cards_pending_and_explicit_stage_evidence(self):
        self.config(extra="docs:\n  requirements: docs/prd.md\n  cards_dir: docs/cards\n  overview: docs/missing.md\n")
        self.write("docs/prd.md", "# 需求\n说明：全部已完成\n- 阶段：prd｜状态：已完成\n")
        self.write("docs/cards/a.md", "### A-R1 登录\n- [x] 子需求完成（仅自测完成后勾选）\n- 待确认：账号｜影响：联调｜负责人：小王｜恢复条件：提供账号｜来源：PRD#3\n")
        data = self.build()
        self.assertEqual(data["tasks"][0]["id"], "A-R1")
        self.assertEqual(data["tasks"][0]["state"], "completed")
        self.assertIn("docs/cards/a.md:", data["tasks"][0]["source"])
        self.assertEqual(data["pending"][0]["resume"], "提供账号")
        self.assertIn("PRD#3", data["pending"][0]["source"])
        self.assertEqual(data["stages"][0]["state"], "completed")
        self.assertTrue(all(s["state"] == "unknown" for s in data["stages"][1:]))
        self.assertIn({"path": "docs/missing.md", "title": "missing", "exists": False}, data["documents"])
        self.assertNotIn("说明：全部已完成", json.dumps(data, ensure_ascii=False))

    def test_conflicting_card_state_stays_unknown(self):
        self.config(extra="docs:\n  cards_dir: cards\n")
        self.write("cards/a.md", "### A-R1 登录\n- 状态：已完成\n- 状态：进行中\n")
        data = self.build()
        self.assertEqual(data["tasks"][0]["state"], "unknown")
        self.assertTrue(any("冲突" in x for x in data["issues"]))

    def test_repeated_consistent_evidence_does_not_conflict(self):
        self.config(extra="docs:\n  cards_dir: cards\n")
        self.write("cards/a.md", "### A-R1 登录\n- 状态：已完成\n- 状态：已完成\n- 状态：已完成\n")
        self.assertEqual(self.build()["tasks"][0]["state"], "completed")

    def test_prose_and_fenced_examples_are_not_evidence(self):
        self.config(extra="docs:\n  home: home.md\n")
        self.write("home.md", "# 首页\n已完成全部开发\n```md\n- 阶段：delivery｜状态：已完成\n### A-R1 示例\n- 状态：已完成\n```\n")
        data = self.build()
        self.assertEqual(data["tasks"], [])
        self.assertTrue(all(s["state"] == "unknown" for s in data["stages"]))

    def test_symlink_root_is_rejected(self):
        self.write("docs/good.md", "正文")
        link = self.root.parent / "alias"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            self.api.read_document(link, "docs/good.md")

    def test_legacy_false_still_reads_database(self):
        self.config(False)
        self.database([{"id": "A", "root": str(self.root), "protocol_version": 2,
                        "current_round": "r", "rounds": [{"id": "r", "state": "implementing"}]}])
        data = self.build()
        self.assertEqual(data["tasks"][0]["state"], "implementing")
        self.assertTrue(data["mode"]["available"])
        self.assertIn("迁移", data["mode"]["warning"])

    def test_template_without_engine_key_reads_database(self):
        template = Path(__file__).parent.parent / "templates" / "ai-workflow.yaml"
        self.write("ai-workflow.yaml", template.read_text(encoding="utf-8"))
        self.database([{"id": "A", "root": str(self.root), "protocol_version": 2,
                        "current_round": "r", "rounds": [{"id": "r", "state": "implementing"}]}])
        data = self.build()
        self.assertEqual(data["tasks"][0]["id"], "A")
        self.assertEqual(data["mode"]["state"], "active")

    def test_missing_engine_key_does_not_create_missing_database(self):
        self.write("ai-workflow.yaml", "version: 1\n")
        data = self.build()
        self.assertEqual(data["mode"]["state"], "unavailable")
        self.assertFalse(self.db.exists())

    def test_human_delivery_checkbox_is_independent_of_agent_state(self):
        self.config(extra="docs:\n  cards_dir: cards\n")
        for checked in (False, True):
            with self.subTest(checked=checked):
                self.write("cards/a.md", "### A-R1 登录\n- 状态：评审通过\n- [" + ("x" if checked else " ") + "] 子需求人工验收/交付完成\n")
                item = self.build()["tasks"][0]
                self.assertEqual(item["human_delivery_completed"], checked)
                self.assertNotEqual(item["state"], "completed")
                self.assertFalse(any("冲突" in issue for issue in self.build()["issues"]))

    def test_human_delivery_document_does_not_override_v2_review(self):
        self.config(False, "docs:\n  cards_dir: cards\n")
        self.write("cards/a.md", "### A-R1 登录\n- [ ] 子需求人工验收/交付完成\n")
        self.database([{"id": "A-R1", "root": str(self.root), "protocol_version": 2,
                        "current_round": "r", "rounds": [{"id": "r", "state": "review_passed"}]}])
        item = self.build()["tasks"][0]
        self.assertEqual(item["state"], "review_passed")
        self.assertIs(item["human_delivery_completed"], False)
        self.assertIs(item["delivered"], False)

    def test_checkbox_constraints_preserve_noncompleted_state(self):
        self.config(extra="docs:\n  cards_dir: cards\n")
        for checked in (False, True):
            for raw in ("进行中", "实施完成待验证", "待开发", "待验证", "已完成"):
                for reversed_order in (False, True):
                    with self.subTest(checked=checked, raw=raw, reversed_order=reversed_order):
                        baseline = self.api._state(raw)
                        lines = ["- [{}] 子需求完成（仅自测完成后勾选）".format("x" if checked else " "), "- 状态：" + raw]
                        if reversed_order:
                            lines.reverse()
                        self.write("cards/a.md", "### A-R1 登录\n" + "\n".join(lines) + "\n")
                        data = self.build()
                        conflict = checked != (baseline == "completed")
                        self.assertEqual(data["tasks"][0]["state"], "unknown" if conflict else baseline)
                        self.assertEqual(any("冲突" in issue for issue in data["issues"]), conflict)

    def test_unchecked_box_without_state_is_pending(self):
        self.config(extra="docs:\n  cards_dir: cards\n")
        self.write("cards/a.md", "### A-R1 登录\n- [ ] 子需求完成（仅自测完成后勾选）\n")
        self.assertEqual(self.build()["tasks"][0]["state"], "pending")

    def test_corrupt_config_is_reported(self):
        self.write("ai-workflow.yaml", "docs: [bad]\n")
        self.assertTrue(self.build()["issues"])

    def test_nearest_configuration_is_used(self):
        self.config(extra="docs:\n  home: docs/home.md\n")
        self.write("docs/home.md", "# 项目首页")
        sub = self.root / "src" / "feature"
        sub.mkdir(parents=True)
        data = self.api.build_dashboard(sub)
        self.assertEqual(data["project"]["root"], str(self.root))
        self.assertTrue(any(d["path"] == "docs/home.md" for d in data["documents"]))

    def test_disabled_enabled_unbound_and_missing_database(self):
        self.config(False)
        self.assertEqual(self.build()["mode"]["state"], "unavailable")
        self.config(True)
        data = self.build("not-bound")
        self.assertTrue(data["mode"]["configured_enabled"])
        self.assertFalse(data["mode"]["available"])
        self.assertFalse(self.db.exists())
        self.database([])
        data = self.build("not-bound")
        self.assertTrue(data["mode"]["available"])
        self.assertEqual(data["mode"]["binding"], "unbound")

    def test_engine_read_only_stale_and_root_binding(self):
        self.config(True)
        self.database([{"id": "A", "root": str(self.root), "state": "passed", "phase": "verification", "plan_digest": "plan", "snapshot": "before"}])
        before = self.db.read_bytes()
        with patch("workflow_engine.snapshot.capture", return_value="after"):
            data = self.build("A")
        self.assertEqual(data["mode"]["binding"], "bound")
        self.assertEqual(data["tasks"][0]["state"], "unknown")
        self.assertIn("历史未核验", data["tasks"][0]["summary"])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(set(p.name for p in self.db.parent.iterdir()), {"project", "state.sqlite"})
        with sqlite3.connect(str(self.db)) as db:
            db.execute("UPDATE tasks SET data=?", (json.dumps({"id": "A", "root": "/another", "state": "completed"}),))
        self.assertEqual(self.build("A")["mode"]["binding"], "mismatch")

    def test_unknown_engine_state_and_bad_json(self):
        self.config(True)
        self.database([{"id": "A", "root": str(self.root), "state": "future-mode"}])
        self.assertEqual(self.build("A")["tasks"][0]["state"], "unknown")
        with sqlite3.connect(str(self.db)) as db:
            db.execute("UPDATE tasks SET data='invalid'")
        self.assertTrue(self.build()["issues"])

    def test_v2_round_is_authoritative_and_never_hashes(self):
        self.config(True)
        self.database([{"id": "A", "protocol_version": 2, "root": str(self.root),
            "state": "completed", "tier": "standard", "current_round": "r2",
            "rounds": [{"id": "r1", "state": "review_passed"},
                       {"id": "r2", "state": "implementing", "phase": "implementation",
                        "todos": [{"id": "s1", "title": "测试", "status": "done"},
                                  {"id": "s2", "title": "实施", "status": "pending"}],
                        "missing": ["baseline"], "attempts": [], "evidence": []}]}])
        before = self.db.read_bytes()
        with patch("workflow_engine.snapshot.capture", side_effect=AssertionError("不能哈希")):
            item = self.build()["tasks"][0]
        self.assertEqual(item["state"], "implementing")
        self.assertEqual(item["progress"], {"done": 1, "total": 2, "current": "实施"})
        self.assertEqual(item["activity_status"], "unknown")
        self.assertEqual(item["details"]["rounds"][0]["id"], "r1")
        self.assertEqual(self.db.read_bytes(), before)

    def test_review_passed_is_not_delivery(self):
        self.config(True)
        self.database([{"id": "A", "protocol_version": 2, "root": str(self.root),
            "current_round": "r", "rounds": [{"id": "r", "state": "review_passed",
            "phase": "done", "attempts": [], "evidence": []}]}])
        item = self.build()["tasks"][0]
        self.assertEqual(item["state"], "review_passed")
        self.assertIn("待人工", item["summary"])
        self.assertFalse(item["delivered"])
        self.assertEqual(item["freshness"], "not_checked")

    def test_missing_current_round_cannot_use_top_level_success(self):
        self.config(True)
        self.database([{"id": "A", "protocol_version": 2, "root": str(self.root),
            "state": "review_passed", "current_round": "absent", "rounds": []}])
        self.assertEqual(self.build()["tasks"][0]["state"], "unknown")

    def test_engine_overrides_document_state_without_conflict(self):
        self.config(True, "docs:\n  cards_dir: cards\n")
        self.write("cards/a.md", "### A-R1 标题\n- 状态：已完成\n")
        self.database([{"id": "A-R1", "protocol_version": 2, "root": str(self.root),
            "current_round": "r", "rounds": [{"id": "r", "state": "failed", "phase": "verification"}]}])
        self.assertEqual(self.build()["tasks"][0]["state"], "failed")

    def test_engine_json_limit_is_enforced_before_materialization(self):
        self.config(True)
        self.database([{"id": "A", "root": str(self.root), "payload": "x" * 10000}])
        with patch.object(self.api, "MAX_ENGINE_JSON_BYTES", 1024):
            data = self.build()
        self.assertEqual(data["tasks"], [])
        self.assertTrue(data["issues"])

    def test_trace_requires_project_task_round_and_session(self):
        self.config(True)
        self.database([{"id": "A", "protocol_version": 2, "root": str(self.root),
            "current_round": "r", "rounds": [{"id": "r", "state": "implementing", "session_id": "s"}]}])
        trace = Path(self.temp.name).resolve() / "trace"
        (trace / "events").mkdir(parents=True)
        event = {"cwd": str(self.root), "task_id": "A", "round_id": "r", "session_id": "s", "event": "PreToolUse", "ts": "2026-11-15T10:00:00Z"}
        events = [event, dict(event, cwd="/other"), dict(event, task_id="B"),
                  dict(event, round_id="old"), dict(event, session_id="other"),
                  {"event": "PreToolUse"}, {"cwd": str(self.root), "event": "PreToolUse"}]
        (trace / "events" / "s.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        with patch.dict(os.environ, {"WORKFLOW_TRACE_DIR": str(trace)}):
            data = self.build("A")["trace"]
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(len(data["unassigned"]), 3)
        self.assertTrue(all(e.get("task_id") != "B" for e in data["unassigned"]))

    def test_trace_events_are_bounded_and_symlinks_rejected(self):
        trace = Path(self.temp.name).resolve() / "trace"
        (trace / "events").mkdir(parents=True)
        event = json.dumps({"cwd": str(self.root), "event": "PreToolUse"}) + "\n"
        (trace / "events" / "s.jsonl").write_text(event * 250)
        with patch.dict(os.environ, {"WORKFLOW_TRACE_DIR": str(trace)}):
            data = self.build()["trace"]
            self.assertEqual(len(data["unassigned"]), 200)
            self.assertTrue(data["limited"])
            (trace / "events" / "s.jsonl").unlink()
            outside = Path(self.temp.name).resolve() / "outside.jsonl"
            outside.write_text(event)
            (trace / "events" / "link.jsonl").symlink_to(outside)
            self.assertEqual(self.build()["trace"]["unassigned"], [])

    def test_document_security(self):
        self.write("docs/good.md", "# 正文")
        self.assertEqual(self.api.read_document(self.root, "docs/good.md"), "# 正文")
        self.write(".env", "SECRET")
        self.write("secrets/private.md", "SECRET")
        self.write("docs/big.md", "x" * (self.api.MAX_DOCUMENT_BYTES + 1))
        (self.root / "linked").symlink_to(self.root / "docs", target_is_directory=True)
        (self.root / "docs/link.md").symlink_to(self.root / "docs/good.md")
        (self.root / "docs/dir.md").mkdir()
        for path in ["../outside.md", "/tmp/a.md", ".env", "secrets/private.md", "docs/big.md", "linked/good.md", "docs/link.md", "docs/dir.md"]:
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                self.api.read_document(self.root, path)

    def test_config_symlink_and_oversized_config_rejected(self):
        outside = Path(self.temp.name) / "config"
        outside.write_text("version: 1\n", encoding="utf-8")
        (self.root / "ai-workflow.yaml").symlink_to(outside)
        self.assertTrue(self.build()["issues"])
        (self.root / "ai-workflow.yaml").unlink()
        self.write("ai-workflow.yaml", "x" * (self.api.MAX_CONFIG_BYTES + 1))
        self.assertTrue(self.build()["issues"])


if __name__ == "__main__":
    unittest.main()
