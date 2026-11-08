#!/usr/bin/env python3
"""把一次 Claude Code 会话记录生成单页执行轨迹（原型，只读，仅用 Python 标准库）。

用法：
  python3 workflow_trace.py --session <会话 id 或 jsonl 路径> --out trace.html
                            [--project <项目根>] [--config <ai-workflow.yaml>]

会话记录是 Claude Code 的内部格式，可能随版本变化；识别不了的记录跳过，不报错。
"""
import argparse
import html
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).parent))
from workflow_config import ConfigError, parse_yaml_subset  # noqa: E402
from trace_hook import clip, redact  # noqa: E402

KIND_LABELS = {'skill': 'Skill', 'mcp': 'MCP', 'verify': '验证', 'edit': '改动',
               'agent': '子代理', 'bash': '命令', 'read': '读取'}
INTERNAL_TOOLS = ('mcp__ccd_', 'mcp__visualize__')
INTERNAL_NAMES = ('ToolSearch', 'TodoWrite', 'AskUserQuestion', 'SubagentHandback')
READ_TOOLS = ('Read', 'Grep', 'Glob', 'LS')
EDIT_TOOLS = ('Edit', 'Write', 'NotebookEdit', 'MultiEdit')
# (正则, 显示名, 覆盖的检查项)。只匹配命令片段开头，避免 grep "flutter test" 误判。
VERIFY_PATTERNS = [
    (r'(flutter|dart) analyze\b', '静态分析', {'analyze'}),
    (r'(flutter|dart) test\b', '测试', {'test'}),
    (r'dart format\b', '格式检查', {'format'}),
    (r'flutter build\b', '构建', {'build'}),
    (r'python3? (\S*/)?check\.py full\b', '完整检查', {'analyze', 'test', 'format'}),
    (r'python3? (\S*/)?check\.py docs\b', '文档检查', {'docs'}),
    (r'python3? (\S*/)?check_docs\.py\b', '文档检查', {'docs'}),
    (r'openspec validate\b', '规格校验', {'spec'}),
    (r'(npx )?(tsc|eslint)\b', '静态分析', {'analyze'}),
    (r'(npm|pnpm|yarn) (run )?test\b|pytest\b|python3? -m (unittest|pytest)\b', '测试', {'test'}),
]
FAILURE_OUTPUT = re.compile(r'Some tests failed|\bFAILED\b|status=(FAIL|BLOCKED)|\d+ issues? found|'
                            r'^\s*error [•-]|BUILD FAILED', re.M)
SUCCESS_OUTPUT = re.compile(r'All tests passed|No issues found|status=PASS|\\bPASS\\b|Built build/|BUILD SUCCESSFUL')
# Bash 里的写文件动作：AI 常用 sed / 脚本批量改代码，只看 Edit 工具会漏算。
BASH_WRITE = re.compile(r"sed -i|write_text\(|open\([^)]*['\"]w['\"]|\bperl -pi\b|(?:^|\s)>>?\s*[\w./-]+\.\w+")
CODE_PATH = re.compile(r'[\w./-]+\.(?:dart|py|tsx?|jsx?|vue|kt|swift|java|sh)\b')
GENERATED = re.compile(r'\.(g|freezed|gr|config|mocks)\.dart$')
SEGMENT_SPLIT = re.compile(r'&&|\|\||;|\n')
PREFIX = re.compile(r'^(?:\s*(?:cd\s+\S+|[A-Z_]+=\S*|timeout\s+\d+|fvm|command)\s+)*')
COMMAND_TAG = re.compile(r'<command-name>/?([^<]+)</command-name>')


def result_text(content):
    """把 tool_result 的 content 转成文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(b.get('text', '') for b in content if isinstance(b, dict))
    return ''


def load_verify_config(path):
    """读取配置的 verify 段，返回 [(命令, 档位键)]；无配置或无效时返回空列表和说明。"""
    if not path or not Path(path).is_file():
        return [], '未提供 ai-workflow.yaml，只按通用命令识别'
    try:
        verify = parse_yaml_subset(Path(path).read_text(encoding='utf-8')).get('verify') or {}
    except ConfigError as error:
        return [], f'配置无法解析：{error}'
    pairs = []
    for key, value in verify.items():
        for command in (value if isinstance(value, list) else [value]):
            pairs.append((command, f'verify.{key}'))
    return pairs, f'命令档位来自 {path}'


def classify_verify(command, config):
    """识别 Bash 命令里的验证动作。

    参数 [command]：命令全文；[config]：load_verify_config 的命令列表。
    返回：(显示名列表, 覆盖项集合, 配置键列表, 退出码是否可能被管道掩盖)。
    """
    names, covers, keys, masked = [], set(), [], False
    for raw in SEGMENT_SPLIT.split(command):
        pipeline = raw.split('|')
        segment = PREFIX.sub('', pipeline[0]).strip()
        hit = False
        for pattern, name, cover in VERIFY_PATTERNS:
            if re.match(pattern, segment):
                hit = True
                if name not in names:
                    names.append(name)
                covers |= cover
                break
        for configured, key in config:
            if segment and (segment == configured or segment.startswith(configured + ' ')):
                hit = True
                if key not in keys:
                    keys.append(key)
        masked = masked or (hit and len(pipeline) > 1)
    return names, covers, keys, masked


def read_jsonl(path):
    """逐行解析 jsonl，跳过损坏的行。"""
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            try:
                yield json.loads(line)
            except ValueError:
                continue


def summarize_subagent(session_file, agent_id):
    """统计子代理调用过的工具；找不到记录时返回 None。"""
    path = session_file.with_suffix('') / 'subagents' / f'agent-{agent_id}.jsonl'
    if not path.is_file():
        return None
    seen, counts = set(), {}
    for record in read_jsonl(path):
        content = (record.get('message') or {}).get('content')
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('id') not in seen:
                seen.add(block.get('id'))
                counts[block['name']] = counts.get(block['name'], 0) + 1
    return counts


def describe(name, data):
    """返回 (类型, 标题, 分组)；类型为 None 表示框架内部调用，不展示。"""
    if name.startswith(INTERNAL_TOOLS) or name in INTERNAL_NAMES:
        return None, '', ''
    if name == 'Skill':
        return 'skill', data.get('skill', '?'), ''
    if name.startswith('mcp__'):
        parts = name.split('__')
        return 'mcp', parts[-1], parts[1] if len(parts) > 2 else ''
    if name in EDIT_TOOLS:
        return 'edit', data.get('file_path') or data.get('notebook_path') or '?', ''
    if name in ('Agent', 'Task'):
        return 'agent', data.get('description') or data.get('subagent_type') or '子代理', ''
    if name in READ_TOOLS:
        return 'read', data.get('file_path') or data.get('pattern') or data.get('path') or '?', name
    if name == 'Bash':
        return 'bash', data.get('description') or data.get('command', '')[:80], ''
    return 'bash', name, ''


def make_step(tool, data, stamp, config, root):
    """由一次工具调用生成步骤；框架内部调用返回 None。"""
    step_kind, title, group = describe(tool, data)
    if step_kind is None:
        return None
    step = {'kind': step_kind, 'title': title, 'group': group, 'tool': tool, 'start': stamp, 'end': None,
            'error': False, 'output': '', 'detail': json.dumps(data, ensure_ascii=False, indent=1)}
    if step_kind == 'edit' and title.startswith(str(root.resolve())):
        step['rel'] = str(Path(title).relative_to(root.resolve()))
    if tool == 'Bash':
        step['detail'] = data.get('command', '')
        if BASH_WRITE.search(step['detail']):
            step['bash_edits'] = sorted({m for m in CODE_PATH.findall(step['detail'])
                                         if is_code(m) and (root / m).is_file()})
        names, covers, keys, masked = classify_verify(step['detail'], config)
        if names or keys:
            step.update(kind='verify', title=' + '.join(names or keys), group=' '.join(keys),
                        covers=covers, masked=masked)
    if step_kind == 'read' and str(data.get('file_path', '')).endswith('SKILL.md'):
        step.update(kind='skill', title=Path(data['file_path']).parent.name, group='读取 SKILL.md')
    return step


def parse_session(path, config, root=Path('.')):
    """解析会话记录，返回 {turns, start, end, branch}。每个 turn 含用户话语和步骤列表。"""
    turns, by_id, branch, start, end = [], {}, '', None, None
    current = None
    for record in read_jsonl(path):
        kind = record.get('type')
        if kind not in ('user', 'assistant') or record.get('isSidechain'):
            continue
        stamp = record.get('timestamp')
        start, end = start or stamp, stamp or end
        branch = record.get('gitBranch') or branch
        content = (record.get('message') or {}).get('content')
        if kind == 'user':
            text = content if isinstance(content, str) else ''
            if isinstance(content, list):
                text = '\n'.join(b.get('text', '') for b in content
                                 if isinstance(b, dict) and b.get('type') == 'text')
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get('type') == 'tool_result' and block.get('tool_use_id') in by_id:
                    step = by_id[block['tool_use_id']]
                    step['error'] = bool(block.get('is_error'))
                    step['output'] = result_text(block.get('content'))
                    step['end'] = stamp
                    extra = record.get('toolUseResult')
                    if step['kind'] == 'agent' and isinstance(extra, dict) and extra.get('agentId'):
                        step['subagent'] = summarize_subagent(Path(path), extra['agentId'])
            command = COMMAND_TAG.search(text)
            is_real = text.strip() and not record.get('isMeta') and not text.lstrip().startswith(
                ('<system-reminder', '<local-command', '<task-notification', 'Base directory for this skill'))
            if command or (is_real and not (isinstance(content, list) and any(
                    isinstance(b, dict) and b.get('type') == 'tool_result' for b in content))):
                if text.startswith('This session is being continued'):
                    text = '（上下文压缩后继续）'
                current = {'prompt': clip(text.strip(), 400), 'time': stamp, 'steps': []}
                turns.append(current)
                if command:
                    current['steps'].append({'kind': 'skill', 'title': command.group(1), 'group': '斜杠命令',
                                             'detail': '', 'start': stamp, 'end': stamp, 'error': False,
                                             'output': '', 'tool': 'slash'})
            continue
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get('type') != 'tool_use' or block.get('id') in by_id:
                continue
            data = block.get('input') or {}
            step = make_step(block['name'], data, stamp, config, root)
            if step is None:
                continue
            if current is None:
                current = {'prompt': '（会话开始）', 'time': stamp, 'steps': []}
                turns.append(current)
            by_id[block['id']] = step
            current['steps'].append(step)
    for step in by_id.values():
        step['status'] = status_of(step)
    return {'turns': turns, 'start': start, 'end': end, 'branch': branch}


def status_of(step):
    """判定步骤结果：ok、fail、masked（退出码被掩盖且输出无失败特征）或 pending。"""
    if step['end'] is None:
        return 'running' if step.get('live') else 'pending'
    if step['error']:
        return 'fail'
    if step['kind'] == 'verify':
        if FAILURE_OUTPUT.search(step['output']):
            return 'fail'
        if step.get('masked'):
            return 'ok' if SUCCESS_OUTPUT.search(step['output']) else 'masked'
    return 'ok'


def is_code(path):
    """判断是否手写代码文件（排除文档、配置和生成文件）。"""
    return not GENERATED.search(path) and Path(path).suffix in (
        '.dart', '.py', '.ts', '.tsx', '.js', '.jsx', '.vue', '.kt', '.swift', '.java', '.sh')


def build_checks(steps):
    """根据步骤生成检查结果，返回 [(状态, 名称, 说明)]；状态 ok / warn / fail / na。"""
    edits = [s for s in steps if not s['error'] and (
        (s['kind'] == 'edit' and is_code(s['title'])) or s.get('bash_edits'))]
    files = {s.get('rel', s['title']) for s in edits if s['kind'] == 'edit'} | {f for s in edits for f in s.get('bash_edits', ())}
    last_edit = max((s['start'] for s in edits), default=None)
    checks = [('ok' if edits else 'na', '代码改动', f'{len(files)} 个手写代码文件（含 Bash 写入，按命令文本推断）' if edits else '没有改动手写代码')]

    def coverage(item, label):
        runs = [s for s in steps if s['kind'] == 'verify' and item in s.get('covers', ())]
        if not edits:
            return ('na', label, '无代码改动，不要求')
        after = [s for s in runs if s['start'] > last_edit]
        if not after:
            note = f'运行过 {len(runs)} 次，但都在最后一次代码改动之前' if runs else '未见执行'
            return ('warn', label, note)
        final = after[-1]
        text = {'ok': '最后一次改动后已通过', 'fail': '最后一次改动后的运行失败',
                'masked': '已运行，退出码被管道掩盖，输出无失败特征', 'pending': '没有结果', 'running': '正在运行'}[final['status']]
        return ('ok' if final['status'] == 'ok' else 'fail' if final['status'] == 'fail' else 'warn', label, text)

    checks += [coverage('analyze', '静态分析'), coverage('test', '测试')]
    skills = [s['title'] for s in steps if s['kind'] == 'skill']
    workflow = sorted({s for s in skills if s.startswith('workflow-core:')})
    checks.append(('ok', '工作流技能', '、'.join(workflow)) if workflow else
                  ('warn', '工作流技能', '未见 workflow-core 技能调用'))
    reviewed = [s for s in skills if s.split(':')[-1] in ('review', 'code-review', 'requesting-code-review')]
    has_review = reviewed or not edits
    checks.append(('ok' if reviewed else 'na' if has_review else 'warn', '代码评审',
                   '、'.join(sorted(set(reviewed))) if reviewed else '无代码改动' if not edits else '未见评审技能'))
    return checks


CSS = '''
:root{--bg:#fbfaf7;--card:#fff;--ink:#23211c;--quiet:#716c60;--line:#e4e0d6;--ok:#2c7a4b;--fail:#c0392b;
--warn:#b7791f;--accent:#2f6fc4;--tint:#f3f0e8}
@media (prefers-color-scheme:dark){:root{--bg:#191815;--card:#23211d;--ink:#ece8df;--quiet:#a39d90;--line:#3a372f;
--ok:#5cc489;--fail:#ef7f70;--warn:#e0b050;--accent:#7fb0ee;--tint:#2d2a24}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 -apple-system,"PingFang SC",sans-serif}
main{max-width:920px;margin:0 auto;padding:24px 16px 64px}h1{font-size:20px;margin:0 0 4px}
.meta{color:var(--quiet);font-size:13px;overflow-wrap:anywhere}section{margin-top:24px}h2{font-size:15px;margin:0 0 8px}
.stats{display:flex;flex-wrap:wrap;gap:8px}.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 14px;min-width:84px}
.stat b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.stat span{color:var(--quiet);font-size:12px}
.check{display:grid;grid-template-columns:20px 88px 1fr;gap:8px;padding:6px 0;border-bottom:1px solid var(--line)}
.ok{color:var(--ok)}.fail{color:var(--fail)}.warn,.masked{color:var(--warn)}.na,.pending{color:var(--quiet)}
.filters{display:flex;flex-wrap:wrap;gap:6px;position:sticky;top:0;background:var(--bg);padding:8px 0;z-index:1}
button{font:inherit;font-size:13px;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:999px;padding:3px 12px;cursor:pointer}
button[aria-pressed=true]{border-color:var(--accent);color:var(--accent);font-weight:600}
.turn{margin-top:16px}.prompt{background:var(--tint);border-radius:8px;padding:8px 12px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:7.5em;overflow:auto}
.time{color:var(--quiet);font-size:12px;margin:0 0 4px}details.step{border-left:2px solid var(--line);margin-left:6px;padding:3px 0 3px 12px}
details.step{color:var(--ink)}details.step.fail{border-left-color:var(--fail)}details.step.skill,details.step.verify{border-left-color:var(--accent)}
summary{cursor:pointer;display:flex;gap:8px;align-items:baseline;list-style:none}summary::-webkit-details-marker{display:none}
.tag{flex:none;font-size:11.5px;color:var(--quiet);width:44px}.title{min-width:0;overflow-wrap:anywhere;flex:1}.side{flex:none;font-size:12px}
.group{color:var(--quiet);font-size:12px;margin-left:6px}pre{background:var(--tint);border-radius:6px;padding:8px;margin:6px 0;overflow:auto;max-height:320px;font:12px/1.5 ui-monospace,Menlo,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
.label{color:var(--quiet);font-size:12px}.hide{display:none}
'''

SCRIPT = '''
const buttons=[...document.querySelectorAll('[data-filter]')];
buttons.forEach(b=>b.onclick=()=>{buttons.forEach(x=>x.setAttribute('aria-pressed',x===b));
const f=b.dataset.filter;document.querySelectorAll('.step').forEach(s=>{
s.classList.toggle('hide',!(f==='all'?!s.classList.contains('quiet'):f==='fail'?s.classList.contains('fail'):s.classList.contains(f)))});
document.querySelectorAll('.turn').forEach(t=>t.classList.toggle('hide',!t.querySelector('.step:not(.hide)')&&f!=='all'))});
'''

MARKS = {'ok': '✓', 'fail': '✕', 'warn': '!', 'masked': '!', 'na': '–', 'pending': '…'}
STATUS_TEXT = {'ok': '通过', 'fail': '失败', 'masked': '退出码被掩盖', 'pending': '无结果'}


def clock(stamp):
    """把 ISO 时间裁成“月-日 时:分:秒（UTC）”。"""
    return f'{stamp[5:10]} {stamp[11:19]}' if stamp else ''


def render_step(step):
    """渲染一个步骤。读取类默认隐藏，避免淹没关键步骤。"""
    e = html.escape
    quiet = ' quiet hide' if step['kind'] == 'read' else ''
    status = step['status']
    side = f'<span class="side {status}">{MARKS[status]} {STATUS_TEXT[status]}</span>' \
        if status != 'ok' or step['kind'] in ('verify', 'skill', 'mcp', 'agent') else ''
    group = f'<span class="group">{e(step["group"])}</span>' if step.get('group') else ''
    body = ''
    if step.get('detail'):
        body += f'<div class="label">输入</div><pre>{e(clip(step["detail"], 2000))}</pre>'
    if step.get('subagent'):
        used = '、'.join(f'{k}×{v}' for k, v in sorted(step['subagent'].items()))
        body += f'<div class="label">子代理内部工具</div><pre>{e(used)}</pre>'
    if step.get('output'):
        body += f'<div class="label">结果</div><pre>{e(clip(step["output"]))}</pre>'
    return (f'<details class="step {step["kind"]} {status}{quiet}"><summary><span class="tag">'
            f'{KIND_LABELS[step["kind"]]}</span><span class="title">{e(redact(step["title"]))}{group}</span>'
            f'{side}</summary>{body}</details>')


def render(session, name, config_note):
    """生成完整 HTML。"""
    e = html.escape
    steps = [s for t in session['turns'] for s in t['steps']]
    count = lambda kind: sum(s['kind'] == kind for s in steps)
    fails = sum(s['status'] == 'fail' for s in steps)
    stats = ''.join(f'<div class="stat"><b>{v}</b><span>{k}</span></div>' for k, v in [
        ('Skill', count('skill')), ('MCP', count('mcp')), ('验证', count('verify')), ('改动', count('edit')),
        ('子代理', count('agent')), ('命令', count('bash')), ('失败', fails)])
    checks = ''.join(f'<div class="check"><span class="{s}">{MARKS[s]}</span><b>{e(n)}</b><span>{e(d)}</span></div>'
                     for s, n, d in build_checks(steps))
    filters = [('all', '关键步骤')] + [(k, KIND_LABELS[k]) for k in ('skill', 'mcp', 'verify', 'edit', 'agent', 'bash', 'read')] + [('fail', '失败')]
    buttons = ''.join(f'<button data-filter="{k}" aria-pressed="{str(k == "all").lower()}">{v}</button>' for k, v in filters)
    turns = ''.join(
        f'<div class="turn"><p class="time">{clock(t["time"])} UTC</p><div class="prompt">{e(t["prompt"])}</div>'
        + ''.join(render_step(s) for s in t['steps']) + '</div>' for t in session['turns'])
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>执行轨迹</title>'
            f'<style>{CSS}</style></head><body><main><h1>执行轨迹</h1>'
            f'<p class="meta">{e(name)} · 分支 {e(session["branch"] or "未知")} · {clock(session["start"])} → '
            f'{clock(session["end"])} UTC<br>{e(config_note)}</p>'
            f'<section><div class="stats">{stats}</div></section><section><h2>检查</h2>{checks}</section>'
            f'<section><h2>时间线</h2><div class="filters">{buttons}</div>{turns}</section>'
            f'</main><script>{SCRIPT}</script></body></html>')


def locate(session, project):
    """由会话 id 或路径定位 jsonl 文件。"""
    path = Path(session).expanduser()
    if path.is_file():
        return path
    slug = re.sub(r'[^A-Za-z0-9]', '-', str(Path(project).resolve()))
    return Path.home() / '.claude' / 'projects' / slug / f'{session}.jsonl'


def main():
    """命令行入口；0 成功，2 找不到会话记录。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--project', default='.')
    parser.add_argument('--config')
    args = parser.parse_args()
    path = locate(args.session, args.project)
    if not path.is_file():
        print(f'status=BLOCKED reason=找不到会话记录 path={path}')
        return 2
    config, note = load_verify_config(args.config or str(Path(args.project) / 'ai-workflow.yaml'))
    session = parse_session(path, config, Path(args.project))
    Path(args.out).write_text(render(session, path.stem, note), encoding='utf-8')
    steps = [s for t in session['turns'] for s in t['steps']]
    print(f'status=PASS turns={len(session["turns"])} steps={len(steps)} out={args.out}')
    for state, name, detail in build_checks(steps):
        print(f'{state}\t{name}\t{detail}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
