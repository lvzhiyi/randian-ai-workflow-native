"""覆盖存储完整性及写入失败恢复；全部数据均使用临时目录。"""
import copy
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "src" / "task_store.py"


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.is_file(), "存储模块尚未实现")
        spec = importlib.util.spec_from_file_location("task_store", SOURCE)
        self.store = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.store)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "tasks.json"
        self.data = {"version": 1, "next_id": 2, "tasks": [
            {"id": 1, "title": "待办", "status": "pending"}]}

    def test_missing_read_has_no_side_effect(self):
        path = self.root / "missing" / "tasks.json"
        self.assertEqual(self.store.load(path), {"version": 1, "next_id": 1, "tasks": []})
        self.assertFalse(path.parent.exists())

    def test_roundtrip_and_private_permissions(self):
        self.store.save(self.path, self.data)
        self.assertEqual(self.store.load(self.path), self.data)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_corrupt_file_is_not_overwritten_and_can_recover(self):
        for bad in (b"{secret", b"\xff", b'{"version":1,"version":1,"next_id":1,"tasks":[]}'):
            with self.subTest(bad=bad):
                self.path.write_bytes(bad)
                with self.assertRaises(self.store.StoreError):
                    self.store.load(self.path)
                with self.assertRaises(self.store.StoreError):
                    self.store.save(self.path, self.data)
                self.assertEqual(self.path.read_bytes(), bad)
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        self.assertEqual(self.store.load(self.path), self.data)

    def test_rejects_invalid_schema_on_read_and_save(self):
        invalid = [[], {}, {**self.data, "version": True},
                   {**self.data, "version": 2}, {**self.data, "next_id": True},
                   {**self.data, "next_id": 1}, {**self.data, "extra": 0},
                   {**self.data, "tasks": self.data["tasks"] * 2}]
        for field, values in {"id": [True, 0, -1, 1.5],
                              "title": ["", "  ", " x", "x" * 81, None],
                              "status": ["unknown", None]}.items():
            for value in values:
                data = copy.deepcopy(self.data)
                data["tasks"][0][field] = value
                invalid.append(data)
        for data in invalid:
            with self.subTest(data=data):
                self.path.write_text(json.dumps(data), encoding="utf-8")
                before = self.path.read_bytes()
                with self.assertRaises(self.store.StoreError):
                    self.store.load(self.path)
                with self.assertRaises(self.store.StoreError):
                    self.store.save(self.root / "new.json", data)
                self.assertFalse((self.root / "new.json").exists())
                self.assertEqual(self.path.read_bytes(), before)

    def test_duplicate_titles_are_valid(self):
        self.data["tasks"].append({"id": 2, "title": "待办", "status": "completed"})
        self.data["next_id"] = 3
        self.store.save(self.path, self.data)
        self.assertEqual(self.store.load(self.path), self.data)

    def test_missing_parent_is_not_created(self):
        with self.assertRaises(self.store.StoreError):
            self.store.save(self.root / "missing" / "tasks.json", self.data)
        self.assertFalse((self.root / "missing").exists())

    def test_symlink_and_directory_are_rejected(self):
        target = self.root / "target.json"
        target.write_text(json.dumps(self.data), encoding="utf-8")
        self.path.symlink_to(target)
        for path in (self.path, self.root):
            with self.subTest(path=path):
                with self.assertRaises(self.store.StoreError):
                    self.store.load(path)
                with self.assertRaises(self.store.StoreError):
                    self.store.save(path, self.data)
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(json.loads(target.read_text()), self.data)

    def test_replace_and_fsync_failure_preserve_old_file(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        before = self.path.read_bytes()
        for operation in ("replace", "fsync"):
            with self.subTest(operation=operation):
                with patch.object(self.store.os, operation, side_effect=OSError("private content")):
                    with self.assertRaises(self.store.StoreError) as result:
                        self.store.save(self.path, self.data)
                self.assertNotIn("private content", str(result.exception))
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_deep_json_is_classified_as_storage_error(self):
        self.path.write_text("[" * 2000 + "]" * 2000, encoding="utf-8")
        with self.assertRaises(self.store.StoreError):
            self.store.load(self.path)
        with self.assertRaises(self.store.StoreError):
            self.store.save(self.path, self.data)

    def test_invalid_old_snapshot_cannot_be_overwritten(self):
        for bad in ({}, {**self.data, "tasks": self.data["tasks"] * 2}):
            self.path.write_text(json.dumps(bad), encoding="utf-8")
            before = self.path.read_bytes()
            with self.assertRaises(self.store.StoreError):
                self.store.save(self.path, self.data)
            self.assertEqual(self.path.read_bytes(), before)

    def test_serialization_failure_cleans_temporary_file(self):
        self.store.save(self.path, self.data)
        before = self.path.read_bytes()
        with patch.object(self.store.json, "dump", side_effect=OSError("write failure")):
            with self.assertRaises(self.store.StoreError):
                self.store.save(self.path, self.data)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_counter_cannot_go_backwards(self):
        self.store.save(self.path, self.data)
        with self.assertRaises(self.store.StoreError):
            self.store.save(self.path, {"version": 1, "next_id": 1, "tasks": []})
        self.assertEqual(self.store.load(self.path), self.data)


if __name__ == "__main__":
    unittest.main()
