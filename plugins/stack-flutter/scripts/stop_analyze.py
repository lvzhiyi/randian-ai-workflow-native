#!/usr/bin/env python3
"""stack-flutter 的 Stop 钩子：AI 结束回合前，对本次改动的手写 Dart 文件做静态分析。

- 只在 Flutter/Dart 项目、且相对 HEAD 有改动的手写 Dart 文件时运行；否则直接放行。
- 发现 error 级问题时，按当前客户端的 Stop 协议请求继续修复。
- stop_hook_active 为 true（已经因 Stop 钩子继续过一次）时不再要求继续，只提示用户，避免死循环。
- 分析器不可用、超时或输出无法解析时一律放行：钩子出故障不能卡住会话。
输入：stdin 上的 Stop 事件 JSON；输出：stdout 上的钩子 JSON（无问题时不输出）。
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from flutter_check import changed_dart_files, clean_env  # noqa: E402

# 单次分析的最长等待时间（秒）；超过则放行，避免拖慢每个回合。
ANALYZE_TIMEOUT = 90
# 反馈给 AI 的问题条数上限，避免大量错误塞满上下文。
MAX_REPORTED = 20


def is_codex():
    return os.environ.get('WORKFLOW_HOST') == 'codex'


def project_root(cwd):
    """找到包含 pubspec.yaml 的项目根。

    参数 [cwd]：钩子输入里的当前工作目录。
    返回：git 仓库根（或 cwd 本身）下存在 pubspec.yaml 时返回该目录 Path，否则返回 None。
    """
    start = Path(cwd or os.environ.get('CLAUDE_PROJECT_DIR') or '.').resolve()
    try:
        top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=start, env=clean_env(),
                             capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        top = ''
    for candidate in (Path(top) if top else None, start):
        if candidate and (candidate / 'pubspec.yaml').is_file():
            return candidate
    return None


def analyze_errors(root, files):
    """对指定文件运行 dart analyze，返回 error 级问题。

    参数 [root]：项目根；[files]：相对路径列表。
    返回：问题描述列表，形如「lib/a.dart:12:3 错误信息 (诊断码)」；
    分析器不可用、超时或启动失败时返回 None，表示无法判断（调用方放行）。
    machine 格式每行为：SEVERITY|TYPE|CODE|FILE|LINE|COLUMN|LENGTH|MESSAGE。
    """
    if not shutil.which('dart'):
        return None
    try:
        result = subprocess.run(['dart', 'analyze', '--format=machine', *files], cwd=root,
                                env=clean_env(), capture_output=True, text=True,
                                timeout=ANALYZE_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    errors = []
    for line in (result.stdout + '\n' + result.stderr).splitlines():
        parts = line.split('|', 7)
        if len(parts) == 8 and parts[0] == 'ERROR':
            path = Path(parts[3])
            shown = path.relative_to(root) if path.is_absolute() and root in path.parents else path
            errors.append(f'{shown}:{parts[4]}:{parts[5]} {parts[7]} ({parts[2].lower()})')
    return errors


def record_metric(event, root, outcome, errors):
    """写一条拦截度量，只含计数；出错时静默跳过，不影响钩子。

    参数 [event]：Stop 事件；[root]：项目根；[outcome]：blocked 已拦截、fixed 重试后无错误、
    unresolved 重试后仍有错误；[errors]：错误数。
    其他 Stop 钩子也可能让回合继续，统计时 fixed 要与同会话的 blocked 配对。
    """
    try:
        home = (Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser()
                if is_codex() else Path.home() / '.claude')
        folder = Path(os.environ.get('WORKFLOW_METRICS_DIR') or home / 'workflow-metrics')
        if (folder / 'disabled').exists():
            return
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        line = json.dumps({'v': 1, 'ts': time.time(), 'type': 'stop_block', 'session_id': event.get('session_id', ''),
                           'project': root.name, 'stack': 'flutter', 'outcome': outcome, 'errors': errors},
                          ensure_ascii=False)
        handle = os.open(folder / 'records.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(handle, (line + '\n').encode('utf-8'))
        finally:
            os.close(handle)
    except Exception:  # 度量故障不能影响钩子
        pass


def main():
    """钩子入口：读取 stdin 的 Stop 事件，按需输出钩子 JSON。

    返回：始终为 0；是否让 AI 继续由输出的 JSON 决定。
    """
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    root = project_root(event.get('cwd'))
    if root is None:
        return 0
    files = changed_dart_files(root)
    if not files:
        return 0
    errors = analyze_errors(root, files)
    if errors is None:
        return 0
    if not errors:
        if event.get('stop_hook_active'):
            record_metric(event, root, 'fixed', 0)
        return 0

    shown = errors[:MAX_REPORTED]
    more = f'\n……另有 {len(errors) - MAX_REPORTED} 条未列出' if len(errors) > MAX_REPORTED else ''
    detail = '\n'.join(f'- {item}' for item in shown) + more
    record_metric(event, root, 'unresolved' if event.get('stop_hook_active') else 'blocked', len(errors))
    if event.get('stop_hook_active'):
        # 已经因本钩子继续过一次仍有错误：放行结束，只提示用户，避免无限循环。
        print(json.dumps({'systemMessage': f'stack-flutter：本次改动的 Dart 文件仍有 {len(errors)} 个分析错误，'
                                            '交付结果不应写成“实施完成”。'}, ensure_ascii=False))
        return 0
    context = (f'stack-flutter Stop 检查：本次改动的 {len(files)} 个 Dart 文件中有 {len(errors)} 个 '
               f'dart analyze 错误，结束前请先修复，或在交付“验证”项说明无法修复的原因：\n{detail}')
    output = ({'decision': 'block', 'reason': context} if is_codex()
              else {'hookSpecificOutput': {'hookEventName': 'Stop', 'additionalContext': context}})
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
