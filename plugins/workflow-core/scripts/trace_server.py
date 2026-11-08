#!/usr/bin/env python3
"""执行轨迹的开关与实时页面（只监听本机，仅用 Python 标准库）。

用法：trace_server.py on | off | status | serve [--port N]
退出码：0 成功，2 执行受阻。
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).parent))
from trace_hook import SESSION_ID, trace_dir  # noqa: E402
from workflow_trace import CSS, build_checks, load_verify_config, make_step, status_of  # noqa: E402

FIRST_PORT = 8770
PORT_TRIES = 10
RETENTION_DAYS = 7
APP_ID = 'workflow-trace'
# 框架转交的消息也会触发 UserPromptSubmit，不是用户的新一轮提问。
SYSTEM_PROMPTS = ('<agent-message', '<task-notification', '<side-sessions-event', '<ci-monitor-event')


def read_events(path):
    """读取事件日志，跳过未写完或损坏的行，按时间排序（异步钩子可能乱序落盘）。"""
    events = []
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return sorted(events, key=lambda item: item.get('ts', 0))


def new_step(event, config_for):
    """由 PreToolUse 或缺少开始事件的结束事件生成步骤；内部调用返回 None。"""
    cwd = event.get('cwd') or '.'
    step = make_step(event.get('tool_name', ''), event.get('input') or {}, event['ts'], config_for(cwd), Path(cwd))
    if step is not None:
        step.update(id=event.get('tool_use_id'), live=True, agent=event.get('agent_type') or event.get('agent_id') or '')
    return step


def reduce_events(events, config_for):
    """把事件序列还原成轮次和步骤。

    参数 [events]：read_events 的结果；[config_for]：由 cwd 返回 verify 命令配置的函数。
    返回：{turns, state, cwd, last}；state 为 running 或 idle。
    """
    turns, by_id, current, pending_slash, state, cwd = [], {}, None, None, 'idle', ''

    def turn_at(stamp):
        nonlocal current
        if current is None:
            current = {'prompt': '（开启轨迹时会话已在进行）', 'time': stamp, 'steps': []}
            turns.append(current)
        return current

    def abandon():
        # 用户取消工具时不会有结束事件，回合结束后不再显示“运行中”。
        for step in by_id.values():
            if step['end'] is None and not step['agent']:
                step['live'] = False

    for event in events:
        name, stamp = event.get('event'), event.get('ts', 0)
        cwd = event.get('cwd') or cwd
        if name == 'UserPromptSubmit' and event.get('prompt', '').lstrip().startswith(SYSTEM_PROMPTS):
            continue
        if name == 'UserPromptSubmit':
            abandon()
            current = {'prompt': event.get('prompt', ''), 'time': stamp, 'steps': []}
            turns.append(current)
            if pending_slash:
                current['steps'].append(pending_slash)
                pending_slash = None
            state = 'running'
        elif name == 'UserPromptExpansion' and event.get('expansion_type') == 'slash_command':
            step = {'id': f'slash-{stamp}', 'kind': 'skill', 'title': event.get('command_name', '?'), 'group': '斜杠命令',
                    'tool': 'slash', 'start': stamp, 'end': stamp, 'error': False, 'output': '', 'detail': '',
                    'live': False, 'agent': ''}
            if current is not None and stamp - current['time'] < 5:
                current['steps'].append(step)
            else:
                pending_slash = step
        elif name == 'PreToolUse':
            if event.get('tool_use_id') not in by_id:
                step = new_step(event, config_for)
                if step is not None:
                    by_id[step['id']] = step
                    turn_at(stamp)['steps'].append(step)
            state = 'running'
        elif name in ('PostToolUse', 'PostToolUseFailure'):
            step = by_id.get(event.get('tool_use_id'))
            if step is None:
                step = new_step(event, config_for)
                if step is None:
                    continue
                by_id[step['id']] = step
                turn_at(stamp)['steps'].append(step)
            step.update(end=stamp, duration_ms=event.get('duration_ms'))
            if name == 'PostToolUse':
                step['output'] = event.get('output', '')
                if event.get('host') == 'codex' and step['tool'] == 'Bash':
                    step['no_exit_code'] = True
                if step['kind'] == 'agent' and 'async_launched' in step['output']:
                    step['group'] = '已转入后台，结果见下方子代理步骤'
            else:
                step.update(error=True, output=event.get('error', ''))
        elif name in ('Stop', 'Interrupt') and not event.get('agent_id'):
            abandon()
            state = 'idle'
    for step in by_id.values():
        step['status'] = status_of(step)
    for turn in turns:
        for step in turn['steps']:
            step.setdefault('status', 'ok')
            if 'covers' in step:
                step['covers'] = sorted(step['covers'])
    return {'turns': turns, 'state': state, 'cwd': cwd, 'last': events[-1].get('ts') if events else None}


def verify_config_cache():
    """返回按 cwd 缓存的 verify 配置读取函数。"""
    cache = {}

    def config_for(cwd):
        if cwd not in cache:
            cache[cwd] = load_verify_config(os.path.join(cwd, 'ai-workflow.yaml'))[0]
        return cache[cwd]
    return config_for


def session_payload(root, session_id, version):
    """返回会话的展示数据；内容未变化时返回 unchanged，会话不存在时返回 None。"""
    path = Path(root) / 'events' / f'{session_id}.jsonl'
    if not path.is_file():
        return None
    size = str(path.stat().st_size)
    if size == version:
        return {'unchanged': True}
    state = reduce_events(read_events(path), verify_config_cache())
    steps = [step for turn in state['turns'] for step in turn['steps']]
    state['checks'] = build_checks(steps)
    state['version'] = size
    return state


def list_sessions(root):
    """按最近更新列出会话（最多 30 个）。"""
    files = sorted((Path(root) / 'events').glob('*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)[:30]
    sessions = []
    for path in files:
        prompt, cwd = '', ''
        with open(path, encoding='utf-8') as handle:
            for _, line in zip(range(50), handle):
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                cwd = cwd or event.get('cwd', '')
                if event.get('event') == 'UserPromptSubmit':
                    prompt = event.get('prompt', '')
                    break
        sessions.append({'id': path.stem, 'project': os.path.basename(cwd), 'prompt': prompt[:40], 'mtime': path.stat().st_mtime})
    return sessions


PAGE_CSS = CSS + '''
.bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-top:8px}select{font:inherit;max-width:100%;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:3px 6px}
label{font-size:13px;color:var(--quiet)}.badge{font-size:12px;border-radius:999px;padding:2px 10px;border:1px solid var(--line)}.badge.running{color:var(--accent);border-color:var(--accent)}
.side.running{color:var(--accent)}.spin{display:inline-block;width:9px;height:9px;border:2px solid var(--accent);border-right-color:transparent;border-radius:50%;animation:s .8s linear infinite;margin-right:4px}
@keyframes s{to{transform:rotate(360deg)}}@media (prefers-reduced-motion:reduce){.spin{animation:none}}
details.step.running{border-left-color:var(--accent)}details.step.sub{margin-left:26px}.notice{background:var(--tint);border-radius:8px;padding:10px 12px;margin-top:16px}
'''

PAGE_JS = r'''
const KINDS={skill:'Skill',mcp:'MCP',verify:'验证',edit:'改动',agent:'子代理',bash:'命令',read:'读取'};
const MARK={ok:'✓',fail:'✕',warn:'!',masked:'!',unknown:'!',na:'–',pending:'…'};
const TEXT={ok:'通过',fail:'失败',masked:'退出码被掩盖',unknown:'结果未确认',pending:'无结果',running:'运行中'};
const $=id=>document.getElementById(id);
const el=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!==undefined)e.textContent=x;return e};
let sid=null,pinned=false,version='',filter='all',listKey='',turnEls=[],stepEls=new Map();
function clock(t){return new Date(t*1000).toLocaleTimeString('zh-CN',{hour12:false})}
function reset(){version='';turnEls=[];stepEls=new Map();$('timeline').replaceChildren()}
$('session').onchange=e=>{sid=e.target.value;pinned=true;reset()};
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.filter;
 document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',x===b));applyFilter()});
function visible(d){const s=d.step;if(filter==='all')return s.kind!=='read';if(filter==='fail')return s.status==='fail';return s.kind===filter}
function applyFilter(){stepEls.forEach(d=>d.classList.toggle('hide',!visible(d)));
 turnEls.forEach(t=>t.classList.toggle('hide',filter!=='all'&&!t.querySelector('.step:not(.hide)')))}
function section(parent,key,label){let n=parent.querySelector(`[data-k=${key}]`);
 if(!n){const l=el('div','label',label);const p=el('pre');p.dataset.k=key;parent.append(l,p);n=p}return n}
function updateStep(d,s){d.step=s;
 d.className=`step ${s.kind} ${s.status}${s.agent?' sub':''}`;
 d.querySelector('.title span').textContent=s.title;
 d.querySelector('.group').textContent=[s.group,s.agent?'子代理 '+s.agent:''].filter(Boolean).join(' · ');
 const side=d.querySelector('.side');side.className=`side ${s.status}`;
 if(s.status==='running'){side.replaceChildren(el('i','spin'),el('span','elapsed',''));side.dataset.start=s.start}
 else{delete side.dataset.start;
  const ms=s.duration_ms?` ${(s.duration_ms/1000).toFixed(1)}s`:'';
  side.textContent=(s.status!=='ok'||['verify','skill','mcp','agent'].includes(s.kind))?`${MARK[s.status]||''} ${TEXT[s.status]}${ms}`:ms.trim()}
 const body=d.querySelector('.body');
 if(s.detail)section(body,'in','输入').textContent=s.detail;
 if(s.output)section(body,'out','结果').textContent=s.output}
function makeStep(){const d=el('details');const sum=el('summary');const t=el('span','title');
 d.tag=el('span','tag');t.append(el('span'),el('span','group'));sum.append(d.tag,t,el('span','side'));d.append(sum,el('div','body'));return d}
function render(s){
 const st=$('state');st.textContent=s.state==='running'?'运行中':'等待输入';st.className='badge '+s.state;
 $('meta').textContent=s.cwd+(s.last?' · 最后事件 '+clock(s.last):'');
 const steps=s.turns.flatMap(t=>t.steps),c=k=>steps.filter(x=>x.kind===k).length;
 const items=[['Skill',c('skill')],['MCP',c('mcp')],['验证',c('verify')],['改动',c('edit')],['子代理',c('agent')],['命令',c('bash')],['运行中',steps.filter(x=>x.status==='running').length],['失败',steps.filter(x=>x.status==='fail').length]];
 $('stats').replaceChildren(...items.map(([k,v])=>{const d=el('div','stat');d.append(el('b','',v),el('span','',k));return d}));
 $('checks').replaceChildren(...s.checks.map(([a,n,t])=>{const d=el('div','check');d.append(el('span',a,MARK[a]),el('b','',n),el('span','',t));return d}));
 let added=false;
 s.turns.forEach((t,i)=>{let box=turnEls[i];
  if(!box){box=el('div','turn');box.append(el('p','time',clock(t.time)),el('div','prompt',t.prompt));$('timeline').append(box);turnEls[i]=box}
  t.steps.forEach(step=>{let d=stepEls.get(step.id);
   if(!d){d=makeStep();d.tag.textContent=KINDS[step.kind]||step.kind;box.append(d);stepEls.set(step.id,d);added=true}
   updateStep(d,step)})});
 applyFilter();$('empty').classList.toggle('hide',steps.length>0||s.turns.length>0);
 if(added&&$('follow').checked)window.scrollTo(0,document.body.scrollHeight)}
function tickElapsed(){document.querySelectorAll('.side[data-start]').forEach(n=>{
 const e=n.querySelector('.elapsed');if(e)e.textContent=` ${Math.max(0,Math.floor(Date.now()/1000-n.dataset.start))}s`})}
async function poll(){try{
 const l=await (await fetch('/api/sessions')).json();
 $('off').classList.toggle('hide',l.enabled);
 const key=JSON.stringify(l.sessions.map(x=>[x.id,x.prompt]));
 if(key!==listKey){listKey=key;const box=$('session');box.replaceChildren(...l.sessions.map(x=>{const o=el('option','',`${x.project} · ${x.prompt||x.id.slice(0,8)}`);o.value=x.id;return o}));if(sid)box.value=sid}
 if(!pinned&&l.sessions[0]&&l.sessions[0].id!==sid){sid=l.sessions[0].id;$('session').value=sid;reset()}
 if(sid){const r=await fetch(`/api/session?id=${encodeURIComponent(sid)}&v=${version}`);
  if(r.ok){const s=await r.json();if(!s.unchanged){version=s.version;render(s)}}}
 $('lost').classList.add('hide');
}catch(e){$('lost').classList.remove('hide')}setTimeout(poll,1000)}
setInterval(tickElapsed,1000);poll();
'''


def page_html():
    """生成实时页面。动态内容全部用 textContent 写入，避免会话内容被当成 HTML 执行。"""
    filters = [('all', '关键步骤'), ('skill', 'Skill'), ('mcp', 'MCP'), ('verify', '验证'), ('edit', '改动'),
               ('agent', '子代理'), ('bash', '命令'), ('read', '读取'), ('fail', '失败')]
    buttons = ''.join(f'<button data-filter="{k}" aria-pressed="{str(k == "all").lower()}">{v}</button>' for k, v in filters)
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>实时执行轨迹</title>'
            f'<style>{PAGE_CSS}</style></head><body><main><h1>实时执行轨迹</h1><p class="meta" id="meta"></p>'
            '<div class="bar"><select id="session" aria-label="选择会话"></select><span class="badge" id="state">等待数据</span>'
            '<label><input type="checkbox" id="follow" checked> 跟随最新</label></div>'
            '<div class="notice hide" id="off">采集已关闭，页面只显示已有记录。</div>'
            '<div class="notice hide" id="lost">连接不到本地服务，正在重试。</div>'
            '<div class="notice" id="empty">还没有事件。开启后在 Claude Code 里执行任务，步骤会出现在这里；刚升级插件时需要重开会话。</div>'
            '<section><div class="stats" id="stats"></div></section><section><h2>检查</h2><div id="checks"></div></section>'
            f'<section><h2>时间线</h2><div class="filters">{buttons}</div><div id="timeline"></div></section>'
            f'</main><script>{PAGE_JS}</script></body></html>')


class Handler(BaseHTTPRequestHandler):
    """只读页面和接口。校验 Host，防止其他网站通过 DNS 重绑定读取本机轨迹。"""

    root = ''

    def log_message(self, *_):
        pass

    def reply(self, status, body, kind='application/json; charset=utf-8'):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, value, status=200):
        self.reply(status, json.dumps(value, ensure_ascii=False))

    def do_GET(self):
        port = self.server.server_address[1]
        if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
            return self.send_json({'error': 'host'}, 403)
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == '/':
            return self.reply(200, page_html(), 'text/html; charset=utf-8')
        if url.path == '/api/ping':
            return self.send_json({'app': APP_ID, 'pid': os.getpid()})
        if url.path == '/api/sessions':
            return self.send_json({'sessions': list_sessions(self.root),
                                   'enabled': (Path(self.root) / 'enabled').exists()})
        if url.path == '/api/session':
            session_id = query.get('id', [''])[0]
            if not SESSION_ID.match(session_id):
                return self.send_json({'error': 'id'}, 400)
            payload = session_payload(self.root, session_id, query.get('v', [''])[0])
            return self.send_json(payload) if payload else self.send_json({'error': 'missing'}, 404)
        return self.send_json({'error': 'path'}, 404)


def bind_server(root, port=None):
    """绑定 127.0.0.1 的可用端口并返回服务对象。"""
    handler = type('BoundHandler', (Handler,), {'root': root})
    for candidate in ([port] if port is not None else range(FIRST_PORT, FIRST_PORT + PORT_TRIES)):
        try:
            return ThreadingHTTPServer(('127.0.0.1', candidate), handler)
        except OSError:
            continue
    return None


def ping(root):
    """返回运行中的轨迹服务信息 {pid, port}；没有运行时返回 None。"""
    try:
        state = json.loads((Path(root) / 'server.json').read_text(encoding='utf-8'))
        with urlopen(f'http://127.0.0.1:{state["port"]}/api/ping', timeout=1) as response:
            data = json.load(response)
    except (OSError, ValueError, KeyError):
        return None
    return state if data.get('app') == APP_ID and data.get('pid') == state.get('pid') else None


def prune(root):
    """删除超过保留期的日志。"""
    limit = time.time() - RETENTION_DAYS * 86400
    for path in (Path(root) / 'events').glob('*.jsonl'):
        if path.stat().st_mtime < limit:
            path.unlink()


def serve(root, port):
    """前台运行服务，并记录 pid 和端口。"""
    server = bind_server(root, port)
    if server is None:
        print('status=BLOCKED reason=没有可用端口')
        return 2
    state = {'pid': os.getpid(), 'port': server.server_address[1]}
    (Path(root) / 'server.json').write_text(json.dumps(state), encoding='utf-8')
    server.serve_forever()
    return 0


def turn_on(root):
    """开启采集并确保页面服务在运行。"""
    Path(root, 'events').mkdir(parents=True, exist_ok=True, mode=0o700)
    prune(root)
    Path(root, 'enabled').touch()
    state = ping(root)
    if state is None:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'serve'], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                         env={**os.environ, 'WORKFLOW_TRACE_DIR': str(root)})
        for _ in range(30):
            time.sleep(0.1)
            state = ping(root)
            if state:
                break
    if state is None:
        print('status=BLOCKED reason=页面服务启动失败（采集已开启）')
        return 2
    print(f'status=ON url=http://127.0.0.1:{state["port"]}/')
    return 0


def turn_off(root):
    """关闭采集和页面服务，保留日志。"""
    Path(root, 'enabled').unlink(missing_ok=True)
    state = ping(root)
    if state:
        os.kill(state['pid'], signal.SIGTERM)
    Path(root, 'server.json').unlink(missing_ok=True)
    print('status=OFF')
    return 0


def show_status(root):
    """输出当前状态。"""
    enabled = Path(root, 'enabled').exists()
    state = ping(root)
    url = f'http://127.0.0.1:{state["port"]}/' if state else '-'
    print(f'status={"ON" if enabled else "OFF"} server={"running" if state else "stopped"} url={url}')
    return 0


def main():
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='status', choices=['on', 'off', 'status', 'serve'])
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    root = trace_dir()
    try:
        if args.action == 'serve':
            Path(root).mkdir(parents=True, exist_ok=True, mode=0o700)
            return serve(root, args.port)
        return {'on': turn_on, 'off': turn_off, 'status': show_status}[args.action](root)
    except OSError as error:
        print(f'status=BLOCKED reason={error}')
        return 2


if __name__ == '__main__':
    sys.exit(main())
