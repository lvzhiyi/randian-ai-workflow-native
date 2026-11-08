#!/usr/bin/env python3
"""流程度量报告：汇总技能触发率、评审、拦截、待验证比例，生成规则命中表和删除候选（只读，仅用 Python 标准库）。

数据来源：workflow_metric.py 写的 records.jsonl，和 Claude Code 会话记录（算触发率）。
用法：metrics_report.py [--project 目录] [--days 90] [--all] [--min-reviews 20]
"""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))
from workflow_metric import git_value, metrics_dir  # noqa: E402
from workflow_trace import code_edit_steps, parse_session, read_jsonl  # noqa: E402

DAY = 86400
# 触发率低于该值时，“零命中”不足以说明规则没用。
LOW_TRIGGER = 0.5
# 命中达到该次数才判断规则该强化还是该改写。
MIN_HITS = 3
# 这类规则频率低但后果重，不因零命中进入删除候选。
PROTECTED = re.compile(r'安全|鉴权|权限|登录|凭据|密码|令牌|敏感|数据完整|迁移|支付|(?i:auth|token|secret|security)')
PENDING_STATUS = '实施完成，待验证'


def load_records(root):
    """读取全部度量记录；文件不存在时返回空列表。"""
    path = Path(root) / 'records.jsonl'
    return [r for r in read_jsonl(path) if isinstance(r, dict)] if path.is_file() else []


def project_name(project):
    """返回与度量记录一致的项目名（git 根目录名）。"""
    top = git_value(['rev-parse', '--show-toplevel'], project)
    return os.path.basename(top or os.path.abspath(project))


def transcript_files(projects_dir, project, include_all, since):
    """列出统计窗口内更新过的会话记录；项目模式包含该项目的 worktree。"""
    base = Path(projects_dir)
    if include_all:
        folders = [p for p in base.iterdir() if p.is_dir()] if base.is_dir() else []
    else:
        slug = re.sub(r'[^A-Za-z0-9]', '-', str(Path(project).resolve()))
        folders = [base / slug] + sorted(base.glob(slug + '--claude-worktrees-*'))
    return [f for folder in folders for f in folder.glob('*.jsonl') if f.stat().st_mtime >= since]


def session_cwd(path):
    """取会话记录里第一个 cwd，用于判断 Bash 写入的文件是否存在。"""
    for record in read_jsonl(path):
        if record.get('cwd'):
            return Path(record['cwd'])
    return Path('.')


def workflow_skill(step):
    """返回步骤对应的 workflow-core 技能短名；不是则返回 None。"""
    if step['kind'] != 'skill':
        return None
    if step['title'].startswith('workflow-core:'):
        return step['title'].split(':', 1)[1]
    return step['title'] if 'workflow-core' in step.get('detail', '') else None


def session_usage(path):
    """统计一个会话是否改了代码、用了哪些工作流技能。"""
    session = parse_session(path, [], session_cwd(path))
    steps = [step for turn in session['turns'] for step in turn['steps']]
    return {'id': Path(path).stem, 'code_changed': bool(code_edit_steps(steps)),
            'skills': {name for name in map(workflow_skill, steps) if name}}


def trigger_stats(usages, records):
    """计算改了代码的会话中各环节的触发情况。"""
    code = [u for u in usages if u['code_changed']]
    recorded = {r.get('session_id') for r in records if r.get('type') == 'deliver'}
    count = lambda test: sum(1 for u in code if test(u))
    return {'total': len(code), 'any': count(lambda u: u['skills']), 'verify': count(lambda u: 'verify' in u['skills']),
            'review': count(lambda u: 'review' in u['skills']), 'deliver': count(lambda u: 'deliver' in u['skills']),
            'recorded': count(lambda u: u['id'] in recorded),
            'other_review': sum(1 for u in usages if not u['code_changed'] and 'review' in u['skills']),
            'other_deliver': sum(1 for u in usages if not u['code_changed'] and 'deliver' in u['skills'])}


def source_matches(source, rule):
    """判断命中的规则是否来自某规则来源（rule 约定为“文件 + 规则标题”）。"""
    if '坏味道' in source and rule.startswith('坏味道'):
        return True
    name = Path(source).name
    return bool(name) and (source in rule or name in rule or (Path(source).stem and Path(source).stem in rule))


def standards_findings(review):
    """只取 Standards 轴的问题：Spec 轴的依据是单个任务的验收，不是可保留或删除的规则。"""
    return [f for f in review.get('findings', []) if f.get('axis') == 'standards']


def rule_table(reviews, delivers):
    """按规则汇总命中与去向，并给出建议动作。"""
    table = defaultdict(lambda: {'hits': 0, '阻塞': 0, '应修': 0, '建议': 0, '已修复': 0, '接受例外': 0, '未解决': 0})
    for review in reviews:
        for finding in standards_findings(review):
            row = table[finding['rule']]
            row['hits'] += 1
            row[finding['severity']] += 1
    for deliver in delivers:
        for item in deliver.get('resolutions', []):
            if item['rule'] in table:
                table[item['rule']][item['outcome']] += 1
    rows = []
    for rule, row in table.items():
        if row['hits'] < MIN_HITS:
            action = '观察'
        elif row['接受例外'] * 2 >= row['hits']:
            action = '多被接受为例外：修改或降级'
        elif row['已修复'] * 2 >= row['hits']:
            action = '有效：保留，能脚本判断的升级成检查'
        else:
            action = '观察（去向数据不足）'
        rows.append({'rule': rule, 'action': action, **row})
    return sorted(rows, key=lambda r: (-r['hits'], r['rule']))


def deletion_candidates(reviews, older_reviews, min_reviews):
    """找删除候选：只有被检查过足够次数仍零命中才算。

    参数 [reviews]：窗口内评审；[older_reviews]：窗口前评审；[min_reviews]：最少检查次数。
    返回：{candidates, watching, protected}；candidates 项为 (名称, 类型, 检查次数)。
    """
    checked = Counter(s for r in reviews for s in set(r.get('sources', [])))
    rules = [f['rule'] for r in reviews for f in standards_findings(r)]
    old_rules = {f['rule'] for r in older_reviews for f in standards_findings(r)} - set(rules)
    result = {'candidates': [], 'watching': [], 'protected': []}
    for source, times in sorted(checked.items(), key=lambda kv: (-kv[1], kv[0])):
        if any(source_matches(source, rule) for rule in rules):
            continue
        bucket = 'protected' if PROTECTED.search(source) else 'candidates' if times >= min_reviews else 'watching'
        result[bucket].append((source, '规则来源零命中', times))
    for rule in sorted(old_rules):
        times = max((n for s, n in checked.items() if source_matches(s, rule)), default=0)
        if times:
            bucket = 'protected' if PROTECTED.search(rule) else 'candidates' if times >= min_reviews else 'watching'
            result[bucket].append((rule, '以前命中、窗口内零命中', times))
    return result


def cell(text):
    """转义 Markdown 表格单元格。"""
    return str(text).replace('|', '\\|')


def percent(part, whole):
    """格式化比例。"""
    return f'{part}/{whole}（{part * 100 // whole}%）' if whole else '0/0（无样本）'


def render(args, name, usages, records, older):
    """生成 Markdown 报告。"""
    reviews = [r for r in records if r.get('type') == 'review']
    delivers = [r for r in records if r.get('type') == 'deliver']
    stops = [r for r in records if r.get('type') == 'stop_block']
    stats = trigger_stats(usages, records)
    scope = '本机所有项目' if args.all else f'项目 {name}'
    lines = [f'# 流程度量报告', '', f'范围：{scope}，最近 {args.days} 天。样本：{len(usages)} 个会话，'
             f'{len(reviews)} 次评审，{len(delivers)} 次交付，{len(stops)} 条拦截记录。', '']
    if len(delivers) < args.min_reviews:
        lines += [f'> 样本不足（交付记录 {len(delivers)}/{args.min_reviews}）：以下数字只看趋势，不下结论。', '']

    lines += ['## 技能触发率', '', '分母是改了手写代码的会话（一个会话可能含多个任务，子代理内的改动未计入）。', '',
              '| 环节 | 触发 |', '| --- | --- |']
    for label, key in (('任一 workflow-core 技能', 'any'), ('verify', 'verify'), ('review', 'review'), ('deliver', 'deliver'),
                       ('写了交付度量记录', 'recorded')):
        lines.append(f'| {label} | {percent(stats[key], stats["total"])} |')
    if stats['other_review'] or stats['other_deliver']:
        lines += ['', f'另有未改代码的会话触发了 review {stats["other_review"]} 次、deliver {stats["other_deliver"]} 次'
                      '（如对已有分支补评审），不计入上表。']
    review_rate = stats['review'] / stats['total'] if stats['total'] else 0
    low_trigger = review_rate < LOW_TRIGGER
    if low_trigger:
        lines += ['', f'> review 触发率低于 {int(LOW_TRIGGER * 100)}%：规则零命中可能只是没被检查，先解决触发问题。']

    blocked_sessions = {r.get('session_id') for r in stops if r.get('outcome') == 'blocked'}
    outcomes = Counter(r.get('outcome') for r in stops if r.get('outcome') != 'fixed' or r.get('session_id') in blocked_sessions)
    pending = [r for r in delivers if r.get('status') == PENDING_STATUS]
    reasons = Counter(u for r in delivers for u in r.get('unverified', []))
    with_block = sum(1 for r in reviews if any(f['severity'] == '阻塞' for f in r.get('findings', [])))
    spec_findings = [f for r in reviews for f in r.get('findings', []) if f.get('axis') == 'spec']
    spec_blocks = sum(f['severity'] == '阻塞' for f in spec_findings)
    lines += ['', '## 核心指标', '', '| 指标 | 数值 |', '| --- | --- |',
              f'| Spec 轴问题 | {len(spec_findings)} 项，其中阻塞 {spec_blocks} |',
              f'| 含阻塞项的评审 | {percent(with_block, len(reviews))} |',
              f'| Stop 钩子拦截 | {outcomes["blocked"]} 次，重试后修好 {outcomes["fixed"]}，仍有错误 {outcomes["unresolved"]} |',
              f'| 「待验证」交付 | {percent(len(pending), len(delivers))} |']
    if reasons:
        lines += ['', '未验证原因：' + '、'.join(f'{k} {v}' for k, v in reasons.most_common()) + '。']

    rows = rule_table(reviews, delivers)
    lines += ['', '## 规则命中表', '', '只统计 Standards 轴；Spec 轴针对单个任务的验收，见核心指标。', '']
    if rows:
        lines += ['| 规则 | 命中 | 阻塞/应修/建议 | 已修复/例外/未解决 | 建议 |', '| --- | --- | --- | --- | --- |']
        lines += [f'| {cell(r["rule"])} | {r["hits"]} | {r["阻塞"]}/{r["应修"]}/{r["建议"]} | '
                  f'{r["已修复"]}/{r["接受例外"]}/{r["未解决"]} | {r["action"]} |' for r in rows]
    else:
        lines.append('暂无评审命中记录。')

    found = deletion_candidates(reviews, older, args.min_reviews)
    lines += ['', '## 删除候选', '', '候选只供人工判断，不会自动删除。只能精确到规则来源文件，或曾经命中过的规则；从未命中的单条规则无法单独识别。', '']
    if found['candidates'] and not low_trigger:
        lines += ['| 名称 | 原因 | 检查次数 |', '| --- | --- | --- |']
        lines += [f'| {cell(n)} | {why} | {times} |' for n, why, times in found['candidates']]
    elif found['candidates']:
        lines.append(f'有 {len(found["candidates"])} 项满足次数，但 review 触发率过低，暂不列为候选。')
    else:
        lines.append(f'暂无候选（需要被检查至少 {args.min_reviews} 次仍零命中）。')
    if found['watching']:
        lines += ['', '观察中：' + '、'.join(f'{cell(n)}（{t}/{args.min_reviews}）' for n, _, t in found['watching']) + '。']
    if found['protected']:
        lines += ['', '受保护、不进候选（安全、鉴权、数据类）：' + '、'.join(cell(n) for n, _, _ in found['protected']) + '。']
    return '\n'.join(lines) + '\n'


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default='.')
    parser.add_argument('--days', type=int, default=90)
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--min-reviews', type=int, default=20)
    args = parser.parse_args()
    since = time.time() - args.days * DAY
    name = project_name(args.project)
    records = [r for r in load_records(metrics_dir()) if args.all or r.get('project') == name]
    projects_dir = os.environ.get('WORKFLOW_CLAUDE_PROJECTS') or Path.home() / '.claude' / 'projects'
    usages = [session_usage(path) for path in transcript_files(projects_dir, args.project, args.all, since)]
    current = [r for r in records if r.get('ts', 0) >= since]
    older = [r for r in records if r.get('ts', 0) < since and r.get('type') == 'review']
    sys.stdout.write(render(args, name, usages, current, older))
    return 0


if __name__ == '__main__':
    sys.exit(main())
