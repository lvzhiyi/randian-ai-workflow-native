"""纯业务规则不接触文件系统，拒绝操作必须保留原快照。"""
import copy
import importlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((Path(__file__).resolve().parents[1] / "src/task_domain.py").is_file(), "领域模块尚未实现")
        self.domain = importlib.import_module("task_domain")
        self.data = {"version": 1, "next_id": 1, "tasks": []}

    def test_title_boundaries_unicode_and_duplicate_ids(self):
        for title in ("一", "😀" * 80, "  内 部  空白  ", "一"):
            task = self.domain.add(self.data, title)
            self.assertEqual(task["title"], title.strip())
            self.assertEqual(task["status"], "pending")
        self.assertEqual([task["id"] for task in self.data["tasks"]], [1, 2, 3, 4])
        self.assertEqual(self.data["next_id"], 5)

    def test_invalid_title_preserves_snapshot(self):
        for title in ("", " \t\n", "字" * 81, None, True):
            before = copy.deepcopy(self.data)
            with self.assertRaises(self.domain.DomainError):
                self.domain.add(self.data, title)
            self.assertEqual(self.data, before)

    def test_sorted_filter_and_return_values_are_detached(self):
        self.data = {"version": 1, "next_id": 4, "tasks": [
            {"id": 3, "title": "三", "status": "completed"},
            {"id": 1, "title": "一", "status": "pending"}]}
        self.assertEqual([t["id"] for t in self.domain.list_tasks(self.data)], [1, 3])
        self.assertEqual([t["id"] for t in self.domain.list_tasks(self.data, "pending")], [1])
        self.assertEqual([t["id"] for t in self.domain.list_tasks(self.data, "completed")], [3])
        result = self.domain.list_tasks(self.data)
        result[0]["title"] = "外部更改"
        self.assertEqual(self.data["tasks"][1]["title"], "一")
        before = copy.deepcopy(self.data)
        with self.assertRaises(self.domain.DomainError):
            self.domain.list_tasks(self.data, "invalid")
        self.assertEqual(self.data, before)
        self.assertEqual(self.domain.list_tasks({"tasks": []}), [])

    def test_transitions_are_idempotent(self):
        result = self.domain.add(self.data, "待办")
        result["title"] = "外部更改"
        for state in ("completed", "completed", "pending", "pending"):
            task = self.domain.set_status(self.data, 1, state)
            self.assertEqual(task["status"], state)
            task["title"] = "外部更改"
            self.assertEqual(self.data["tasks"][0]["title"], "待办")
        self.assertEqual(self.data["next_id"], 2)
        self.assertEqual(len(self.data["tasks"]), 1)

    def test_invalid_id_and_status_preserve_snapshot(self):
        self.domain.add(self.data, "待办")
        for identifier in (True, False, 0, -1, 1.0, "1", None, 2):
            before = copy.deepcopy(self.data)
            with self.assertRaises(self.domain.DomainError):
                self.domain.set_status(self.data, identifier, "completed")
            self.assertEqual(self.data, before)
        with self.assertRaises(self.domain.DomainError):
            self.domain.set_status(self.data, 1, "unknown")
