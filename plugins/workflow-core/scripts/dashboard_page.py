"""提供无第三方依赖的只读工作流看板页面。"""


def page_html() -> str:
    """返回静态页面；项目数据只通过同源只读接口取得。"""
    return r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>工作流看板</title>
<style>
:root{color-scheme:dark;--bg:#0c1019;--panel:#151c29;--line:#2a3549;--text:#e7edf8;--muted:#a0aec5;--accent:#91b5ff;--warn:#ffd18a;--bad:#ff9eaa;--good:#85ddba}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}button{font:inherit;background:#202e46;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 13px;cursor:pointer}button:hover{border-color:var(--accent)}button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}button:disabled{cursor:wait;opacity:.6}h1,h2,h3,p{margin:0}h1{font-size:26px}h2{font-size:18px;margin-bottom:14px}h3{font-size:16px}.shell{max-width:1440px;margin:auto;padding:28px}.header{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:20px}.eyebrow{font-size:12px;letter-spacing:.15em;color:var(--accent)}.muted,.source{color:var(--muted);font-size:13px;overflow-wrap:anywhere}.actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.statusbar,.panel,.notice{border:1px solid var(--line);background:var(--panel);border-radius:12px;padding:20px}.statusbar{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin-bottom:18px}.statusbar strong{display:block;font-size:18px;margin:3px 0}.notice{margin-bottom:18px;color:var(--warn);white-space:pre-wrap;overflow-wrap:anywhere}.notice.error{color:var(--bad);border-color:#74434c}.notice[hidden]{display:none}.grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(280px,1fr);gap:18px}.panel{min-width:0;margin-bottom:18px}.stages{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.stage,.card{border:1px solid var(--line);border-radius:9px;padding:14px;min-width:0}.stage-index{color:var(--accent);font-size:12px}.stage h3{margin:5px 0}.badge{display:inline-block;font-size:12px;border:1px solid var(--line);border-radius:20px;padding:2px 9px;color:var(--muted);overflow-wrap:anywhere;max-width:100%}.badge[data-tone=good]{color:var(--good);border-color:#33574d}.badge[data-tone=bad]{color:var(--bad);border-color:#74434c}.badge[data-tone=active]{color:var(--accent);border-color:#425d89}.cards{display:grid;gap:12px}.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:8px}.card h3,.card dd{overflow-wrap:anywhere}.card dl{margin:12px 0 0;display:grid;grid-template-columns:70px minmax(0,1fr);gap:6px 10px}.card dt{color:var(--muted)}.card dd{margin:0;white-space:pre-wrap}.source{margin-top:10px}.empty{color:var(--muted);padding:12px 0}.document{width:100%;text-align:left;margin-bottom:9px;display:block;overflow-wrap:anywhere}.document small{display:block;color:var(--muted)}.legend{margin-top:14px;color:var(--muted);font-size:12px}.drawer{position:fixed;inset:0 0 0 auto;width:min(680px,100%);background:#111925;border-left:1px solid var(--line);box-shadow:-20px 0 70px #0008;padding:22px;z-index:2;display:flex;flex-direction:column}.drawer[hidden]{display:none}.drawer-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.drawer h2{overflow-wrap:anywhere}.drawer pre{white-space:pre-wrap;overflow-wrap:anywhere;overflow:auto;flex:1;font:13px/1.75 ui-monospace,SFMono-Regular,monospace;border-top:1px solid var(--line);padding-top:18px}.drawer-status{color:var(--warn);white-space:pre-wrap}.issues{margin:0;padding-left:20px;color:var(--warn);overflow-wrap:anywhere}
@media(max-width:1000px){.stages{grid-template-columns:repeat(2,minmax(0,1fr))}.grid{grid-template-columns:1fr}}@media(max-width:600px){.shell{padding:16px}.header{flex-direction:column}.statusbar{grid-template-columns:1fr}.stages{grid-template-columns:1fr 1fr}.panel{padding:15px}.card-head{flex-direction:column}}
</style>
</head>
<body>
<main class="shell">
<header class="header"><div><p class="eyebrow">WORKFLOW / READ ONLY</p><h1 id="project-name">工作流看板</h1><p id="project-root" class="muted">等待项目数据</p></div><div class="actions"><span id="updated" class="muted">每 2 秒刷新</span><button id="refresh" type="button">立即刷新</button></div></header>
<div id="connection" class="notice" role="status" aria-live="polite">正在读取看板…</div>
<section class="statusbar" aria-label="任务与引擎状态"><div><span class="muted">任务概览</span><strong id="task-summary">未知</strong><span class="muted">任务卡状态不等同于验证通过</span></div><div><span class="muted">执行模式</span><strong id="engine-mode">未知</strong><span id="engine-binding" class="muted">绑定：未知</span></div><div><span class="muted">引擎状态</span><strong id="engine-state">未知</strong><span id="engine-available" class="muted">可用性：未知</span></div></section>
<div id="warning" class="notice" hidden></div>
<div class="grid"><div><section class="panel"><h2>任务卡</h2><label>任务筛选 <input id="task-filter" placeholder="编号、标题、状态、档位"></label><div id="tasks" class="cards"></div></section><section class="panel"><h2>执行观测 · Trace</h2><p class="legend">绑定事件只作观测；未归属事件不改变任务状态。严格限定当前项目，不推测其他项目归属。</p><div id="trace"></div></section></div><aside><section class="panel"><h2>文档来源</h2><div id="documents"></div><p class="legend">只读纯文本预览，不执行 Markdown 或 HTML。</p></section><section class="panel"><h2>读取问题</h2><ul id="issues" class="issues"></ul></section><p class="muted">首版仅展示当前服务绑定的一个项目。此页面不批准、不修改状态，也不提供工具拦截或安全沙箱。</p></aside></div>
</main>
<aside id="drawer" class="drawer" aria-label="文档纯文本预览" hidden><div class="drawer-header"><h2 id="document-title">文档</h2><button id="close-document" type="button">关闭预览</button></div><p id="document-status" class="drawer-status" role="status"></p><pre id="document-content" tabindex="0"></pre></aside>
<script>
'use strict';
const byId = id => document.getElementById(id);
const text = (value, fallback = '未知') => value === null || value === undefined || value === '' ? fallback : typeof value === 'object' ? JSON.stringify(value) : String(value);
const list = value => Array.isArray(value) ? value : [];
function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = text(value);
  if (className) node.className = className;
  return node;
}
const labels = {unknown:'未知',pending:'待处理',not_started:'未开始',in_progress:'进行中',active:'进行中',running:'执行中',blocked:'受阻',done:'完成',completed:'完成',passed:'通过',failed:'失败',skipped:'已跳过',ready:'就绪',unavailable:'不可用',disabled:'未启用',enabled:'已启用'};
function stateLabel(state) { return labels[state] || text(state); }
function badge(state) {
  const node = element('span', stateLabel(state), 'badge');
  node.dataset.tone = ['blocked','failed','review_failed','unavailable'].includes(state) ? 'bad' : ['in_progress','active','running'].includes(state) ? 'active' : 'unknown';
  return node;
}
function sourceLabel(source) {
  // 只根据服务明确给出的来源标识分类，不从任务状态猜测权威性。
  const value = text(source, '');
  if (/^(engine|引擎)(?:$|[:/ ·])/i.test(value)) return '引擎权威 · ' + value;
  if (/^(document|docs?|文档)(?:$|[:/ ·])/i.test(value) || /\.(md|txt|yaml)(?:$|[:#])/i.test(value)) return '文档状态 · ' + value;
  return '来源未确认为权威 · ' + (value || '未知');
}
function sourceNode(source) { return element('p', sourceLabel(source), 'source'); }
const expandedTasks = new Set();
let taskValues = [];
const phaseLabels = {planning:'就绪与授权',implementation:'实施',verification:'验证',review:'双轴评审',done:'Agent 结束'};
Object.assign(labels,{created:'待就绪',implementing:'实施中',pending_verification:'待验证',stale:'证据失效',review_failed:'评审未通过',review_passed:'评审通过 · 待人工验收',cancelled:'已取消'});
function detailBlock(title, value) {
  const section = element('section');
  const pre = element('pre');
  pre.style.whiteSpace = 'pre-wrap';pre.style.overflowWrap = 'anywhere';
  pre.textContent = value === null || value === undefined ? '未记录' : JSON.stringify(value,null,2);
  section.append(element('h3',title),pre);return section;
}
function renderTasks(values) {
  taskValues = list(values);
  const query = byId('task-filter').value.trim().toLowerCase();
  const items = taskValues.filter(item => [item.id,item.title,item.state,item.tier].some(v => text(v,'').toLowerCase().includes(query)));
  byId('task-summary').textContent = taskValues.length + ' 个任务 · 显示 ' + items.length;
  byId('tasks').replaceChildren(...(items.length ? items.map(item => {
    const node = element('article',undefined,'card');
    const head = element('div',undefined,'card-head');
    head.append(element('h3',text(item.id) + ' · ' + text(item.title)),badge(item.state));
    const progress = item.progress || {};
    node.append(head,element('p','档位：' + ({light:'轻量',standard:'标准',full:'完整'}[item.tier] || text(item.tier)) + ' · 当前阶段：' + (phaseLabels[item.phase] || '未知')),
      element('p',item.summary || '文档历史未核验，不构成当前通过证据'),
      element('p',list(item.flow).map(p => (p.current ? '▶ ' : '') + (phaseLabels[p.id] || p.id)).join(' → '),'muted'),
      element('p','Todo：' + text(progress.done,'未知') + '/' + text(progress.total,'未知') + ' · 当前步：' + text(progress.current,'无记录')),
      element('p','更新时间：' + text(item.updated_at) + ' · 活动未知（无退出或心跳证据）','muted'),
      element('p','执行者：' + text(item.executor) + ' · 会话：' + text(item.session_id),'muted'),
      element('p','证据为保存记录，当前文件新鲜度未核验；评审通过不是交付。','legend'),sourceNode(item.source));
    for (const [key,label] of [['missing','待确认 / 就绪缺项'],['blocked','阻塞'],['pending','待确认'],['failures','失败 / 执行异常']]) {
      if (Array.isArray(item[key]) ? item[key].length : item[key]) node.append(detailBlock(label,item[key]));
    }
    const details = element('details');details.open = expandedTasks.has(item.id);
    details.append(element('summary','展开任务详情 · 只读'));
    details.addEventListener('toggle',() => details.open ? expandedTasks.add(item.id) : expandedTasks.delete(item.id));
    const d = item.details || {};
    for (const [label,value] of [
      ['基线读取 / 批准版本',{baseline:d.baseline,receipts:d.baseline_receipts,approvals:d.approvals,binding_version:d.binding_version,control_digest:d.control_digest}],
      ['实施 Todos',d.todos],['验证 attempt / 错误 / 诊断',d.attempts],
      ['双轴评审 · Spec + Standards',{reports:d.review,required_findings:d.required_findings}],
      ['有效性记录（未实时核验）',d.evidence],['方案与检查计划',{proposal:d.proposal,plan:d.plan}],
      ['验收 / 人工验收',{acceptance:d.acceptance,human_acceptance:d.human_acceptance,document_delivery_completed:item.human_delivery_completed,document_delivery_source:item.human_delivery_source}],
      ['handoff',d.handoff],['轮次历史',d.rounds]]) details.append(detailBlock(label,value));
    node.append(details);return node;
  }) : [element('p','暂无匹配任务；不代表任务已完成。','empty')]));
}
function renderTrace(value) {
  const trace = value || {};
  const node = byId('trace');
  const events = list(trace.events).slice().sort((a,b) => text(a.ts,'').localeCompare(text(b.ts,'')));
  node.replaceChildren(detailBlock('当前绑定事件时间线',events),detailBlock('未归属事件（绑定缺失或不匹配）',list(trace.unassigned)));
  if (trace.limited) node.append(element('p','读取达到限额，仅显示部分观测；不代表完整执行历史。','muted'));
}
function renderDocuments(values) {
  const items = list(values);
  byId('documents').replaceChildren(...(items.length ? items.map(item => {
    const node = element('button', undefined, 'document');
    node.type = 'button';
    node.append(element('span',item.title || item.path),element('small',text(item.path) + ' · ' + (item.exists === true ? '存在' : item.exists === false ? '缺失' : '存在性未知')));
    node.disabled = item.exists === false || typeof item.path !== 'string' || !item.path;
    node.addEventListener('click', () => openDocument(item.path, item.title, node));
    return node;
  }) : [element('p','未提供文档来源','empty')]));
}
function render(data) {
  const project = data.project || {}, mode = data.mode || {};
  byId('project-name').textContent = text(project.name,'工作流看板');
  byId('project-root').textContent = text(project.root,'项目根未知');
  byId('engine-mode').textContent = '任务级流程门禁';
  byId('engine-binding').textContent = '绑定：' + text(mode.binding);
  byId('engine-state').textContent = stateLabel(mode.state);
  byId('engine-available').textContent = '可用性：' + (mode.available === true ? '可用' : mode.available === false ? '不可用，不降级为通过' : '未知');
  const warnings = [];
  if (mode.warning) warnings.push(text(mode.warning));
  if (mode.migration_warning && mode.migration_warning !== mode.warning) warnings.push(text(mode.migration_warning));
  if (mode.available !== true) warnings.push('未确认任务数据源可用。页面保留文档信息，不将其视为引擎批准或验证结果。');
  byId('warning').textContent = warnings.join('\n');
  byId('warning').hidden = !warnings.length;
  renderTasks(data.tasks);renderTrace(data.trace);renderDocuments(data.documents);
  const issues = list(data.issues);
  byId('issues').replaceChildren(...(issues.length ? issues.map(issue => element('li',issue)) : [element('li','暂无读取问题')]));
}
async function getJSON(url, signal) {
  const response = await fetch(url,{method:'GET',cache:'no-store',signal,headers:{Accept:'application/json'}});
  if (!response.ok) throw new Error('HTTP ' + response.status);
  return response.json();
}
let polling = false, timer, lastSuccess = null, lastPayload = null;
async function refresh() {
  if (polling) return;
  polling = true;clearTimeout(timer);byId('refresh').disabled = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const data = await getJSON('/api/dashboard',controller.signal);
    if (!data || typeof data !== 'object' || Array.isArray(data) || !data.project || !data.mode || !['stages','tasks','pending','documents','issues'].every(key => Array.isArray(data[key]))) throw new Error('看板响应格式不正确');
    const payload = JSON.stringify(data);
    if (payload !== lastPayload) { render(data); lastPayload = payload; }
    lastSuccess = new Date();
    byId('updated').textContent = '最近成功：' + lastSuccess.toLocaleTimeString('zh-CN');
    byId('connection').hidden = true;
  } catch (error) {
    // 失败只更新连接提示，保留最后一次成功快照，避免旧数据被误认为实时状态。
    byId('connection').hidden = false;byId('connection').className = 'notice error';
    byId('connection').textContent = '刷新失败：' + (error.name === 'AbortError' ? '请求超时' : text(error.message)) + '。' + (lastSuccess ? '当前保留 ' + lastSuccess.toLocaleTimeString('zh-CN') + ' 的旧数据，请勿视为实时状态。' : '尚无成功读取的数据。') + ' 2 秒后重试。';
  } finally {
    clearTimeout(timeout);polling = false;byId('refresh').disabled = false;
    // 用完成后再排期代替固定间隔，慢请求也不会形成重叠轮询。
    timer = setTimeout(refresh,2000);
  }
}
let documentController = null, documentVersion = 0, documentTrigger = null;
async function openDocument(path, title, trigger) {
  if (documentController) documentController.abort();
  const version = ++documentVersion;
  const controller = new AbortController();documentController = controller;documentTrigger = trigger;
  byId('drawer').hidden = false;byId('document-title').textContent = text(title || path);
  byId('document-content').textContent = '';byId('document-status').textContent = '正在读取：' + path;
  byId('close-document').focus();
  const timeout = setTimeout(() => controller.abort(),8000);
  try {
    const data = await getJSON('/api/document?path=' + encodeURIComponent(path),controller.signal);
    if (!data || typeof data.content !== 'string' || typeof data.path !== 'string') throw new Error('文档响应格式不正确');
    if (version !== documentVersion) return;
    // 文档只能作为纯文本显示，即使含脚本、链接或 HTML 也不创建可执行节点。
    byId('document-content').textContent = data.content;
    byId('document-status').textContent = data.path + ' · 纯文本，只读';
  } catch (error) {
    if (version !== documentVersion) return;
    byId('document-status').textContent = '文档读取失败：' + (error.name === 'AbortError' ? '请求超时' : text(error.message));
  } finally {
    clearTimeout(timeout);
    if (version === documentVersion) documentController = null;
  }
}
function closeDocument() {
  ++documentVersion;
  if (documentController) documentController.abort();
  documentController = null;byId('drawer').hidden = true;
  if (documentTrigger && documentTrigger.isConnected) documentTrigger.focus();
  else byId('refresh').focus();
}
byId('refresh').addEventListener('click',refresh);
byId('close-document').addEventListener('click',closeDocument);
document.addEventListener('keydown',event => { if (event.key === 'Escape' && !byId('drawer').hidden) closeDocument(); });
byId('task-filter').addEventListener('input',() => renderTasks(taskValues));
refresh();
</script>
</body>
</html>'''
