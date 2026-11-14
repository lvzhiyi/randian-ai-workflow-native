"""状态机入口：命令不在数据库事务内运行，结果必须匹配前后快照。"""
import copy
import os
from pathlib import Path
import threading
import uuid
from .model import EngineError, canonical, digest
from .policy import TIERS, missing, validate_plan
from .runner import run_checks
from .snapshot import capture
from .store import Store

_ACTIVE = set()
_ACTIVE_LOCK = threading.Lock()


class Engine:
    def __init__(self, root: Path, db: Path):
        self.root = Path(root).resolve()
        self.db = Path(db).resolve()
        if self.db == self.root or self.root in self.db.parents:
            raise EngineError("DB_LOCATION", "数据库必须放在 root 外部")
        if not self.root.is_dir():
            raise EngineError("ROOT_INVALID", "root 必须是目录")
        self.store = Store(self.db)

    def _view(self, task):
        task["missing"] = missing(task)
        return task

    def _version(self, task, expected):
        if type(expected) is not int or task["version"] != expected:
            raise EngineError("VERSION_CONFLICT", "任务版本已变化")

    def _refresh(self, db, task):
        if task["state"] in ("passed", "completed"):
            try:
                changed = capture(self.root, task["plan_digest"]) != task["snapshot"]
            except EngineError:
                changed = True
            if changed:
                task.update(state="stale", phase="verification", version=task["version"] + 1)
                self._view(task)
                self.store.save(db, task, "invalidate")
        return self._view(task)

    def create(self, task_id, tier, acceptance, plan, request_id):
        payload = {"action": "create", "id": task_id, "tier": tier, "acceptance": acceptance, "plan": plan, "root": str(self.root)}
        with self.store.transaction() as db:
            previous = self.store.replay(db, request_id, payload)
            if previous is not None:
                return previous
            if not isinstance(task_id, str) or not task_id.strip() or not isinstance(tier, str) or tier not in TIERS:
                raise EngineError("INPUT_INVALID", "任务标识或档位无效")
            plan_hash = validate_plan(plan, acceptance)
            if db.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
                raise EngineError("TASK_EXISTS", "任务已存在")
            task = self._view({"id": task_id, "tier": tier, "phase": "planning", "state": "created", "version": 1, "root": str(self.root), "acceptance": copy.deepcopy(acceptance), "plan": copy.deepcopy(plan), "plan_digest": plan_hash, "confirmed_digest": None, "snapshot": capture(self.root, plan_hash), "results": []})
            self.store.save(db, task, "create", request_id, payload)
            return task

    def status(self, task_id):
        with self.store.transaction() as db:
            task = self._load(db, task_id)
            return self._refresh(db, task)

    def _load(self, db, task_id):
        task = self.store.load(db, task_id)
        if task["root"] != str(self.root):
            raise EngineError("ROOT_MISMATCH", "任务绑定其他 root")
        # 计划被外部修改时旧批准不可复用；不提供修改计划或任意通过接口。
        if validate_plan(task["plan"], task["acceptance"]) != task["plan_digest"]:
            raise EngineError("PLAN_DIGEST", "存储计划摘要不匹配")
        return task

    def _mutate(self, action, task_id, expected_version, request_id, extra=None):
        payload = {"action": action, "id": task_id, "version": expected_version, "extra": extra, "root": str(self.root)}
        with self.store.transaction() as db:
            previous = self.store.replay(db, request_id, payload)
            if previous is not None:
                # 重放不重复推进，但完成结论必须反映当前快照而非历史响应。
                if action == "complete":
                    current = self._refresh(db, self._load(db, task_id))
                    if current["state"] != "completed" or current["missing"]:
                        return {"_error": "MISSING", "task": current}
                    return current
                return previous
            task = self._load(db, task_id)
            self._version(task, expected_version)
            if task["state"] == "running":
                raise EngineError("ACTIVE_OPERATION", "执行中任务仅允许明确恢复孤立操作")
            if action == "confirm_plan":
                if extra != task["plan_digest"]:
                    raise EngineError("PLAN_DIGEST", "批准摘要不匹配")
                if task["state"] != "created":
                    raise EngineError("STATE_INVALID", "仅新建任务可以确认计划")
                task["confirmed_digest"] = extra
            elif action == "start":
                if task["confirmed_digest"] != task["plan_digest"]:
                    raise EngineError("PLAN_UNCONFIRMED", "需要本机人工入口确认计划摘要")
                if task["tier"] == "full":
                    raise EngineError("APPROVAL_REQUIRED", "完整档缺少可信人工批准")
                if task["state"] != "created":
                    raise EngineError("STATE_INVALID", "任务不可开始")
                task.update(state="ready", phase="verification")
            elif action == "complete":
                task = self._refresh(db, task)
                if task["missing"]:
                    # 失效必须持久化，不能随拒绝完成的异常回滚。
                    return {"_error": "MISSING", "task": task}
                task.update(state="completed", phase="done")
            elif action == "cancel":
                task.update(state="cancelled", phase="done")
            task["version"] += 1
            self._view(task)
            self.store.save(db, task, action, request_id, payload)
            return task

    def confirm_plan(self, task_id, expected_version, request_id, digest):
        return self._mutate("confirm_plan", task_id, expected_version, request_id, digest)

    def start(self, task_id, expected_version, request_id):
        return self._mutate("start", task_id, expected_version, request_id)

    def complete(self, task_id, expected_version, request_id):
        result = self._mutate("complete", task_id, expected_version, request_id)
        if "_error" in result:
            raise EngineError("MISSING", "完成条件缺失：" + ", ".join(result["task"]["missing"]))
        return result

    def cancel(self, task_id, expected_version, request_id):
        return self._mutate("cancel", task_id, expected_version, request_id)

    def run(self, task_id, expected_version, request_id):
        payload = {"action": "run", "id": task_id, "version": expected_version, "root": str(self.root)}
        token = uuid.uuid4().hex
        with _ACTIVE_LOCK:
            _ACTIVE.add(token)
        try:
            with self.store.transaction() as db:
                previous = self.store.replay(db, request_id, payload)
                if previous is not None:
                    return previous
                task = self._load(db, task_id)
                self._version(task, expected_version)
                if task["state"] not in ("ready", "failed", "stale"):
                    raise EngineError("STATE_INVALID", "任务尚未开始或不可执行")
                if task["confirmed_digest"] != task["plan_digest"]:
                    raise EngineError("PLAN_UNCONFIRMED", "计划未确认")
                before = capture(self.root, task["plan_digest"])
                task.update(state="running", phase="verification", version=task["version"] + 1, operation={"token": token, "pid": os.getpid(), "request_id": request_id, "payload": payload})
                self._view(task)
                self.store.save(db, task, "run_started", request_id, payload)
            # 运行期间不持有 SQLite 锁；幂等重放返回已登记的 running 响应。
            results = []
            failure = None
            try:
                results = run_checks(self.root, task["plan"])
                after = capture(self.root, task["plan_digest"])
            except (EngineError, OSError) as exc:
                after = None
                failure = getattr(exc, "code", "RUN_ERROR")
            with self.store.transaction() as db:
                latest = self._load(db, task_id)
                if latest.get("operation", {}).get("token") != token:
                    raise EngineError("OPERATION_CONFLICT", "执行租约已变化")
                state = "stale" if before != after else "passed" if all(r["exit_code"] == 0 and r["reason"] == "exit" for r in results) else "failed"
                latest.update(state=state, snapshot=before, results=results, version=latest["version"] + 1)
                latest.pop("operation", None)
                if failure:
                    latest["failure"] = failure
                self._view(latest)
                self.store.save(db, latest, "run_finished")
                db.execute("UPDATE requests SET response=? WHERE key=?", (canonical(latest), request_id))
                return latest
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE.discard(token)

    def recover(self, task_id, expected_version, request_id):
        payload = {"action": "recover", "id": task_id, "version": expected_version, "root": str(self.root)}
        with self.store.transaction() as db:
            previous = self.store.replay(db, request_id, payload)
            if previous is not None:
                return previous
            task = self._load(db, task_id)
            self._version(task, expected_version)
            operation = task.get("operation")
            if task["state"] != "running" or not operation:
                raise EngineError("STATE_INVALID", "仅恢复孤立 running 记录")
            with _ACTIVE_LOCK:
                active = operation["token"] in _ACTIVE
            try:
                os.kill(operation["pid"], 0)
                alive = True
            except ProcessLookupError:
                alive = False
            except PermissionError:
                alive = True
            if active or alive:
                raise EngineError("ACTIVE_OPERATION", "所有者进程仍活跃，不能恢复或终止")
            task.update(state="failed", phase="verification", version=task["version"] + 1, failure="orphaned_operation", results=[])
            task.pop("operation")
            self._view(task)
            self.store.save(db, task, "recover", request_id, payload)
            return task
