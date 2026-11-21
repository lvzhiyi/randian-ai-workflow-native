#!/usr/bin/env python3
"""将 workflow_config.py 与 check_docs.py 打包为零第三方依赖的单文件脚本。

用法：
  python3 vendor_check_docs.py --output <目标项目>/scripts/check_docs.py
  python3 vendor_check_docs.py --check <目标项目>/scripts/check_docs.py
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent
PLUGIN_JSON = SCRIPTS_DIR.parent / '.claude-plugin/plugin.json'
CONFIG_SRC = SCRIPTS_DIR / 'workflow_config.py'
DOCS_SRC = SCRIPTS_DIR / 'check_docs.py'


def _strip_header(source):
    """去掉开头的 shebang 与模块文档字符串，保留纯模块正文。"""
    lines = source.splitlines(keepends=True)
    if lines and lines[0].startswith('#!'):
        lines = lines[1:]
    body = ''.join(lines)
    tree = ast.parse(body)
    if (tree.body and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)):
        end_line = tree.body[0].end_lineno
        body = ''.join(body.splitlines(keepends=True)[end_line:])
    return body.lstrip('\n')


def plugin_version():
    """读取 workflow-core 插件版本号。"""
    if PLUGIN_JSON.is_file():
        data = json.loads(PLUGIN_JSON.read_text(encoding='utf-8'))
        if isinstance(data.get('version'), str):
            return data['version']
    return 'unknown'


def render_standalone():
    """生成自包含单文件版 check_docs.py 内容。"""
    config_raw = CONFIG_SRC.read_text(encoding='utf-8')
    docs_raw = DOCS_SRC.read_text(encoding='utf-8')
    digest = hashlib.sha256((config_raw + '\n' + docs_raw).encode('utf-8')).hexdigest()[:12]
    version = plugin_version()

    config_body = _strip_header(config_raw).rstrip() + '\n'
    docs_body = _strip_header(docs_raw)
    import_line = 'from workflow_config import ConfigError, load as load_config'
    if import_line not in docs_body:
        raise RuntimeError(f'未找到预期导入行：{import_line}')
    docs_body = docs_body.replace(import_line, 'load_config = load', 1).rstrip() + '\n'

    header = (
        '#!/usr/bin/env python3\n'
        '"""自包含文档规范检查脚本（只读，仅依赖 Python 标准库，可直接提交至消费项目）。\n'
        '\n'
        f'来源：workflow-core {version} (source-sha256: {digest})\n'
        '重新生成：python3 <workflow-core>/scripts/vendor_check_docs.py --output scripts/check_docs.py\n'
        '"""\n\n'
    )
    return (
        header
        + '# === embedded: workflow_config.py ===\n'
        + config_body
        + '\n# === embedded: check_docs.py ===\n'
        + docs_body
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description='导出或校验自包含单文件版 check_docs.py')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', help='输出路径；传 - 输出到标准输出')
    group.add_argument('--check', help='校验已有文件是否与当前插件版本一致')
    args = parser.parse_args(argv)

    rendered = render_standalone()
    if args.check:
        target = Path(args.check)
        if not target.is_file():
            print(f'[vendor] 目标不存在：{target}', file=sys.stderr)
            return 1
        if target.read_text(encoding='utf-8') != rendered:
            print(f'[vendor] 已过期或有手工修改：{target}', file=sys.stderr)
            return 1
        print(f'[vendor] 最新一致：{target}')
        return 0

    if args.output == '-':
        sys.stdout.write(rendered)
        return 0

    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding='utf-8')
    try:
        os.chmod(target, 0o755)
    except OSError:
        pass
    print(f'[vendor] 已生成自包含检查脚本：{target}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
