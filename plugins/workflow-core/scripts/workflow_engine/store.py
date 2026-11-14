"""短事务串行化写入；任务、事件和幂等响应共同提交。"""
from contextlib import contextmanager
import json
import os
import sqlite3
from .model import EngineError, canonical, digest


class Store:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # 预创建限制权限，避免 SQLite 按宽松 umask 暴露任务与命令元数据。
        if path.is_symlink():
            raise EngineError("DB_LOCATION", "数据库不允许符号链接")
        descriptor = os.open(str(path), os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
        with self.transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise EngineError("DB_VERSION", "数据库版本不受支持，拒绝隐式降级")
            db.execute("PRAGMA user_version=1")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests(key TEXT PRIMARY KEY, payload TEXT NOT NULL, response TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, version INTEGER NOT NULL, action TEXT NOT NULL, data TEXT NOT NULL);
            """)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def load(self, db, task_id):
        row = db.execute("SELECT data FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise EngineError("NOT_FOUND", "任务不存在")
        return json.loads(row[0])

    def replay(self, db, key, payload):
        if not isinstance(key, str) or not key.strip():
            raise EngineError("REQUEST_INVALID", "request_id 不得为空")
        row = db.execute("SELECT payload,response FROM requests WHERE key=?", (key,)).fetchone()
        if row:
            if row[0] != digest(payload):
                raise EngineError("IDEMPOTENCY_CONFLICT", "请求键已绑定其他参数")
            return json.loads(row[1])
        return None

    def save(self, db, task, action, key=None, payload=None):
        db.execute("INSERT INTO tasks(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (task["id"], canonical(task)))
        db.execute("INSERT INTO events(task_id,version,action,data) VALUES(?,?,?,?)", (task["id"], task["version"], action, canonical(task)))
        if key is not None:
            db.execute("INSERT INTO requests VALUES(?,?,?)", (key, digest(payload), canonical(task)))
