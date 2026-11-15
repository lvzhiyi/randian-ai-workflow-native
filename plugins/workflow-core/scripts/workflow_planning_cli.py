#!/usr/bin/env python3
"""会话级规划登记：技能流程授权，不提供真人身份认证或写入沙箱。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

from workflow_config import Config, load, validate
from workflow_engine_cli import default_db

MAX_TTL = 3600
DOC_DEFAULTS = {
    "product_root": "docs/product", "cards_dir": "docs/product/任务",
    "home": "docs/product/项目首页.md", "requirements": "docs/product/需求/需求说明.md",
    "overview": "docs/product/任务/版本任务总览.md", "glossary": "docs/product/术语表.md",
    "design_index": "docs/product/设计/设计索引.md", "dev_docs": "docs/development",
}
ENTRIES = {"README.md", "AGENTS.md", "CLAUDE.md"}


def safe_path(root, value):
    """先拒绝词法穿越，再逐级拒绝符号链接，包含尚未创建的目标。"""
    if not isinstance(value, str) or not value or any(c in value for c in "\\\x00\n\r"):
        raise ValueError("规划路径无效")
    path = Path(value)
    if ".." in path.parts or "." in value.split("/"):
        raise ValueError("规划路径不能含点路径")
    # 只改写 macOS 已知系统祖先别名，不 resolve 整个目标，保留项目内链接证据。
    if path.is_absolute() and sys.platform == "darwin":
        for alias in ("/var", "/tmp", "/etc"):
            prefix = Path(alias)
            if prefix.is_symlink() and prefix.resolve() == Path("/private" + alias):
                try:
                    suffix = path.relative_to(prefix)
                    candidate = prefix.resolve() / suffix
                    candidate.relative_to(root)
                except ValueError:
                    continue
                path = candidate
                break
    relative = path.relative_to(root) if path.is_absolute() else path
    if not relative.parts:
        raise ValueError("规划目标必须为文件")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("规划路径不能含符号链接")
    current.resolve().relative_to(root)
    return relative.as_posix()


def session_path(root, session):
    if not session or len(session) > 512:
        raise ValueError("需要宿主真实会话标识")
    key = hashlib.sha256(session.encode()).hexdigest()
    return default_db(root).parent / ("planning-" + key + ".json")


def legal_target(root, operation, value, config):
    """只认可配置中的具体文档角色、模块卡或有限自举骨架，不开放文档目录。"""
    path = safe_path(root, value)
    # 插件实现和模板边界不能被项目配置或初始化草稿覆盖。
    parts = Path(path).parts
    if (any(part in {"plugins", "skills", "scripts", "templates", ".cursor", ".claude", ".codex", ".git"} for part in parts[:-1]) or
            (root / path).is_relative_to(Path(__file__).resolve().parent.parent)):
        raise ValueError("插件源码与模板不属于规划授权")
    if path == "README.md" or operation == "init" and path in ENTRIES:
        return path
    if operation == "init" and path == "ai-workflow.yaml":
        return path
    if Path(path).suffixes != [".md"] or any(Path(p).suffix for p in Path(path).parts[:-1]):
        raise ValueError("规划只允许 Markdown 文档目标")
    def doc(key):
        product = config.get("docs.product_root", DOC_DEFAULTS["product_root"])
        fallback = DOC_DEFAULTS[key]
        if fallback.startswith("docs/product/"):
            fallback = product + fallback[len("docs/product"):]
        return config.get("docs." + key, fallback)
    exact = {safe_path(root, doc(key)) for key in ("home", "requirements", "overview", "glossary", "design_index") if doc(key) not in ("无", "待确认")}
    if path in exact:
        return path
    cards = safe_path(root, doc("cards_dir"))
    if operation == "prd-breakdown" and Path(path).parent.as_posix() == cards:
        return path
    if operation == "init":
        dev = safe_path(root, doc("dev_docs"))
        if path in {dev + "/" + name + ".md" for name in ("coding", "architecture", "testing", "ui", "api-integration")}:
            return path
    raise ValueError("目标不属于本操作的规划文档：" + path)


def read_record(root, session):
    path = session_path(root, session)
    if not path.is_file() or path.stat().st_size > 65536:
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    if (record.get("root") != str(root) or record.get("session") != session or record.get("closed_at") or
            not isinstance(record.get("expires_at"), (int, float)) or record["expires_at"] <= time.time()):
        return None
    return record


def allows(root, session, paths):
    """全部目标精确命中才放行；有效期内仍复核路径，避免登记后换链接。"""
    try:
        record = read_record(root, session)
        return bool(record and paths and all(safe_path(root, p) in record["paths"] for p in paths))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def write_record(path, record):
    """原子替换避免回调读到半份登记；状态保存在项目源码树之外。"""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex)
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False)
        os.replace(temporary, path)
        # 每次开闭保留完整快照；单会话登记替换不抹去历史授权范围。
        audit = path.with_suffix(".jsonl")
        fd = os.open(audit, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    finally:
        temporary.unlink(missing_ok=True)


def parser():
    result = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    result.add_argument("action", choices=("open", "close", "status"))
    result.add_argument("--root", required=True)
    result.add_argument("--session", required=True)
    result.add_argument("--operation", choices=("init", "prd-breakdown"))
    result.add_argument("--path", action="append", default=[])
    result.add_argument("--ttl", type=int, default=1800)
    result.add_argument("--config-json")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        root = Path(args.root).resolve(strict=True)
        path = session_path(root, args.session)
        record = read_record(root, args.session)
        if args.action == "open":
            if not args.operation or not args.path or len(args.path) > 128 or not 1 <= args.ttl <= MAX_TTL:
                raise ValueError("open 需要操作、精确目标与 1～3600 秒有效期")
            config = load(root)
            if args.config_json:
                if args.operation != "init":
                    raise ValueError("配置草稿仅限 init")
                data = json.loads(args.config_json)
                if validate(data):
                    raise ValueError("配置草稿结构无效")
                config = Config(data, "初始化草稿", root)
            paths = sorted(set(legal_target(root, args.operation, p, config) for p in args.path))
            now = time.time()
            record = {"root": str(root), "session": args.session, "operation": args.operation,
                      "paths": paths, "created_at": now, "expires_at": now + args.ttl,
                      "id": uuid.uuid4().hex, "previous_id": record.get("id") if record else None}
            write_record(path, record)
        elif args.action == "close" and record:
            record["closed_at"] = time.time()
            write_record(path, record)
        print(json.dumps({"planning": record, "active": bool(read_record(root, args.session))}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
