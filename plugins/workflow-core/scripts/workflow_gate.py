#!/usr/bin/env python3
"""双宿主同步流程门禁；受支持前置路径遇到错误必须拒绝写入。"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from host_gate import context, pre_tool, project_root, safe_shell_input


def codex():
    return os.environ.get("WORKFLOW_HOST") == "codex"


def emit_context(name, message):
    if codex() and name != "UserPromptSubmit":
        value = {"systemMessage": message}
    else:
        value = {"hookSpecificOutput": {"hookEventName": name, "additionalContext": message}}
    print(json.dumps(value, ensure_ascii=False))


def deny(reason):
    # 两宿主均支持 deny；Codex 不支持 ask，不输出不存在的权限值。
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                            "permissionDecisionReason": reason}}, ensure_ascii=False))


def handle(event, root=None):
    """旧 disabled 文件与 engine.enabled 均不再成为门禁绕过条件。"""
    if not isinstance(event, dict):
        raise ValueError("事件必须是 JSON 对象")
    if project_root(event.get("cwd"), event.get("session_id")) is None:
        return
    if event.get("hook_event_name") == "PreToolUse":
        reason = pre_tool(event)
        if reason:
            deny(reason)
        else:
            updated = safe_shell_input(event)
            if updated:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "updatedInput": updated}}, ensure_ascii=False))
        return
    if event.get("hook_event_name") in {"SessionStart", "Stop", "PostToolUse", "UserPromptSubmit"}:
        message = context(event)
        if message:
            emit_context(event["hook_event_name"], message)


def main():
    """无法解析事件时用宿主阻断退出码，绝不能吞异常并成功放行。"""
    event = None
    try:
        event = json.load(sys.stdin)
        handle(event)
        return 0
    except Exception as exc:
        reason = "ENGINE_GATE_ERROR：门禁异常，受支持写入路径拒绝：" + str(exc)
        if isinstance(event, dict) and event.get("hook_event_name") == "PreToolUse":
            deny(reason)
            return 0
        print(reason, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
