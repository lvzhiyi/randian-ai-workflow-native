"""Cursor 扁平事件适配：仅归一化协议，流程授权仍由共享门禁和引擎决定。"""
import json
import os
from pathlib import Path
import re
import sys

import host_gate

EVENTS = {
    "sessionStart": "SessionStart",
    "preToolUse": "PreToolUse",
    "postToolUse": "PostToolUse",
    "beforeSubmitPrompt": "UserPromptSubmit",
    "subagentStart": "SubagentStart",
}
MAX_INPUT = 2 * 1024 * 1024


def choose_root(payload):
    """不用插件 cwd 猜项目；多根必须由显式项目目录或 Shell 执行目录消歧。"""
    roots = payload.get("workspace_roots", [])
    if not isinstance(roots, list) or len(roots) > 64:
        raise ValueError("workspace_roots 无效")
    candidates = []
    for value in roots:
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError("工作区根必须是绝对路径")
        candidate = Path(value).resolve()
        if candidate not in candidates:
            candidates.append(candidate)
    explicit = os.environ.get("CURSOR_PROJECT_DIR")
    working = payload.get("tool_input", {}).get("working_directory") if payload.get("tool_name") == "Shell" else None
    directories = []
    for value in (explicit, working):
        if value is None:
            continue
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError("执行目录必须是绝对路径")
        directory = Path(value).resolve()
        matches = [p for p in candidates if directory == p or p in directory.parents]
        if candidates and not matches:
            raise ValueError("执行目录不在工作区根内")
        directories.append(directory)
    if len(directories) == 2 and directories[0] != directories[1] and directories[0] not in directories[1].parents:
        raise ValueError("显式默认目录与工具执行目录冲突")
    # Shell 实际目录优先；不能折叠为工作区根而借用父项目授权。
    selected = directories[-1] if directories else None
    if selected is None:
        if len(candidates) != 1:
            raise ValueError("多根或缺少根目录，必须提供 CURSOR_PROJECT_DIR 或 Shell working_directory")
        selected = candidates[0]
    return selected


def normalize(payload):
    """保留工具输入字段；保留 Cursor 工具输出的字符串格式。"""
    if not isinstance(payload, dict):
        raise ValueError("事件必须是对象")
    name = payload.get("hook_event_name")
    if name not in EVENTS:
        raise ValueError("未知事件")
    session = payload.get("conversation_id")
    if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", session) or session in {".", ".."}:
        raise ValueError("conversation_id 无效")
    data = payload.get("tool_input", {})
    if not isinstance(data, dict):
        raise ValueError("tool_input 必须是对象")
    if name in {"preToolUse", "postToolUse"} and not isinstance(payload.get("tool_name"), str):
        raise ValueError("缺少 tool_name")
    root = choose_root(payload)
    event = {"cwd": str(root), "session_id": session, "hook_event_name": EVENTS[name], "tool_name": payload.get("tool_name", ""), "tool_input": data}
    if name == "beforeSubmitPrompt":
        event["prompt"] = payload.get("prompt")
    for key in ("tool_use_id", "generation_id"):
        if key in payload:
            if not isinstance(payload[key], str) or len(payload[key]) > 160:
                raise ValueError(key + " 无效")
            event[key] = payload[key]
    if "tool_output" in payload:
        if not isinstance(payload["tool_output"], str):
            raise ValueError("tool_output 必须是 JSON 序列化字符串")
        event["tool_response"] = payload["tool_output"]
    return event


def handle(payload):
    os.environ["WORKFLOW_HOST"] = "cursor"
    event = normalize(payload)
    name, tool = event["hook_event_name"], event["tool_name"]
    # 初始化前不拦工具；解析故障仍由入口拒绝，不能降级为旁路。
    if host_gate.project_root(event["cwd"]) is None:
        return {"permission": "allow"} if name in {"PreToolUse", "SubagentStart"} else {}
    if name == "UserPromptSubmit":
        # 回复照常进入会话，由 Agent 读 status 并在版本失效时重新展示选项。
        host_gate.context(event)
        return {"continue": True}
    if name == "PreToolUse":
        if tool in {"Write", "Delete", "Edit"}:
            values = [event["tool_input"][key] for key in ("file_path", "path", "target_file") if key in event["tool_input"]]
            if not values or any(not isinstance(value, str) or not value.strip() for value in values):
                return deny("ENGINE_TARGET_REQUIRED：写入目标 schema 不受支持")
        if tool == "AskQuestion":
            error = None
        else:
            error = host_gate.pre_tool(event)
        if error:
            return deny(error)
        result = {"permission": "allow"}
        if tool in host_gate.SHELL_TOOLS:
            updated = host_gate.safe_shell_input(event)
            if updated:
                result["updated_input"] = updated
        return result
    if name == "SessionStart":
        workflow_context = host_gate.context(event) or host_gate.CONFIRM_HELP
        context = (
            f"Cursor conversation_id: {event['session_id']}\n"
            f"文档规划登记命令的 --session 使用上述会话 ID。\n{workflow_context}"
        )
        return {"env": {"WORKFLOW_HOST": "cursor"}, "additional_context": bounded(context)}
    if name == "PostToolUse":
        message = host_gate.context(event)
        return {"additional_context": bounded(message)} if message else {}
    if name == "SubagentStart":
        return {"permission": "allow", "user_message": "子 Agent 不继承独立写入授权；需以其真实 conversation_id 绑定当前轮次并 CLI read-baseline。父 Task 放行不代表子工具路径全部覆盖。"}


def bounded(message):
    return str(message)[:4000]


def deny(message):
    return {"permission": "deny", "user_message": bounded(message), "agent_message": bounded(message)}


def main():
    payload = None
    try:
        raw = sys.stdin.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError("事件超过大小上限")
        payload = json.loads(raw)
        result = handle(payload)
    except Exception as exc:
        # 无法确认事件类型时采用 deny；已知非门禁事件不冒充权限协议。
        result = deny("ENGINE_CURSOR_FORMAT_ERROR：" + str(exc))
        if isinstance(payload, dict) and payload.get("hook_event_name") == "subagentStart":
            result.pop("agent_message", None)
        elif isinstance(payload, dict) and payload.get("hook_event_name") in EVENTS and payload["hook_event_name"] != "preToolUse":
            result = {}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
