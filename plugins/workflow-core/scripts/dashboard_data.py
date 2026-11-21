"""只读工作流看板；仅返回结构化摘要，不把文档正文或引擎命令带入 JSON。

公开接口为 build_dashboard(root, task_id=None) 与 read_document(root, relative_path)。
阶段证据仅接受独立字段「- 阶段：阶段 ID｜状态：状态」，不扫描自然语言完成词。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Optional

import workflow_config
import workflow_engine_cli
from workflow_engine import snapshot
from dashboard_projection import project_task

MAX_CONFIG_BYTES = 64 * 1024
MAX_DOCUMENT_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_DOCUMENTS = 256
MAX_ENGINE_JSON_BYTES = 1024 * 1024
STAGES = (("prd", "需求接收"), ("breakdown", "需求拆解"), ("kickoff", "开工准备"),
          ("proposal", "方案提案"), ("implementation", "实施"),
          ("verification", "验证"), ("review", "评审"), ("delivery", "交付"))
STATES = {"已完成": "completed", "自测完成": "completed", "人工验收通过": "completed", "已交付": "completed",
          "进行中": "in_progress", "实施中": "in_progress", "研发中": "in_progress",
          "待处理": "pending", "待开始": "pending", "未开始": "pending", "待开发": "pending", "待联调": "pending",
          "受阻": "blocked", "待确认": "blocked", "可评审": "ready",
          "评审通过": "ready", "评审通过，待人工验收": "ready", "待人工验收": "ready",
          "实施完成待验证": "pending", "待验证": "pending",
          "已取消": "cancelled", "通过": "passed", "失败": "failed"}
KNOWN_STATES = {"unknown", "created", "ready", "running", "passed", "completed", "failed",
                "stale", "cancelled", "pending", "in_progress", "blocked"}
CARD = re.compile(r"^###\s+([A-Za-z0-9][A-Za-z0-9_-]*-R[0-9]+)\s+(.+?)\s*$")
FIELD = re.compile(r"^\s*-\s+(?:\*\*)?(状态|协作状态)(?:\*\*)?[:：]\s*(.+?)\s*$")


def _relative(value):
    """拒绝敏感组件及路径歧义，避免解析器和文件系统对同一输入理解不同。"""
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError("文档路径无效")
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts or snapshot.sensitive(rel):
        raise ValueError("拒绝敏感路径或越界路径")
    if any(p.startswith(".env") or p.lower() in {".git", ".gnupg", ".azure"} for p in rel.parts):
        raise ValueError("拒绝敏感路径")
    return rel


def _open_directory(path):
    """逐层打开目录且不跟随链接，包含 root 自身与祖先，缩小检查/使用竞态窗口。"""
    absolute = Path(os.path.abspath(str(path)))
    fd = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in absolute.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read(root, relative_path, limit):
    rel = _relative(relative_path)
    parent = _open_directory(root)
    try:
        for part in rel.parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = nxt
        fd = os.open(rel.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError("文档不是普通文件或超过大小限制")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                data = handle.read(limit + 1)
            if len(data) > limit:
                raise ValueError("文档超过大小限制")
            return data.decode("utf-8")
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def read_document(root: Path, relative_path: str) -> str:
    """只允许 root 内普通 .md；拒绝任意层级链接、敏感路径和超过 512 KiB 的文件。

    非法路径抛出 ValueError，文件不存在或权限不足抛出 OSError；不自动寻找父项目。
    """
    rel = _relative(relative_path)
    if rel.suffix.lower() != ".md":
        raise ValueError("只允许 Markdown 文档")
    return _read(Path(root), relative_path, MAX_DOCUMENT_BYTES)


def _project_root(root):
    path = Path(os.path.abspath(str(root)))
    fd = _open_directory(path)
    os.close(fd)
    for candidate in (path,) + tuple(path.parents):
        config = candidate / workflow_config.CONFIG_FILE
        if config.exists() or config.is_symlink():
            return candidate
    return path


def _state(raw):
    raw = raw.strip().strip("*` ")
    return STATES.get(raw, raw if raw in KNOWN_STATES else "unknown")


def _evidence(item, state, source, issues):
    """冲突时保留全部位置并降级 unknown，后续证据不能掩盖先前冲突。"""
    previous = item["source"]
    if previous and item["state"] != state:
        item["state"] = "unknown"
        issues.append("状态证据冲突：" + previous + "；" + source)
    else:
        item["state"] = state
    item["source"] = previous + "；" + source if previous else source


def _parse(text, path, result, stage_map, task_map):
    current = None
    headings = {}
    checkboxes = []
    fenced = None
    in_comment = False
    for number, original in enumerate(text.splitlines(), 1):
        line = original.strip()
        if "<!--" in line:
            in_comment = "-->" not in line
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.startswith(("```", "~~~")):
            marker = line[:3]
            if fenced is None:
                fenced = marker
            elif marker == fenced:
                fenced = None
            continue
        if fenced:
            continue
        source = "{}:{}".format(path, number)
        match = CARD.match(line)
        if match:
            identity, title = match.groups()
            headings.setdefault(identity, source)
            current = task_map.get(identity)
            if current is None:
                current = {"id": identity, "title": title, "state": "unknown", "source": ""}
                task_map[identity] = current
            elif current["title"] != title:
                result["issues"].append("任务标题冲突：" + identity + " " + source)
            continue
        if line.startswith("#"):
            current = None
        field = FIELD.match(line)
        human_delivery = re.match(r"^- \[([ xX])\] 子需求人工验收/交付完成(?:（.*）)?$", line)
        # 人工验收独立于 Agent 主状态，未勾选不能撤销评审通过。
        if current is not None and human_delivery:
            current["human_delivery_completed"] = human_delivery.group(1).lower() == "x"
            current["human_delivery_source"] = source
        checked = re.match(r"^- \[([ xX])\] 子需求完成(?:（.*）)?$", line)
        if current is not None and field:
            _evidence(current, _state(field.group(2)), source, result["issues"])
        if current is not None and checked:
            checkboxes.append((current, checked.group(1).lower() == "x", source))
        stage = re.match(r"^- 阶段[:：]\s*([a-z]+)\s*｜\s*状态[:：]\s*(.+)$", line)
        if stage and stage.group(1) in stage_map:
            _evidence(stage_map[stage.group(1)], _state(stage.group(2)), source, result["issues"])
        if line.startswith(("- 待确认：", "- 待确认:")) and "｜" in line:
            fields = {}
            for part in line[2:].split("｜"):
                pair = re.split("[:：]", part.strip(), maxsplit=1)
                if len(pair) == 2:
                    fields[pair[0].strip()] = pair[1].strip()
            required = ("待确认", "影响", "恢复条件")
            if all(fields.get(key) for key in required):
                entry = {
                    "question": fields["待确认"],
                    "impact": fields["影响"],
                    "owner": fields.get("负责人") or "未指定",
                    "resume": fields["恢复条件"],
                    "source": source + ("｜" + fields["来源"] if fields.get("来源") else ""),
                }
                result["pending"].append(entry)
                if current is not None:
                    current.setdefault("pending", []).append(entry)
            else:
                result["issues"].append("待确认记录字段不完整：" + source)
    # 复选框只约束是否完成，不把未勾选误当成具体协作状态；延后处理以消除字段顺序影响。
    for item, completed, source in checkboxes:
        if not item["source"]:
            _evidence(item, "completed" if completed else "pending", source, result["issues"])
        elif completed != (item["state"] == "completed"):
            _evidence(item, "completed" if completed else "pending", source, result["issues"])
        else:
            item["source"] += "；" + source
    # 无状态字段的任务也必须保留可定位的标题行。
    for identity, source in headings.items():
        if not task_map[identity]["source"]:
            task_map[identity]["source"] = source


def _documents(root, config, issues):
    paths = set()
    for key in workflow_config.SCHEMA["docs"]:
        value = config.get("docs." + key)
        if not value or value in workflow_config.PLACEHOLDERS:
            continue
        try:
            rel = _relative(value)
            path = root / rel
            if rel.suffix.lower() == ".md":
                paths.add(rel.as_posix())
            elif path.exists():
                fd = _open_directory(path)
                os.close(fd)
                # 限制目录访问数量，防止巨大工作区耗尽看板请求资源。
                visited = 0
                for directory, dirs, files in os.walk(str(path), followlinks=False):
                    visited += 1
                    dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink()
                                     and not snapshot.sensitive(Path(d)) and not d.startswith("."))
                    for name in sorted(files):
                        if name.lower().endswith(".md"):
                            paths.add((Path(directory) / name).relative_to(root).as_posix())
                        if len(paths) >= MAX_DOCUMENTS:
                            break
                    if len(paths) >= MAX_DOCUMENTS or visited >= MAX_DOCUMENTS:
                        issues.append("文档扫描达到数量限制")
                        break
            else:
                issues.append("配置文档目录不存在：" + value)
        except (OSError, ValueError):
            issues.append("配置文档路径不可安全访问：" + str(value))
    if len(paths) > MAX_DOCUMENTS:
        issues.append("文档数量超过限制")
    return sorted(paths)[:MAX_DOCUMENTS]


def _engine(root, task_id, result, task_map, stage_map):
    mode = result["mode"]
    # 旧 engine.enabled 仅用于迁移提示，不参与只读数据源选择。
    mode.update(state="unavailable", binding="unbound")
    path = workflow_engine_cli.default_db(root)
    if not path.is_file():
        mode["warning"] = "引擎数据库不存在；未创建数据库"
        return
    try:
        # 不能实例化 Store/Engine：它们会创建表，status 还会进行文件内容哈希。
        if any(p.is_symlink() for p in (path,) + tuple(path.parents)):
            raise ValueError("数据库路径不允许符号链接")
        db = sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=0.2)
        try:
            db.execute("PRAGMA query_only=ON")
            cursor = db.execute("SELECT id, CASE WHEN length(CAST(data AS BLOB)) <= ? THEN data END FROM tasks WHERE (? IS NULL OR id=?) ORDER BY id LIMIT ?",
                                (MAX_ENGINE_JSON_BYTES, task_id, task_id, MAX_DOCUMENTS + 1))
            rows = []
            read_bytes = 0
            for row in cursor:
                read_bytes += len(row[1].encode("utf-8")) if isinstance(row[1], str) else 0
                if read_bytes > MAX_TOTAL_BYTES:
                    result["issues"].append("引擎任务累计读取达到限制")
                    break
                rows.append(row)
        finally:
            db.close()
        mode.update(available=True, state="unbound")
        if len(rows) > MAX_DOCUMENTS:
            result["issues"].append("引擎任务数量超过限制")
        total = 0
        for identity, raw in rows[:MAX_DOCUMENTS]:
            total += len(raw.encode("utf-8")) if isinstance(raw, str) else 0
            if total > MAX_TOTAL_BYTES:
                result["issues"].append("引擎任务累计读取达到限制")
                break
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_ENGINE_JSON_BYTES:
                raise ValueError("引擎任务数据超过限制")
            task = json.loads(raw)
            if not isinstance(task, dict) or task.get("id") != identity:
                raise ValueError("引擎任务结构无效")
            if task.get("root") != str(root):
                mode.update(binding="mismatch", state="mismatch", warning="任务绑定其他 root")
                result["issues"].append("引擎任务 root 绑定不匹配：" + str(identity))
                continue
            if mode["binding"] != "mismatch":
                mode.update(binding="bound", state="active")
            previous = task_map.get(identity, {})
            task_map[identity] = project_task(task, previous)
            # 文档人工验收是独立来源，不覆盖轮次权威状态或引擎交付记录。
            for key in ("human_delivery_completed", "human_delivery_source"):
                if key in previous:
                    task_map[identity][key] = previous[key]
    except (OSError, ValueError, sqlite3.Error, TypeError, AttributeError, RecursionError):
        mode.update(state="unavailable", warning="引擎数据库或任务数据不可用")
        result["issues"].append("引擎数据库无法只读解析")


def build_dashboard(root: Path, task_id: Optional[str] = None) -> dict:
    """按最近 ai-workflow.yaml 的根采集摘要；配置/数据损坏进入 issues，不写磁盘。

    mode.binding 为 unknown/unbound/bound/mismatch，available 只说明数据库可查询，
    configured_enabled 固定为 True；旧 engine.enabled 只产生迁移提示，不控制查询。
    """
    root = Path(root)
    issues = []
    try:
        root = _project_root(root)
        config_path = root / workflow_config.CONFIG_FILE
        if config_path.exists() or config_path.is_symlink():
            _read(root, workflow_config.CONFIG_FILE, MAX_CONFIG_BYTES)
        config = workflow_config.load(root)
    except (OSError, ValueError, workflow_config.ConfigError) as error:
        issues.append("工作流配置不可安全加载：" + type(error).__name__)
        config = workflow_config.Config({}, "不可用", root)
    legacy_enabled = config.get("engine.enabled")
    migration_warning = "旧 engine.enabled 已废弃，请迁移配置；该键不影响任务读取" if legacy_enabled is not None else ""
    result = {"project": {"name": root.name, "root": str(root)},
              "mode": {"configured_enabled": True, "binding": "unknown", "available": False,
                       "state": "unknown", "warning": migration_warning,
                       "migration_warning": migration_warning},
              "stages": [{"id": key, "label": label, "state": "unknown", "source": ""} for key, label in STAGES],
              "tasks": [], "pending": [], "documents": [], "issues": issues}
    stage_map = {item["id"]: item for item in result["stages"]}
    task_map = {}
    total = 0
    for path in _documents(root, config, issues):
        document = {"path": path, "title": Path(path).stem, "exists": False}
        result["documents"].append(document)
        try:
            text = read_document(root, path)
            document["exists"] = True
            total += len(text.encode("utf-8"))
            if total > MAX_TOTAL_BYTES:
                issues.append("文档总大小超过限制")
                break
            _parse(text, path, result, stage_map, task_map)
        except (OSError, ValueError):
            issues.append("文档不存在或不可安全读取：" + path)
    _engine(root, task_id, result, task_map, stage_map)
    result["tasks"] = [task_map[key] for key in sorted(task_map)]
    if task_id is not None:
        result["tasks"] = [item for item in result["tasks"] if item["id"] == task_id]
    return result
