"""有界只读查找活动会话绑定，不创建数据库、不计算源码快照。"""
import json
import sqlite3

MAX_TASKS = 4096
MAX_TASK_BYTES = 1048576
MAX_TOTAL_BYTES = 16777216
ACTIVE_STATES = {"created", "implementing", "pending_verification", "running", "passed", "failed", "stale", "review_failed"}


def lookup(root, session_id, database):
    """旧终态不占会话；超预算拒绝并要求显式任务，避免无界扫描与反序列化。"""
    if not session_id or not database.is_file() or database.is_symlink():
        raise ValueError("ENGINE_TASK_UNBOUND：请先 CLI create / bind-executor")
    matches = []
    total = 0
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        # 先限行并只获取有界正文，超大任务不会先进入 Python 内存。
        rows = db.execute("SELECT length(CAST(data AS BLOB)), CASE WHEN length(CAST(data AS BLOB)) <= ? THEN data ELSE NULL END FROM tasks LIMIT ?", (MAX_TASK_BYTES, MAX_TASKS + 1))
        for index, (size, text) in enumerate(rows):
            total += size
            if index >= MAX_TASKS or size > MAX_TASK_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError("ENGINE_BINDING_LIMIT：会话查询超过资源上限，请显式设置 WORKFLOW_TASK_ID")
            task = json.loads(text)
            if task.get("state") not in ACTIVE_STATES:
                continue
            active = next((r for r in task.get("rounds", []) if r.get("id") == task.get("current_round")), {})
            if (task.get("protocol_version") == 2 and task.get("root") == str(root.resolve()) and
                    active.get("session_id") == session_id and active.get("executor")):
                matches.append(task["id"])
                if len(matches) > 1:
                    break
    if len(matches) != 1:
        raise ValueError("ENGINE_TASK_UNBOUND：会话未绑定或绑定多个活动任务，请显式选择 WORKFLOW_TASK_ID")
    return matches[0]
