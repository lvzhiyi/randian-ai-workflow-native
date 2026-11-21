#!/usr/bin/env python3
"""归档已完成任务的变更目录（如 docs/development/changes/<task-id>/）。

用法：
  python3 archive_change.py --root . --task <task-id> [--task <task-id2>] [--changes-dir DIR] [--dry-run]
  python3 archive_change.py --root . --task <change-id> --changes-dir openspec/changes
"""
import argparse
from datetime import date
from pathlib import Path
import shutil
import sys

from check_docs import main as check_docs_main
from workflow_config import ConfigError, load as load_config


def safe_name(name):
    """只接受单层目录名，拒绝路径穿越、空名与 archive 保留名。"""
    if not name or name in ('.', '..', 'archive') or '/' in name or '\\' in name:
        raise ValueError(f'无效的变更目录名：{name}')
    return name


def resolve_changes_dir(root, override, config):
    """定位变更根目录：优先 --changes-dir，否则取 <docs.dev_docs>/changes。"""
    if override:
        rel = Path(override)
    else:
        dev_docs = config.get('docs.dev_docs') or 'docs/development'
        rel = Path(dev_docs) / 'changes'
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError(f'变更目录必须位于项目根内：{rel}')
    target = (root / rel).resolve()
    target.relative_to(root)
    return target


def archive_one(changes_dir, task_id, month_prefix, dry_run=False):
    """归档单个变更目录，返回 (src, dst)。"""
    name = safe_name(task_id)
    src = changes_dir / name
    if src.is_symlink() or not src.is_dir():
        raise FileNotFoundError(f'变更目录不存在或为符号链接：{src}')
    archive_root = changes_dir / 'archive'
    if archive_root.is_symlink():
        raise ValueError(f'归档目录不能为符号链接：{archive_root}')
    dst_name = name if name.startswith(month_prefix + '-') else f'{month_prefix}-{name}'
    dst = archive_root / dst_name
    if dst.exists():
        raise FileExistsError(f'归档目标已存在：{dst}')
    if not dry_run:
        archive_root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    return src, dst


def main(argv=None):
    parser = argparse.ArgumentParser(description='归档已完成的变更目录并校验文档链接')
    parser.add_argument('--root', default='.', help='项目根目录，默认当前目录')
    parser.add_argument('--task', action='append', required=True, help='待归档的变更目录名（可重复）')
    parser.add_argument('--changes-dir', help='覆盖变更目录路径（默认 <docs.dev_docs>/changes）')
    parser.add_argument('--month', default=date.today().strftime('%Y-%m'), help='归档月份前缀，默认 YYYY-MM')
    parser.add_argument('--dry-run', action='store_true', help='仅预览归档目标，不实际移动文件')
    parser.add_argument('--skip-check', action='store_true', help='归档后跳过文档链接检查')
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f'[archive] status=BLOCKED reason=项目根不存在 {root}', file=sys.stderr)
        return 2
    try:
        config = load_config(root)
        changes_dir = resolve_changes_dir(root, args.changes_dir, config)
    except (ConfigError, ValueError) as error:
        print(f'[archive] status=BLOCKED reason={error}', file=sys.stderr)
        return 2

    if not changes_dir.is_dir():
        print(f'[archive] status=BLOCKED reason=变更目录不存在 {changes_dir}', file=sys.stderr)
        return 2

    # 先校验全部目标，避免部分移动后再失败
    planned = []
    try:
        for task_id in args.task:
            src, dst = archive_one(changes_dir, task_id, args.month, dry_run=True)
            planned.append((task_id, src, dst))
    except (ValueError, FileNotFoundError, FileExistsError) as error:
        print(f'[archive] status=FAILED reason={error}', file=sys.stderr)
        return 1

    for task_id, src, dst in planned:
        rel_src = src.relative_to(root)
        rel_dst = dst.relative_to(root)
        if args.dry_run:
            print(f'[archive] dry-run: {rel_src} -> {rel_dst}')
        else:
            archive_one(changes_dir, task_id, args.month, dry_run=False)
            print(f'[archive] archived: {rel_src} -> {rel_dst}')

    if args.dry_run or args.skip_check:
        return 0
    return check_docs_main(['--root', str(root), '--skip-cards'])


if __name__ == '__main__':
    sys.exit(main())
