"""有界只读查找活动会话绑定，不创建数据库、不计算源码快照。"""
import json
import sqlite3

MAX_TASKS = 4096
MAX_TASK_BYTES = 1048576
MAX_TOTAL_BYTES = 16777216
ACTIVE_STATES = {"created", "implementing", "pending_verification", "running", "passed", "failed", "stale", "review_failed"}


def iter_tasks(root, database):
    """有界只读遍历当前项目根的已存任务，不创建数据库或反序列化超限行。"""
    if database.is_symlink():
        raise ValueError("DB_LOCATION：数据库不允许符号链接")
    if not database.is_file():
        return
    resolved_root = str(root.resolve())
    total = 0
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        # 先限行并只获取有界正文，超大任务不会先进入 Python 内存。
        rows = db.execute(
            "SELECT length(CAST(data AS BLOB)), CASE WHEN length(CAST(data AS BLOB)) <= ? THEN data ELSE NULL END FROM tasks LIMIT ?",
            (MAX_TASK_BYTES, MAX_TASKS + 1),
        )
        for index, (size, text) in enumerate(rows):
            total += size
            if index >= MAX_TASKS or size > MAX_TASK_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError("ENGINE_BINDING_LIMIT：会话查询超过资源上限，请显式设置 WORKFLOW_TASK_ID")
            task = json.loads(text)
            if task.get("root") == resolved_root:
                yield task


def list_tasks(root, database, active_only=False):
    """只读列出当前项目根下的任务摘要；缺库返回空列表，不隐式创建库。"""
    items = []
    for task in iter_tasks(root, database):
        if active_only and task.get("state") not in ACTIVE_STATES:
            continue
        active = next((r for r in task.get("rounds", []) if r.get("id") == task.get("current_round")), {})
        items.append({
            "id": task.get("id"),
            "version": task.get("version"),
            "protocol_version": task.get("protocol_version"),
            "tier": task.get("tier"),
            "state": task.get("state"),
            "goal": task.get("goal"),
            "current_round": task.get("current_round"),
            "executor": active.get("executor"),
            "session_id": active.get("session_id"),
            "missing": task.get("missing", []),
        })
    items.sort(key=lambda item: str(item.get("id") or ""))
    return items


def lookup(root, session_id, database):
    """旧终态不占会话；超预算拒绝并要求显式任务，避免无界扫描与反序列化。"""
    if not session_id or not database.is_file() or database.is_symlink():
        raise ValueError(
            "ENGINE_TASK_UNBOUND：当前项目尚无可用任务库；新任务请由 Agent 执行 CLI prepare（--executor agent --session 当前会话ID --request-tier）建档并绑定，不要让用户手动绑定"
        )
    matches = []
    for task in iter_tasks(root, database):
        if task.get("protocol_version") != 2 or task.get("state") not in ACTIVE_STATES:
            continue
        active = next((r for r in task.get("rounds", []) if r.get("id") == task.get("current_round")), {})
        if active.get("session_id") == session_id and active.get("executor"):
            matches.append(task["id"])
            if len(matches) > 1:
                break
    if len(matches) != 1:
        raise ValueError(
            "ENGINE_TASK_UNBOUND：当前会话未绑定唯一活动任务；请由 Agent 先执行 CLI list --active 查已有任务（存在则 bind-executor --session 当前会话ID，不存在则 prepare --request-tier 新建），多任务冲突时显式指定 WORKFLOW_TASK_ID，不要让用户外部手动绑定"
        )
    return matches[0]
