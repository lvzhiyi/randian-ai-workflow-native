#!/usr/bin/env python3
"""stack-flutter 默认代码检查：格式 → 静态分析 → 测试（仅 Python 标准库）。

项目「工作流配置」没有给出验证命令时使用；项目有自己的检查入口（如 scripts/check.py full）时优先用项目的。
用法：
  python3 flutter_check.py [--root 项目根] [--all] [--no-test] [测试路径 ...]
    默认只格式检查本次改动的 Dart 文件（相对 HEAD 的修改 + 未跟踪文件，排除生成文件）；
    --all 改为检查 lib/ test/ 下全部手写 Dart 文件；
    给出测试路径时只跑这些测试，否则跑全部测试；--no-test 跳过测试（交付时须说明原因）。
退出码：0 全部通过；1 有检查未通过；2 执行受阻（不是 Flutter 项目、缺少 flutter/dart）。
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

# 代码生成器产出的文件后缀：不手改，也不参与格式检查和 Stop 钩子分析。
GENERATED_SUFFIXES = ('.g.dart', '.freezed.dart', '.gr.dart', '.mocks.dart', '.config.dart',
                      '.iconfig.dart', '.injection.dart', '.router.dart', '.r.g.dart', '.part.dart')


def clean_env():
    """返回去掉 git 钩子变量的环境副本。

    返回：os.environ 的副本，去掉 GIT_DIR、GIT_INDEX_FILE、GIT_WORK_TREE。
    原因：在 git 钩子里调用 flutter 时，这些变量会让 Flutter 读到项目仓库的 git 元数据，
    把 SDK 版本识别成 0.0.0-unknown，导致版本约束解析失败。
    """
    env = dict(os.environ)
    for key in ('GIT_DIR', 'GIT_INDEX_FILE', 'GIT_WORK_TREE'):
        env.pop(key, None)
    return env


def is_handwritten_dart(name):
    """判断是否为需要检查的手写 Dart 文件。

    参数 [name]：相对项目根的路径。
    返回：以 .dart 结尾且不是生成文件时为 True。
    """
    return name.endswith('.dart') and not name.endswith(GENERATED_SUFFIXES)


def changed_dart_files(root):
    """列出相对 HEAD 有改动的手写 Dart 文件（含新增未跟踪文件，不含已删除文件）。

    参数 [root]：项目根 Path。
    返回：相对路径列表，已排序去重；不是 git 仓库或 git 不可用时返回空列表。
    还没有任何提交的仓库只统计未跟踪文件。
    """
    commands = [
        ['git', 'diff', '--name-only', '--diff-filter=ACMR', 'HEAD', '--', '*.dart'],
        ['git', 'ls-files', '--others', '--exclude-standard', '--', '*.dart'],
    ]
    names = set()
    for command in commands:
        try:
            output = subprocess.run(command, cwd=root, env=clean_env(), capture_output=True,
                                    text=True, check=False).stdout
        except OSError:
            return []
        names.update(line.strip() for line in output.splitlines() if line.strip())
    return sorted(name for name in names if is_handwritten_dart(name) and (root / name).is_file())


def all_dart_files(root):
    """列出 lib/ 与 test/ 下全部手写 Dart 文件。

    参数 [root]：项目根 Path。
    返回：相对路径列表，已排序。
    """
    files = []
    for folder in ('lib', 'test'):
        base = root / folder
        if base.is_dir():
            files += [path.relative_to(root).as_posix() for path in base.rglob('*.dart')]
    return sorted(name for name in files if is_handwritten_dart(name))


def run(label, command, root):
    """执行一项检查并打印统一状态行。

    参数 [label]：检查名称；[command]：命令列表；[root]：工作目录。
    返回：0 通过；1 未通过；2 执行受阻（找不到可执行文件或无法启动）。
    """
    print(f'\n[{label}] {" ".join(command)}', flush=True)
    if not shutil.which(command[0]):
        print(f'[{label}] status=BLOCKED reason=missing-tool {command[0]}', flush=True)
        return 2
    try:
        result = subprocess.run(command, cwd=root, env=clean_env(), check=False)
    except OSError as error:
        print(f'[{label}] status=BLOCKED reason=launch-error: {error}', flush=True)
        return 2
    state = 'PASS' if result.returncode == 0 else 'CHECK_FAILED'
    print(f'[{label}] status={state} exit={result.returncode}', flush=True)
    return int(result.returncode != 0)


def main(argv=None):
    """命令行入口。

    参数 [argv]：命令行参数列表，None 时读取 sys.argv。
    返回：退出码，0 通过、1 未通过、2 执行受阻（受阻优先于未通过）。
    """
    parser = argparse.ArgumentParser(description='stack-flutter 默认代码检查')
    parser.add_argument('--root', default='.', help='项目根目录，默认当前目录')
    parser.add_argument('--all', action='store_true', help='格式检查 lib/ test/ 全部手写 Dart 文件')
    parser.add_argument('--no-test', action='store_true', help='跳过测试')
    parser.add_argument('tests', nargs='*', help='只运行这些测试文件或目录')
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not (root / 'pubspec.yaml').is_file():
        print(f'[flutter_check] status=BLOCKED reason=不是 Flutter/Dart 项目（缺少 pubspec.yaml）: {root}')
        return 2

    results = []
    files = all_dart_files(root) if args.all else changed_dart_files(root)
    if files:
        results.append(run('format', ['dart', 'format', '--output=none', '--set-exit-if-changed',
                                      *files], root))
    else:
        print('\n[format] status=SKIPPED reason=没有改动的手写 Dart 文件', flush=True)

    # 依赖已解析时加 --no-pub，避免每次检查都联网解析依赖。
    pub_flag = ['--no-pub'] if (root / '.dart_tool/package_config.json').is_file() else []
    results.append(run('analyze', ['flutter', 'analyze', *pub_flag], root))

    if args.no_test:
        print('\n[test] status=SKIPPED reason=--no-test（交付时须说明原因）', flush=True)
    elif (root / 'test').is_dir() or args.tests:
        results.append(run('test', ['flutter', 'test', *pub_flag, *args.tests], root))
    else:
        print('\n[test] status=SKIPPED reason=项目没有 test/ 目录', flush=True)

    code = 2 if 2 in results else int(any(results))
    print(f'\n[flutter_check] Result: {("PASS", "FAIL", "BLOCKED")[code]}', flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
