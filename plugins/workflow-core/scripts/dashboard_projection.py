"""看板专属只读投影：不实例化引擎，不核算文件哈希。"""


def records(value):
    """异常形状不推断为成功，展示层只消费字典记录。"""
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def business_projection(task, current, phase):
    """仅解释保存的证据，不执行检查或重新核算文件哈希。"""
    evidence = records(current.get("evidence"))
    attempts = records(current.get("attempts"))
    missing = current.get("missing", task.get("missing", []))
    missing = missing if isinstance(missing, list) else []
    labels = {"goal": "任务目标未明确", "scope": "任务范围未明确", "source": "需求来源未明确", "acceptance": "验收标准未明确", "dependencies": "依赖尚未就绪", "tier_confirmation": "档位尚未确认", "approval": "方案尚未批准", "proposal": "方案信息不完整", "steps": "实施步骤尚未就绪", "executor_binding": "执行者尚未绑定", "baseline": "基线尚未完成有效读取", "verify_config": "验证配置尚未就绪", "snapshot": "证据快照已失效", "plan_confirmation": "检查计划尚未确认", "checks": "当前验证尚未通过", "review": "当前双轴评审尚未通过"}
    blocking, upcoming = [], []
    for key in missing:
        if key == "checks" and phase in {"planning", "implementation"}:
            upcoming.append("后续验证尚未完成")
        elif key == "review" and phase in {"planning", "implementation", "verification"}:
            upcoming.append("后续双轴评审尚未完成")
        else:
            blocking.append(labels.get(str(key), "未知就绪条件：" + str(key)))
    for entry in current.get("blocked", []) if isinstance(current.get("blocked"), list) else []:
        blocking.append(str(entry.get("message") or entry.get("reason") or "当前阻塞条件待确认") if isinstance(entry, dict) else str(entry))
    def valid(item):
        return item.get("valid") is not False and (not current.get("control_digest") or item.get("control_digest") == current.get("control_digest"))
    baseline = []
    for path in task.get("baseline", []) if isinstance(task.get("baseline"), list) else []:
        receipts = [e for e in evidence if e.get("kind") == "baseline" and isinstance(e.get("data"), dict) and e["data"].get("path") == path]
        latest = receipts[-1] if receipts else None
        data = latest.get("data", {}) if latest else {}
        # 失效优先于 complete，旧会话的完整读取不能冒充当前基线。
        bound = all(data.get(k) == current.get(k) for k in ("executor", "session_id", "binding_version"))
        status = "未读" if not latest else "已失效" if not valid(latest) or not bound else "已读" if data.get("complete") is True else "未读"
        baseline.append({"path": path, "status": status})
    verification = []
    for a in attempts:
        if a.get("stage") != "verification":
            continue
        checks = []
        for result in records(a.get("results")):
            checks.append({key: result.get(key) for key in ("id", "exit_code", "reason", "stdout", "stderr", "truncated")})
        verification.append({"status": a.get("status", "unknown"), "failure": a.get("failure"), "checks": checks})
    review = []
    reports = [e for e in evidence if e.get("kind") == "review"]
    report = reports[-1] if reports else {}
    axes = report.get("data", {}).get("axes", {}) if isinstance(report.get("data"), dict) else {}
    for axis, title in (("spec", "需求符合性"), ("standards", "工程规范")):
        value = axes.get(axis, {}) if isinstance(axes, dict) else {}
        value = value if isinstance(value, dict) else {}
        findings = records(value.get("findings"))
        required = current.get("required_findings", {})
        outstanding = required.get(axis, {}) if isinstance(required, dict) else {}
        conclusion = value.get("conclusion", "unknown") if valid(report) else "invalidated"
        if conclusion == "pass" and (any(f.get("required") is True and f.get("resolved") is not True for f in findings) or isinstance(outstanding, dict) and any(v is not True for v in outstanding.values())):
            conclusion = "fail"
        review.append({"title": title, "conclusion": conclusion, "findings": [{"message": f.get("message"), "required": f.get("required"), "resolved": f.get("resolved")} for f in findings], "unresolved": sum(v is not True for v in outstanding.values()) if isinstance(outstanding, dict) else 0})
    invalidations = []
    for e in evidence:
        if not valid(e):
            summary = {"baseline": "基线读取", "review": "双轴评审", "verification": "验证", "approval": "方案批准", "tier_confirmation": "档位确认"}.get(e.get("kind"), "证据") + "已失效：" + str(e.get("reason") or e.get("invalidated_reason") or "版本或绑定已变化，需重新取得证据")
            if summary not in invalidations:
                invalidations.append(summary)
    approvals = [{"title": {"tier_confirmation": "档位确认", "proposal_approval": "方案批准", "approval": "方案批准"}[e["kind"]], "status": "已记录（非交付）" if valid(e) else "已失效"} for e in evidence if e.get("kind") in {"tier_confirmation", "proposal_approval", "approval"}]
    return {"blocking": list(dict.fromkeys(blocking)), "upcoming": list(dict.fromkeys(upcoming))}, {"baseline": baseline, "approvals": approvals, "verification": verification, "review": review, "invalidations": invalidations, "rounds": [{"number": i + 1, "state": r.get("state", "unknown"), "phase": r.get("phase", "unknown"), "current": r.get("id") == current.get("id")} for i, r in enumerate(records(task.get("rounds")))]}


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
    todos = records(current.get("todos"))
    attempts = records(current.get("attempts"))
    evidence = records(current.get("evidence"))
    activity = task.get("activity", {})
    if not isinstance(activity, dict) or activity.get("round_id") != current.get("id"):
        activity = {}
    descriptions = {"created": "任务登记，等待就绪门槛", "implementing": "正在实施当前步骤", "pending_verification": "实施完成待真实验证", "running": "验证执行中", "passed": "验证记录通过，等待双轴评审", "failed": "验证失败，查看尝试与诊断", "stale": "证据失效，需重新验证", "review_failed": "双轴评审未通过", "review_passed": "Agent 评审通过并结束，待人工验收（不是交付）", "cancelled": "本轮已取消"}
    readiness, business = business_projection(task, current, phase)
    return {"readiness": readiness, "business": business, "id": task["id"], "title": previous.get("title", task.get("goal") or task["id"]),
        "source": "engine:tasks/" + str(task["id"]), "protocol_version": task.get("protocol_version"),
        "state": state, "tier": task.get("tier", "unknown"), "phase": phase,
        "summary": descriptions.get(state, "状态未知") if modern else "历史未核验：旧记录不构成当前通过证据",
        "freshness": "not_checked", "delivered": False, "current_round": task.get("current_round"),
        "progress": {"done": sum(t.get("status") == "done" for t in todos), "total": len(todos),
                     "current": next((t.get("title", t.get("id")) for t in todos if t.get("status") != "done"), None)},
        "flow": [{"id": p, "current": p == phase} for p in ("planning", "implementation", "verification", "review", "done")],
        "missing": current.get("missing", task.get("missing", [])), "blocked": current.get("blocked", []),
        "pending": previous.get("pending", []), "failures": [a for a in attempts if a.get("stage") == "verification" and a.get("status") in {"failed", "error", "invalidated"}],
        "updated_at": activity.get("at", task.get("updated_at")), "activity_status": "unknown", "activity": activity,
        "executor": current.get("executor"), "session_id": current.get("session_id"),
        "details": {"goal": task.get("goal"), "scope": task.get("scope"), "baseline": task.get("baseline", []), "baseline_receipts": [e for e in evidence if e.get("kind") == "baseline"],
            "approvals": [e for e in evidence if e.get("kind") in {"tier_confirmation", "proposal_approval", "approval"}],
            "binding_version": current.get("binding_version"), "control_digest": current.get("control_digest"),
            "todos": todos, "attempts": attempts, "evidence": evidence,
            "review": [e for e in evidence if e.get("kind") == "review"],
            "required_findings": current.get("required_findings", []), "rounds": rounds,
            "proposal": task.get("proposal"), "plan": task.get("plan"), "acceptance": task.get("acceptance", []),
            "human_acceptance": task.get("human_acceptance"), "handoff": current.get("handoff", task.get("handoff"))}}
