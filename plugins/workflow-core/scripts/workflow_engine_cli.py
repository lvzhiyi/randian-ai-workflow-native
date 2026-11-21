#!/usr/bin/env python3
"""任务工作流 JSON 入口；人工确认是流程证据，不是身份签名。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

TIER_MAP = {'轻量': 'light', '标准': 'standard', '完整': 'full'}


class ArgumentError(Exception):
    """参数错误也输出 JSON。"""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ArgumentError(message)


def default_db(root):
    """状态不进入纳管源码指纹。"""
    home = Path(os.environ.get('WORKFLOW_ENGINE_HOME') or Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'workflow-engine')
    return home / hashlib.sha256(str(root.resolve()).encode()).hexdigest() / 'state.sqlite'


def parser():
    result = Parser(description=__doc__)
    result.add_argument('--root', default='.')
    result.add_argument('--db')
    commands = result.add_subparsers(dest='action', required=True, parser_class=Parser)
    list_command = commands.add_parser('list')
    list_command.add_argument('--active', action='store_true', help='仅显示未终态的活动任务')
    reads = ('status', 'snapshot', 'history', 'progress')
    actions = reads + ('prepare', 'begin', 'create', 'start', 'resume', 'run', 'complete', 'cancel', 'recover', 'confirm-plan', 'confirm-tier', 'request-confirmation', 'approve-proposal', 'read-baseline', 'register-baseline', 'record-tdd', 'finish-step', 'finish-implementation', 'review', 'sync-review-card', 'update-task', 'adopt-protocol', 'bind-executor', 'repair', 'refine-steps', 'return-task')
    for action in actions:
        command = commands.add_parser(action)
        command.add_argument('--task', required=True)
        if action not in reads:
            command.add_argument('--request', default=None, help='幂等请求 ID；省略时自动生成')
        if action not in reads + ('create', 'prepare', 'begin'):
            command.add_argument('--version', type=int, required=True)
        if action == 'begin':
            command.add_argument('--version', type=int, default=None, help='可选 CAS 版本号；省略时按当前版本检查')
        if action in ('create', 'prepare'):
            command.add_argument('--tier', choices=('轻量', '标准', '完整'), required=True)
            command.add_argument('--acceptance', action='append', required=True)
            for name in ('plan', 'details'):
                group = command.add_mutually_exclusive_group(required=(action == 'create' or name == 'details'))
                group.add_argument('--' + name)
                group.add_argument('--' + name + '-json')
        if action == 'prepare':
            command.add_argument('--executor', default=None, help='可选：同时绑定执行者')
            command.add_argument('--session', default=None, help='可选：同时绑定宿主会话')
            command.add_argument('--request-tier', action='store_true', help='可选：同时登记聊天定档请求（需配合 --executor 和 --session）')
        if action == 'begin':
            command.add_argument('--executor', required=True)
            command.add_argument('--session', required=True)
            command.add_argument('--max-bytes', type=int, default=65536)
            tdd_group = command.add_mutually_exclusive_group(required=False)
            tdd_group.add_argument('--tdd')
            tdd_group.add_argument('--tdd-json')
        if action in ('confirm-plan', 'approve-proposal'):
            command.add_argument('--digest', required=True)
        if action in ('confirm-tier', 'approve-proposal', 'return-task'):
            command.add_argument('--actor', required=True)
        if action in ('register-baseline', 'record-tdd', 'review', 'update-task', 'adopt-protocol', 'repair', 'refine-steps'):
            group = command.add_mutually_exclusive_group(required=True)
            group.add_argument('--file')
            group.add_argument('--file-json')
        if action in ('read-baseline', 'bind-executor'):
            command.add_argument('--executor', required=True)
        if action in ('read-baseline', 'bind-executor', 'request-confirmation'):
            command.add_argument('--session', required=True)
        if action == 'request-confirmation':
            command.add_argument('--kind', choices=('tier_confirmation', 'approval'), required=True)
        if action == 'read-baseline':
            group = command.add_mutually_exclusive_group(required=True)
            group.add_argument('--path', action='append', help='基线路径，可重复指定')
            group.add_argument('--all', action='store_true', help='读取任务声明的全部基线')
            command.add_argument('--max-bytes', type=int, default=65536)
        if action in ('repair', 'refine-steps'):
            command.add_argument('--reason', required=True)
        if action == 'finish-step':
            command.add_argument('--step', required=True)
            command.add_argument('--summary', required=True)
            command.add_argument('--finish-implementation', action='store_true', help='完成步骤后顺带执行 finish-implementation')
        if action == 'return-task':
            command.add_argument('--reason', required=True)
        if action == 'sync-review-card':
            command.add_argument('--round', required=True)
            command.add_argument('--card-path', required=True)
            command.add_argument('--card-id', required=True)
    return result


def load_json(path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def input_json(args, name):
    inline = getattr(args, name + '_json', None)
    return json.loads(inline) if inline is not None else load_json(getattr(args, name))


def human_confirmation(label):
    # 终端交互保留人工流程属性；同用户程序仍可代答，绝非安全认证。
    if not sys.stdin.isatty():
        raise ArgumentError('人工流程确认须在交互终端执行')
    print(label + '，请输入 confirm：', file=sys.stderr)
    if input().strip() != 'confirm':
        raise ArgumentError('未确认人工流程')


def baseline_document(engine, path, limit):
    data = engine.read_baseline_bytes(path, limit + 1)
    truncated = len(data) > limit
    try:
        content = data[:limit].decode('utf-8', errors='ignore' if truncated else 'strict')
    except UnicodeDecodeError:
        raise ArgumentError(f'{path}：基线正文必须为完整 UTF-8 文本，未登记完整读取')
    return dict(path=path, content=content, truncated=truncated, bytes_read=min(len(data), limit)), data


def baseline_receipt(args, task, document, data):
    return dict(path=document['path'], sha256=hashlib.sha256(data).hexdigest(),
                bytes_read=len(data), complete=True, executor=args.executor,
                session_id=args.session, round_id=task['current_round'])


def collect_baseline_batch(args, engine, task, paths):
    from workflow_engine.model import EngineError

    if not paths or any(path not in task['baseline'] for path in paths):
        raise EngineError('BASELINE_INVALID', '基线清单为空或包含未声明的基线')
    documents = []
    receipts = []
    # 限制整个 documents 数组的 UTF-8 JSON 大小，包括转义和分隔符。
    remaining = args.max_bytes - 2
    for path in paths:
        document, data = baseline_document(engine, path, max(0, remaining))
        remaining -= len(json.dumps(document, ensure_ascii=False).encode('utf-8'))
        if document['truncated'] or remaining < 0:
            raise EngineError('BASELINE_BATCH_LIMIT',
                              f'基线批次超出输出限额（{path}），请用 --path 缩小批次')
        remaining -= 2
        documents.append(document)
        receipts.append(baseline_receipt(args, task, document, data))
    return documents, receipts


def read_baseline_batch(args, engine, task):
    paths = list(dict.fromkeys(task['baseline'] if args.all else args.path))
    documents, receipts = collect_baseline_batch(args, engine, task, paths)
    value = engine.register_baselines(args.task, args.version, args.request, receipts)
    print(json.dumps(dict(ok=True, version=value['version'], documents=documents), ensure_ascii=False))
    return 0


def derive_plan(root, tier_key, acceptance):
    from workflow_engine import config_checks
    from workflow_engine.model import EngineError

    commands, _ = config_checks.configured(root, tier_key)
    if not commands:
        raise EngineError('VERIFY_CONFIG', f'ai-workflow.yaml 未配置 verify.{tier_key}，请补充配置或显式传入 --plan/--plan-json')
    checks = []
    for index, argv in enumerate(commands, 1):
        covers = ['format', 'analyze', 'test'] if index == 1 else ['analyze']
        checks.append({'id': f'check-{index}', 'argv': argv, 'cwd': '.', 'timeout': 300,
                       'covers': covers, 'acceptance': list(acceptance)})
    return {'version': 1, 'checks': checks}


def derive_baselines(root, details):
    from baseline_config import resolve_baselines
    from workflow_config import load as load_config

    paths = resolve_baselines(root, details.get('scope') or [], load_config(root))
    if not paths:
        raise ArgumentError('details.baseline 缺失且 ai-workflow.yaml 未配置 baseline.required')
    return paths


def handle_prepare(args, engine, root, database):
    details = input_json(args, 'details')
    if not isinstance(details, dict):
        raise ArgumentError('details 必须为任务协议 v2 对象，不得为 null')
    if bool(args.executor) != bool(args.session):
        raise ArgumentError('--executor 与 --session 必须成对提供')
    if args.request_tier and not args.session:
        raise ArgumentError('--request-tier 需要同时提供 --executor 与 --session')
    if args.request_tier and args.db and database != default_db(root).resolve():
        raise ArgumentError('聊天确认须与宿主使用同一默认状态库')
    tier_key = TIER_MAP[args.tier]
    if not details.get('baseline'):
        details = dict(details, baseline=derive_baselines(root, details))
    plan = (derive_plan(root, tier_key, args.acceptance)
            if args.plan is None and args.plan_json is None else input_json(args, 'plan'))
    req = args.request
    task = engine.create(args.task, tier_key, args.acceptance, plan, f'{req}:create', details=details)
    if args.executor and args.session:
        task = engine.bind_executor(args.task, task['version'], f'{req}:bind', args.executor, args.session)
    confirmation = None
    if args.request_tier:
        from host_gate import request_chat_confirmation
        confirmation = request_chat_confirmation(
            root, task, task['version'], args.session, 'tier_confirmation', f'{req}:confirm')
    return task, confirmation


def handle_begin(args, engine):
    from workflow_engine.model import EngineError
    from workflow_engine.protocol import readiness

    if not 0 < args.max_bytes <= 1048576:
        raise ArgumentError('max-bytes 必须在 1 到 1048576 之间')
    task = engine.status(args.task)
    if task.get('protocol_version') != 2:
        raise EngineError('PROTOCOL_REQUIRED', '旧任务必须先 adopt-protocol，CLI 不执行旧协议变更')
    if args.version is not None and task['version'] != args.version:
        raise EngineError('VERSION_CONFLICT', '版本不匹配，请重新读取 status')
    if task.get('state') != 'created':
        raise EngineError('INVALID_STATE', f"当前状态 {task.get('state')} 不能执行 begin")
    blockers = [item for item in readiness(task) if item not in ('executor_binding', 'baseline')]
    if blockers:
        raise EngineError('NOT_READY', '任务尚缺前置条件，不能开工：' + ', '.join(blockers))
    req = args.request
    current_round = task['rounds'][-1]
    if current_round.get('executor') != args.executor or current_round.get('session_id') != args.session:
        task = engine.bind_executor(args.task, task['version'], f'{req}:bind', args.executor, args.session)
    documents, receipts = collect_baseline_batch(args, engine, task, list(dict.fromkeys(task['baseline'])))
    task = engine.register_baselines(args.task, task['version'], f'{req}:baseline', receipts)
    task = engine.start(args.task, task['version'], f'{req}:start')
    if args.tdd is not None or args.tdd_json is not None:
        task = engine.record_tdd(args.task, task['version'], f'{req}:tdd', input_json(args, 'tdd'))
    return task, documents


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        if hasattr(args, 'request') and args.request is None:
            args.request = uuid.uuid4().hex
        document = None
        documents = None
        confirmation = None
        from workflow_engine.engine import Engine
        root = Path(args.root).resolve()
        raw_database = Path(args.db) if args.db else default_db(root)
        if args.action == 'list':
            from session_binding import list_tasks
            from workflow_engine.model import EngineError

            try:
                tasks = list_tasks(root, raw_database, active_only=args.active)
            except ValueError as exc:
                message = str(exc)
                code = message.split('：', 1)[0] if '：' in message else 'BLOCKED'
                raise EngineError(code, message) from exc
            print(json.dumps({'ok': True, 'tasks': tasks}, ensure_ascii=False))
            return 0
        database = raw_database.resolve()
        if args.action == 'request-confirmation' and args.db and database != default_db(root).resolve():
            raise ArgumentError('聊天确认须与宿主使用同一默认状态库')
        if args.action in ('status', 'snapshot', 'history', 'progress', 'request-confirmation', 'begin') and not database.is_file():
            from workflow_engine.model import EngineError
            raise EngineError('NOT_FOUND', '状态库不存在，未执行初始化')
        engine = Engine(root, database)
        if args.action == 'create':
            details = input_json(args, 'details')
            if not isinstance(details, dict):
                raise ArgumentError('details 必须为任务协议 v2 对象，不得为 null')
            value = engine.create(args.task, TIER_MAP[args.tier], args.acceptance, input_json(args, 'plan'), args.request, details=details)
        elif args.action == 'prepare':
            value, confirmation = handle_prepare(args, engine, root, database)
        elif args.action == 'begin':
            value, documents = handle_begin(args, engine)
        elif args.action == 'progress':
            from agent_progress import project_progress
            value = project_progress(engine.status(args.task))
        elif args.action in ('status', 'snapshot', 'history'):
            value = getattr(engine, args.action)(args.task)
        elif args.action == 'request-confirmation':
            from host_gate import request_chat_confirmation
            value = request_chat_confirmation(root, engine.status(args.task), args.version, args.session, args.kind, args.request)
        else:
            task = engine.status(args.task)
            if task.get('protocol_version') != 2 and args.action != 'adopt-protocol':
                from workflow_engine.model import EngineError
                raise EngineError('PROTOCOL_REQUIRED', '旧任务必须先 adopt-protocol，CLI 不执行旧协议变更')
            operation = getattr(engine, args.action.replace('-', '_'), None)
            parameters = [args.task, args.version, args.request]
            if args.action in ('confirm-plan', 'confirm-tier', 'approve-proposal', 'return-task'):
                human_confirmation('确认已由人工审阅此操作')
            if args.action == 'confirm-plan':
                parameters.append(args.digest)
            elif args.action == 'confirm-tier':
                parameters.append(args.actor)
            elif args.action == 'approve-proposal':
                parameters += [args.actor, args.digest]
            elif args.action == 'return-task':
                parameters += [args.reason, args.actor]
            elif args.action == 'bind-executor':
                parameters += [args.executor, args.session]
            elif args.action in ('register-baseline', 'record-tdd', 'review', 'update-task', 'adopt-protocol', 'repair', 'refine-steps'):
                parameters.append(input_json(args, 'file'))
                if args.action in ('repair', 'refine-steps'):
                    parameters.append(args.reason)
            elif args.action == 'finish-step':
                parameters += [args.step, args.summary]
            elif args.action == 'sync-review-card':
                parameters += [args.round, {'path': args.card_path, 'id': args.card_id}]
            elif args.action == 'read-baseline':
                if not 0 < args.max_bytes <= 1048576:
                    raise ArgumentError('max-bytes 必须在 1 到 1048576 之间')
                if args.all or len(args.path) > 1:
                    return read_baseline_batch(args, engine, task)
                document, data = baseline_document(engine, args.path[0], args.max_bytes)
                if document['truncated']:
                    print(json.dumps(dict(ok=False, code='BASELINE_TRUNCATED', document=document, task=task), ensure_ascii=False))
                    return 2
                parameters.append(baseline_receipt(args, task, document, data))
                operation = engine.register_baseline
            value = operation(*parameters)
            if args.action == 'finish-step' and args.finish_implementation:
                value = engine.finish_implementation(args.task, value['version'], f'{args.request}:finish-impl')
        expected_state = {'run': 'passed', 'review': 'review_passed', 'sync-review-card': 'review_passed'}
        passed = args.action not in expected_state or value.get('state') == expected_state[args.action]
        key = {'history': 'history', 'progress': 'progress', 'request-confirmation': 'confirmation'}.get(args.action, 'task')
        output = {'ok': passed, key: value}
        if document is not None:
            output['document'] = document
        if documents is not None:
            output['version'] = value['version']
            output['documents'] = documents
        if confirmation is not None:
            output['confirmation'] = confirmation
        if key == 'task' and isinstance(value, dict) and value.get('protocol_version') == 2 and args.action not in ('status', 'snapshot'):
            from agent_progress import project_progress
            output['progress'] = project_progress(value)
        print(json.dumps(output, ensure_ascii=False))
        return 0 if passed else 1
    except Exception as error:
        code = 'ARGUMENT' if isinstance(error, ArgumentError) else getattr(error, 'code', 'BLOCKED')
        message = str(error) if isinstance(error, ArgumentError) or hasattr(error, 'code') else '引擎不可用或输入无效'
        print(json.dumps({'ok': False, 'code': code, 'message': message}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
