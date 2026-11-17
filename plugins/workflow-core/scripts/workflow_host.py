"""按宿主定位本机工作流服务的数据目录。"""
import os
from pathlib import Path


def is_codex():
    """由入口显式指定宿主，避免嵌套会话继承环境后走错分支。"""
    return os.environ.get('WORKFLOW_HOST') == 'codex'


def workflow_home():
    """按显式宿主选择本机数据目录。"""
    if os.environ.get("WORKFLOW_HOST") == "cursor":
        return Path.home() / ".cursor"
    if is_codex():
        return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser()
    return Path.home() / '.claude'
