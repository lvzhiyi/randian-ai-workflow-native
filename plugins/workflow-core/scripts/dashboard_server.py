#!/usr/bin/env python3
"""单项目只读流程看板；服务状态写本机，不修改项目或引擎数据库。"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from dashboard_data import build_dashboard, read_document
from dashboard_page import page_html
from trace_hook import workflow_home

APP = "workflow-dashboard"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, status, value, html=False):
        body = (value if html else json.dumps(value, ensure_ascii=False)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.reply(405, {"error": "read_only"})

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST

    def do_GET(self):
        port = self.server.server_port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return self.reply(403, {"error": "host"})
        parsed = urlparse(self.path)
        if parsed.path == "/api/ping":
            return self.reply(200, {"app": APP, "pid": os.getpid(), "root": str(self.root), "task": self.task})
        if parsed.path == "/":
            return self.reply(200, page_html(), html=True)
        try:
            if parsed.path == "/api/dashboard":
                return self.reply(200, build_dashboard(self.root, self.task))
            if parsed.path == "/api/document":
                path = parse_qs(parsed.query).get("path", [""])[0]
                # 只允许当前看板已登记的文档，不能把接口当成任意文件读取器。
                allowed = {item["path"] for item in build_dashboard(self.root, self.task)["documents"]}
                if path not in allowed:
                    return self.reply(400, {"error": "document_not_registered"})
                return self.reply(200, {"path": path, "content": read_document(self.root, path)})
        except (OSError, ValueError):
            return self.reply(400, {"error": "document_unavailable"})
        except Exception:
            return self.reply(503, {"error": "dashboard_unavailable"})
        self.reply(404, {"error": "path"})


def bind_server(root, task=None, port=None):
    handler = type("BoundDashboard", (Handler,), {"root": Path(root).resolve(), "task": task})
    for candidate in ([port] if port is not None else range(8780, 8790)):
        try:
            return ThreadingHTTPServer(("127.0.0.1", candidate), handler)
        except OSError:
            continue
    raise OSError("没有可用看板端口")


def state_path(root):
    key = hashlib.sha256(str(root).encode()).hexdigest()
    return workflow_home() / "workflow-dashboard" / (key + ".json")


def ping(path):
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        with urlopen(f'http://127.0.0.1:{state["port"]}/api/ping', timeout=1) as response:
            active = json.load(response)
        if active == {"app": APP, "pid": state["pid"], "root": state["root"], "task": state.get("task")}:
            return state
    except (OSError, ValueError, KeyError):
        pass
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("on", "off", "status", "serve"), nargs="?", default="status")
    parser.add_argument("--root", default=".")
    parser.add_argument("--task", default=os.environ.get("WORKFLOW_TASK_ID"))
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    path = state_path(root)
    try:
        if not root.is_dir():
            raise OSError("项目根目录不存在")
        if args.action == "serve":
            server = bind_server(root, args.task)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(str(path), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"pid": os.getpid(), "port": server.server_port, "root": str(root), "task": args.task}, handle)
            server.serve_forever()
            return 0
        active = ping(path)
        if args.action == "off":
            if active:
                os.kill(active["pid"], signal.SIGTERM)
            path.unlink(missing_ok=True)
            print("status=OFF")
            return 0
        if args.action == "on" and active and active.get("task") != args.task:
            print("status=BLOCKED reason=同项目已启动其他任务，请先off再on")
            return 2
        if args.action == "on" and not active:
            command = [sys.executable, str(Path(__file__).resolve()), "serve", "--root", str(root)]
            if args.task:
                command += ["--task", args.task]
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            for _ in range(30):
                time.sleep(0.1)
                active = ping(path)
                if active:
                    break
            if not active:
                raise OSError("看板启动失败")
        print(f'status=ON url=http://127.0.0.1:{active["port"]}/' if active else "status=OFF")
        return 0
    except OSError as error:
        print(f"status=BLOCKED reason={error}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
