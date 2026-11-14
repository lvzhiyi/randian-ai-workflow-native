"""计划只允许显式命令与完整覆盖；确认仅信任本机同用户人工入口。"""
import math
from pathlib import PurePosixPath
from .model import EngineError, digest

POLICY_VERSION = 1
TIERS = {"light", "standard", "full"}


def validate_plan(plan, acceptance):
    def invalid():
        raise EngineError("PLAN_INVALID", "计划不符合严格 schema 或检查覆盖不完整")
    if not isinstance(acceptance, list) or not acceptance or any(not isinstance(a, str) or not a.strip() for a in acceptance) or len(set(acceptance)) != len(acceptance):
        invalid()
    if not isinstance(plan, dict) or set(plan) != {"version", "checks"} or type(plan["version"]) is not int or plan["version"] != 1:
        invalid()
    checks = plan["checks"]
    if not isinstance(checks, list) or not checks:
        invalid()
    ids, covered, accepted = set(), set(), set()
    for c in checks:
        if not isinstance(c, dict) or set(c) != {"id", "argv", "cwd", "timeout", "covers", "acceptance"}:
            invalid()
        if not isinstance(c["id"], str) or not c["id"].strip() or c["id"] in ids:
            invalid()
        ids.add(c["id"])
        if not isinstance(c["argv"], list) or not c["argv"] or any(not isinstance(a, str) or "\x00" in a for a in c["argv"]) or not c["argv"][0]:
            invalid()
        cwd = c["cwd"]
        if not isinstance(cwd, str) or not cwd or "\x00" in cwd or "\\" in cwd or PurePosixPath(cwd).is_absolute() or ".." in PurePosixPath(cwd).parts:
            invalid()
        timeout = c["timeout"]
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
            invalid()
        for name, allowed in (("covers", {"format", "analyze", "test"}), ("acceptance", set(acceptance))):
            values = c[name]
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values) or not set(values) <= allowed:
                invalid()
        if not c["covers"]:
            invalid()
        covered.update(c["covers"])
        accepted.update(c["acceptance"])
    if covered != {"format", "analyze", "test"} or accepted != set(acceptance):
        invalid()
    return digest(plan)


def missing(task):
    out = []
    if task.get("confirmed_digest") != task["plan_digest"]:
        out.append("plan_confirmation")
    if task["tier"] == "full":
        out.append("approval")
    if task["tier"] != "light":
        out.append("review")
    if task["state"] == "stale":
        out.append("snapshot")
    if task["state"] not in ("passed", "completed"):
        out.append("checks")
    return out
