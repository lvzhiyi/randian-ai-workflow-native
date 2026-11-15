"""解析有限的编码基线清单，不递归展开文档引用。"""
from pathlib import Path, PurePosixPath
from fnmatch import fnmatchcase

from workflow_config import PLACEHOLDERS


def _path(root, value):
    """只接受工作区内路径；即使规则未匹配也先校验，防止潜伏错误。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("编码基线路径必须是非空字符串")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("编码基线必须使用项目内相对路径")
    candidate = root / value
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("编码基线不能通过符号链接指向项目外")
    return path.as_posix()


def _matches(path, pattern):
    # **/ 允许匹配零层目录，使 lib/**/*.dart 也能覆盖 lib/main.dart。
    # 任务声明目录范围时保守包含其下规则；实际编辑目标还会再次精确核验。
    literal_prefix = pattern
    for marker in ("*", "?", "["):
        literal_prefix = literal_prefix.split(marker, 1)[0]
    prefix = literal_prefix.rstrip("/")
    if path == "." or prefix == path or prefix.startswith(path.rstrip("/") + "/"):
        return True
    if fnmatchcase(path, pattern):
        return True
    if "**/" in pattern:
        return _matches(path, pattern.replace("**/", "", 1))
    return False


def resolve_baselines(root, changed_paths, config):
    """合并旧规范入口、全局必读和范围匹配规则，保持顺序并去重。"""
    root = Path(root)
    getter = config.get
    if isinstance(config, dict):
        baseline = getter("baseline") or {}
        required = baseline.get("required") or []
        scoped = baseline.get("scoped") or []
        legacy = getter("code_rules_doc")
    else:
        required = getter("baseline.required") or []
        scoped = getter("baseline.scoped") or []
        legacy = getter("code_rules_doc")
    if not isinstance(required, list) or not isinstance(scoped, list):
        raise ValueError("编码基线清单必须是列表")
    selected = []
    if legacy and legacy not in PLACEHOLDERS:
        selected.append(_path(root, legacy))
    selected.extend(_path(root, value) for value in required)
    paths = [_path(root, value) for value in changed_paths]
    for rule in scoped:
        if not isinstance(rule, str) or rule.count(" => ") != 1:
            raise ValueError("范围基线规则必须是 路径模式 => 文档相对路径")
        pattern, document = (part.strip() for part in rule.split(" => "))
        if not pattern or pattern.startswith("/") or ".." in PurePosixPath(pattern).parts:
            raise ValueError("范围模式必须限定在项目内")
        document = _path(root, document)
        if any(_matches(path, pattern) for path in paths):
            selected.append(document)
    return list(dict.fromkeys(selected))
