#!/usr/bin/env python3
"""仓库自检入口；每组测试须有目标，缺少格式工具明确受阻。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lint", action="store_true")
    args = parser.parse_args()
    failures = []
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    groups = ("plugins/workflow-core/scripts", "plugins/stack-flutter/scripts",
              "plugins/workflow-core/scripts/tests_engine", "examples/workflow-sandbox/tests")
    for group in groups:
        if not list((ROOT / group).glob("test_*.py")):
            failures.append("EMPTY_TEST_TARGET:" + group)
            continue
        code = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", group],
                              cwd=ROOT, env=env).returncode
        if code:
            failures.append("TEST_FAILED:" + group)
    for path in ROOT.glob("plugins/**/plugin.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            failures.append("INVALID_JSON:" + str(path.relative_to(ROOT)))
    for path in ROOT.glob(".claude-plugin/*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            failures.append("INVALID_JSON:" + str(path.relative_to(ROOT)))
    if subprocess.run(["git", "diff", "--check"], cwd=ROOT).returncode:
        failures.append("WHITESPACE")
    if args.lint:
        if not shutil.which("ruff"):
            failures.append("BLOCKED:missing-tool ruff")
        else:
            targets = ["plugins/workflow-core/scripts/workflow_engine", "plugins/workflow-core/scripts/tests_engine",
                       "plugins/workflow-core/scripts/workflow_engine_cli.py", "plugins/workflow-core/scripts/engine_codex.py",
                       "examples/workflow-sandbox/src", "examples/workflow-sandbox/tests", "scripts/check.py"]
            for command in (["ruff", "format", "--check", *targets], ["ruff", "check", *targets]):
                if subprocess.run(command, cwd=ROOT).returncode:
                    failures.append("LINT_FAILED")
    print(json.dumps({"ok": not failures, "failures": failures}, ensure_ascii=False))
    return 2 if any(item.startswith("BLOCKED") for item in failures) else int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
