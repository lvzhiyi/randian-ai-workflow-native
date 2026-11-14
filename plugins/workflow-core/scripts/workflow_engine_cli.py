#!/usr/bin/env python3
"""本地工作流引擎入口；失败统一输出 JSON，不提供手工标记通过的命令。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


class ArgumentError(Exception):
    """参数错误也走统一的机器可读输出。"""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentError(message)


def default_db(root):
    """按绝对项目路径隔离数据库，禁止把运行状态混入源文件指纹。"""
    home = Path(os.environ.get("WORKFLOW_ENGINE_HOME") or
                Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "workflow-engine")
    identity = hashlib.sha256(str(root.resolve()).encode()).hexdigest()
    return home / identity / "state.sqlite"


def parser():
    result = Parser(description=__doc__)
    result.add_argument("--root", default=".")
    result.add_argument("--db")
    commands = result.add_subparsers(dest="action", required=True, parser_class=Parser)
    for action in ("create", "status", "start", "run", "complete", "cancel", "recover", "confirm-plan"):
        command = commands.add_parser(action)
        command.add_argument("--task", required=True)
        if action != "status":
            command.add_argument("--request", required=True)
        if action not in ("status", "create"):
            command.add_argument("--version", type=int, required=True)
        if action == "create":
            command.add_argument("--tier", choices=("轻量", "标准", "完整"), required=True)
            command.add_argument("--acceptance", action="append", required=True)
            command.add_argument("--plan", required=True)
        if action == "confirm-plan":
            command.add_argument("--digest", required=True)
    return result


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        from workflow_engine.engine import Engine
        root = Path(args.root).resolve()
        engine = Engine(root, Path(args.db).resolve() if args.db else default_db(root))
        if args.action == "create":
            with open(args.plan, encoding="utf-8") as handle:
                plan = json.load(handle)
            value = engine.create(args.task, {"轻量": "light", "标准": "standard", "完整": "full"}[args.tier], args.acceptance, plan, args.request)
        elif args.action == "status":
            value = engine.status(args.task)
        else:
            operation = getattr(engine, args.action.replace("-", "_"))
            parameters = [args.task, args.version, args.request]
            if args.action == "confirm-plan":
                # 本地终端确认仅证明操作者输入，不能抵御同用户权限的代理伪装。
                if not sys.stdin.isatty():
                    raise ArgumentError("计划确认须在独立交互终端执行")
                print("确认已人工审阅此检查计划？请输入计划摘要：", file=sys.stderr)
                answer = input()
                if answer.strip() != args.digest:
                    raise ArgumentError("计划摘要未确认")
                parameters.append(args.digest)
            value = operation(*parameters)
        passed = args.action != "run" or value.get("state") == "passed"
        print(json.dumps({"ok": passed, "task": value}, ensure_ascii=False))
        return 0 if passed else 1
    except Exception as error:
        code = getattr(error, "code", "BLOCKED")
        if isinstance(error, ArgumentError):
            code = "ARGUMENT"
        # 未知异常不输出路径、命令或异常正文，避免泄露敏感数据。
        message = str(error) if isinstance(error, ArgumentError) or hasattr(error, "code") else "引擎不可用或输入无效"
        print(json.dumps({"ok": False, "code": code, "message": message}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
