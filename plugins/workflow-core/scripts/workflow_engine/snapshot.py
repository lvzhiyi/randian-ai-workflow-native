"""只读取纳管普通文件；先检查敏感路径、链接及子模块再读取内容。"""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
from .model import EngineError, digest
from .policy import POLICY_VERSION

CACHE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", ".dart_tool"}


def git(root, *args):
    p = subprocess.run(["git", "-C", str(root)] + list(args), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if p.returncode:
        raise EngineError("GIT_REQUIRED", "root 必须位于有效 Git 工作区")
    return p.stdout


def sensitive(path):
    name = path.name.lower()
    return name == ".env" or name.startswith(".env.") or name in {"credentials", "credentials.json", "id_rsa", "id_ed25519", ".npmrc", ".pypirc"} or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"} or any(part.lower() in {".ssh", "secrets", ".aws"} for part in path.parts)


def capture(root, plan_digest):
    names = set(git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", ".").split(b"\0")) - {b""}
    tracked = set(git(root, "ls-files", "-z", "--cached", "--", ".").split(b"\0"))
    stages = git(root, "ls-files", "--stage", "-z", "--", ".").split(b"\0")
    if any(item.startswith(b"160000 ") for item in stages):
        raise EngineError("SUBMODULE", "纳管范围不支持子模块")
    paths = []
    for raw in sorted(names):
        rel = Path(os.fsdecode(raw))
        if rel.is_absolute() or ".." in rel.parts:
            raise EngineError("PATH_ESCAPE", "Git 路径越界")
        # 链接必须在缓存过滤前拒绝，避免通过缓存目录绕过边界。
        current = root
        for part in rel.parts:
            current = current / part
            if current.is_symlink():
                raise EngineError("SYMLINK", "纳管路径不允许符号链接")
        if raw not in tracked and any(part in CACHE_PARTS for part in rel.parts):
            continue
        if sensitive(rel):
            raise EngineError("SENSITIVE_FILE", "发现敏感文件，未读取内容")
        paths.append((rel, root / rel))
    entries = []
    for rel, path in paths:
        try:
            fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        except FileNotFoundError:
            entries.append([rel.as_posix(), "deleted"])
            continue
        except OSError as exc:
            raise EngineError("SNAPSHOT_UNSAFE", "无法安全读取纳管文件") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise EngineError("SNAPSHOT_UNSAFE", "纳管路径不是普通文件")
            h = hashlib.sha256()
            while True:
                data = os.read(fd, 1024 * 1024)
                if not data:
                    break
                h.update(data)
            entries.append([rel.as_posix(), h.hexdigest(), info.st_mode & 0o111])
        finally:
            os.close(fd)
    return digest({"files": entries, "plan": plan_digest, "policy": POLICY_VERSION})
