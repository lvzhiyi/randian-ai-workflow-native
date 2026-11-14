"""临时副本上的钩子协议探针；不冒充真实 Codex 会话或批准记录。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT.parents[1] / "plugins/workflow-core/scripts/workflow_gate.py"


def main():
    observations = {}
    with tempfile.TemporaryDirectory() as temporary:
        home = Path(temporary)
        project = home / "sandbox"
        shutil.copytree(ROOT, project, ignore=shutil.ignore_patterns("__pycache__"))
        (project / ".git").mkdir()
        env = {**os.environ, "WORKFLOW_GATE_DIR": str(home / "gate"),
               "WORKFLOW_HOME": str(home / "home"), "WORKFLOW_HOST": "codex",
               "PYTHONDONTWRITEBYTECODE": "1"}

        def hook(session, name, **fields):
            event = {"session_id": session, "cwd": str(project),
                     "hook_event_name": name, **fields}
            result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event),
                                    text=True, capture_output=True, env=env, timeout=20)
            if result.returncode or result.stderr:
                raise RuntimeError("钩子探针异常: " + result.stderr)
            return json.loads(result.stdout) if result.stdout.strip() else None

        def edit(session):
            return hook(session, "PostToolUse", tool_name="apply_patch", tool_input={
                "command": "*** Update File: src/task_domain.py"})

        edit("s04")
        observations["S04"] = {"missing_checks_stop": hook("s04", "Stop"),
                                "second_stop": hook("s04", "Stop")}
        injected = project / "tests/test_injected_failure.py"
        injected.write_text("import unittest\nclass Injected(unittest.TestCase):\n    def test_failure(self):\n        self.fail('合成失败')\n", encoding="utf-8")
        failed = subprocess.run([sys.executable, "scripts/check.py", "tests"], cwd=project,
                                env=env, text=True, capture_output=True, timeout=30)
        edit("s05")
        hook("s05", "PostToolUse", tool_name="Bash", tool_input={
            "command": "python3 scripts/check.py tests"},
            tool_response={"exit_code": failed.returncode, "output": failed.stderr})
        observations["S05"] = {"actual_test_exit": failed.returncode,
                                "failure_file_preserved": injected.exists(),
                                "stop": hook("s05", "Stop")}
        injected.unlink()
        passed = subprocess.run([sys.executable, "scripts/check.py", "tests"], cwd=project,
                                env=env, text=True, capture_output=True, timeout=30)
        source = project / "src/task_domain.py"
        source.write_text(source.read_text(encoding="utf-8") + "\n# 合成改动：旧测试证据不覆盖此快照。\n", encoding="utf-8")
        edit("s06")
        observations["S06"] = {"previous_test_exit": passed.returncode,
                                "retested_after_change": False, "stop": hook("s06", "Stop")}
        edit("s07")
        hook("s07", "PostToolUse", tool_name="Skill", tool_input={"skill": "workflow-core:deliver"})
        observations["S07"] = {"only_skill_loaded_stop": hook("s07", "Stop"),
                                "checks_or_delivery_executed": False}
    print(json.dumps({"mode": "synthetic-hook-input", "real_codex_accepted": False,
                      "approval_fabricated": False, "observations": observations},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
