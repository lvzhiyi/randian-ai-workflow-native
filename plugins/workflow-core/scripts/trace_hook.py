#!/usr/bin/env python3
"""执行轨迹采集钩子：把工具事件脱敏后追加到本机日志（仅用 Python 标准库）。

默认关闭：没有开关文件时不读输入、不写数据。任何异常都静默放行，钩子不能影响会话。
事件写在对应客户端的 workflow-trace/events/<session_id>.jsonl，可用 WORKFLOW_TRACE_DIR 覆盖目录。
"""
import json
import os
from pathlib import Path
import re
import sys
import time

SECRET = re.compile(r'(?i)(bearer\s+|(?:token|password|passwd|secret|api[_-]?key)["\']?\s*[=:]\s*["\']?)'
                    r'[^\s"\'&]+|\bsk-[A-Za-z0-9_-]{12,}')
SESSION_ID = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
PATCH_PATH = re.compile(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$', re.M)
FORWARD = ('session_id', 'cwd', 'agent_id', 'agent_type', 'tool_name', 'tool_use_id', 'is_interrupt',
           'duration_ms', 'expansion_type', 'command_name', 'command_source')


def redact(text):
    """遮盖文本中疑似令牌、密码的值。"""
    return SECRET.sub(lambda m: (m.group(1) or '') + '***', text)


def clip(text, limit=3000):
    """脱敏并截断过长文本。"""
    text = redact(text or '')
    return text if len(text) <= limit else text[:limit] + f'\n…（已截断，共 {len(text)} 字符）'


def is_codex():
    """由入口显式指定宿主，避免嵌套会话继承环境后走错分支。"""
    return os.environ.get('WORKFLOW_HOST') == 'codex'


def workflow_home():
    """按显式宿主选择本机数据目录，Cursor 看板复用同一轨迹来源。"""
    if os.environ.get("WORKFLOW_HOST") == "cursor":
        return Path.home() / ".cursor"
    if is_codex():
        return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser()
    return Path.home() / '.claude'


def trace_dir():
    """返回轨迹数据目录。"""
    return os.environ.get('WORKFLOW_TRACE_DIR') or str(workflow_home() / 'workflow-trace')


def response_text(response):
    """把 tool_response 转成文本；Bash 取 stdout 和 stderr。"""
    if isinstance(response, str):
        return response
    if isinstance(response, dict) and ('stdout' in response or 'stderr' in response):
        return '\n'.join(part for part in (response.get('stdout'), response.get('stderr')) if part)
    return json.dumps(response, ensure_ascii=False)


def shrink_input(data):
    """脱敏并截断工具输入，保持顶层字典结构。"""
    if not isinstance(data, dict):
        return {}
    return {key: clip(value, 2000) if isinstance(value, str) else clip(json.dumps(value, ensure_ascii=False), 500)
            for key, value in data.items()}


def session_identity(hook):
    """只读解析唯一会话归属；不计算源码哈希，不创建引擎或状态库。"""
    import sqlite3
    try:
        cwd, session = hook.get('cwd'), hook.get('session_id')
        if not isinstance(cwd, str) or not session:
            return {}
        directory = Path(cwd).resolve()
        root = next((p for p in (directory, *directory.parents)
                     if (p / 'ai-workflow.yaml').is_file()), None)
        if root is None:
            return {}
        from workflow_engine_cli import default_db
        database = default_db(root)
        if not database.is_file() or database.is_symlink():
            return {}
        matches, total = [], 0
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=0.2) as db:
            # 同时限制行数和总载荷；无法完整确定唯一归属时宁可不关联。
            rows = db.execute('SELECT length(CAST(data AS BLOB)), CASE WHEN length(CAST(data AS BLOB)) <= 1048576 THEN data ELSE NULL END FROM tasks LIMIT 1001')
            for index, (size, text) in enumerate(rows):
                total += size
                if index >= 1000 or text is None or total > 2 * 1024 * 1024:
                    return {}
                task = json.loads(text)
                active = next((r for r in task.get('rounds', []) if r.get('id') == task.get('current_round')), {})
                if (task.get('root') == str(root) and task.get('protocol_version') == 2
                        and active.get('session_id') == session and active.get('executor')
                        and active.get('state') not in ('cancelled', 'review_passed')):
                    matches.append({'task_id': task['id'], 'round_id': active['id'], 'executor': active['executor']})
        return matches[0] if len(matches) == 1 else {}
    except Exception:
        # 采集故障只能保留未归属，不改变任务状态或影响编码会话。
        return {}


def build_event(hook, stamp):
    """把钩子输入转成日志事件。"""
    event = {'ts': stamp, 'event': hook.get('hook_event_name')}
    event.update(session_identity(hook))
    # 只继承显式绑定，不从提示词或文件名猜测任务，避免跨任务归属污染。
    for key, variable in (('task_id', 'WORKFLOW_TASK_ID'),
                          ('round_id', 'WORKFLOW_ROUND_ID'),
                          ('executor', 'WORKFLOW_EXECUTOR')):
        value = os.environ.get(variable)
        if value:
            event[key] = clip(value, 160)
    if os.environ.get('WORKFLOW_HOST') in {'codex', 'cursor'}:
        event['host'] = os.environ['WORKFLOW_HOST']
    event.update({key: hook[key] for key in FORWARD if key in hook})
    if 'tool_input' in hook:
        data = hook['tool_input']
        event['input'] = shrink_input(data)
        if hook.get('tool_name') == 'apply_patch' and isinstance(data, dict):
            event['input']['patch_paths'] = [clip(path) for path in PATCH_PATH.findall(data.get('command', ''))]
    if 'tool_response' in hook:
        event['output'] = clip(response_text(hook['tool_response']))
    if 'error' in hook:
        event['error'] = clip(str(hook['error']))
    if 'prompt' in hook:
        event['prompt'] = clip(str(hook['prompt']), 400)
    return event


def append_event(root, event):
    """以追加方式写一行事件；目录和文件只允许当前用户访问。"""
    folder = os.path.join(root, 'events')
    os.makedirs(folder, mode=0o700, exist_ok=True)
    path = os.path.join(folder, event['session_id'] + '.jsonl')
    handle = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(handle, (json.dumps(event, ensure_ascii=False) + '\n').encode('utf-8'))
    finally:
        os.close(handle)


def main():
    """钩子入口，始终返回 0。"""
    stamp = time.time()
    root = trace_dir()
    try:
        hook = json.load(sys.stdin)
        # 已接入项目统一采集供看板观测，不再要求先启动独立 Trace 功能。
        # 非接入项目仍遵循旧的显式开关，避免扩大本机采集范围。
        cwd = hook.get('cwd')
        configured = False
        if isinstance(cwd, str):
            directory = Path(cwd).resolve()
            configured = any((parent / 'ai-workflow.yaml').is_file()
                             for parent in (directory, *directory.parents))
        if not configured and not os.path.exists(os.path.join(root, 'enabled')):
            return 0
        if SESSION_ID.match(str(hook.get('session_id', ''))):
            append_event(root, build_event(hook, stamp))
    except Exception:  # 钩子故障不能影响会话
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
