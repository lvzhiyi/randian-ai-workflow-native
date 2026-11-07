#!/usr/bin/env python3
"""读取与校验项目工作流配置 ai-workflow.yaml（只读，仅用 Python 标准库）。

配置文件使用 YAML 的受限子集，由本模块自带解析器读取，不依赖 PyYAML：
- 映射 `键: 值`，值为空时下一行缩进 2 格开始子映射或列表；
- 字符串列表 `- 值`；
- 标量：字符串（可加单 / 双引号）、true / false；
- 整行或行尾 `#` 注释（引号内的 # 保留）。
不支持：行内 [] / {}、多行字符串 | >、锚点 & *、多文档 ---、制表符缩进。
遇到不支持的写法抛出 ConfigError 并给出行号，不静默回退默认值。

读取优先级：ai-workflow.yaml → AGENTS.md / CLAUDE.md 的「工作流配置」Markdown 小节（旧格式，仅取路径）→ 无配置。
"""
from pathlib import Path
import re

CONFIG_FILE = 'ai-workflow.yaml'

# 占位值：表示该项未确认或不适用，路径检查时跳过。
PLACEHOLDERS = ('待确认', '无')

# 配置结构：段名 → {键名: 类型}；类型 'str' 字符串，'path' 相对项目根的路径，
# 'list' 字符串列表，'cmd' 单条命令或命令列表，'enum:a|b' 枚举。
SCHEMA = {
    'version': 'version',
    'docs': {
        'product_root': 'path', 'home': 'path', 'requirements': 'path', 'cards_dir': 'path',
        'overview': 'path', 'design_index': 'path', 'dev_docs': 'path', 'glossary': 'path',
    },
    'spec': {'tool': 'enum:openspec|none', 'dir': 'path'},
    'handoff': {'with_change': 'str', 'default': 'str'},
    'review': {'base_branch': 'str'},
    'verify': {'docs': 'cmd', 'light': 'cmd', 'standard': 'cmd', 'full': 'cmd'},
    'platforms': {'default': 'list', 'on_request': 'list', 'excluded': 'list'},
    'design': {'tool': 'str', 'source_doc': 'path'},
    'api': {'tool': 'str', 'project': 'str', 'project_id_file': 'path'},
    'code_rules_doc': 'path',
    'notes': 'list',
}

# 旧格式 Markdown 小节的标签 → 新配置键，只用于兼容期读取路径。
LEGACY_LABELS = {
    '产品文档根': 'docs.product_root',
    '任务卡目录': 'docs.cards_dir',
    '工程规范': 'docs.dev_docs',
}

_KEY = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*):(?:\s+(.*))?$')
_UNSUPPORTED_VALUE = ('[', '{', '|', '>', '&', '*', '!', '%', '@')


class ConfigError(Exception):
    """配置无法解析或不符合结构时抛出。

    参数 [message]：错误说明；[line]：出错行号（从 1 开始），未知时为 None；[file]：配置文件名。
    """

    def __init__(self, message, line=None, file=None):
        self.message = message
        self.line = line
        self.file = file
        super().__init__(self.__str__())

    def __str__(self):
        where = self.file or ''
        if self.line is not None:
            where = f'{where}:{self.line}' if where else f'第 {self.line} 行'
        return f'{where}: {self.message}' if where else self.message


def _strip_comment(text):
    """去掉行尾注释，引号内的 # 保留。

    参数 [text]：去掉缩进后的一行。
    返回：去掉注释和尾部空白后的内容。
    """
    quote = None
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = None
        elif char in '"\'':
            quote = char
        elif char == '#' and (index == 0 or text[index - 1] in ' \t'):
            return text[:index].rstrip()
    return text.rstrip()


def _scalar(raw, line):
    """把标量文本转成值。

    参数 [raw]：冒号或短横线后的文本；[line]：行号，用于报错。
    返回：去掉引号的字符串，或 true / false 对应的布尔值。
    """
    raw = raw.strip()
    if raw[:1] in '"\'':
        if len(raw) < 2 or raw[-1] != raw[0]:
            raise ConfigError('引号未闭合', line)
        return raw[1:-1]
    if raw.startswith(_UNSUPPORTED_VALUE):
        raise ConfigError(f'不支持的写法“{raw[:1]}”：只允许字符串、true / false，'
                          f'列表请逐行写 “- 值”', line)
    if raw in ('true', 'false'):
        return raw == 'true'
    return raw


def parse_yaml_subset(text):
    """解析 YAML 受限子集文本。

    参数 [text]：配置全文。
    返回：嵌套的 dict / list / 标量。
    出错时抛出 ConfigError（带行号）。
    """
    lines = []
    for number, original in enumerate(text.splitlines(), 1):
        if '\t' in original[:len(original) - len(original.lstrip())]:
            raise ConfigError('缩进不能用制表符', number)
        content = _strip_comment(original.strip())
        if not content:
            continue
        if content in ('---', '...') or content.startswith('? '):
            raise ConfigError('不支持多文档或复杂键', number)
        indent = len(original) - len(original.lstrip(' '))
        if indent % 2:
            raise ConfigError('缩进必须是 2 的倍数', number)
        lines.append((indent, content, number))

    def block(index, indent):
        """从 lines[index] 起解析一个缩进为 [indent] 的块，返回 (值, 下一个下标)。"""
        is_list = lines[index][1] == '-' or lines[index][1].startswith('- ')
        result = [] if is_list else {}
        while index < len(lines):
            line_indent, content, number = lines[index]
            if line_indent < indent:
                break
            if line_indent > indent:
                raise ConfigError('缩进过深或位置不对', number)
            item = content == '-' or content.startswith('- ')
            if item != is_list:
                raise ConfigError('同一层不能混用列表项和键值', number)
            if is_list:
                value = content[1:].strip()
                if not value:
                    raise ConfigError('列表项不能为空，也不支持嵌套', number)
                if _KEY.match(value):
                    raise ConfigError('列表项只能是字符串，不支持映射', number)
                result.append(_scalar(value, number))
                index += 1
                continue
            match = _KEY.match(content)
            if not match:
                raise ConfigError('应为 “键: 值”，键只能用字母、数字和下划线', number)
            key, raw = match.group(1), match.group(2)
            if key in result:
                raise ConfigError(f'重复的键 {key}', number)
            index += 1
            if raw:
                result[key] = _scalar(raw, number)
            elif index < len(lines) and lines[index][0] > indent:
                if lines[index][0] != indent + 2:
                    raise ConfigError('子项应比上一级多缩进 2 格', lines[index][2])
                result[key], index = block(index, indent + 2)
            else:
                result[key] = None
        return result, index

    if not lines:
        return {}
    if lines[0][0] != 0:
        raise ConfigError('第一项不能缩进', lines[0][2])
    data, index = block(0, 0)
    if index < len(lines):
        raise ConfigError('无法解析', lines[index][2])
    if not isinstance(data, dict):
        raise ConfigError('顶层必须是 “键: 值”', lines[0][2])
    return data


def _type_error(kind, value):
    """检查 [value] 是否符合类型 [kind]；返回错误说明，符合时返回 None。"""
    if value is None:
        return None
    if kind == 'list':
        ok = isinstance(value, list)
        return None if ok else '应为字符串列表（逐行 “- 值”）'
    if kind == 'cmd':
        ok = isinstance(value, str) or isinstance(value, list)
        return None if ok else '应为一条命令或命令列表'
    if kind.startswith('enum:'):
        options = kind[5:].split('|')
        return None if value in options else f'只能是 {" / ".join(options)}'
    return None if isinstance(value, str) else '应为字符串'


def validate(data):
    """按 SCHEMA 校验配置结构。

    参数 [data]：parse_yaml_subset 的结果。
    返回：错误说明列表，空列表表示通过。未知键、类型不符、缺少或错误的 version 都会报错。
    """
    errors = []
    if str(data.get('version')) != '1':
        errors.append('version: 缺失或不支持，当前只支持 1')
    for key, value in data.items():
        rule = SCHEMA.get(key)
        if rule is None:
            errors.append(f'{key}: 未知的配置项')
        elif rule == 'version':
            continue
        elif isinstance(rule, dict):
            if value is None:
                continue
            if not isinstance(value, dict):
                errors.append(f'{key}: 应为子映射（下一行缩进 2 格写 “键: 值”）')
                continue
            for sub, sub_value in value.items():
                kind = rule.get(sub)
                if kind is None:
                    errors.append(f'{key}.{sub}: 未知的配置项')
                elif _type_error(kind, sub_value):
                    errors.append(f'{key}.{sub}: {_type_error(kind, sub_value)}')
        elif _type_error(rule, value):
            errors.append(f'{key}: {_type_error(rule, value)}')
    return errors


class Config:
    """已加载的项目配置。

    参数 [data]：配置数据（嵌套 dict）；[source]：来源说明；[root]：项目根；[legacy]：是否来自旧格式。
    """

    def __init__(self, data, source, root, legacy=False):
        self.data = data
        self.source = source
        self.root = root
        self.legacy = legacy

    def get(self, dotted, default=None):
        """按 “段.键” 读取配置值。

        参数 [dotted]：如 `docs.product_root`；[default]：未配置时的返回值。
        返回：配置值；路径类字符串去掉尾部斜杠。
        """
        value = self.data
        for part in dotted.split('.'):
            if not isinstance(value, dict) or value.get(part) is None:
                return default
            value = value[part]
        return value.rstrip('/') if isinstance(value, str) else value

    def missing_paths(self):
        """列出配置里写了但在项目中不存在的路径。

        返回：形如 `docs.product_root: docs/product` 的列表；占位值和含 {} 的模式跳过。
        """
        missing = []
        for section, rule in SCHEMA.items():
            items = rule.items() if isinstance(rule, dict) else [(None, rule)]
            for key, kind in items:
                dotted = f'{section}.{key}' if key else section
                value = self.get(dotted)
                if kind != 'path' or not isinstance(value, str):
                    continue
                if value in PLACEHOLDERS or '{' in value:
                    continue
                if not (self.root / value).exists():
                    missing.append(f'{dotted}: {value}')
        return missing


def _read_legacy(root):
    """从 AGENTS.md / CLAUDE.md 的「工作流配置」Markdown 小节读取路径（旧格式兼容）。

    参数 [root]：项目根。
    返回：{'docs': {...}} 形式的数据；没有小节或没取到值时返回空 dict。
    """
    for name in ('AGENTS.md', 'CLAUDE.md'):
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8')
        match = re.search(r'^##\s+工作流配置.*?$(.*?)(?=^##\s|\Z)', text, re.M | re.S)
        if not match:
            continue
        docs = {}
        for line in match.group(1).splitlines():
            for label, dotted in LEGACY_LABELS.items():
                key = dotted.split('.')[1]
                if key in docs or not re.match(rf'^\s*-\s*{re.escape(label)}', line):
                    continue
                value = re.search(r'`([^`]+)`', line)
                if value:
                    docs[key] = value.group(1).strip().rstrip('/')
        if docs:
            return {'docs': docs}
    return {}


def load(root):
    """加载项目配置。

    参数 [root]：项目根目录（Path）。
    返回：Config；来源依次为 ai-workflow.yaml、旧格式 Markdown 小节、默认值（空配置）。
    ai-workflow.yaml 存在但无法解析或结构不符时抛出 ConfigError，不回退到其他来源。
    """
    path = root / CONFIG_FILE
    if path.is_file():
        try:
            data = parse_yaml_subset(path.read_text(encoding='utf-8'))
        except ConfigError as error:
            raise ConfigError(error.message, error.line, CONFIG_FILE) from None
        errors = validate(data)
        if errors:
            raise ConfigError('结构不符：' + '；'.join(errors), None, CONFIG_FILE)
        return Config(data, CONFIG_FILE, root)
    legacy = _read_legacy(root)
    if legacy:
        return Config(legacy, '工作流配置（Markdown 旧格式）', root, legacy=True)
    return Config({}, '默认值', root)
