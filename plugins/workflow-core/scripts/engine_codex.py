"""Codex 的只读状态适配；宿主提示不是工具执行权限拦截。"""
import json
import os
from pathlib import Path

from workflow_config import load


def project_root(cwd):
    """选择最近配置，遇到 Git 根停止，避免父子项目串用。"""
    path = Path(cwd or ".").resolve()
    for folder in (path, *path.parents):
        if (folder / "ai-workflow.yaml").is_file():
            return folder
        if (folder / ".git").exists():
            break
    return None


def context(event):
    """未启用返回 None；启用后故障必须展示受阻而非回退提醒模式。"""
    root = project_root(event.get("cwd"))
    if root is None:
        return None
    config = load(root)
    if config.get("engine.enabled") is not True:
        return None
    if event.get("hook_event_name") not in ("SessionStart", "Stop", "PostToolUse"):
        return ""
    task_id = os.environ.get("WORKFLOW_TASK_ID")
    if not task_id:
        return "ENGINE_TASK_UNBOUND：严格引擎已启用，未通过 WORKFLOW_TASK_ID 绑定任务；不得声称完成。"
    try:
        from workflow_engine.engine import Engine
        from workflow_engine_cli import default_db
        value = Engine(root, default_db(root)).status(task_id)
        return "ENGINE_STATE：" + json.dumps(value, ensure_ascii=False)
    except Exception:
        return "ENGINE_BLOCKED：无法查询权威任务状态；不得降级为已完成。"
