"""单写进程的 JSON 存储；拒绝损坏数据，原子替换不保证断电耐久性。"""
import json
import os
from pathlib import Path
import tempfile


class StoreError(Exception):
    """存储失败或数据不可信；消息不得包含文件正文。"""


def validate(data):
    """线性校验完整快照，避免读取后将损坏数据重新保存为有效状态。"""
    if not isinstance(data, dict) or set(data) != {"version", "next_id", "tasks"}:
        raise StoreError("数据结构不合法")
    if type(data["version"]) is not int or data["version"] != 1:
        raise StoreError("不支持的数据版本")
    if type(data["next_id"]) is not int or data["next_id"] < 1:
        raise StoreError("编号计数不合法")
    if not isinstance(data["tasks"], list):
        raise StoreError("待办集合不合法")
    seen = set()
    for task in data["tasks"]:
        if not isinstance(task, dict) or set(task) != {"id", "title", "status"}:
            raise StoreError("待办结构不合法")
        identifier = task["id"]
        if type(identifier) is not int or identifier < 1 or identifier in seen:
            raise StoreError("待办编号不合法或重复")
        seen.add(identifier)
        title = task["title"]
        if (not isinstance(title, str) or title != title.strip()
                or not 1 <= len(title) <= 80):
            raise StoreError("待办标题不合法")
        if task["status"] not in ("pending", "completed"):
            raise StoreError("待办状态不合法")
    if data["next_id"] <= max(seen, default=0):
        raise StoreError("编号计数必须大于已有编号")


def _unique_object(pairs):
    """拒绝重复 JSON 键，避免解析器静默选择最后一个值。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise StoreError("JSON 字段重复")
        result[key] = value
    return result


def load(path):
    """读取并校验快照；缺失文件返回新空值，不创建目录或文件。"""
    path = Path(path)
    if path.is_symlink():
        raise StoreError("不支持符号链接数据文件")
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle, object_pairs_hook=_unique_object)
    except FileNotFoundError:
        return {"version": 1, "next_id": 1, "tasks": []}
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise StoreError("无法读取数据文件或 JSON 已损坏") from None
    validate(data)
    return data


def save(path, data):
    """先校验新旧快照，再同目录写入和替换；失败时清理临时文件。

    调用者必须保证单写进程；检查到替换之间不提供跨进程防竞争保证。
    """
    path = Path(path)
    validate(data)
    old = load(path)
    if data["next_id"] < old["next_id"]:
        raise StoreError("编号计数不能回退")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=".task-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise StoreError("无法保存数据文件") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # 保留原始失败原因；残留临时文件永远不作为有效快照读取。
                pass
