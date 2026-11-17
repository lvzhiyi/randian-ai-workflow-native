"""任务协议 v2：轮次拥有阶段与证据，任务顶层仅为兼容投影。"""
import copy
import hashlib
import json
import time
import uuid
from pathlib import Path

from .model import EngineError, digest
from .policy import validate_plan
from .snapshot import capture
from .config_checks import enforce, configured


def require(condition, code, message):
    if not condition:
        raise EngineError(code, message)


def current(task):
    return task['rounds'][-1]


def control(task):
    return digest({key: task.get(key) for key in ('tier', 'acceptance', 'plan', 'goal', 'scope', 'source', 'dependencies', 'baseline', 'steps', 'proposal')})


def evidence(task, kind):
    return [e for e in current(task)['evidence'] if e['kind'] == kind and e['control_digest'] == task['control_digest'] and e.get('valid', True)]


def validate_steps(steps):
    require(isinstance(steps, list) and all(isinstance(s, dict) and isinstance(s.get('id'), str) and s['id'].strip() and isinstance(s.get('title'), str) and s['title'].strip() for s in steps), 'INPUT_INVALID', '步骤需非空字符串 id/title')
    require(len({s['id'] for s in steps}) == len(steps), 'INPUT_INVALID', '步骤 id 不可重复')
    return steps


def baseline_matches(task, receipt):
    r = current(task)
    return receipt.get('executor') == r.get('executor') and receipt.get('session_id') == r.get('session_id') and receipt.get('binding_version') == r.get('binding_version')


def readiness(task):
    out = [key for key in ('goal', 'scope', 'source', 'acceptance') if not task.get(key)]
    dependencies = task.get('dependencies')
    if not isinstance(dependencies, list) or any(not isinstance(d, dict) or not d.get('id') or d.get('status') != 'done' for d in dependencies):
        out.append('dependencies')
    if not evidence(task, 'tier_confirmation'):
        out.append('tier_confirmation')
    if task['tier'] == 'full' and not evidence(task, 'approval'):
        out.append('approval')
    todos = current(task)['todos']
    if not todos or (task['tier'] == 'standard' and not 3 <= len(task.get('steps', [])) <= 5):
        out.append('steps')
    if task['tier'] == 'full' and not all(task.get('proposal', {}).get(k) for k in ('goal', 'scope', 'impact', 'risk', 'rollback', 'acceptance')):
        out.append('proposal')
    if not current(task).get('executor') or not current(task).get('session_id'):
        out.append('executor_binding')
    paths = {e['data']['path'] for e in evidence(task, 'baseline') if baseline_matches(task, e['data'])}
    if not task.get('baseline') or not set(task['baseline']) <= paths:
        out.append('baseline')
    return out


class ProtocolMixin:
    def create(self, task_id, tier, acceptance, plan, request_id, details=None):
        if details is None:
            return super().create(task_id, tier, acceptance, plan, request_id)
        require(isinstance(details, dict), 'INPUT_INVALID', 'details 必须为对象')
        require(tier in ('light', 'standard', 'full'), 'INPUT_INVALID', '档位无效')
        require(isinstance(task_id, str) and task_id.strip(), 'INPUT_INVALID', '任务标识为空')
        plan_hash = validate_plan(plan, acceptance)
        enforce(self.root, tier, plan)
        payload = dict(action='create_v2', id=task_id, tier=tier, acceptance=acceptance, plan=plan, details=details, root=str(self.root))
        with self.store.transaction() as db:
            previous = self.store.replay(db, request_id, payload)
            if previous is not None:
                return previous
            require(not db.execute('SELECT 1 FROM tasks WHERE id=?', (task_id,)).fetchone(), 'TASK_EXISTS', '任务已存在')
            allowed = {'goal', 'scope', 'source', 'dependencies', 'baseline', 'steps', 'proposal', 'note'}
            require(set(details) <= allowed, 'INPUT_INVALID', '未知任务字段')
            task = dict(copy.deepcopy(details), id=task_id, tier=tier, acceptance=acceptance, plan=copy.deepcopy(plan), plan_digest=plan_hash, root=str(self.root), version=1, protocol_version=2, rounds=[], state='created', phase='planning', results=[], confirmed_digest=None, snapshot=capture(self.root, plan_hash))
            task['control_digest'] = control(task)
            task['verify_config_digest'] = enforce(self.root, task['tier'], task['plan'])
            self._new_round(task)
            self._view(task)
            self.store.save(db, task, 'create', request_id, payload)
            return task

    def adopt_protocol(self, task_id, version, request, details):
        """显式升级旧任务，保留旧事件但不复用不完整的首期证据。"""
        payload = dict(action='adopt_protocol', id=task_id, version=version, details=details, root=str(self.root))
        with self.store.transaction() as db:
            previous = self.store.replay(db, request, payload)
            if previous is not None:
                return self._refresh(db, self._load(db, task_id))
            task = self._load(db, task_id)
            self._version(task, version)
            require(task.get('protocol_version') != 2 and task['state'] not in ('running', 'cancelled'), 'STATE_INVALID', '只能升级未取消的旧任务')
            allowed = {'goal', 'scope', 'source', 'dependencies', 'baseline', 'steps', 'proposal', 'note'}
            require(isinstance(details, dict) and set(details) <= allowed, 'INPUT_INVALID', '升级详情字段无效')
            task.update(copy.deepcopy(details))
            task.update(protocol_version=2, rounds=[], confirmed_digest=None)
            task['control_digest'] = control(task)
            task['verify_config_digest'] = enforce(self.root, task['tier'], task['plan'])
            self._new_round(task)
            task['version'] += 1
            self._view(task)
            self.store.save(db, task, 'adopt_protocol', request, payload)
            return task

    def _new_round(self, task):
        steps = validate_steps(task.get('steps', []))
        round_id = uuid.uuid4().hex
        task.update(current_round=round_id, state='created', phase='planning', results=[])
        task['rounds'].append(dict(id=round_id, state='created', phase='planning', control_digest=task['control_digest'], todos=[dict(id=s['id'], title=s['title'], status='pending') for s in steps], attempts=[], evidence=[], executor=None, session_id=None, binding_version=0))

    def _view(self, task):
        if task.get('protocol_version') != 2:
            return super()._view(task)
        missing = readiness(task)
        if task['state'] != 'review_passed':
            missing.append('review')
        if task['state'] not in ('passed', 'review_failed', 'review_passed'):
            missing.append('checks')
        try:
            signature = enforce(self.root, task['tier'], task['plan'])
            if signature != task.get('verify_config_digest'):
                missing.append('verify_config')
        except EngineError:
            missing.append('verify_config')
        if task['state'] == 'stale':
            missing.append('snapshot')
        current(task).update(state=task['state'], phase=task['phase'])
        task['missing'] = missing
        return task

    def _refresh(self, db, task):
        # 只读投影；持久化失效只在下一次写操作中发生。
        if task.get('protocol_version') != 2:
            if task['state'] in ('passed', 'completed'):
                try:
                    changed = capture(self.root, task['plan_digest']) != task['snapshot']
                except EngineError:
                    changed = True
                if changed:
                    task.update(state='stale', phase='verification')
            return self._view(task)
        try:
            snapshot = capture(self.root, task['plan_digest'])
            _, signature = configured(self.root, task['tier'])
            changed = snapshot != task['snapshot'] or signature != task.get('verify_config_digest')
        except EngineError:
            changed = True
        if changed:
            for attempt in current(task)['attempts']:
                if attempt['stage'] in ('verification', 'review') and attempt['status'] == 'passed':
                    attempt['status'] = 'invalidated'
                    for item in current(task)['evidence']:
                        if item['id'] == attempt['evidence_id']:
                            item['valid'] = False
            if task['state'] in ('passed', 'review_passed', 'review_failed'):
                task.update(state='stale', phase='verification')
        for item in evidence(task, 'baseline'):
            try:
                data = self._baseline_bytes(item['data']['path'])
                valid = hashlib.sha256(data).hexdigest() == item['data']['sha256']
            except (OSError, EngineError):
                valid = False
            if not valid:
                item['valid'] = False
                if task['state'] not in ('cancelled', 'created'):
                    task.update(state='stale', phase='planning')
        return self._view(task)

    def status(self, task_id):
        with self.store.read() as db:
            return self._refresh(db, self._load(db, task_id))

    def task_for_session(self, session_id, executor=None):
        """只读解析唯一活动绑定；歧义拒绝，不借助父进程环境变量。"""
        require(isinstance(session_id, str) and session_id.strip(), 'INPUT_INVALID', '会话不可为空')
        with self.store.read() as db:
            candidates = []
            for row in db.execute('SELECT data FROM tasks'):
                task = json.loads(row[0])
                if task.get('root') != str(self.root) or task.get('protocol_version') != 2:
                    continue
                task = self._refresh(db, task)
                r = current(task)
                if task['state'] in ('cancelled', 'review_passed'):
                    continue
                if r.get('session_id') == session_id and (executor is None or r.get('executor') == executor):
                    candidates.append(task)
            require(len(candidates) <= 1, 'SESSION_AMBIGUOUS', '会话绑定多个活动任务，须显式消歧')
            return self._refresh(db, candidates[0]) if candidates else None

    def snapshot(self, task_id):
        return self.status(task_id)

    def history(self, task_id):
        with self.store.read() as db:
            self._load(db, task_id)
            return [dict(seq=row[0], action=row[1], task=json.loads(row[2])) for row in db.execute('SELECT seq,action,data FROM events WHERE task_id=? ORDER BY seq', (task_id,))]

    def _record(self, task, kind, data):
        item = dict(id=uuid.uuid4().hex, kind=kind, round_id=task['current_round'], control_digest=task['control_digest'], executor=current(task).get('executor'), session_id=current(task).get('session_id'), binding_version=current(task).get('binding_version'), data=copy.deepcopy(data), valid=True)
        current(task)['evidence'].append(item)
        return item

    def _attempt(self, task, stage, status, data):
        item = self._record(task, stage, data)
        current(task)['attempts'].append(dict(id=uuid.uuid4().hex, stage=stage, status=status, evidence_id=item['id'], round_id=task['current_round'], control_digest=task['control_digest'], snapshot=task['snapshot'], executor=current(task).get('executor'), session_id=current(task).get('session_id'), binding_version=current(task).get('binding_version')))

    def _change(self, action, task_id, version, request, data, operation):
        payload = dict(action=action, id=task_id, version=version, data=data, root=str(self.root))
        with self.store.transaction() as db:
            previous = self.store.replay(db, request, payload)
            if previous is not None:
                return self._refresh(db, self._load(db, task_id))
            task = self._load(db, task_id)
            self._version(task, version)
            require(task.get('protocol_version') == 2, 'PROTOCOL_REQUIRED', '此操作需要任务协议 v2')
            require(task['state'] != 'running', 'ACTIVE_OPERATION', '验证正在执行')
            require(task['state'] != 'cancelled' or action == 'return_task', 'STATE_INVALID', '取消任务须人工退回新轮次')
            self._refresh(db, task)
            operation(task)
            task['version'] += 1
            r = current(task)
            r.update(state=task['state'], phase=task['phase'], control_digest=task['control_digest'])
            task['activity'] = dict(action=action, at=time.time(), round_id=task['current_round'], state=task['state'])
            self._view(task)
            self.store.save(db, task, action, request, payload)
            return task

    def confirm_tier(self, task_id, version, request, actor, selected_tier=None):
        def apply(task):
            require(isinstance(actor, str) and actor.strip(), 'INPUT_INVALID', '需人工流程操作者')
            data = dict(actor=actor, human_process=True)
            if selected_tier is not None:
                require(selected_tier in ('light', 'standard', 'full'), 'INPUT_INVALID', '档位无效')
                require(task['state'] == 'created' and not evidence(task, 'tier_confirmation'), 'STATE_INVALID', '当前轮次未等待定档')
                if selected_tier != task['tier']:
                    task['tier'] = selected_tier
                    try:
                        task['verify_config_digest'] = enforce(self.root, selected_tier, task['plan'])
                    except EngineError as error:
                        if error.code not in ('VERIFY_REQUIRED', 'VERIFY_CONFIG'):
                            raise
                        # 先记住用户的选择，由 Agent 补齐该档位的验证计划。
                        task['verify_config_digest'] = None
                    self._invalidate_control(task)
                data['selected'] = True
            self._record(task, 'tier_confirmation', dict(data, tier=task['tier']))
        payload = actor if selected_tier is None else [actor, selected_tier]
        return self._change('confirm_tier', task_id, version, request, payload, apply)

    def approve_proposal(self, task_id, version, request, actor, control_digest):
        def apply(task):
            require(actor and control_digest == task['control_digest'], 'APPROVAL_INVALID', '批准版本不匹配')
            require(task['tier'] == 'full' and 'proposal' not in readiness(task) and 'steps' not in readiness(task), 'PROPOSAL_REQUIRED', '完整方案与 todos 不完整')
            self._record(task, 'approval', dict(actor=actor, human_process=True))
        return self._change('approve_proposal', task_id, version, request, [actor, control_digest], apply)

    def read_baseline_bytes(self, path, limit=None):
        require(limit is None or (type(limit) is int and limit > 0), 'BASELINE_LIMIT', '读取限额必须为正整数')
        require(isinstance(path, str) and path and not Path(path).is_absolute() and '..' not in Path(path).parts, 'BASELINE_INVALID', '基线路径越界')
        target = self.root / path
        require(target.resolve().is_relative_to(self.root) and not any(p.is_symlink() for p in [target, *target.parents] if p != self.root.parent), 'BASELINE_INVALID', '基线路径不可链接')
        require(target.is_file(), 'BASELINE_INVALID', '基线不是文件')
        with target.open('rb') as handle:
            data = handle.read(min(limit, 1048577) if limit is not None else 1048577)
        if limit is None:
            require(len(data) <= 1048576, 'BASELINE_LIMIT', '基线超过 1MiB 上限')
        return data

    def _baseline_bytes(self, path):
        return self.read_baseline_bytes(path)

    def register_baseline(self, task_id, version, request, receipt):
        def apply(task):
            require(isinstance(receipt, dict) and receipt.get('complete') is True and receipt.get('executor') and receipt.get('round_id') == task['current_round'], 'BASELINE_INVALID', '需要完整读取、执行者与当前轮次')
            require(receipt.get('path') in task.get('baseline', []), 'BASELINE_INVALID', '未声明的基线')
            require(receipt.get('executor') == current(task).get('executor') and receipt.get('session_id') == current(task).get('session_id'), 'BASELINE_INVALID', '回执执行者与会话须匹配当前绑定')
            data = self._baseline_bytes(receipt['path'])
            require(type(receipt.get('bytes_read')) is int and receipt['bytes_read'] == len(data) and receipt.get('sha256') == hashlib.sha256(data).hexdigest(), 'BASELINE_INVALID', '基线缺失、截断或摘要不符')
            bound_receipt = dict(receipt, binding_version=current(task)['binding_version'])
            self._record(task, 'baseline', bound_receipt)
        return self._change('register_baseline', task_id, version, request, receipt, apply)

    def start(self, task_id, expected_version, request_id):
        if self.status(task_id).get('protocol_version') != 2:
            return super().start(task_id, expected_version, request_id)
        def apply(task):
            require(not readiness(task), 'MISSING', '就绪条件缺失：' + ', '.join(readiness(task)))
            signature = enforce(self.root, task['tier'], task['plan'])
            require(signature == task.get('verify_config_digest'), 'VERIFY_CONFIG_CHANGED', '验证配置变化须更新任务验证计划')
            require(task['state'] in ('created', 'implementing', 'stale'), 'STATE_INVALID', '当前阶段不能实施')
            task.update(state='implementing', phase='implementation')
        return self._change('start', task_id, expected_version, request_id, None, apply)

    def record_tdd(self, task_id, version, request, record):
        def apply(task):
            require(task['state'] == 'implementing', 'STATE_INVALID', '尚未实施')
            require(isinstance(record, dict) and type(record.get('adopted')) is bool and (record['adopted'] or (isinstance(record.get('reason'), str) and record['reason'].strip() and isinstance(record.get('alternative_validation'), str) and record['alternative_validation'].strip())), 'TDD_INVALID', '不采用 TDD 需原因与替代验证')
            require('step_id' not in record or record['step_id'] in {s['id'] for s in current(task)['todos'] if s['status'] != 'done'}, 'TDD_INVALID', '步骤决策须引用有效未完成步骤')
            self._record(task, 'tdd', record)
        return self._change('record_tdd', task_id, version, request, record, apply)

    def finish_step(self, task_id, version, request, step_id, summary):
        def apply(task):
            require(task['state'] == 'implementing' and summary, 'STATE_INVALID', '需处于实施阶段并提供完成记录')
            pending = [s for s in current(task)['todos'] if s['status'] != 'done']
            require(pending and pending[0]['id'] == step_id, 'STEP_INVALID', '只能完成当前步骤')
            require(not readiness(task), 'MISSING', '实施证据缺失或失效')
            require(any(e['executor'] == current(task)['executor'] and e['session_id'] == current(task)['session_id'] and e['binding_version'] == current(task)['binding_version'] and ('step_id' not in e['data'] or e['data']['step_id'] == step_id) for e in evidence(task, 'tdd')), 'TDD_INVALID', '需当前执行者的任务级或当前步骤 TDD 决策')
            pending[0].update(status='done', summary=summary)
            self._attempt(task, 'implementation', 'passed', dict(step_id=step_id, summary=summary))
        return self._change('finish_step', task_id, version, request, [step_id, summary], apply)

    def finish_implementation(self, task_id, version, request):
        def apply(task):
            require(task['state'] == 'implementing' and current(task)['todos'] and all(s['status'] == 'done' for s in current(task)['todos']), 'STEPS_INCOMPLETE', '实施步骤未完成')
            require(not readiness(task), 'MISSING', '就绪证据失效')
            for attempt in current(task)['attempts']:
                if attempt['stage'] == 'repair' and attempt['status'] == 'running':
                    attempt['status'] = 'passed'
            task.update(state='pending_verification', phase='verification')
        return self._change('finish_implementation', task_id, version, request, None, apply)

    def review(self, task_id, version, request, report):
        def apply(task):
            require(task['state'] in ('passed', 'review_failed', 'review_passed'), 'CHECKS_REQUIRED', '需当前版本验证全部通过')
            require(isinstance(report, dict) and report.get('snapshot') == task['snapshot'] and report.get('control_digest') == task['control_digest'] and report.get('round_id') == task['current_round'] and report.get('executor'), 'REVIEW_INVALID', '评审版本或执行者缺失')
            axes = report.get('axes', {})
            require(set(axes) == {'spec', 'standards'}, 'REVIEW_INVALID', '需双轴结构化结论')
            passed = True
            for name, axis in axes.items():
                require(isinstance(axis, dict) and axis.get('conclusion') in ('pass', 'fail') and isinstance(axis.get('findings'), list), 'REVIEW_INVALID', '评审轴结构无效')
                for finding in axis['findings']:
                    require(isinstance(finding, dict) and finding.get('id') and type(finding.get('required')) is bool and type(finding.get('resolved')) is bool and finding.get('message'), 'REVIEW_INVALID', '问题需 id/required/resolved/message')
                unresolved = current(task).setdefault('required_findings', {}).setdefault(name, {})
                for finding in axis['findings']:
                    if finding['required'] or finding['id'] in unresolved:
                        unresolved[finding['id']] = finding['resolved']
                passed = passed and all(unresolved.values()) and axis['conclusion'] == 'pass' and not any(f['required'] and not f['resolved'] for f in axis['findings'])
            self._attempt(task, 'review', 'passed' if passed else 'failed', report)
            task.update(state='review_passed' if passed else 'review_failed', phase='done' if passed else 'review')
        return self._change('review', task_id, version, request, report, apply)

    def _invalidate_control(self, task):
        task['control_digest'] = control(task)
        for item in current(task)['evidence']:
            item['valid'] = False
        for attempt in current(task)['attempts']:
            if attempt['status'] == 'passed':
                attempt['status'] = 'invalidated'
        current(task)['todos'] = [dict(id=s['id'], title=s['title'], status='pending') for s in task.get('steps', [])]
        task.update(state='created', phase='planning', results=[])

    def update_task(self, task_id, version, request, changes):
        def apply(task):
            allowed = {'goal', 'scope', 'source', 'dependencies', 'baseline', 'steps', 'proposal', 'note', 'tier', 'acceptance', 'plan'}
            require(isinstance(changes, dict) and set(changes) <= allowed, 'INPUT_INVALID', '未知控制字段')
            # 初次补齐定档后才需要的材料时，沿用用户对同一档位和范围的选择。
            changed = {key for key, value in changes.items() if value != task.get(key)} - {'note'}
            fillable = set(task['missing']) & {'steps', 'proposal'}
            if 'verify_config' in task['missing']:
                fillable.add('plan')
            selection = next((e for e in evidence(task, 'tier_confirmation') if e['data'].get('selected')), None)
            keep_selection = (selection and task['state'] == 'created' and changed <= fillable
                              and not evidence(task, 'approval'))
            task.update(copy.deepcopy(changes))
            require(task['tier'] in ('light', 'standard', 'full'), 'INPUT_INVALID', '档位无效')
            validate_steps(task.get('steps', []))
            task['plan_digest'] = validate_plan(task['plan'], task['acceptance'])
            task['verify_config_digest'] = enforce(self.root, task['tier'], task['plan'])
            if task['control_digest'] != control(task):
                self._invalidate_control(task)
                if keep_selection:
                    self._record(task, 'tier_confirmation', dict(selection['data'], carried_from=selection['id']))
        return self._change('update_task', task_id, version, request, changes, apply)

    def bind_executor(self, task_id, version, request, executor, session_id):
        def apply(task):
            require(isinstance(executor, str) and executor.strip() and isinstance(session_id, str) and session_id.strip(), 'INPUT_INVALID', '执行者与会话不可为空')
            r = current(task)
            if (r.get('executor'), r.get('session_id')) != (executor, session_id):
                r.update(executor=executor, session_id=session_id, binding_version=r.get('binding_version', 0)+1)
                for attempt in r['attempts']:
                    if attempt['stage'] in ('verification', 'review') and attempt['status'] == 'passed':
                        attempt['status'] = 'invalidated'
                if task['state'] in ('passed', 'review_passed', 'review_failed'):
                    task.update(state='stale', phase='planning')
            self._record(task, 'executor_binding', {'executor': executor, 'session_id': session_id, 'binding_version': r['binding_version']})
        return self._change('bind_executor', task_id, version, request, [executor, session_id], apply)

    def refine_steps(self, task_id, version, request, steps, reason):
        def apply(task):
            require(task['state'] in ('created', 'implementing', 'failed', 'review_failed', 'stale'), 'STATE_INVALID', '当前阶段不可细化步骤')
            require(isinstance(reason, str) and reason.strip(), 'INPUT_INVALID', '细化需审计原因')
            validate_steps(steps)
            existing = {s['id']: s for s in current(task)['todos']}
            require(steps and all(set(s) == {'id', 'title', 'parent_id'} and s['parent_id'] in existing and s['id'] not in existing for s in steps), 'INPUT_INVALID', '细化仅追加具有已有父步骤的新 todo，不可修改控制字段')
            current(task)['todos'].extend(dict(id=s['id'], title=s['title'], parent_id=s['parent_id'], status='pending', refinement=True) for s in steps)
            self._record(task, 'steps_refined', {'steps': steps, 'reason': reason, 'scope': task['scope'], 'acceptance': task['acceptance']})
            if task['state'] not in ('created', 'implementing'):
                task.update(state='implementing', phase='implementation')
        return self._change('refine_steps', task_id, version, request, [steps, reason], apply)

    def repair(self, task_id, version, request, steps, reason):
        def apply(task):
            require(task['state'] in ('failed', 'review_failed', 'stale'), 'STATE_INVALID', '仅失败或失效任务可同轮修复')
            require(isinstance(reason, str) and reason.strip(), 'INPUT_INVALID', '修复需原因')
            validate_steps(steps)
            require(steps and not ({s['id'] for s in steps} & {s['id'] for s in current(task)['todos']}), 'INPUT_INVALID', '修复步骤需唯一新 id')
            require(not readiness(task), 'MISSING', '修复前需恢复当前执行者就绪证据')
            current(task)['todos'].extend(dict(id=s['id'], title=s['title'], status='pending', repair=True) for s in steps)
            self._attempt(task, 'repair', 'running', {'reason': reason, 'steps': steps, 'scope': task['scope']})
            task.update(state='implementing', phase='implementation')
        return self._change('repair', task_id, version, request, [steps, reason], apply)

    def resume(self, task_id, version, request):
        def apply(task):
            # 同轮继续只记录活动，不推测阻塞、跳过门禁或复活已取消任务。
            self._record(task, 'resume', {'state': task['state']})
        return self._change('resume', task_id, version, request, None, apply)

    def return_task(self, task_id, version, request, reason, actor):
        def apply(task):
            require(reason and actor, 'INPUT_INVALID', '退回需要人工操作者与原因')
            current(task)['return'] = dict(reason=reason, actor=actor)
            self._new_round(task)
        return self._change('return_task', task_id, version, request, [reason, actor], apply)

    def cancel(self, task_id, expected_version, request_id):
        if self.status(task_id).get('protocol_version') != 2:
            return super().cancel(task_id, expected_version, request_id)
        def apply(task):
            task.update(state='cancelled', phase='done')
        return self._change('cancel', task_id, expected_version, request_id, None, apply)

    def complete(self, task_id, expected_version, request_id):
        if self.status(task_id).get('protocol_version') != 2:
            return super().complete(task_id, expected_version, request_id)
        def apply(task):
            require(task['state'] == 'review_passed' and not task['missing'], 'MISSING', '尚未完成最终评审')
        return self._change('complete', task_id, expected_version, request_id, None, apply)
