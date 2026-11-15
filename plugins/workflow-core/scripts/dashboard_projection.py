"""看板专属只读投影：不实例化引擎，不核算文件哈希。"""
import json
import os
import stat
from pathlib import Path


def project_task(task, previous):
    """current_round 是唯一权威；历史通过记录不代表当前证据有效。"""
    rounds = task.get("rounds", [])
    rounds = rounds if isinstance(rounds, list) else []
    matches = [r for r in rounds if isinstance(r, dict) and r.get("id") == task.get("current_round")]
    current = matches[0] if len(matches) == 1 and task.get("current_round") else {}
    modern = task.get("protocol_version") == 2
    state = current.get("state", "unknown") if modern else "unknown"
    phase = current.get("phase", "unknown") if modern else "unknown"
    allowed = {"created", "implementing", "pending_verification", "running", "passed", "failed", "stale", "review_failed", "review_passed", "cancelled"}
    state = state if state in allowed else "unknown"
    todos = [t for t in current.get("todos", []) if isinstance(t, dict)]
    attempts = [a for a in current.get("attempts", []) if isinstance(a, dict)]
    evidence = [e for e in current.get("evidence", []) if isinstance(e, dict)]
    activity = task.get("activity", {})
    if not isinstance(activity, dict) or activity.get("round_id") != current.get("id"):
        activity = {}
    descriptions = {"created": "任务登记，等待就绪门槛", "implementing": "正在实施当前步骤", "pending_verification": "实施完成待真实验证", "running": "验证执行中", "passed": "验证记录通过，等待双轴评审", "failed": "验证失败，查看尝试与诊断", "stale": "证据失效，需重新验证", "review_failed": "双轴评审未通过", "review_passed": "Agent 评审通过并结束，待人工验收（不是交付）", "cancelled": "本轮已取消"}
    return {"id": task["id"], "title": previous.get("title", task.get("goal") or task["id"]),
        "source": "engine:tasks/" + str(task["id"]), "protocol_version": task.get("protocol_version"),
        "state": state, "tier": task.get("tier", "unknown"), "phase": phase,
        "summary": descriptions.get(state, "状态未知") if modern else "历史未核验：旧记录不构成当前通过证据",
        "freshness": "not_checked", "delivered": False, "current_round": task.get("current_round"),
        "progress": {"done": sum(t.get("status") == "done" for t in todos), "total": len(todos),
                     "current": next((t.get("title", t.get("id")) for t in todos if t.get("status") != "done"), None)},
        "flow": [{"id": p, "current": p == phase} for p in ("planning", "implementation", "verification", "review", "done")],
        "missing": current.get("missing", task.get("missing", [])), "blocked": current.get("blocked", []),
        "pending": previous.get("pending", []), "failures": [a for a in attempts if a.get("status") in {"failed", "error", "invalidated"}],
        "updated_at": activity.get("at", task.get("updated_at")), "activity_status": "unknown", "activity": activity,
        "executor": current.get("executor"), "session_id": current.get("session_id"),
        "details": {"baseline": task.get("baseline", []), "baseline_receipts": [e for e in evidence if e.get("kind") == "baseline"],
            "approvals": [e for e in evidence if e.get("kind") in {"tier_confirmation", "proposal_approval", "approval"}],
            "binding_version": current.get("binding_version"), "control_digest": current.get("control_digest"),
            "todos": todos, "attempts": attempts, "evidence": evidence,
            "review": [e for e in evidence if e.get("kind") == "review"],
            "required_findings": current.get("required_findings", []), "rounds": rounds,
            "proposal": task.get("proposal"), "plan": task.get("plan"), "acceptance": task.get("acceptance", []),
            "human_acceptance": task.get("human_acceptance"), "handoff": current.get("handoff", task.get("handoff"))}}


def read_trace(root, tasks, task_id, open_directory):
    """cwd 精确匹配项目；任务、轮次、会话缺一不归属，读取总量固定有界。"""
    from trace_hook import trace_dir
    output = {"events": [], "unassigned": [], "limited": False}
    folder = Path(trace_dir()) / "events"
    budget = 262144
    mapping = {t["id"]: t for t in tasks if t.get("protocol_version") == 2}
    try:
        fd = open_directory(folder)
        os.close(fd)
        with os.scandir(folder) as entries:
            for index, entry in enumerate(entries):
                if index >= 32 or budget <= 0:
                    output["limited"] = True
                    break
                if not entry.name.endswith(".jsonl") or not entry.is_file(follow_symlinks=False):
                    continue
                parent = open_directory(folder)
                try:
                    fd = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    try:
                        if not stat.S_ISREG(os.fstat(fd).st_mode):
                            continue
                        with os.fdopen(fd, "rb", closefd=False) as stream:
                            raw = stream.read(budget + 1)
                        used = min(len(raw), budget)
                        if len(raw) > budget:
                            output["limited"] = True
                            raw = raw[:budget]
                            raw = raw.rsplit(b"\n", 1)[0] if b"\n" in raw else b""
                        budget -= used
                    finally:
                        os.close(fd)
                finally:
                    os.close(parent)
                for line in raw.splitlines():
                    if len(output["events"]) + len(output["unassigned"]) >= 200:
                        output["limited"] = True
                        return output
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeError, RecursionError):
                        continue
                    if not isinstance(event, dict) or event.get("cwd") != str(root):
                        continue
                    identity = event.get("task_id")
                    if identity is not None and not isinstance(identity, str):
                        continue
                    if task_id is not None and identity not in (None, task_id):
                        continue
                    task = mapping.get(identity)
                    bound = bool(task and task.get("current_round") and task.get("session_id") and event.get("round_id") == task["current_round"] and event.get("session_id") == task["session_id"])
                    summary = {k: event.get(k) for k in ("ts", "event", "tool_name", "task_id", "round_id", "session_id")}
                    summary["binding"] = "bound" if bound else "unassigned"
                    output["events" if bound else "unassigned"].append(summary)
    except (OSError, ValueError):
        pass
    return output
