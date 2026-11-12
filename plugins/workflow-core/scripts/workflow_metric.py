#!/usr/bin/env python3
"""流程度量记录：把评审和交付的结论写成一行结构化数据（仅用 Python 标准库）。

只接受固定字段：枚举、计数和不超过 120 字符的单行文本（任务名、规则名），不存代码、命令或输出。
记录写在对应客户端的 workflow-metrics/records.jsonl，可用 WORKFLOW_METRICS_DIR 覆盖目录。

用法：
  workflow_metric.py record review|deliver [--session ID] < 记录.json
  workflow_metric.py on | off | status
退出码：0 已记录或已关闭，1 记录不符合格式，2 无法写入。度量失败不影响评审和交付。
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))
from trace_hook import is_codex, redact, workflow_home  # noqa: E402

TIERS = ('轻量', '标准', '完整')
AXES = ('spec', 'standards')
SEVERITIES = ('阻塞', '应修', '建议')
STATUSES = ('实施完成，待验证', '可评审', '自测完成', '受阻')
UNVERIFIED = ('本次回归', '环境或工具问题', '既有失败', '原因待定位', '需求或接口不明确', '超出范围', '尝试无进展', '按约定未执行')
REVIEW_STATES = ('已评审', '已跳过', '不要求')
OUTCOMES = ('已修复', '接受例外', '未解决')
MAX_TEXT = 120
MAX_ITEMS = 100


class RecordError(Exception):
    """记录不符合格式。"""


def metrics_dir():
    """返回度量数据目录。"""
    return Path(os.environ.get('WORKFLOW_METRICS_DIR') or workflow_home() / 'workflow-metrics')


def text(value, name):
    """校验单行短文本并脱敏。"""
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT or '\n' in value:
        raise RecordError(f'{name} 必须是不超过 {MAX_TEXT} 字符的单行文本')
    return redact(value.strip())


def choice(value, options, name):
    """校验枚举值。"""
    if value not in options:
        raise RecordError(f'{name} 只能是 {" / ".join(options)}')
    return value


def items(value, name):
    """校验列表长度。"""
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise RecordError(f'{name} 必须是不超过 {MAX_ITEMS} 项的列表')
    return value


def only_keys(data, allowed, name):
    """拒绝未约定的字段，防止正文混入记录。"""
    if not isinstance(data, dict):
        raise RecordError(f'{name} 必须是对象')
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise RecordError(f'{name} 有未知字段：{"、".join(unknown)}')


def clean_review(data):
    """校验评审记录。sources 是当次检查过的规则来源，用作规则命中率的分母。"""
    only_keys(data, ('task', 'tier', 'files', 'sources', 'skipped_axes', 'findings'), '记录')
    if not isinstance(data.get('files'), int) or data['files'] < 0:
        raise RecordError('files 必须是非负整数')
    findings = []
    for item in items(data.get('findings'), 'findings'):
        only_keys(item, ('axis', 'severity', 'rule'), 'findings 项')
        findings.append({'axis': choice(item.get('axis'), AXES, 'axis'),
                         'severity': choice(item.get('severity'), SEVERITIES, 'severity'),
                         'rule': text(item.get('rule'), 'rule')})
    return {'task': text(data.get('task'), 'task'), 'tier': choice(data.get('tier'), TIERS, 'tier'), 'files': data['files'],
            'sources': [text(s, 'sources 项') for s in items(data.get('sources'), 'sources')],
            'skipped_axes': [choice(a, AXES, 'skipped_axes 项') for a in items(data.get('skipped_axes', []), 'skipped_axes')],
            'findings': findings}


def clean_deliver(data):
    """校验交付记录。resolutions 记录评审问题最后的去向。"""
    only_keys(data, ('task', 'tier', 'status', 'code_changed', 'review', 'unverified', 'resolutions'), '记录')
    if not isinstance(data.get('code_changed'), bool):
        raise RecordError('code_changed 必须是 true 或 false')
    resolutions = []
    for item in items(data.get('resolutions', []), 'resolutions'):
        only_keys(item, ('rule', 'outcome'), 'resolutions 项')
        resolutions.append({'rule': text(item.get('rule'), 'rule'), 'outcome': choice(item.get('outcome'), OUTCOMES, 'outcome')})
    return {'task': text(data.get('task'), 'task'), 'tier': choice(data.get('tier'), TIERS, 'tier'),
            'status': choice(data.get('status'), STATUSES, 'status'), 'code_changed': data['code_changed'],
            'review': choice(data.get('review'), REVIEW_STATES, 'review'),
            'unverified': [choice(u, UNVERIFIED, 'unverified 项') for u in items(data.get('unverified', []), 'unverified')],
            'resolutions': resolutions}


def git_value(args, cwd):
    """读取 git 信息，失败时返回空字符串。"""
    try:
        return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, timeout=5, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def append_record(root, record):
    """追加一行记录；目录和文件只允许当前用户访问。"""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = os.open(root / 'records.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(handle, (json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8'))
    finally:
        os.close(handle)


def record(kind, session, raw, cwd='.'):
    """校验并写入一条记录。"""
    root = metrics_dir()
    if (root / 'disabled').exists():
        print('status=SKIPPED reason=度量已关闭')
        return 0
    try:
        data = json.loads(raw)
        cleaned = (clean_review if kind == 'review' else clean_deliver)(data)
    except (ValueError, RecordError) as error:
        print(f'status=REJECTED reason={error}')
        return 1
    top = git_value(['rev-parse', '--show-toplevel'], cwd)
    entry = {'v': 1, 'ts': time.time(), 'type': kind, 'session_id': session or '',
             'project': os.path.basename(top or os.path.abspath(cwd)),
             'branch': git_value(['branch', '--show-current'], cwd), **cleaned}
    try:
        append_record(root, entry)
    except OSError as error:
        print(f'status=BLOCKED reason={error}')
        return 2
    print(f'status=RECORDED type={kind}')
    return 0


def switch(action):
    """开关度量或查看状态。关闭只停止写入，已有记录保留。"""
    root = metrics_dir()
    flag = root / 'disabled'
    if action == 'off':
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        flag.touch()
    elif action == 'on':
        flag.unlink(missing_ok=True)
    data = root / 'records.jsonl'
    count = sum(1 for _ in open(data, encoding='utf-8')) if data.is_file() else 0
    print(f'status={"OFF" if flag.exists() else "ON"} records={count} path={data}')
    return 0


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['record', 'on', 'off', 'status'])
    parser.add_argument('kind', nargs='?', choices=['review', 'deliver'])
    session_var = 'CODEX_THREAD_ID' if is_codex() else 'CLAUDE_SESSION_ID'
    parser.add_argument('--session', default=os.environ.get(session_var, ''))
    args = parser.parse_args()
    if args.action != 'record':
        return switch(args.action)
    if not args.kind:
        parser.error('record 需要指定 review 或 deliver')
    # Codex 不替换技能里的 ${CLAUDE_SESSION_ID}，shell 展开后传入空字符串。
    session = args.session or os.environ.get(session_var, '')
    return record(args.kind, session, sys.stdin.read())


if __name__ == '__main__':
    sys.exit(main())
