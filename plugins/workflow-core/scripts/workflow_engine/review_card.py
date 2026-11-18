"""Prepare and apply one bounded task-card status edit."""
from contextlib import contextmanager
import errno
import hashlib
import os
from pathlib import Path
import re
import stat
import uuid

from workflow_config import ConfigError, load
from workflow_planning_cli import DOC_DEFAULTS, safe_path

from .model import EngineError
from .snapshot import capture, capture_files, fingerprint, sensitive


STATUS = '评审通过，待人工验收'
MAX_BYTES = 1048576
HEADING = re.compile(r'^ {0,3}(#{1,3})(?:[ \t]+(\S+)|[ \t]*$)')
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
LABEL = r'(?:协作状态|状态)'
FIELD = re.compile(
    rf'^- (?:{LABEL}[：:]|\*\*{LABEL}\*\*[：:]|\*\*{LABEL}[：:]\*\*)[ \t]*(.*?)'
    r'[ \t]*(?:(?:[；;][ \t]*(?:\*\*)?[\w /、-]+(?:\*\*)?[：:]|<!--).*)?$'
)


def validate_binding(root, binding):
    if (not isinstance(binding, dict) or set(binding) != {'path', 'id'}
            or not isinstance(binding['path'], str) or Path(binding['path']).is_absolute()
            or not isinstance(binding['id'], str) or not re.fullmatch(r'[^\s#]+', binding['id'])):
        raise EngineError('CARD_INVALID', '任务卡绑定需要仓库相对 path 和卡内标题 ID')
    try:
        config = load(root)
        directory = Path(safe_path(root, config.get('docs.cards_dir') or DOC_DEFAULTS['cards_dir']))
        path = Path(safe_path(root, binding['path']))
        if path.as_posix() != binding['path'] or directory not in path.parents or path.suffix != '.md' or sensitive(path):
            raise ValueError('任务卡必须是任务卡目录下的 Markdown 文件')
    except (ValueError, OSError, ConfigError) as error:
        raise EngineError('CARD_INVALID', '任务卡路径无效或不在配置的任务卡目录内') from error
    return path


def replace_status(data, card_id):
    try:
        lines = data.decode('utf-8').splitlines(keepends=True)
    except UnicodeDecodeError as error:
        raise EngineError('CARD_INVALID', '任务卡须使用 UTF-8') from error
    sections = 0
    fields = []
    selected = False
    fence = None
    comment = False
    for index, line in enumerate(lines):
        body = line.rstrip('\r\n')
        marker = FENCE.match(body)
        if fence is not None:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if comment:
            comment = '-->' not in body
            continue
        if marker:
            fence = marker[1]
            continue
        comment_start = body.find('<!--')
        if comment_start >= 0:
            comment = '-->' not in body[comment_start:]
            if not body[:comment_start].strip():
                continue
        heading = HEADING.match(body)
        if heading:
            selected = heading.groups() == ('###', card_id)
            sections += selected
        field = FIELD.match(body) if selected else None
        if field:
            fields.append((index, field.start(1), field.end(1)))
    if sections != 1 or len(fields) != 1:
        raise EngineError('CARD_INVALID', '须唯一定位任务卡标题和独立的协作状态字段')
    index, start, end = fields[0]
    lines[index] = lines[index][:start] + STATUS + lines[index][end:]
    return ''.join(lines).encode('utf-8')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


@contextmanager
def open_parent(root, path):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(root, flags)
    try:
        for part in path.parent.parts:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        yield directory
    finally:
        os.close(directory)


def read_card(directory, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise EngineError('CARD_INVALID', '任务卡须为无其他硬链接的普通文件')
        data = handle.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise EngineError('CARD_INVALID', '任务卡超过 1 MiB')
        return data, info


def prepare(root, task, binding, previous):
    path = validate_binding(root, binding)
    try:
        entries = capture_files(root)
        observed = fingerprint(entries, task['plan_digest'])
        if previous and previous['binding'] == binding and previous['original'] == task['snapshot'] and observed == previous['projected']:
            return dict(previous, temporary=temporary_name())
        if observed != task['snapshot']:
            raise EngineError('CARD_CONFLICT', '工作区与原验证快照不一致')
        with open_parent(root, path) as directory:
            data, info = read_card(directory, path.name)
        before = sha256(data)
        entry = [path.as_posix(), before, info.st_mode & 0o111]
        if entry not in entries:
            raise EngineError('CARD_CONFLICT', '任务卡已变化或不在验证快照内')
        updated = replace_status(data, binding['id'])
        if len(updated) > MAX_BYTES:
            raise EngineError('CARD_INVALID', '更新后的任务卡超过 1 MiB')
        after = sha256(updated)
        entries[entries.index(entry)] = [entry[0], after, entry[2]]
        baseline_before = before
        if previous and previous['binding']['path'] == binding['path'] and previous['after'] == before and before == after:
            baseline_before = previous['baseline_before']
        return dict(binding=binding, original=observed, projected=fingerprint(entries, task['plan_digest']),
                    before=before, after=after, baseline_before=baseline_before, temporary=temporary_name())
    except FileNotFoundError as error:
        raise EngineError('CARD_INVALID', '任务卡不存在') from error
    except OSError as error:
        raise EngineError('CARD_WRITE', '无法读取任务卡或工作区') from error


def temporary_name():
    return '.workflow-review-' + uuid.uuid4().hex + '.tmp'


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def atomic_replace(directory, name, temporary, contents, info):
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(contents)
            handle.flush()
            os.fchmod(fd, stat.S_IMODE(info.st_mode))
            os.fsync(fd)
        if identity(os.stat(name, dir_fd=directory, follow_symlinks=False)) != identity(info):
            raise EngineError('CARD_CONFLICT', '任务卡在回写时已变化')
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        unlink_temporary(directory, temporary)


def unlink_temporary(directory, temporary):
    try:
        os.unlink(temporary, dir_fd=directory)
    except FileNotFoundError:
        pass


def clean_temporary(root, projection):
    path = Path(projection['binding']['path'])
    try:
        with open_parent(root, path) as directory:
            unlink_temporary(directory, projection['temporary'])
    except OSError as error:
        if error.errno not in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
            raise EngineError('CARD_WRITE', '无法清理待回写的临时文件，请重试同一请求') from error


def apply(root, plan_digest, projection):
    path = validate_binding(root, projection['binding'])
    temporary = projection['temporary']
    try:
        with open_parent(root, path) as directory:
            observed = capture(root, plan_digest)
            if observed == projection['projected']:
                os.fsync(directory)
                return
            if observed != projection['original']:
                raise EngineError('CARD_CONFLICT', '回写期间工作区已变化')
            data, info = read_card(directory, path.name)
            updated = replace_status(data, projection['binding']['id'])
            if sha256(data) != projection['before'] or sha256(updated) != projection['after']:
                raise EngineError('CARD_CONFLICT', '任务卡原文与预期回写内容不符')
            atomic_replace(directory, path.name, temporary, updated, info)
            os.fsync(directory)
        if capture(root, plan_digest) != projection['projected']:
            raise EngineError('CARD_CONFLICT', '回写后快照与预期不符')
    except FileNotFoundError as error:
        raise EngineError('CARD_CONFLICT', '回写期间任务卡或目录已移动') from error
    except OSError as error:
        raise EngineError('CARD_WRITE', '任务卡写入未确认，请重试同一请求') from error
