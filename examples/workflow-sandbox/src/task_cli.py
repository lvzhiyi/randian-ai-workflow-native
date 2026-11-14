"""显式文件路径的待办命令入口；运行期仅依赖标准库。"""
import argparse
import json
import sys

import task_domain
import task_store


class ArgumentParser(argparse.ArgumentParser):
    """将参数错误归为业务输入错误，保留帮助的成功退出行为。"""

    def error(self, message):
        raise task_domain.DomainError("命令参数不合法，请使用 --help 查看用法")


def parse_arguments(argv):
    parser = ArgumentParser(description="本地待办清单（仅支持单写进程）")
    parser.add_argument("--file", required=True, help="数据文件路径，父目录必须存在")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("add").add_argument("title")
    commands.add_parser("list").add_argument(
        "--status", default="all", choices=("all", "pending", "completed"))
    for name in ("complete", "undo"):
        commands.add_parser(name).add_argument("identifier", type=int)
    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_arguments(argv)
        data = task_store.load(args.file)
        if args.command == "list":
            result = task_domain.list_tasks(data, args.status)
        else:
            if args.command == "add":
                result = task_domain.add(data, args.title)
            else:
                status = "completed" if args.command == "complete" else "pending"
                result = task_domain.set_status(data, args.identifier, status)
            task_store.save(args.file, data)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except task_domain.DomainError as error:
        print("输入错误: " + str(error), file=sys.stderr)
        return 1
    except task_store.StoreError as error:
        print("存储错误: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
