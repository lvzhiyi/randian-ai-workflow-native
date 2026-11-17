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
.searchbar{display:flex;align-items:end;flex-wrap:wrap;gap:12px;background:#101725;border:1px solid var(--line);border-radius:12px;padding:15px;margin-bottom:18px}.searchbar label{display:block;margin-bottom:5px}.search-input{flex:1 1 210px}.searchbar input,.searchbar select{width:100%;font:inherit;color:var(--text);background:#0c1320;border:1px solid #3a4961;border-radius:8px;padding:9px 12px;min-height:43px}.searchbar input::placeholder{color:var(--muted)}.searchbar input:focus-visible,.searchbar select:focus-visible{outline:2px solid var(--accent);outline-offset:2px}.searchbar button{min-height:43px}.searchbar #filter-count{flex-basis:100%}.business-section{border-top:1px solid var(--line);padding-top:12px;margin-top:12px}.business-section h3{margin-bottom:7px}.business-section p{margin:5px 0}.technical{margin-top:16px;border-top:1px solid var(--line);padding-top:12px}.technical summary,.business-section>summary,details.log summary{cursor:pointer;color:var(--accent)}pre{max-height:320px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}details.log{margin-top:7px}.empty{text-align:center;padding:28px 12px;border:1px dashed var(--line);border-radius:10px}@media(max-width:600px){.searchbar{align-items:stretch}.searchbar>div,.searchbar>button{flex:1 1 100%}}
</style>
</head>
<body>
<main class="shell">
<header class="header"><div><p class="eyebrow">WORKFLOW / READ ONLY</p><h1 id="project-name">工作流看板</h1><p id="project-root" class="muted">等待项目数据</p></div><div class="actions"><span id="updated" class="muted">每 2 秒刷新</span><button id="refresh" type="button">立即刷新</button></div></header>
<div id="connection" class="notice" role="status" aria-live="polite">正在读取看板…</div>
<section class="statusbar" aria-label="任务与引擎状态"><div><span class="muted">任务概览</span><strong id="task-summary">未知</strong><span class="muted">任务卡状态不等同于验证通过</span></div><div><span class="muted">执行模式</span><strong id="engine-mode">未知</strong><span id="engine-binding" class="muted">绑定：未知</span></div><div><span class="muted">引擎状态</span><strong id="engine-state">未知</strong><span id="engine-available" class="muted">可用性：未知</span></div></section>
<div id="warning" class="notice" hidden></div>
<div class="grid"><div><section class="panel"><h2>任务卡</h2><div class="searchbar" role="search" aria-label="任务筛选：搜索、状态与档位"><div class="search-input"><label class="muted" for="task-filter">搜索任务</label><input id="task-filter" type="search" placeholder="搜索编号或标题" autocomplete="off"></div><button id="clear-filter" type="button">清空筛选</button><div><label class="muted" for="state-filter">状态</label><select id="state-filter"><option value="all">全部状态</option></select></div><div><label class="muted" for="tier-filter">档位</label><select id="tier-filter"><option value="all">全部档位</option><option value="light">轻量</option><option value="standard">标准</option><option value="full">完整</option><option value="unknown">未知</option></select></div><p id="filter-count" class="muted" role="status" aria-live="polite"></p></div><div id="tasks" class="cards"></div></section></div><aside><section class="panel"><h2>文档来源</h2><div id="documents"></div><p class="legend">只读纯文本预览，不执行 Markdown 或 HTML。</p></section><section class="panel"><h2>读取问题</h2><ul id="issues" class="issues"></ul></section><p class="muted">首版仅展示当前服务绑定的一个项目。此页面不批准、不修改状态，也不提供工具拦截或安全沙箱。</p></aside></div>
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
Object.assign(labels,{error:'执行异常',invalidated:'已失效',created:'待就绪',implementing:'实施中',pending_verification:'待验证',stale:'证据失效',review_failed:'评审未通过',review_passed:'评审通过 · 待人工验收',cancelled:'已取消'});
function detailBlock(title, value) {
  const section = element('section');
  const pre = element('pre');
  pre.style.whiteSpace = 'pre-wrap';pre.style.overflowWrap = 'anywhere';
  pre.textContent = value === null || value === undefined ? '未记录' : JSON.stringify(value,null,2);
  section.append(element('h3',title),pre);return section;
}
// 编号/标题、状态和档位取交集；纯函数与页面共用，避免测试复制筛选逻辑。
function filterTasks(values, query = '', state = 'all', tier = 'all') {
  const needle = query.trim().toLocaleLowerCase();
  return list(values).filter(item => [item.id,item.title].some(v => text(v,'').toLocaleLowerCase().includes(needle)) && (state === 'all' || text(item.state,'unknown') === state) && (tier === 'all' || text(item.tier,'unknown') === tier));
}
function summarySection(title, lines, fallback = '尚无记录，不能视为通过') {
  const section = element('section',undefined,'business-section');
  section.append(element('h3',title));
  for (const line of (lines.length ? lines : [fallback])) section.append(element('p',line));
  return section;
}
// 只遍历已知业务字段，不将对象兜底序列化，内部哈希与会话标识不会混入正文。
const businessFields = {goal:'目标',scope:'范围',title:'标题',description:'说明',summary:'摘要',content:'内容',status:'状态',impact:'影响',risk:'风险',rollback:'回滚',acceptance:'验收标准',criteria:'验收条件',result:'结果',conclusion:'结论',message:'说明',note:'备注',owner:'负责人',reviewer:'验收人',by:'确认人',at:'时间',next_step:'下一步',next_steps:'下一步',next:'下一步',reason:'原因',source:'来源',documents:'参考文档',completed:'是否完成',accepted:'是否接受',decision:'决定',steps:'步骤',path:'路径',question:'待确认',resume:'恢复条件'};
function businessLines(value, prefix = '', depth = 0) {
  if (depth > 5 || value === null || value === undefined || value === '') return [];
  if (Array.isArray(value)) return value.flatMap(v => businessLines(v,prefix,depth+1));
  if (typeof value === 'object') return Object.entries(businessFields).flatMap(([key,label]) => businessLines(value[key],prefix ? prefix + ' / ' + label : label,depth+1));
  return [(prefix ? prefix + '：' : '') + (typeof value === 'boolean' ? value ? '是' : '否' : String(value))];
}
function businessDetails(title, sections) {
  const details = element('details',undefined,'business-section');
  details.append(element('summary',title),...sections);return details;
}
function technicalRecord(item) {
  const d = item.details || {};
  const identity = value => Object.fromEntries(['id','kind','stage','evidence_id','round_id','session_id','executor','binding_version','control_digest','snapshot','valid'].filter(key => value[key] !== undefined).map(key => [key,value[key]]));
  return {current_round:item.current_round,executor:item.executor,session_id:item.session_id,binding_version:d.binding_version,control_digest:d.control_digest,evidence:list(d.evidence).map(identity),attempts:list(d.attempts).map(identity),rounds:list(d.rounds).map(identity)};
}
function renderBusiness(item) {
  const root = element('div'), b = item.business || {}, readiness = item.readiness || {};
  root.append(summarySection('当前阻止条件',list(readiness.blocking),'暂无已记录的当前阻止条件；不代表验证通过'),summarySection('后续阶段',list(readiness.upcoming),'暂无后续阶段缺项记录'));
  const d = item.details || {};
  const pending = list(item.pending).flatMap(p => typeof p === 'string' ? [p] : ['待确认：' + text(p.question,'内容未记录'),'影响：' + text(p.impact,'未记录'),'负责人：' + text(p.owner,'未记录'),'恢复条件：' + text(p.resume,'未记录'),'来源：' + text(p.source,'来源未记录')]);
  root.append(summarySection('当前待确认',pending,'暂无已记录的待确认事项'));
  const todos = list(d.todos);
  root.append(summarySection('实施步骤',todos.map(t => text(t.title,'未命名步骤') + ' · ' + stateLabel(t.status))));
  root.append(businessDetails('目标、范围与验收',[
    summarySection('任务目标与范围',[...businessLines(d.goal,'目标'),...businessLines(d.scope,'范围')]),
    summarySection('验收标准',businessLines(d.acceptance)),
    summarySection('人工验收',businessLines(d.human_acceptance), '人工验收尚未发生；Agent 评审通过不等于人工接受或交付'),
    summarySection('文档交付标记',item.human_delivery_completed === true ? ['文档标记已交付（非引擎验收证据）','来源：' + text(item.human_delivery_source)] : ['尚无文档交付完成标记'])
  ]));
  const checks = list((d.plan || {}).checks).map(c => text(c.name || c.title || c.id,'未命名检查') + ' · 命令：' + list(c.argv).filter(v=>typeof v==='string').join(' ') + ' · 工作目录：' + text(c.cwd));
  root.append(businessDetails('方案、检查计划与交接',[
    summarySection('方案摘要',businessLines(d.proposal)),summarySection('验证检查计划',checks,'尚无可读检查命令，不能视为验证已执行'),summarySection('交接下一步',businessLines(d.handoff),'尚未记录交接下一步')
  ]));
  root.append(summarySection('基线读取' ,list(b.baseline).map(v => text(v.path) + ' · ' + text(v.status))),summarySection('批准摘要',list(b.approvals).map(v => text(v.title) + ' · ' + text(v.status))));
  root.append(summarySection('双轴评审',list(b.review).flatMap(v => [v.title + '：' + ({pass:'通过（保存记录）',fail:'未通过',invalidated:'已失效',unknown:'未知，未确认通过'}[v.conclusion] || '未知，未确认通过') + ' · 必须解决待办 ' + text(v.unresolved),...list(v.findings).map(f => text(f.message) + ' · ' + (f.resolved === true ? '已解决' : f.required === true ? '必须解决' : '待确认'))])));
  const verification = summarySection('验证尝试与逐项诊断',[],'尚无真实验证尝试');
  if (list(b.verification).length) verification.replaceChildren(element('h3','验证尝试与逐项诊断'));
  list(b.verification).forEach((attempt,index) => {
    verification.append(element('p','第 ' + (index+1) + ' 次验证 · ' + stateLabel(attempt.status) + (attempt.failure ? ' · 执行异常：' + text(attempt.failure) : '')));
    list(attempt.checks).forEach(check => {
      verification.append(element('p',text(check.id,'未命名检查') + ' · 退出码：' + text(check.exit_code) + ' · 原因：' + text(check.reason)));
      const logs = element('details',undefined,'log');logs.append(element('summary','展开此检查日志 · 纯文本（最多 16384 字符）'));
      const raw = '标准输出\n' + text(check.stdout,'无') + '\n标准错误\n' + text(check.stderr,'无');
      logs.append(element('pre',raw.slice(0,16384) + (raw.length > 16384 || check.truncated ? '\n[日志已达到限额或源日志被截断]' : '')));verification.append(logs);
    });
  });root.append(verification);
  root.append(summarySection('证据失效摘要',list(b.invalidations),'未记录失效；文件新鲜度仍未核验'),summarySection('轮次历史',list(b.rounds).map(r => '第 ' + r.number + ' 轮' + (r.current ? '（当前）' : '') + ' · ' + stateLabel(r.state) + ' · ' + (phaseLabels[r.phase] || '未知阶段'))));
  return root;
}
function renderTasks(values) {
  taskValues = list(values);
  const query = byId('task-filter').value.trim().toLowerCase();
  const items = filterTasks(taskValues,query,byId('state-filter').value,byId('tier-filter').value);
  byId('filter-count').textContent = '找到 ' + items.length + ' / ' + taskValues.length + ' 个任务';
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

      element('p','证据为保存记录，当前文件新鲜度未核验；评审通过不是交付。','legend'),sourceNode(item.source));
    node.append(renderBusiness(item));
    const details = element('details',undefined,'technical');details.open = expandedTasks.has(item.id);
    details.append(element('summary','技术详情 · 原始记录 / 标识 / 绑定（默认折叠）'));
    // 大体积原始记录仅在展开时序列化，避免轮询刷新为折叠内容重复分配字符串。
    let loaded = false;
    const load = () => { if (!loaded) { details.append(detailBlock('内部证据标识与绑定',technicalRecord(item)));loaded = true; } };
    details.addEventListener('toggle',() => { if (details.open) { expandedTasks.add(item.id);load(); } else expandedTasks.delete(item.id); });
    if (details.open) load();
    node.append(details);return node;
  }) : [element('p',taskValues.length ? '没有匹配任务，试试清空筛选或调整状态和档位；不代表任务已完成。' : '暂无任务记录；等待任务登记，不代表已完成。','empty')]));
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
  renderTasks(data.tasks);renderDocuments(data.documents);
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
for (const id of ['state-filter','tier-filter']) byId(id).addEventListener('change',() => renderTasks(taskValues));
byId('clear-filter').addEventListener('click',() => { byId('task-filter').value = '';byId('state-filter').value = 'all';byId('tier-filter').value = 'all';renderTasks(taskValues);byId('task-filter').focus(); });
for (const state of ['created','implementing','pending_verification','running','passed','failed','stale','review_failed','review_passed','cancelled','unknown','pending','in_progress','blocked','completed']) { const option = element('option',stateLabel(state));option.value = state;byId('state-filter').append(option); }
refresh();
</script>
</body>
</html>'''
