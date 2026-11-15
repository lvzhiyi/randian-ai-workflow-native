"""并发排空双管道，仅保留有界脱敏诊断；超时回收整个进程组。"""
import os
import re
import selectors
import signal
import subprocess
import time
from .model import EngineError

OUTPUT_LIMIT = 4096


def diagnostic(data):
    text = data.decode('utf-8', errors='replace')
    # 诊断只是尽力脱敏，不能当作凭据保险库；不保留常见令牌与口令值。
    text = re.sub(r'(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|(?:token|password|passwd|secret|api[_-]?key)\s*[:=]\s*)[^\s,;]+', r'\1[REDACTED]', text)
    text = re.sub(r'(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]+)', '[REDACTED]', text)
    return text.encode('utf-8')[:OUTPUT_LIMIT].decode('utf-8', errors='ignore')


def kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def collect(proc, timeout):
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    truncated = False
    reason = 'exit'
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    try:
        for name in buffers:
            stream = getattr(proc, name)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map() or proc.poll() is None:
            if time.monotonic() >= deadline:
                reason = 'timeout'
                truncated = truncated or bool(selector.get_map())
                kill_group(proc)
                break
            if proc.poll() is not None:
                # 父进程退出但子进程持有管道时也须清理，不能等到管道永久 EOF。
                kill_group(proc)
            for key, _ in selector.select(.02):
                chunk = os.read(key.fileobj.fileno(), 16384)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                target = buffers[key.data]
                room = OUTPUT_LIMIT - len(target)
                target.extend(chunk[:room])
                truncated = truncated or len(chunk) > room
        code = proc.wait()
    finally:
        kill_group(proc)
        proc.wait()
        selector.close()
        proc.stdout.close()
        proc.stderr.close()
    return dict(exit_code=code, reason=reason, stdout=diagnostic(buffers['stdout']), stderr=diagnostic(buffers['stderr']), truncated=truncated)


def run_checks(root, plan):
    root = root.resolve()
    results = []
    for check in plan['checks']:
        cwd = root / check['cwd']
        current = root
        for part in cwd.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                raise EngineError('SYMLINK', '检查目录不能包含符号链接')
        if not cwd.resolve().is_relative_to(root):
            raise EngineError('PATH_ESCAPE', '检查目录越界')
        try:
            proc = subprocess.Popen(check['argv'], cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, start_new_session=True)
        except OSError:
            results.append(dict(id=check['id'], exit_code=None, reason='spawn_error', stdout='', stderr='', truncated=False))
            continue
        results.append(dict(id=check['id'], **collect(proc, check['timeout'])))
    return results
