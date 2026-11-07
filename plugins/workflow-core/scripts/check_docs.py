#!/usr/bin/env python3
"""workflow-core 文档规范检查（只读，仅用 Python 标准库）。

检查两类内容：
1. 文档本地链接与锚点：Agent 入口、工程规范、产品文档中的相对链接目标是否存在、锚点标题是否存在。
2. 模块任务卡：子需求小节的必填字段，以及结构化「待确认」记录的五段格式。
3. 术语表（配置了 docs.glossary 时）：每个词条有「定义」字段、词条不重名。

路径从项目配置读取（见 workflow_config.py：ai-workflow.yaml 优先，旧格式 Markdown 小节兼容），命令行参数优先。
用法：python3 check_docs.py [--root 项目根] [--product-root DIR] [--cards-dir DIR] [--dev-docs DIR] [--check-config]
退出码：0 通过；1 检查未通过；2 执行受阻（如项目根不存在、配置无法解析）。
"""
import argparse
from pathlib import Path
import re
import sys
from urllib.parse import unquote

from workflow_config import ConfigError, load as load_config

# 子需求标题：### <模块>-R<编号> 标题，例如 ### AUTH-R01 学员选择登录方式
DEFAULT_CARD_ID = r'[A-Z][A-Z0-9]*-R\d+'

# 子需求必填字段：字段名 → 匹配规则；与 templates/task-card.md 保持一致。
CARD_REQUIRED = {
    '完成勾选框': re.compile(r'^- \[[ xX]\] ', re.M),
    '来源': re.compile(r'^- 来源[：:]', re.M),
    '负责人': re.compile(r'负责人'),
    '验收': re.compile(r'^- 验收[：:]', re.M),
}

# 结构化「待确认」记录（含全角竖线「｜」）必须包含的段落。
PENDING_KEYS = ('影响：', '负责人：', '恢复条件：', '来源：')

def resolve_paths(root, args, config):
    """合并命令行参数、项目配置和默认值，得到本次检查使用的目录。

    参数 [root]：项目根目录；[args]：argparse 结果；[config]：workflow_config.Config。
    返回：(product_root, cards_dir, dev_docs)，均为绝对 Path。
    默认值：产品文档根 docs/product，任务卡目录 <产品文档根>/任务，工程规范 docs/development。
    """
    product = args.product_root or config.get('docs.product_root') or 'docs/product'
    cards = args.cards_dir or config.get('docs.cards_dir') or f'{product}/任务'
    dev = args.dev_docs or config.get('docs.dev_docs') or 'docs/development'
    return root / product, root / cards, root / dev


def check_glossary(root, path):
    """检查术语表：每个三级标题是一个词条，必须有「- 定义：」字段，词条不重名。

    参数 [root]：项目根，用于输出相对路径；[path]：术语表文件。
    返回：错误描述列表。
    """
    errors = []
    content = path.read_text(encoding='utf-8')
    rel = path.relative_to(root)
    entries = list(re.finditer(r'^###\s+(.+?)\s*$', content, re.M))
    seen = set()
    for index, match in enumerate(entries):
        term = match.group(1)
        end = entries[index + 1].start() if index + 1 < len(entries) else len(content)
        section = re.split(r'^## ', content[match.end():end], maxsplit=1, flags=re.M)[0]
        if term in seen:
            errors.append(f'{rel}: 词条重名「{term}」')
        seen.add(term)
        if not re.search(r'^- 定义[：:]\s*\S', section, re.M):
            errors.append(f'{rel}: 词条「{term}」缺少「定义」')
    return errors


def heading_slugs(text):
    """按 GitHub 规则把 Markdown 标题转成锚点列表，重名标题依次追加 -1、-2。

    参数 [text]：Markdown 全文。
    返回：所有可用锚点的集合。
    """
    seen = {}
    slugs = set()
    for title in re.findall(r'^#{1,6}\s+(.+?)\s*#*\s*$', text, re.M):
        slug = re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        slugs.add(slug if count == 0 else f'{slug}-{count}')
    return slugs


def check_links(root, paths):
    """检查文档里的本地相对链接与锚点。

    参数 [root]：项目根，用于输出相对路径；[paths]：要检查的 Markdown 文件。
    返回：错误描述列表。外部链接（带协议，如 https:、mailto:）不检查。
    代码块中的链接也会被检查，与项目原有脚本行为一致。
    """
    errors = []
    cache = {}
    for path in paths:
        content = path.read_text(encoding='utf-8')
        for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', content):
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target):
                continue
            name, _, anchor = unquote(target).partition('#')
            dest = (path.parent / name).resolve() if name else path
            rel = path.relative_to(root)
            if not dest.exists():
                errors.append(f'{rel}: 链接目标不存在 {target}')
            elif anchor and dest.suffix == '.md':
                if dest not in cache:
                    cache[dest] = heading_slugs(dest.read_text(encoding='utf-8'))
                if anchor not in cache[dest]:
                    errors.append(f'{rel}: 锚点不存在 {target}')
    return errors


def check_cards(root, cards_dir, card_id=DEFAULT_CARD_ID):
    """检查模块卡子需求的必填字段与结构化「待确认」格式。

    参数 [root]：项目根；[cards_dir]：任务卡目录；[card_id]：子需求编号正则。
    返回：错误描述列表。子需求小节从其 ### 标题到下一个子需求标题或二级标题为止。
    不含「｜」的旧式自由文本「待确认：」不报错，随卡片修改迁移到新格式。
    """
    errors = []
    heading = re.compile(rf'^###\s+({card_id})\b.*$', re.M)
    for path in sorted(cards_dir.glob('*.md')):
        content = path.read_text(encoding='utf-8')
        rel = path.relative_to(root)
        matches = list(heading.finditer(content))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            section = re.split(r'^## ', content[match.end():end], maxsplit=1, flags=re.M)[0]
            for field, pattern in CARD_REQUIRED.items():
                if not pattern.search(section):
                    errors.append(f'{rel}: {match.group(1)} 缺少字段「{field}」')
            for line in re.findall(r'^- 待确认：.*｜.*$', section, re.M):
                missing = [key for key in PENDING_KEYS if key not in line]
                if missing:
                    errors.append(f'{rel}: {match.group(1)} 待确认记录缺少 {"/".join(missing)}')
    return errors


def collect_docs(root, product_root, dev_docs):
    """收集需要做链接检查的文档：Agent 入口、规格工具说明、工程规范、产品文档。

    参数 [root]：项目根；[product_root]、[dev_docs]：目录（不存在则跳过）。
    返回：去重后按路径排序的 Markdown 文件列表。
    """
    paths = [root / name for name in ('AGENTS.md', 'CLAUDE.md', 'openspec/project.md')]
    paths = [path for path in paths if path.is_file()]
    if dev_docs.is_dir():
        paths += sorted(dev_docs.glob('*.md'))
    if product_root.is_dir():
        paths += sorted(product_root.rglob('*.md'))
    return sorted(set(paths))


def main(argv=None):
    """命令行入口。

    参数 [argv]：命令行参数列表，None 时读取 sys.argv。
    返回：退出码，0 通过、1 检查未通过、2 执行受阻。
    """
    parser = argparse.ArgumentParser(description='workflow-core 文档规范检查（只读）')
    parser.add_argument('--root', default='.', help='项目根目录，默认当前目录')
    parser.add_argument('--product-root', help='产品文档根，覆盖工作流配置')
    parser.add_argument('--cards-dir', help='任务卡目录，覆盖工作流配置')
    parser.add_argument('--dev-docs', help='工程规范目录，覆盖工作流配置')
    parser.add_argument('--card-id', default=DEFAULT_CARD_ID, help='子需求编号正则')
    parser.add_argument('--skip-cards', action='store_true', help='只检查链接，不检查任务卡')
    parser.add_argument('--check-config', action='store_true',
                        help='额外检查配置里的路径是否存在')
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f'[docs] status=BLOCKED reason=项目根不存在 {root}', flush=True)
        return 2
    try:
        config = load_config(root)
    except ConfigError as error:
        print(f'[docs] status=BLOCKED reason=配置无法读取 {error}', flush=True)
        return 2
    product_root, cards_dir, dev_docs = resolve_paths(root, args, config)
    print(f'[docs] 路径来源：{config.source}；产品文档根={product_root.relative_to(root)}，'
          f'任务卡={cards_dir.relative_to(root)}，工程规范={dev_docs.relative_to(root)}', flush=True)
    if config.legacy:
        print('[docs] 提示：配置仍在 Markdown 小节，建议运行 /workflow-core:init 迁移到 ai-workflow.yaml',
              flush=True)

    paths = collect_docs(root, product_root, dev_docs)
    link_errors = check_links(root, paths)
    card_errors = []
    if not args.skip_cards:
        if cards_dir.is_dir():
            card_errors = check_cards(root, cards_dir, args.card_id)
        else:
            print(f'[cards] 任务卡目录不存在，跳过：{cards_dir.relative_to(root)}', flush=True)

    glossary_errors = []
    glossary = config.get('docs.glossary')
    if glossary and glossary not in ('待确认', '无') and (root / glossary).is_file():
        glossary_errors = check_glossary(root, root / glossary)
        print(f'[glossary] {len(glossary_errors)} 个错误', flush=True)
    config_errors = []
    if args.check_config:
        config_errors = [f'{config.source}: 路径不存在 {item}' for item in config.missing_paths()]
        print(f'[config] {len(config_errors)} 个错误', flush=True)

    for error in link_errors + card_errors + glossary_errors + config_errors:
        print(error, file=sys.stderr)
    print(f'[links] {len(paths)} 个文件，{len(link_errors)} 个错误', flush=True)
    if not args.skip_cards:
        print(f'[cards] {len(card_errors)} 个错误', flush=True)
    failed = bool(link_errors or card_errors or glossary_errors or config_errors)
    print(f'[docs] status={"CHECK_FAILED" if failed else "PASS"}', flush=True)
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
