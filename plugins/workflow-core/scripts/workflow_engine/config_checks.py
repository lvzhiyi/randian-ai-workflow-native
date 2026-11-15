"""把当前档位配置命令约束为可直接执行的 argv，不允许 shell 语义。"""
import shlex
from workflow_config import load, ConfigError
from .model import EngineError, digest


def configured(root, tier):
    try:
        config = load(root)
        section = config.data.get('verify')
        if section is None:
            return [], None
        values = config.get('verify.' + tier)
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list) or not values:
            raise EngineError('VERIFY_CONFIG', '当前档位 verify 命令缺失')
        # 文档检查在有配置时同样是必执行项，不能只完成当前档位命令。
        docs = config.get('verify.docs')
        if docs is not None:
            docs = [docs] if isinstance(docs, str) else docs
            if not isinstance(docs, list) or not docs:
                raise EngineError('VERIFY_CONFIG', 'verify.docs 必须是非空命令或列表')
            values = [*values, *docs]
        commands = []
        for value in values:
            lexer = shlex.shlex(value, posix=True, punctuation_chars=';&|<>')
            lexer.whitespace_split = True
            lexer.commenters = ''
            tokens = list(lexer)
            if not tokens or any(token and all(c in ';&|<>' for c in token) for token in tokens) or any('$(' in t or '`' in t for t in tokens):
                raise EngineError('VERIFY_CONFIG', 'verify 命令含不支持的 shell 控制语义')
            commands.append(tokens)
        return commands, digest(commands)
    except (ConfigError, ValueError, OSError) as error:
        raise EngineError('VERIFY_CONFIG', 'verify 配置无法安全解析') from error


def enforce(root, tier, plan):
    commands, signature = configured(root, tier)
    actual = [c['argv'] for c in plan['checks'] if c['cwd'] == '.']
    for command in commands:
        if command not in actual:
            raise EngineError('VERIFY_REQUIRED', '检查计划缺少当前档位配置命令（需根目录执行）')
        actual.remove(command)
    return signature
