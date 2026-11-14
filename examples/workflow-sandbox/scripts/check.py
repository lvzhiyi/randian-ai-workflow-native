"""统一检查入口：0 通过、1 失败、2 缺少必要工具而受阻。"""
import argparse
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def run_tests(directory):
    """先统计测试再运行，避免空目录被 unittest 误报为成功。"""
    suite = unittest.TestLoader().discover(str(directory))
    count = suite.countTestCases()
    if count == 0:
        print("FAIL tests: 未发现测试", file=sys.stderr)
        return 1
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    print(stream.getvalue(), end="", file=sys.stderr)
    return 0 if result.wasSuccessful() else 1


def run_ruff(kind):
    if importlib.util.find_spec("ruff") is None:
        print("BLOCKED " + kind + ": 未安装 Ruff；本脚本不会安装工具", file=sys.stderr)
        return 2
    arguments = ["format", "--check"] if kind == "format" else ["check"]
    result = subprocess.run([sys.executable, "-m", "ruff"] + arguments +
                            ["src", "tests", "scripts"], cwd=ROOT)
    # 工具已存在时，配置或运行错误属于失败，不能冒充缺工具受阻。
    return 0 if result.returncode == 0 else 1


def run_check(kind):
    if kind == "tests":
        return run_tests(ROOT / "tests")
    if kind in ("format", "static"):
        return run_ruff(kind)
    script = REPO / "plugins/workflow-core/scripts/check_docs.py"
    if not script.is_file():
        print("BLOCKED docs: 父仓库文档检查器缺失", file=sys.stderr)
        return 2
    return subprocess.run([sys.executable, str(script), "--root", str(ROOT),
                           "--check-config"], cwd=ROOT).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("all", "docs", "format", "static", "tests"),
                        nargs="?", default="all")
    kind = parser.parse_args(argv).kind
    kinds = ("docs", "format", "static", "tests") if kind == "all" else (kind,)
    results = [run_check(item) for item in kinds]
    # 真失败优先于缺工具；仍执行所有检查，避免前一项掩盖后续证据。
    code = 1 if any(result not in (0, 2) for result in results) else (2 if 2 in results else 0)
    print(("PASS", "FAIL", "BLOCKED")[code] + " " + kind)
    return code


if __name__ == "__main__":
    sys.exit(main())
