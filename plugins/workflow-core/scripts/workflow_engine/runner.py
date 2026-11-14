"""检查输出直接丢弃，避免无界缓存；超时终止整个进程组。"""
import os
import signal
import subprocess
from .model import EngineError


def run_checks(root, plan):
    results = []
    for check in plan["checks"]:
        cwd = root / check["cwd"]
        current = root
        for part in cwd.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                raise EngineError("SYMLINK", "检查目录不能包含符号链接")
        if not cwd.resolve().is_relative_to(root):
            raise EngineError("PATH_ESCAPE", "检查目录越界")
        try:
            proc = subprocess.Popen(check["argv"], cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False, start_new_session=True)
        except OSError:
            results.append({"id": check["id"], "exit_code": None, "reason": "spawn_error"})
            continue
        reason = "exit"
        try:
            code = proc.wait(timeout=check["timeout"])
        except subprocess.TimeoutExpired:
            reason = "timeout"
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            code = proc.wait()
        finally:
            # 主进程退出后也回收其遗留子进程，避免后台写入污染证据。
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        results.append({"id": check["id"], "exit_code": code, "reason": reason})
    return results
