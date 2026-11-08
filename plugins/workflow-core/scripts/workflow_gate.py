#!/usr/bin/env python3
"""工作流触发兜底钩子（仅用 Python 标准库）。

技能靠模型自行判断是否调用，实际经常不触发。本钩子在接入了工作流的项目（根目录有 ai-workflow.yaml）里：
- 会话开始时告诉模型这个项目使用工作流；
- 记录代码改动和 deliver 技能；回合结束时如果最后一次改动之后没有 deliver，提醒一次。

只提醒、不阻断：stop_hook_active 为 true 时直接放行，任何异常都放行。
状态写在 ~/.claude/workflow-gate/，可用 WORKFLOW_GATE_DIR 覆盖；目录下有 disabled 文件时关闭。
"""
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))
from workflow_trace import BASH_WRITE, CODE_PATH, is_code  # noqa: E402

SESSION_ID = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
EDIT_TOOLS = ('Edit', 'Write', 'MultiEdit', 'NotebookEdit')
RETENTION_DAYS = 7
SESSION_CONTEXT = ('这个项目接入了 ai-dev-workflow。开发任务（需求、功能、Bug、重构）的入口是 workflow-core:workflow 技能，'
                   '开工时用它分档；改了代码后，验证用 workflow-core:verify，交付用 workflow-core:deliver。')
STOP_CONTEXT = ('本会话最后一次代码改动之后还没有调用 workflow-core:deliver。如果任务已完成或阶段性停下，'
                '请先用 Skill 工具加载 workflow-core:deliver，按它完成验证证据、评审和统一交付。'
                '如果正在等用户回答或任务还没做完，直接结束本回合即可。')


def gate_dir():
    """返回状态目录。"""
    return Path(os.environ.get('WORKFLOW_GATE_DIR') or Path.home() / '.claude' / 'workflow-gate')


def project_uses_workflow(cwd):
    """从 cwd 向上找到 git 根为止，判断项目是否有 ai-workflow.yaml。"""
    path = Path(cwd or '.').resolve()
    for folder in (path, *path.parents):
        if (folder / 'ai-workflow.yaml').is_file():
            return True
        if (folder / '.git').exists():
            return False
    return False


def is_deliver(name):
    """判断技能名是否 deliver。"""
    return name in ('workflow-core:deliver', 'deliver')


def bash_changes_code(command, cwd):
    """按命令文本判断 Bash 是否写了手写代码文件，路径必须真实存在，避免把 import 路径算进去。"""
    if not BASH_WRITE.search(command):
        return False
    return any(is_code(match) and (Path(cwd or '.') / match).is_file() for match in CODE_PATH.findall(command))


def classify(event):
    """把钩子事件归类为 edit、deliver 或 None。"""
    name = event.get('hook_event_name')
    if name == 'UserPromptExpansion':
        return 'deliver' if is_deliver(event.get('command_name')) else None
    if name != 'PostToolUse':
        return None
    tool, data = event.get('tool_name'), event.get('tool_input') or {}
    if tool == 'Skill':
        return 'deliver' if is_deliver(data.get('skill')) else None
    if tool in EDIT_TOOLS:
        return 'edit' if is_code(str(data.get('file_path') or data.get('notebook_path') or '')) else None
    if tool == 'Bash':
        return 'edit' if bash_changes_code(data.get('command', ''), event.get('cwd')) else None
    return None


def state_path(root, session_id):
    """返回会话状态文件。"""
    return root / f'{session_id}.log'


def append_state(root, session_id, value):
    """追加一行状态；用追加写避免并行工具调用互相覆盖。"""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = os.open(state_path(root, session_id), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(handle, (value + '\n').encode('utf-8'))
    finally:
        os.close(handle)


def needs_deliver(root, session_id):
    """最后一条状态是 edit 时，说明改动之后还没有 deliver。"""
    path = state_path(root, session_id)
    if not path.is_file():
        return False
    lines = path.read_text(encoding='utf-8').split()
    return bool(lines) and lines[-1] == 'edit'


def prune(root):
    """删除过期的会话状态。"""
    limit = time.time() - RETENTION_DAYS * 86400
    for path in root.glob('*.log'):
        if path.stat().st_mtime < limit:
            path.unlink()


def emit(event_name, context):
    """输出钩子上下文。"""
    print(json.dumps({'hookSpecificOutput': {'hookEventName': event_name, 'additionalContext': context}},
                     ensure_ascii=False))


def handle(event, root):
    """处理一个钩子事件。"""
    session_id = str(event.get('session_id', ''))
    if (root / 'disabled').exists() or not SESSION_ID.match(session_id) or not project_uses_workflow(event.get('cwd')):
        return
    name = event.get('hook_event_name')
    if name == 'SessionStart':
        if root.is_dir():
            prune(root)
        emit('SessionStart', SESSION_CONTEXT)
    elif name == 'Stop':
        if not event.get('stop_hook_active') and needs_deliver(root, session_id):
            emit('Stop', STOP_CONTEXT)
    else:
        kind = classify(event)
        if kind:
            append_state(root, session_id, kind)


def main():
    """钩子入口，始终返回 0。"""
    try:
        handle(json.load(sys.stdin), gate_dir())
    except Exception:  # 钩子故障不能影响会话
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
