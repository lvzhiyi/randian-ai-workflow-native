#!/usr/bin/env python3
"""执行轨迹采集钩子：把 Claude Code 事件脱敏后追加到本机日志（仅用 Python 标准库）。

默认关闭：没有开关文件时不读输入、不写数据。任何异常都静默放行，钩子不能影响会话。
事件写在 ~/.claude/workflow-trace/events/<session_id>.jsonl，可用 WORKFLOW_TRACE_DIR 覆盖目录。
"""
import json
import os
import re
import sys
import time

SECRET = re.compile(r'(?i)(bearer\s+|(?:token|password|passwd|secret|api[_-]?key)["\']?\s*[=:]\s*["\']?)'
                    r'[^\s"\'&]+|\bsk-[A-Za-z0-9_-]{12,}')
SESSION_ID = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
FORWARD = ('session_id', 'cwd', 'agent_id', 'agent_type', 'tool_name', 'tool_use_id', 'is_interrupt',
           'duration_ms', 'expansion_type', 'command_name', 'command_source')


def redact(text):
    """遮盖文本中疑似令牌、密码的值。"""
    return SECRET.sub(lambda m: (m.group(1) or '') + '***', text)


def clip(text, limit=3000):
    """脱敏并截断过长文本。"""
    text = redact(text or '')
    return text if len(text) <= limit else text[:limit] + f'\n…（已截断，共 {len(text)} 字符）'


def trace_dir():
    """返回轨迹数据目录。"""
    return os.environ.get('WORKFLOW_TRACE_DIR') or os.path.join(os.path.expanduser('~'), '.claude', 'workflow-trace')


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


def build_event(hook, stamp):
    """把钩子输入转成日志事件。"""
    event = {'ts': stamp, 'event': hook.get('hook_event_name')}
    event.update({key: hook[key] for key in FORWARD if key in hook})
    if 'tool_input' in hook:
        event['input'] = shrink_input(hook['tool_input'])
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
    if not os.path.exists(os.path.join(root, 'enabled')):
        return 0
    try:
        hook = json.load(sys.stdin)
        if SESSION_ID.match(str(hook.get('session_id', ''))):
            append_event(root, build_event(hook, stamp))
    except Exception:  # 钩子故障不能影响会话
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
