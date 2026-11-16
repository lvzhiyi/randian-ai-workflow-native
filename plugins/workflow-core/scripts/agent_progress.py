"""从任务当前轮次生成宿主无关的只读进度，不维护第二份任务状态。"""
from urllib.parse import quote

from workflow_engine.model import EngineError


def project_progress(task):
    """稳定标识不依赖标题、数组位置或宿主；阶段结论始终保留引擎状态。"""
    round_id = task.get('current_round')
    rounds = [item for item in task.get('rounds', []) if item.get('id') == round_id]
    if not round_id or len(rounds) != 1:
        raise EngineError('PROGRESS_UNAVAILABLE', '无法唯一定位当前轮次，未投影旧轮次')
    state = task['state']
    todos = []
    current = None
    seen = set()
    for step in rounds[0]['todos']:
        step_id = step['id']
        if step_id in seen:
            raise EngineError('PROGRESS_UNAVAILABLE', '当前轮次步骤 ID 重复')
        seen.add(step_id)
        # 分隔符也编码，避免任务、轮次、步骤之间产生拼接碰撞。
        identity = '/'.join(quote(value, safe='') for value in (task['id'], round_id, step_id))
        status = 'completed' if step['status'] == 'done' else 'pending'
        if status == 'pending' and current is None:
            current = identity
            if state == 'implementing':
                status = 'in_progress'
        todos.append(dict(id=identity, step_id=step_id, content=step['title'], status=status))
    labels = {
        'created': '待就绪，实施未开始',
        'implementing': '实施中' if current else '实施步骤已完成，待进入验证',
        'pending_verification': '实施步骤已完成，待验证',
        'running': '验证执行中，实施清单不表示验证结果',
        'failed': '验证失败，已暂停，待修复',
        'stale': '证据失效，已暂停，待重新核实与修复',
        'passed': '验证通过，待评审',
        'review_failed': '评审失败，已暂停，待修复',
        'review_passed': 'Agent 评审通过，不等于人工验收或交付',
        'cancelled': '任务已取消，已暂停',
    }
    completed = sum(todo['status'] == 'completed' for todo in todos)
    text = '{}：实施步骤 {}/{}；{}'.format(task['id'], completed, len(todos), labels.get(state, '当前状态 ' + state))
    return dict(task_id=task['id'], round_id=round_id, version=task.get('version'),
                control_digest=task.get('control_digest'), state=state, phase=task.get('phase'),
                current=current, todos=todos, text=text)
