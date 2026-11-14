"""仅处理有效快照上的业务规则，文件完整性由存储边界负责。"""


class DomainError(Exception):
    """业务输入不合法，错误消息不包含用户原文。"""


def add(data, title):
    """校验完成后才分配编号，拒绝输入不消耗编号。"""
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 80:
        raise DomainError("标题去除首尾空白后必须为 1～80 个字符")
    task = {"id": data["next_id"], "title": title.strip(), "status": "pending"}
    data["tasks"].append(task)
    data["next_id"] += 1
    return dict(task)


def list_tasks(data, status="all"):
    """返回独立对象，避免调用方通过查询结果隐式修改快照。"""
    if status not in ("all", "pending", "completed"):
        raise DomainError("筛选状态不合法")
    return [dict(task) for task in sorted(data["tasks"], key=lambda task: task["id"])
            if status == "all" or task["status"] == status]


def set_status(data, identifier, status):
    """无删除场景采用线性查找，避免维护重复索引与快照一致性。"""
    if type(identifier) is not int or identifier < 1:
        raise DomainError("待办编号必须为正整数")
    if status not in ("pending", "completed"):
        raise DomainError("目标状态不合法")
    for task in data["tasks"]:
        if task["id"] == identifier:
            task["status"] = status
            return dict(task)
    raise DomainError("待办不存在")
