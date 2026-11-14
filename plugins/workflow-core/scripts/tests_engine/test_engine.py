import concurrent.futures
import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from workflow_engine import Engine, EngineError
except ImportError:
    Engine = None
    EngineError = Exception


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "code.txt").write_text("initial")
        self.assertIsNotNone(Engine, "严格引擎尚未实现")
        self.e = Engine(self.root, self.base / "state.sqlite")

    def plan(self, code="pass", timeout=2):
        return {"version": 1, "checks": [{"id": "all", "argv": [sys.executable, "-c", code], "cwd": ".", "timeout": timeout, "covers": ["format", "analyze", "test"], "acceptance": ["A1"]}]}

    def create(self, tier="light", plan=None):
        return self.e.create("t", tier, ["A1"], plan or self.plan(), "create")

    def ready(self, plan=None, tier="light"):
        r = self.create(tier, plan)
        r = self.e.confirm_plan("t", r["version"], "confirm", r["plan_digest"])
        return self.e.start("t", r["version"], "start")

    def error(self, code, fn):
        with self.assertRaises(EngineError) as ctx:
            fn()
        self.assertEqual(ctx.exception.code, code)

    def test_database_schema_version_and_private_permissions(self):
        with sqlite3.connect(str(self.base / "state.sqlite")) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertEqual((self.base / "state.sqlite").stat().st_mode & 0o777, 0o600)

    def test_tracked_cache_input_invalidates(self):
        file = self.root / "node_modules" / "business.py"
        file.parent.mkdir()
        file.write_text("first")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        task = self.ready()
        task = self.e.run("t", task["version"], "run")
        task = self.e.complete("t", task["version"], "complete")
        file.write_text("second")
        self.assertEqual(self.e.status("t")["state"], "stale")

    def test_complete_replay_does_not_report_stale_success(self):
        task = self.ready()
        task = self.e.run("t", task["version"], "run")
        version = task["version"]
        self.e.complete("t", version, "complete")
        (self.root / "code.txt").write_text("changed")
        self.error("MISSING", lambda: self.e.complete("t", version, "complete"))

    def test_light_lifecycle_and_stale(self):
        r = self.ready()
        r = self.e.run("t", r["version"], "run")
        self.assertEqual(r["state"], "passed")
        r = self.e.complete("t", r["version"], "complete")
        self.assertEqual(r["state"], "completed")
        (self.root / "code.txt").write_text("changed")
        r = self.e.status("t")
        self.assertEqual(r["state"], "stale")
        self.assertIn("snapshot", r["missing"])

    def test_confirmation_required_and_digest_checked(self):
        r = self.create()
        self.error("PLAN_UNCONFIRMED", lambda: self.e.start("t", r["version"], "s"))
        self.error("PLAN_DIGEST", lambda: self.e.confirm_plan("t", r["version"], "c", "wrong"))

    def test_strict_plan(self):
        for mutate in [lambda p: p.update(extra=1), lambda p: p.update(version=True), lambda p: p["checks"][0].update(timeout=True), lambda p: p["checks"][0].update(argv="echo"), lambda p: p["checks"][0].update(covers=["test"]), lambda p: p["checks"][0].update(acceptance=[]), lambda p: p["checks"][0].update(cwd="../"), lambda p: p["checks"][0].update(extra=True)]:
            p = self.plan()
            mutate(p)
            self.error("PLAN_INVALID", lambda: self.e.create("x", "light", ["A1"], p, "bad"))

    def test_failure_is_exit_code_not_output(self):
        r = self.ready(self.plan("print('PASS'); raise SystemExit(3)"))
        r = self.e.run("t", r["version"], "run")
        self.assertEqual(r["state"], "failed")
        self.assertEqual(r["results"][0]["exit_code"], 3)
        self.error("MISSING", lambda: self.e.complete("t", r["version"], "complete"))

    def test_timeout(self):
        r = self.ready(self.plan("import time; time.sleep(10)", .1))
        before = time.monotonic()
        r = self.e.run("t", r["version"], "run")
        self.assertLess(time.monotonic() - before, 3)
        self.assertEqual(r["results"][0]["reason"], "timeout")

    def test_idempotency_payload_and_cas(self):
        r = self.create()
        self.assertEqual(r, self.create())
        self.error("IDEMPOTENCY_CONFLICT", lambda: self.e.create("t", "standard", ["A1"], self.plan(), "create"))
        self.error("VERSION_CONFLICT", lambda: self.e.confirm_plan("t", 99, "bad", r["plan_digest"]))

    def test_human_gates(self):
        r = self.ready(tier="standard")
        r = self.e.run("t", r["version"], "run")
        self.error("MISSING", lambda: self.e.complete("t", r["version"], "complete"))
        self.assertIn("review", self.e.status("t")["missing"])
        e = Engine(self.root, self.base / "full.sqlite")
        r = e.create("f", "full", ["A1"], self.plan(), "c")
        r = e.confirm_plan("f", r["version"], "p", r["plan_digest"])
        self.error("APPROVAL_REQUIRED", lambda: e.start("f", r["version"], "s"))

    def test_snapshot_safety_and_db_location(self):
        self.error("DB_LOCATION", lambda: Engine(self.root, self.root / "db"))
        (self.root / ".env").write_text("secret")
        self.error("SENSITIVE_FILE", lambda: self.create())
        (self.root / ".env").unlink()
        (self.root / "link").symlink_to(self.root / "code.txt")
        self.error("SYMLINK", lambda: self.create())

    def test_ignored_and_subdirectory_scope(self):
        (self.root / ".gitignore").write_text("cache/\n")
        (self.root / "cache").mkdir()
        (self.root / "cache/x").write_text("a")
        r = self.ready()
        (self.root / "cache/x").write_text("b")
        r = self.e.run("t", r["version"], "run")
        self.assertEqual(r["state"], "passed")
        sub = self.root / "sub"
        sub.mkdir()
        (sub / "x").write_text("x")
        e = Engine(sub, self.base / "sub.sqlite")
        r = e.create("s", "light", ["A1"], self.plan(), "c")
        (self.root / "outside").write_text("outside")
        self.assertEqual(r["snapshot"], e.status("s")["snapshot"])

    def test_changes_during_run_invalidated(self):
        r = self.ready(self.plan("from pathlib import Path; Path('code.txt').write_text('mutated')"))
        r = self.e.run("t", r["version"], "run")
        self.assertEqual(r["state"], "stale")

    def test_concurrent_cas(self):
        r = self.create()
        def confirm(i):
            try:
                return self.e.confirm_plan("t", r["version"], str(i), r["plan_digest"])["state"]
            except EngineError as exc:
                return exc.code
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            values = list(pool.map(confirm, range(2)))
        self.assertEqual(values.count("VERSION_CONFLICT"), 1)

    def test_active_recovery_refused_and_cancel(self):
        r = self.ready(self.plan("import time; time.sleep(.6)"))
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            future = pool.submit(self.e.run, "t", r["version"], "run")
            for _ in range(100):
                current = self.e.status("t")
                if current["state"] == "running":
                    break
                time.sleep(.01)
            self.error("ACTIVE_OPERATION", lambda: self.e.recover("t", current["version"], "recover"))
            self.error("ACTIVE_OPERATION", lambda: self.e.cancel("t", current["version"], "cancel"))
            done = future.result()
        cancelled = self.e.cancel("t", done["version"], "cancel2")
        self.assertEqual(cancelled["state"], "cancelled")

    def test_complete_persists_invalidation(self):
        r = self.ready()
        r = self.e.run("t", r["version"], "run")
        (self.root / "code.txt").unlink()
        self.error("MISSING", lambda: self.e.complete("t", r["version"], "complete"))
        self.assertEqual(self.e.status("t")["state"], "stale")

    def test_plan_tampering_cannot_reuse_confirmation(self):
        self.ready()
        with sqlite3.connect(str(self.e.db)) as db:
            data = json.loads(db.execute("SELECT data FROM tasks WHERE id='t'").fetchone()[0])
            data["plan"]["checks"][0]["argv"][-1] = "raise SystemExit(0)"
            db.execute("UPDATE tasks SET data=? WHERE id='t'", (json.dumps(data),))
        self.error("PLAN_DIGEST", lambda: self.e.status("t"))

    def test_submodule_rejected(self):
        subprocess.run(["git", "-C", str(self.root), "update-index", "--add", "--cacheinfo", "160000," + "1" * 40 + ",module"], check=True)
        self.error("SUBMODULE", lambda: self.create())

    def test_orphan_recovery(self):
        r = self.ready()
        with sqlite3.connect(str(self.e.db)) as db:
            data = json.loads(db.execute("SELECT data FROM tasks WHERE id='t'").fetchone()[0])
            data.update(state="running", operation={"token": "orphan", "pid": 2147483647})
            db.execute("UPDATE tasks SET data=? WHERE id='t'", (json.dumps(data),))
        r = self.e.recover("t", r["version"], "recover")
        self.assertEqual(r["state"], "failed")
        self.assertEqual(r["failure"], "orphaned_operation")
        self.assertEqual(r, self.e.recover("t", r["version"] - 1, "recover"))

    def test_large_output_is_discarded(self):
        r = self.ready(self.plan("import os; os.write(1, b'x' * 10000000); os.write(2, b'y' * 10000000)"))
        r = self.e.run("t", r["version"], "run")
        self.assertEqual(r["state"], "passed")
        self.assertLess(len(json.dumps(r)), 4000)

    def test_running_request_replay_and_events(self):
        r = self.ready(self.plan("import time; time.sleep(.4)"))
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            future = pool.submit(self.e.run, "t", r["version"], "run")
            for _ in range(100):
                current = self.e.status("t")
                if current["state"] == "running":
                    break
                time.sleep(.01)
            replay = self.e.run("t", r["version"], "run")
            self.assertEqual(replay["state"], "running")
            self.error("IDEMPOTENCY_CONFLICT", lambda: self.e.run("t", 999, "run"))
            result = future.result()
        self.assertEqual(result, self.e.run("t", r["version"], "run"))
        with sqlite3.connect(str(self.e.db)) as db:
            count = db.execute("SELECT count(*) FROM events WHERE action='run_started'").fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
