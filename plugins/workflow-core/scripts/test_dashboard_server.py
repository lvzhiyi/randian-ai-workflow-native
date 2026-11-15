"""本机只读看板 HTTP 边界测试，不代替真实浏览器验证。"""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class ServerTests(unittest.TestCase):
    def setUp(self):
        import dashboard_server
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "ai-workflow.yaml").write_text("version: 1\n")
        self.server = dashboard_server.bind_server(self.root, None, 0)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def test_dashboard_and_foreign_host(self):
        with urlopen(self.url + "/api/dashboard") as response:
            self.assertIn("mode", json.load(response))
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.url + "/api/dashboard", headers={"Host": "evil.test"}))
        self.assertEqual(caught.exception.code, 403)

    def test_document_escape_and_post_rejected(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.url + "/api/document?path=../private.md")
        self.assertEqual(caught.exception.code, 400)
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.url + "/api/dashboard", data=b"{}", method="POST"))
        self.assertEqual(caught.exception.code, 405)

    def test_task_first_page_and_read_only_execution_observation(self):
        with urlopen(self.url + "/") as response:
            page = response.read().decode("utf-8")
        self.assertNotIn("流程 · 8 步", page)
        self.assertNotIn("阻塞与待确认</h2>", page)
        for label in ("执行观测", "任务筛选", "双轴评审", "活动未知", "待人工验收"):
            self.assertIn(label, page)
        self.assertNotIn("旧配置 / 数据源未启用", page)
        self.assertNotIn("mode.configured_enabled", page)
        self.assertNotIn("innerHTML", page)
        self.assertIn("if (polling) return", page)
        self.assertIn("setTimeout(refresh,2000)", page)


if __name__ == "__main__":
    unittest.main()
