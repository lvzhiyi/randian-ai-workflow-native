"""提供无第三方依赖的只读工作流看板页面。"""


def page_html() -> str:
    """返回静态页面；项目数据只通过同源只读接口取得。"""
    return r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SpecLock · 工作流看板</title>
<style>
:root{
  color-scheme:dark;
  --bg:#070b12;
  --bg-glow:radial-gradient(ellipse 80% 45% at 50% -10%,rgba(59,130,246,.16),transparent 70%);
  --panel:#0e1523;
  --panel-elev:#121b2d;
  --line:rgba(148,163,184,.15);
  --line-strong:rgba(148,163,184,.28);
  --text:#edf2fb;
  --muted:#94a3b8;
  --accent:#60a5fa;
  --accent-bg:rgba(59,130,246,.14);
  --accent-line:rgba(96,165,250,.38);
  --warn:#fbbf24;
  --warn-bg:rgba(251,191,36,.12);
  --warn-line:rgba(251,191,36,.34);
  --bad:#fb7185;
  --bad-bg:rgba(251,113,133,.13);
  --bad-line:rgba(251,113,133,.36);
  --good:#34d399;
  --good-bg:rgba(16,185,129,.14);
  --good-line:rgba(52,211,153,.38);
}
*{box-sizing:border-box}
body{
  margin:0;
  min-height:100vh;
  background:var(--bg-glow),var(--bg);
  color:var(--text);
  font:14px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;
}
button{
  font:inherit;
  background:var(--panel-elev);
  color:var(--text);
  border:1px solid var(--line-strong);
  border-radius:8px;
  padding:7px 12px;
  cursor:pointer;
  transition:border-color .15s,background-color .15s,transform .08s;
}
button:hover{border-color:var(--accent);background:#17233a}
button:active{transform:translateY(1px)}
button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
button:disabled{cursor:wait;opacity:.55}
h1,h2,h3,p{margin:0}
h1{font-size:22px;font-weight:700;letter-spacing:-.02em}
h2{font-size:16px;font-weight:600;margin-bottom:10px}
h3{font-size:15px;font-weight:600}
.shell{max-width:1360px;margin:auto;padding:22px 24px 36px}
.header{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:16px;
  margin-bottom:16px;
}
.brand-row{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.eyebrow{
  font-size:11px;
  font-weight:700;
  letter-spacing:.14em;
  text-transform:uppercase;
  color:var(--accent);
}
.live-pill{
  display:inline-flex;
  align-items:center;
  gap:6px;
  font-size:11px;
  font-weight:600;
  color:var(--good);
  background:var(--good-bg);
  border:1px solid var(--good-line);
  border-radius:999px;
  padding:1px 8px;
}
.live-dot{
  width:6px;
  height:6px;
  border-radius:50%;
  background:var(--good);
  box-shadow:0 0 8px var(--good);
  animation:pulse 2s infinite;
}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.muted,.source{color:var(--muted);font-size:12.5px;overflow-wrap:anywhere}
.actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.statusbar,.panel,.notice{
  border:1px solid var(--line);
  background:var(--panel);
  border-radius:12px;
  padding:16px;
  box-shadow:0 10px 30px rgba(0,0,0,.22);
}
.statusbar{
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:12px;
  padding:12px 16px;
  margin-bottom:14px;
}
.stat-box{
  background:rgba(255,255,255,.02);
  border:1px solid var(--line);
  border-radius:9px;
  padding:9px 12px;
}
.statusbar strong{display:block;font-size:16px;font-weight:650;margin:2px 0;color:var(--text)}
.notice{
  margin-bottom:14px;
  padding:11px 14px;
  color:var(--warn);
  background:var(--warn-bg);
  border-color:var(--warn-line);
  white-space:pre-wrap;
  overflow-wrap:anywhere;
}
.notice.error{color:var(--bad);background:var(--bad-bg);border-color:var(--bad-line)}
.notice[hidden]{display:none}
.panel{min-width:0;margin-bottom:16px}
.dashboard-layout{
  position:relative;
  display:grid;
  grid-template-areas:"documents" "tasks";
  gap:14px;
  align-items:start;
  margin-bottom:16px;
}
.dashboard-layout>.panel{margin:0}
.task-panel{grid-area:tasks;padding:16px}
#document-sources{grid-area:documents;padding:12px 16px}
#document-sources summary{overflow-wrap:anywhere;font-size:13px}
#document-count{margin-inline-start:6px}
#documents{margin-top:10px}
@media(min-width:1001px){
  .dashboard-layout:has(#document-sources[open]){grid-template-columns:minmax(0,1fr) minmax(260px,310px);grid-template-areas:"tasks documents"}
  .dashboard-layout:has(#document-sources:not([open])){grid-template-areas:"tasks"}
  #document-sources:not([open]){position:absolute;top:12px;right:16px;padding:6px 12px;grid-area:auto;background:var(--panel-elev)}
  .dashboard-layout:has(#document-sources:not([open])) h2{padding-right:260px}
  .task-panel .searchbar #filter-count{flex-basis:auto;align-self:center}
}
.searchbar{
  display:flex;
  align-items:end;
  flex-wrap:wrap;
  gap:8px 10px;
  background:#0a101b;
  border:1px solid var(--line);
  border-radius:10px;
  padding:10px 12px;
  margin-bottom:12px;
}
.searchbar label{display:block;margin-bottom:4px}
.search-input{flex:1 1 200px}
.searchbar input,.searchbar select{
  width:100%;
  font:inherit;
  color:var(--text);
  background:var(--panel);
  border:1px solid var(--line-strong);
  border-radius:8px;
  padding:7px 10px;
  min-height:38px;
}
.searchbar input::placeholder{color:var(--muted)}
.searchbar input:focus-visible,.searchbar select:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.searchbar button{min-height:38px}
.cards{display:grid;gap:10px}
.card{
  background:linear-gradient(180deg,rgba(255,255,255,.025),rgba(255,255,255,.01)),var(--panel-elev);
  border:1px solid var(--line-strong);
  border-radius:11px;
  padding:13px 15px;
  line-height:1.45;
  transition:border-color .15s;
}
.card:hover{border-color:rgba(148,163,184,.45)}
.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:4px}
.card h3,.card dd{overflow-wrap:anywhere}
.card-id{
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:12px;
  color:var(--accent);
  background:var(--accent-bg);
  border:1px solid var(--accent-line);
  border-radius:6px;
  padding:1px 6px;
  margin-right:8px;
}
.badge{
  display:inline-flex;
  align-items:center;
  gap:5px;
  font-size:12px;
  font-weight:600;
  border:1px solid var(--line-strong);
  border-radius:999px;
  padding:2px 10px;
  color:var(--muted);
  background:rgba(148,163,184,.08);
  overflow-wrap:anywhere;
  max-width:100%;
  flex-shrink:0;
}
.badge[data-tone=good]{color:var(--good);border-color:var(--good-line);background:var(--good-bg)}
.badge[data-tone=bad]{color:var(--bad);border-color:var(--bad-line);background:var(--bad-bg)}
.badge[data-tone=active]{color:var(--accent);border-color:var(--accent-line);background:var(--accent-bg)}
.badge[data-tone=warn]{color:var(--warn);border-color:var(--warn-line);background:var(--warn-bg)}
.phase-track{
  display:grid;
  grid-template-columns:repeat(5,minmax(0,1fr));
  gap:6px;
  margin:9px 0 8px;
}
.phase-step{
  display:flex;
  align-items:center;
  gap:5px;
  font-size:11.5px;
  color:var(--muted);
  background:rgba(255,255,255,.02);
  border:1px solid var(--line);
  border-radius:7px;
  padding:4px 7px;
  min-width:0;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}
.phase-step[data-step=done]{color:var(--good);border-color:var(--good-line);background:var(--good-bg)}
.phase-step[data-step=current]{color:var(--accent);border-color:var(--accent-line);background:var(--accent-bg);font-weight:600}
.phase-step[data-step=bad]{color:var(--bad);border-color:var(--bad-line);background:var(--bad-bg);font-weight:600}
.gate-strip{
  display:flex;
  flex-wrap:wrap;
  gap:6px;
  margin:6px 0 8px;
}
.gate-chip{
  display:inline-flex;
  align-items:center;
  gap:5px;
  font-size:12px;
  padding:3px 9px;
  border-radius:7px;
  border:1px solid var(--line);
  background:rgba(255,255,255,.02);
  color:var(--muted);
}
.gate-chip[data-tone=good]{color:var(--good);border-color:var(--good-line);background:var(--good-bg)}
.gate-chip[data-tone=bad]{color:var(--bad);border-color:var(--bad-line);background:var(--bad-bg)}
.gate-chip[data-tone=warn]{color:var(--warn);border-color:var(--warn-line);background:var(--warn-bg)}
.gate-chip[data-tone=active]{color:var(--accent);border-color:var(--accent-line);background:var(--accent-bg)}
.task-focus{
  display:flex;
  gap:8px;
  align-items:baseline;
  margin-top:6px;
  padding:7px 10px;
  border-radius:8px;
  background:rgba(255,255,255,.025);
  border:1px solid var(--line);
  overflow-wrap:anywhere;
}
.task-focus strong,.task-focus .remaining{flex-shrink:0;font-size:12.5px}
.task-focus[data-tone=attention]{border-color:var(--warn-line);background:var(--warn-bg)}
.task-focus[data-tone=attention] strong{color:var(--warn)}
.task-focus[data-tone=good]{border-color:var(--good-line);background:var(--good-bg)}
.task-focus[data-tone=good] strong{color:var(--good)}
.task-focus .message{min-width:0;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
.task-details{margin-top:8px}
.task-details>summary{width:fit-content;font-size:12.5px;font-weight:600}
.task-context{margin-top:10px;padding-top:8px;border-top:1px solid var(--line)}
.source{margin-top:8px}
.business-section{border-top:1px solid var(--line);padding-top:10px;margin-top:10px}
.business-section h3{margin-bottom:6px;font-size:13.5px;color:var(--accent)}
.business-section p{margin:4px 0;font-size:13px}
.technical{margin-top:14px;border-top:1px solid var(--line);padding-top:10px}
summary{cursor:pointer;color:var(--accent)}
summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
pre{max-height:320px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}
details.log{margin-top:6px}
.empty{text-align:center;color:var(--muted);padding:26px 12px;border:1px dashed var(--line-strong);border-radius:10px}
.document{width:100%;text-align:left;margin-bottom:8px;display:block;overflow-wrap:anywhere}
.document small{display:block;color:var(--muted)}
.legend{margin-top:10px;color:var(--muted);font-size:12px}
.drawer{position:fixed;inset:0 0 0 auto;width:min(680px,100%);background:#0e1523;border-left:1px solid var(--line-strong);box-shadow:-20px 0 70px #0008;padding:22px;z-index:2;display:flex;flex-direction:column}
.drawer[hidden]{display:none}
.drawer-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.drawer h2{overflow-wrap:anywhere}
.drawer pre{white-space:pre-wrap;overflow-wrap:anywhere;overflow:auto;flex:1;font:13px/1.75 ui-monospace,SFMono-Regular,monospace;border-top:1px solid var(--line);padding-top:16px}
.drawer-status{color:var(--warn);white-space:pre-wrap}
.issues{margin:0;padding-left:20px;color:var(--warn);overflow-wrap:anywhere}
@media(max-width:760px){
  .phase-track{grid-template-columns:repeat(3,minmax(0,1fr))}
}
@media(max-width:600px){
  .shell{padding:14px}
  .header{flex-direction:column}
  .statusbar{grid-template-columns:repeat(2,minmax(0,1fr))}
  .statusbar>div:first-child{grid-column:1/-1}
  .task-panel .searchbar{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr)}
  .searchbar .search-input,.searchbar #filter-count{grid-column:1/-1}
  #clear-filter{grid-column:1/-1;justify-self:start;min-height:0;padding:4px 10px}
  .card-head{flex-direction:row;flex-wrap:wrap;gap:6px 10px}
  .task-focus{flex-wrap:wrap}
}
</style>
</head>
<body>
<main class="shell">
<header class="header">
  <div>
    <div class="brand-row"><span class="eyebrow">SpecLock</span><span class="live-pill"><span class="live-dot"></span><span id="live-tag">实时 · 2s</span></span></div>
    <h1 id="project-name">工作流看板</h1>
    <p id="project-root" class="muted">等待项目数据</p>
  </div>
  <div class="actions">
    <span id="updated" class="muted">每 2 秒刷新</span>
    <button id="lang-toggle" type="button">EN</button>
    <button id="refresh" type="button">立即刷新</button>
  </div>
</header>
<div id="connection" class="notice" role="status" aria-live="polite">正在读取看板…</div>
<section class="statusbar" aria-label="任务与引擎状态">
  <div class="stat-box"><span id="lbl-task-overview" class="muted">任务概览</span><strong id="task-summary">未知</strong><span id="lbl-task-note" class="muted">任务卡状态不等同于验证通过</span></div>
  <div class="stat-box"><span id="lbl-exec-mode" class="muted">执行模式</span><strong id="engine-mode">未知</strong><span id="engine-binding" class="muted">绑定：未知</span></div>
  <div class="stat-box"><span id="lbl-engine-stat" class="muted">引擎状态</span><strong id="engine-state">未知</strong><span id="engine-available" class="muted">可用性：未知</span></div>
</section>
<div id="warning" class="notice" hidden></div>
<section id="reading-issues" class="panel" hidden><h2 id="lbl-issues-title">读取问题</h2><ul id="issues" class="issues"></ul></section>
<div class="dashboard-layout">
  <details id="document-sources" class="panel">
    <summary><strong id="lbl-doc-sources">文档来源</strong> <span id="document-count" class="muted"></span></summary>
    <div id="documents"></div>
    <p id="lbl-doc-legend" class="legend">只读纯文本预览，不执行 Markdown 或 HTML。</p>
  </details>
  <section class="panel task-panel"><h2 id="lbl-cards-title">任务卡</h2>
    <div class="searchbar" role="search" aria-label="任务筛选：搜索、状态与档位">
      <div class="search-input"><label id="lbl-search" class="muted" for="task-filter">搜索任务</label><input id="task-filter" type="search" placeholder="搜索编号或标题" autocomplete="off"></div>
      <div><label id="lbl-state-filter" class="muted" for="state-filter">状态</label><select id="state-filter"><option value="all">全部状态</option></select></div>
      <div><label id="lbl-tier-filter" class="muted" for="tier-filter">档位</label><select id="tier-filter"><option value="all">全部档位</option><option value="light">轻量</option><option value="standard">标准</option><option value="full">完整</option><option value="unknown">未知</option></select></div>
      <button id="clear-filter" type="button">清空筛选</button>
      <p id="filter-count" class="muted" role="status" aria-live="polite"></p>
    </div>
    <div id="tasks" class="cards"></div>
  </section>
</div>
</main>
<aside id="drawer" class="drawer" aria-label="文档纯文本预览" hidden><div class="drawer-header"><h2 id="document-title">文档</h2><button id="close-document" type="button">关闭预览</button></div><p id="document-status" class="drawer-status" role="status"></p><pre id="document-content" tabindex="0"></pre></aside>
<script>
'use strict';
const byId = id => document.getElementById(id);
const currentQuery = typeof location !== 'undefined' && location.search ? location.search : '';
let lang = /[?&]lang=en(?:&|$)/i.test(currentQuery) ? 'en' : 'zh';
const text = (value, fallback) => {
  const fb = fallback !== undefined ? fallback : (lang === 'en' ? 'Unknown' : '未知');
  return value === null || value === undefined || value === '' ? fb : typeof value === 'object' ? JSON.stringify(value) : String(value);
};
const list = value => Array.isArray(value) ? value : [];
function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = text(value);
  if (className) node.className = className;
  return node;
}
const labels = {unknown:'未知',pending:'待处理',not_started:'未开始',in_progress:'进行中',active:'进行中',running:'执行中',blocked:'受阻',done:'完成',completed:'完成',passed:'通过',failed:'失败',skipped:'已跳过',ready:'就绪',unavailable:'不可用',disabled:'未启用',enabled:'已启用',error:'执行异常',invalidated:'已失效',created:'待就绪',implementing:'实施中',pending_verification:'待验证',stale:'证据失效',review_failed:'评审未通过',review_passed:'评审通过 · 待人工验收',cancelled:'已取消'};
const enLabels = {unknown:'Unknown',pending:'Pending',not_started:'Not Started',in_progress:'In Progress',active:'Active',running:'Running',blocked:'Blocked',done:'Done',completed:'Completed',passed:'Passed',failed:'Failed',skipped:'Skipped',ready:'Ready',unavailable:'Unavailable',disabled:'Disabled',enabled:'Enabled',error:'Error',invalidated:'Invalidated',created:'Created',implementing:'Implementing',pending_verification:'Pending Verification',stale:'Stale Snapshot',review_failed:'Review Failed',review_passed:'Review Passed · Pending Acceptance',cancelled:'Cancelled'};
function stateLabel(state) { return (lang === 'en' ? enLabels[state] : labels[state]) || text(state); }
function badge(state) {
  const node = element('span', stateLabel(state), 'badge');
  node.dataset.tone = ['blocked','failed','stale','review_failed','unavailable','error'].includes(state)
    ? 'bad'
    : ['passed','review_passed','completed','ready','done'].includes(state)
      ? 'good'
      : ['in_progress','implementing','active','running'].includes(state)
        ? 'active'
        : 'unknown';
  return node;
}
function sourceLabel(source) {
  const value = text(source, '');
  if (lang === 'en') {
    if (/^(engine|引擎)(?:$|[:/ ·])/i.test(value)) return 'Engine Authoritative · ' + value;
    if (/^(document|docs?|文档)(?:$|[:/ ·])/i.test(value) || /\.(md|txt|yaml)(?:$|[:#])/i.test(value)) return 'Doc Status · ' + value;
    return 'Unverified Source · ' + (value || 'Unknown');
  }
  if (/^(engine|引擎)(?:$|[:/ ·])/i.test(value)) return '引擎权威 · ' + value;
  if (/^(document|docs?|文档)(?:$|[:/ ·])/i.test(value) || /\.(md|txt|yaml)(?:$|[:#])/i.test(value)) return '文档状态 · ' + value;
  return '来源未确认为权威 · ' + (value || '未知');
}
function sourceNode(source) { return element('p', sourceLabel(source), 'source'); }
const taskDisclosure = new Map();
let taskValues = [];
let lastData = null;
const phaseLabels = {planning:'就绪与授权',implementation:'实施',verification:'验证',review:'双轴评审',done:'Agent 结束'};
const enPhaseLabels = {planning:'Ready',implementation:'Implement',verification:'Verify',review:'Review',done:'Done'};
const phaseName = id => (lang === 'en' ? enPhaseLabels[id] : phaseLabels[id]) || id;
const blockerEn = {'任务目标未明确':'Goal not specified','任务范围未明确':'Scope not specified','需求来源未明确':'Source not specified','验收标准未明确':'Acceptance criteria missing','依赖尚未就绪':'Dependencies not ready','档位尚未确认':'Tier confirmation required','方案尚未批准':'Proposal approval required','方案信息不完整':'Proposal incomplete','实施步骤尚未就绪':'Implementation steps not ready','执行者尚未绑定':'Executor session unbound','基线尚未完成有效读取':'Required baselines unread (SHA-256 missing)','验证配置尚未就绪':'Verify config missing','证据快照已失效':'Workspace snapshot invalidated','检查计划尚未确认':'Check plan unconfirmed','当前验证尚未通过':'Verification checks not passed','当前双轴评审尚未通过':'Dual-axis review not passed','后续验证尚未完成':'Upcoming verification checks','后续双轴评审尚未完成':'Upcoming dual-axis review'};
const tBlocker = msg => lang === 'en' ? (blockerEn[msg] || msg) : msg;
function detailBlock(title, value) {
  const section = element('section');
  const pre = element('pre');
  pre.style.whiteSpace = 'pre-wrap';pre.style.overflowWrap = 'anywhere';
  pre.textContent = value === null || value === undefined ? (lang === 'en' ? 'Not recorded' : '未记录') : JSON.stringify(value,null,2);
  section.append(element('h3',title),pre);return section;
}
function filterTasks(values, query = '', state = 'all', tier = 'all') {
  const needle = query.trim().toLocaleLowerCase();
  return list(values).filter(item => [item.id,item.title].some(v => text(v,'').toLocaleLowerCase().includes(needle)) && (state === 'all' || text(item.state,'unknown') === state) && (tier === 'all' || text(item.tier,'unknown') === tier));
}
function summarySection(title, lines, fallback) {
  const fb = fallback !== undefined ? fallback : (lang === 'en' ? 'No record yet — cannot be treated as passed' : '尚无记录，不能视为通过');
  const section = element('section',undefined,'business-section');
  section.append(element('h3',title));
  for (const line of (lines.length ? lines : [fb])) section.append(element('p',line));
  return section;
}
const businessFields = {goal:'目标',scope:'范围',title:'标题',description:'说明',summary:'摘要',content:'内容',status:'状态',impact:'影响',risk:'风险',rollback:'回滚',acceptance:'验收标准',criteria:'验收条件',result:'结果',conclusion:'结论',message:'说明',note:'备注',owner:'负责人',reviewer:'验收人',by:'确认人',at:'时间',next_step:'下一步',next_steps:'下一步',next:'下一步',reason:'原因',source:'来源',documents:'参考文档',completed:'是否完成',accepted:'是否接受',decision:'决定',steps:'步骤',path:'路径',question:'待确认',resume:'恢复条件'};
function businessLines(value, prefix = '', depth = 0) {
  if (depth > 5 || value === null || value === undefined || value === '') return [];
  if (Array.isArray(value)) return value.flatMap(v => businessLines(v,prefix,depth+1));
  if (typeof value === 'object') return Object.entries(businessFields).flatMap(([key,label]) => businessLines(value[key],prefix ? prefix + ' / ' + label : label,depth+1));
  return [(prefix ? prefix + '：' : '') + (typeof value === 'boolean' ? value ? '是' : '否' : String(value))];
}
function disclosure(title, className, state, key, load, initiallyOpen = false) {
  const details = element('details',undefined,className);
  details.append(element('summary',title));
  details.open = state.get(key) ?? initiallyOpen;
  let loaded = false;
  function populate() {
    if (loaded) return;
    details.append(...load());
    loaded = true;
  }
  details.addEventListener('toggle', () => {
    if (!details.isConnected) return;
    state.set(key,details.open);
    if (details.open) populate();
  });
  if (details.open) populate();
  return details;
}
function technicalRecord(item) {
  const d = item.details || {};
  const identity = value => Object.fromEntries(['id','kind','stage','evidence_id','round_id','session_id','executor','binding_version','control_digest','snapshot','valid'].filter(key => value[key] !== undefined).map(key => [key,value[key]]));
  return {current_round:item.current_round,executor:item.executor,session_id:item.session_id,binding_version:d.binding_version,control_digest:d.control_digest,evidence:list(d.evidence).map(identity),attempts:list(d.attempts).map(identity),rounds:list(d.rounds).map(identity)};
}
function renderPhaseTrack(item) {
  const flow = list(item.flow);
  if (!flow.length) return null;
  const track = element('div', undefined, 'phase-track');
  const currentIdx = flow.findIndex(p => p.current);
  const badState = ['failed','stale','review_failed','cancelled'].includes(item.state);
  flow.forEach((p, idx) => {
    const step = element('span', undefined, 'phase-step');
    let mode = 'pending';
    if (item.state === 'review_passed' || item.state === 'completed') mode = 'done';
    else if (currentIdx >= 0 && idx < currentIdx) mode = 'done';
    else if (p.current) mode = badState ? 'bad' : 'current';
    step.dataset.step = mode;
    const icon = mode === 'done' ? '✓ ' : mode === 'bad' ? '✗ ' : mode === 'current' ? '● ' : '○ ';
    step.textContent = icon + phaseName(p.id);
    track.append(step);
  });
  return track;
}
function renderGateStrip(item) {
  const b = item.business || {};
  const strip = element('div', undefined, 'gate-strip');
  const baselines = list(b.baseline);
  const readCount = baselines.filter(v => v.status === '已读').length;
  const invalidBase = baselines.some(v => v.status === '已失效');
  const baseChip = element('span', undefined, 'gate-chip');
  if (baselines.length) {
    baseChip.dataset.tone = invalidBase ? 'bad' : readCount === baselines.length ? 'good' : 'warn';
    baseChip.textContent = (lang === 'en' ? 'Baselines ' : '基线 ') + readCount + '/' + baselines.length + (readCount === baselines.length ? (lang === 'en' ? ' SHA-256 ✓' : ' SHA-256 ✓') : invalidBase ? (lang === 'en' ? ' Stale ✗' : ' 已失效 ✗') : (lang === 'en' ? ' Unread' : ' 待读'));
  } else {
    baseChip.textContent = lang === 'en' ? 'Baselines —' : '基线 —';
  }
  const attempts = list(b.verification);
  const latestRun = attempts.at(-1);
  const checkChip = element('span', undefined, 'gate-chip');
  if (latestRun) {
    const ok = latestRun.status === 'passed' && item.state !== 'stale';
    checkChip.dataset.tone = item.state === 'stale' ? 'warn' : ok ? 'good' : latestRun.status === 'running' ? 'active' : 'bad';
    checkChip.textContent = (lang === 'en' ? 'Checks: ' : '验证：') + stateLabel(item.state === 'stale' ? 'stale' : latestRun.status) + ' (' + attempts.length + ')';
  } else {
    checkChip.textContent = lang === 'en' ? 'Checks: Pending' : '验证：待执行';
  }
  const reviews = list(b.review);
  const spec = reviews[0]?.conclusion, std = reviews[1]?.conclusion;
  const revChip = element('span', undefined, 'gate-chip');
  if (spec === 'pass' && std === 'pass') {
    revChip.dataset.tone = 'good';
    revChip.textContent = lang === 'en' ? 'Dual Review: Passed ✓' : '双轴评审：通过 ✓';
  } else if (spec === 'fail' || std === 'fail' || spec === 'invalidated' || std === 'invalidated') {
    revChip.dataset.tone = 'bad';
    revChip.textContent = lang === 'en' ? 'Dual Review: Action Required ✗' : '双轴评审：未通过 ✗';
  } else {
    revChip.textContent = lang === 'en' ? 'Dual Review: Pending' : '双轴评审：待执行';
  }
  strip.append(baseChip, checkChip, revChip);
  return strip;
}
function renderBusiness(item, state, defaultGroup) {
  const root = element('div'), b = item.business || {}, readiness = item.readiness || {};
  const group = (key, title, load) => disclosure(title,'business-section',state,key,load,key === defaultGroup);
  const d = item.details || {};
  const pending = list(item.pending).flatMap(p => typeof p === 'string' ? [p] : ['待确认：' + text(p.question,'内容未记录'),'影响：' + text(p.impact,'未记录'),'负责人：' + text(p.owner,'未记录'),'恢复条件：' + text(p.resume,'未记录'),'来源：' + text(p.source,'来源未记录')]);
  root.append(group('attention',lang === 'en' ? 'Blockers & Pending Decisions' : '当前阻止条件与待确认',() => [
    summarySection(lang === 'en' ? 'Blocking Gates' : '当前阻止条件',list(readiness.blocking).map(tBlocker),lang === 'en' ? 'No active blocking gates; does not imply verification passed' : '暂无已记录的当前阻止条件；不代表验证通过'),
    summarySection(lang === 'en' ? 'Pending Items' : '当前待确认',pending,lang === 'en' ? 'No pending items' : '暂无已记录的待确认事项'),
    summarySection(lang === 'en' ? 'Upcoming Gates' : '后续阶段',list(readiness.upcoming).map(tBlocker),lang === 'en' ? 'No upcoming gaps' : '暂无后续阶段缺项记录')
  ]));
  const todos = list(d.todos);
  root.append(group('scope',lang === 'en' ? 'Goal, Scope & Acceptance' : '目标、范围与验收',() => [
    summarySection(lang === 'en' ? 'Goal & Scope' : '任务目标与范围',[...businessLines(d.goal,'目标'),...businessLines(d.scope,'范围')]),
    summarySection(lang === 'en' ? 'Acceptance Criteria' : '验收标准',businessLines(d.acceptance)),
    summarySection(lang === 'en' ? 'Human Acceptance' : '人工验收',businessLines(d.human_acceptance), lang === 'en' ? 'Human acceptance not recorded yet; Agent review pass is not delivery' : '人工验收尚未发生；Agent 评审通过不等于人工接受或交付'),
    summarySection(lang === 'en' ? 'Doc Delivery Marker' : '文档交付标记',item.human_delivery_completed === true ? [lang === 'en' ? 'Marked delivered in docs (non-engine evidence)' : '文档标记已交付（非引擎验收证据）',(lang === 'en' ? 'Source: ' : '来源：') + text(item.human_delivery_source)] : [lang === 'en' ? 'No delivery marker in docs' : '尚无文档交付完成标记'])
  ]));
  const checks = list((d.plan || {}).checks).map(c => text(c.name || c.title || c.id,lang === 'en' ? 'Unnamed check' : '未命名检查') + (lang === 'en' ? ' · cmd: ' : ' · 命令：') + list(c.argv).filter(v=>typeof v==='string').join(' ') + (lang === 'en' ? ' · cwd: ' : ' · 工作目录：') + text(c.cwd));
  const baseStatusText = s => lang === 'en' ? ({'已读':'Read (SHA-256 verified)','未读':'Unread','已失效':'Invalidated'}[s] || s) : s;
  root.append(group('implementation',lang === 'en' ? 'Proposal, Steps & Baselines' : '方案、实施与交接',() => [
    summarySection(lang === 'en' ? 'Proposal Summary' : '方案摘要',businessLines(d.proposal)),
    summarySection(lang === 'en' ? 'Implementation Steps' : '实施步骤',todos.map(t => text(t.title,lang === 'en' ? 'Unnamed step' : '未命名步骤') + ' · ' + stateLabel(t.status))),
    summarySection(lang === 'en' ? 'Required Baselines' : '基线读取',list(b.baseline).map(v => text(v.path) + ' · ' + baseStatusText(text(v.status)))),
    summarySection(lang === 'en' ? 'Approvals' : '批准摘要',list(b.approvals).map(v => text(v.title) + ' · ' + text(v.status))),
    summarySection(lang === 'en' ? 'Handoff Next Step' : '交接下一步',businessLines(d.handoff),lang === 'en' ? 'No handoff recorded' : '尚未记录交接下一步')
  ]));
  root.append(group('verification',lang === 'en' ? 'Verification & Dual-Axis Review' : '验证与评审',() => [
    summarySection(lang === 'en' ? 'Check Plan' : '验证检查计划',checks,lang === 'en' ? 'No readable check plan' : '尚无可读检查命令，不能视为验证已执行'),
    renderVerification(b),
    summarySection(lang === 'en' ? 'Dual-Axis Review' : '双轴评审',list(b.review).flatMap(v => [v.title + '：' + ({pass:lang==='en'?'Passed (recorded)':'通过（保存记录）',fail:lang==='en'?'Failed':'未通过',invalidated:lang==='en'?'Invalidated':'已失效',unknown:lang==='en'?'Unknown':'未知，未确认通过'}[v.conclusion] || '未知，未确认通过') + (lang==='en'?' · Unresolved required: ':' · 必须解决待办 ') + text(v.unresolved),...list(v.findings).map(f => text(f.message) + ' · ' + (f.resolved === true ? (lang==='en'?'Resolved':'已解决') : f.required === true ? (lang==='en'?'Required':'必须解决') : (lang==='en'?'Pending':'待确认')))])),
    summarySection(lang === 'en' ? 'Invalidation Log' : '证据失效摘要',list(b.invalidations),lang === 'en' ? 'No invalidations recorded' : '未记录失效；文件新鲜度仍未核验')
  ]));
  root.append(group('history',lang === 'en' ? 'Round History' : '轮次历史',() => [
    summarySection(lang === 'en' ? 'Rounds' : '轮次记录',list(b.rounds).map(r => (lang==='en'?'Round #':'第 ') + r.number + (lang==='en'?'':' 轮') + (r.current ? (lang==='en'?' (Current)':'（当前）') : '') + ' · ' + stateLabel(r.state) + ' · ' + phaseName(r.phase)))
  ]));
  return root;
}
function renderVerification(b) {
  const verification = summarySection(lang === 'en' ? 'Verification Attempts' : '验证尝试与逐项诊断',[],lang === 'en' ? 'No real verification run yet' : '尚无真实验证尝试');
  if (list(b.verification).length) verification.replaceChildren(element('h3',lang === 'en' ? 'Verification Attempts' : '验证尝试与逐项诊断'));
  list(b.verification).forEach((attempt,index) => {
    verification.append(element('p',(lang==='en'?'Attempt #':'第 ') + (index+1) + (lang==='en'?'':' 次验证') + ' · ' + stateLabel(attempt.status) + (attempt.failure ? (lang==='en'?' · Error: ':' · 执行异常：') + text(attempt.failure) : '')));
    list(attempt.checks).forEach(check => {
      verification.append(element('p',text(check.id,'未命名检查') + (lang==='en'?' · exit=':' · 退出码：') + text(check.exit_code) + (lang==='en'?' · reason=':' · 原因：') + text(check.reason)));
      const logs = element('details',undefined,'log');logs.append(element('summary',lang==='en'?'Expand stdout / stderr (max 16384 chars)':'展开此检查日志 · 纯文本（最多 16384 字符）'));
      const raw = '标准输出\n' + text(check.stdout,'无') + '\n标准错误\n' + text(check.stderr,'无');
      logs.append(element('pre',raw.slice(0,16384) + (raw.length > 16384 || check.truncated ? '\n[日志已达到限额或源日志被截断]' : '')));verification.append(logs);
    });
  });
  return verification;
}
function taskHighlight(item) {
  const b = item.business || {};
  const reports = list(b.verification);
  const concerns = list((item.readiness || {}).blocking).map(message => ({label:lang === 'en' ? 'Blocked' : '当前阻止',message:tBlocker(message),group:'attention'}));
  const addConcern = (label, message, genericBlocker) => {
    const index = concerns.findIndex(concern => concern.message === genericBlocker || concern.message === tBlocker(genericBlocker));
    const concern = {label,message,group:'verification'};
    if (index === -1) concerns.push(concern);
    else concerns[index] = concern;
  };
  const latest = reports.at(-1);
  if (item.state === 'failed') {
    const check = list(latest?.checks).find(v => (Number.isInteger(v.exit_code) && v.exit_code !== 0) || (v.reason && v.reason !== 'exit'));
    const message = check ? text(check.id,'检查') + ' · ' + (check.reason && check.reason !== 'exit' ? check.reason : (lang === 'en' ? 'exit ' : '退出码 ') + check.exit_code) : latest?.failure;
    addConcern(lang === 'en' ? 'Check Failed' : '验证失败',message || (lang === 'en' ? 'Inspect latest verification attempt' : '查看最近一次验证尝试'),'当前验证尚未通过');
  }
  if (item.state === 'stale') addConcern(lang === 'en' ? 'Stale' : '证据失效',list(b.invalidations).at(-1) || (lang === 'en' ? 'Re-verification required' : '查看需要重新取得的证据'),'证据快照已失效');
  if (item.state === 'review_failed') {
    const axis = list(b.review).find(v => v.conclusion === 'fail');
    const finding = list(axis?.findings).find(v => v.required === true && v.resolved !== true);
    addConcern(lang === 'en' ? 'Review Failed' : '评审未通过',finding?.message || axis?.title || (lang === 'en' ? 'See dual-axis review findings' : '查看双轴评审记录'),'当前双轴评审尚未通过');
  }
  for (const pending of list(item.pending)) {
    concerns.push({label:lang === 'en' ? 'Pending' : '待确认',message:text(typeof pending === 'string' ? pending : pending?.question,'内容未记录'),group:'attention'});
  }
  if (concerns.length) return {...concerns[0],remaining:concerns.length - 1};
  const d = item.details || {};
  if (item.state === 'implementing' && item.progress?.current) return {label:lang === 'en' ? 'Current Step' : '当前步骤',message:item.progress.current};
  if (item.state === 'pending_verification') {
    const checks = list(d.plan?.checks).filter(c => list(c.argv).some(arg => typeof arg === 'string' && arg.trim()));
    const planned = checks.map(c => text(c.name || c.title || c.id,'未命名检查')).join(lang === 'en' ? ', ' : '、');
    if (planned) return {label:lang === 'en' ? 'Next' : '下一步',message:(lang === 'en' ? 'Run verification: ' : '执行验证：') + planned + (reports.length ? '' : (lang === 'en' ? ' (no attempt yet)' : '（未记录验证尝试）')),group:'verification'};
    if (!reports.length) return {label:lang === 'en' ? 'Unverified' : '验证未记录',message:lang === 'en' ? 'No verification attempt yet' : '尚无验证尝试',group:'verification'};
  }
  if (item.state === 'review_passed') return {label:lang === 'en' ? 'Done (Agent)' : 'Agent 终态',message:lang === 'en' ? 'Verified & dual-axis review passed — ready for human acceptance' : item.summary,tone:'good'};
  const handoff = d.handoff;
  const next = businessLines(handoff?.next_step || handoff?.next_steps || handoff?.next || (typeof handoff === 'string' ? handoff : null))[0];
  return next ? {label:lang === 'en' ? 'Next' : '下一步',message:next} : {message:item.summary || (lang === 'en' ? 'No progress notes yet' : '暂无当前进展记录')};
}
function renderTasks(values) {
  taskValues = list(values);
  const query = byId('task-filter').value.trim().toLowerCase();
  const items = filterTasks(taskValues,query,byId('state-filter').value,byId('tier-filter').value);
  byId('filter-count').textContent = lang === 'en' ? ('Showing ' + items.length + ' / ' + taskValues.length + ' tasks') : ('找到 ' + items.length + ' / ' + taskValues.length + ' 个任务');
  byId('task-summary').textContent = lang === 'en' ? (taskValues.length + ' total · ' + items.length + ' shown') : (taskValues.length + ' 个任务 · 显示 ' + items.length);
  byId('tasks').replaceChildren(...(items.length ? items.map(item => {
    const node = element('article',undefined,'card');
    const head = element('div',undefined,'card-head');
    const titleWrap = element('h3');
    titleWrap.append(element('span', text(item.id), 'card-id'), element('span', text(item.title)));
    head.append(titleWrap,badge(item.state));
    const progress = item.progress || {};
    const tierMap = lang === 'en' ? {light:'Light Tier',standard:'Standard Tier',full:'Full Tier'} : {light:'轻量档',standard:'标准档',full:'完整档'};
    const tier = tierMap[item.tier] || (lang === 'en' ? 'Unknown Tier' : '档位未知');
    const meta = [tier,phaseLabels[item.phase] ? (lang === 'en' ? phaseName(item.phase) + ' Phase' : phaseLabels[item.phase] + '阶段') : (lang === 'en' ? 'Unknown Phase' : '阶段未知')];
    if (Number.isInteger(progress.done) && progress.total > 0) meta.push((lang === 'en' ? 'Steps ' : '实施 ') + progress.done + '/' + progress.total);
    const phaseTrack = renderPhaseTrack(item);
    const gateStrip = renderGateStrip(item);
    const highlight = taskHighlight(item);
    const focus = element('p',undefined,'task-focus');
    if (highlight.remaining !== undefined) focus.dataset.tone = 'attention';
    else if (highlight.tone) focus.dataset.tone = highlight.tone;
    if (highlight.label) focus.append(element('strong',highlight.label));
    focus.append(element('span',highlight.message,'message'));
    if (highlight.remaining) focus.append(element('span',(lang === 'en' ? '+' + highlight.remaining + ' more' : '另有 ' + highlight.remaining + ' 项'),'remaining muted'));
    if (!taskDisclosure.has(item.id)) taskDisclosure.set(item.id,new Map());
    const state = taskDisclosure.get(item.id);
    const details = disclosure(lang === 'en' ? 'Task Details & Evidence' : '任务详情','task-details',state,'task',() => {
      const context = element('div',undefined,'task-context');
      context.append(element('p',item.summary || (lang === 'en' ? 'No phase summary' : '暂无阶段说明')),
        element('p',list(item.flow).map(p => (p.current ? '▶ ' : '') + phaseName(p.id)).join(' → '),'muted'),
        element('p',(lang === 'en' ? 'Updated: ' : '更新时间：') + text(item.updated_at) + (lang === 'en' ? ' · Activity unknown (no heartbeat)' : ' · 活动未知（无退出或心跳证据）'),'muted'),
        element('p',lang === 'en' ? 'Stored evidence only; review pass is not human delivery.' : '证据为保存记录，当前文件新鲜度未核验；评审通过不是交付。','legend'),sourceNode(item.source));
      return [context,renderBusiness(item,state,highlight.group),
        disclosure(lang === 'en' ? 'Technical Details · Raw IDs & Bindings' : '技术详情 · 原始记录 / 标识 / 绑定','technical',state,'technical',() => [
          detailBlock(lang === 'en' ? 'Internal Evidence & Bindings' : '内部证据标识与绑定',technicalRecord(item))
        ])];
    });
    const children = [head,element('p',meta.join(' · '),'muted')];
    if (phaseTrack) children.push(phaseTrack);
    children.push(gateStrip,focus,details);
    node.append(...children);
    return node;
  }) : [element('p',taskValues.length ? (lang === 'en' ? 'No matching tasks. Try clearing filters.' : '没有匹配任务，试试清空筛选或调整状态和档位；不代表任务已完成。') : (lang === 'en' ? 'No tasks registered yet.' : '暂无任务记录；等待任务登记，不代表已完成。'),'empty')]));
}
function renderDocuments(values) {
  const items = list(values);
  const missing = items.filter(item => item.exists === false).length;
  const unknown = items.filter(item => item.exists !== true && item.exists !== false).length;
  byId('document-count').textContent = lang === 'en'
    ? [items.length + ' files',missing ? missing + ' missing' : '',unknown ? unknown + ' unknown' : ''].filter(Boolean).join(' · ')
    : [items.length + ' 份',missing ? missing + ' 份缺失' : '',unknown ? unknown + ' 份状态未知' : ''].filter(Boolean).join(' · ');
  byId('documents').replaceChildren(...(items.length ? items.map(item => {
    const node = element('button', undefined, 'document');
    node.type = 'button';
    const existsText = lang === 'en' ? (item.exists === true ? 'exists' : item.exists === false ? 'missing' : 'unknown') : (item.exists === true ? '存在' : item.exists === false ? '缺失' : '存在性未知');
    node.append(element('span',item.title || item.path),element('small',text(item.path) + ' · ' + existsText));
    node.disabled = item.exists === false || typeof item.path !== 'string' || !item.path;
    node.addEventListener('click', () => openDocument(item.path, item.title, node));
    return node;
  }) : [element('p',lang === 'en' ? 'No document sources configured' : '未提供文档来源','empty')]));
}
function applyChromeLang() {
  const en = lang === 'en';
  byId('lang-toggle').textContent = en ? '中文' : 'EN';
  byId('live-tag').textContent = en ? 'Live · 2s' : '实时 · 2s';
  byId('refresh').textContent = en ? 'Refresh' : '立即刷新';
  byId('lbl-task-overview').textContent = en ? 'Tasks' : '任务概览';
  byId('lbl-task-note').textContent = en ? 'Read-only projection from SQLite & docs' : '任务卡状态不等同于验证通过';
  byId('lbl-exec-mode').textContent = en ? 'Guardrails' : '执行模式';
  byId('lbl-engine-stat').textContent = en ? 'Engine Health' : '引擎状态';
  byId('lbl-issues-title').textContent = en ? 'Reading Issues' : '读取问题';
  byId('lbl-doc-sources').textContent = en ? 'Documents' : '文档来源';
  byId('lbl-doc-legend').textContent = en ? 'Read-only plain-text preview.' : '只读纯文本预览，不执行 Markdown 或 HTML。';
  byId('lbl-cards-title').textContent = en ? 'Tasks & Guardrail Evidence' : '任务卡';
  byId('lbl-search').textContent = en ? 'Search' : '搜索任务';
  byId('task-filter').placeholder = en ? 'Search ID or title' : '搜索编号或标题';
  byId('lbl-state-filter').textContent = en ? 'State' : '状态';
  byId('lbl-tier-filter').textContent = en ? 'Tier' : '档位';
  byId('clear-filter').textContent = en ? 'Clear' : '清空筛选';
  byId('close-document').textContent = en ? 'Close' : '关闭预览';
}
function render(data) {
  lastData = data;
  applyChromeLang();
  const project = data.project || {}, mode = data.mode || {};
  byId('project-name').textContent = text(project.name,lang === 'en' ? 'SpecLock Dashboard' : '工作流看板');
  byId('project-root').textContent = text(project.root,lang === 'en' ? 'Project root unknown' : '项目根未知');
  byId('engine-mode').textContent = lang === 'en' ? 'SQLite + Hooks Gate' : '任务级流程门禁';
  byId('engine-binding').textContent = (lang === 'en' ? 'Binding: ' : '绑定：') + text(mode.binding);
  byId('engine-state').textContent = stateLabel(mode.state);
  byId('engine-available').textContent = (lang === 'en' ? 'Source: ' : '可用性：') + (mode.available === true ? (lang === 'en' ? 'SQLite Ready' : '可用') : mode.available === false ? (lang === 'en' ? 'Unavailable' : '不可用，不降级为通过') : (lang === 'en' ? 'Unknown' : '未知'));
  const warnings = [];
  if (mode.warning) warnings.push(text(mode.warning));
  if (mode.migration_warning && mode.migration_warning !== mode.warning) warnings.push(text(mode.migration_warning));
  if (mode.available !== true) warnings.push(lang === 'en' ? 'Engine database unavailable; showing docs only.' : '未确认任务数据源可用。页面保留文档信息，不将其视为引擎批准或验证结果。');
  byId('warning').textContent = warnings.join('\n');
  byId('warning').hidden = !warnings.length;
  renderTasks(data.tasks);renderDocuments(data.documents);
  const issues = list(data.issues);
  byId('reading-issues').hidden = !issues.length;
  byId('issues').replaceChildren(...issues.map(issue => element('li',issue)));
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
    byId('updated').textContent = (lang === 'en' ? 'Updated ' : '最近成功：') + lastSuccess.toLocaleTimeString(lang === 'en' ? 'en-US' : 'zh-CN');
    byId('connection').hidden = true;
  } catch (error) {
    byId('connection').hidden = false;byId('connection').className = 'notice error';
    byId('connection').textContent = '刷新失败：' + (error.name === 'AbortError' ? '请求超时' : text(error.message)) + '。' + (lastSuccess ? '当前保留 ' + lastSuccess.toLocaleTimeString('zh-CN') + ' 的旧数据，请勿视为实时状态。' : '尚无成功读取的数据。') + ' 2 秒后重试。';
  } finally {
    clearTimeout(timeout);polling = false;byId('refresh').disabled = false;
    timer = setTimeout(refresh,2000);
  }
}
let documentController = null, documentVersion = 0, documentTrigger = null;
async function openDocument(path, title, trigger) {
  if (documentController) documentController.abort();
  const version = ++documentVersion;
  const controller = new AbortController();documentController = controller;documentTrigger = trigger;
  byId('drawer').hidden = false;byId('document-title').textContent = text(title || path);
  byId('document-content').textContent = '';byId('document-status').textContent = (lang === 'en' ? 'Loading: ' : '正在读取：') + path;
  byId('close-document').focus();
  const timeout = setTimeout(() => controller.abort(),8000);
  try {
    const data = await getJSON('/api/document?path=' + encodeURIComponent(path),controller.signal);
    if (!data || typeof data.content !== 'string' || typeof data.path !== 'string') throw new Error('文档响应格式不正确');
    if (version !== documentVersion) return;
    byId('document-content').textContent = data.content;
    byId('document-status').textContent = data.path + (lang === 'en' ? ' · Plain text, read-only' : ' · 纯文本，只读');
  } catch (error) {
    if (version !== documentVersion) return;
    byId('document-status').textContent = (lang === 'en' ? 'Failed to load: ' : '文档读取失败：') + (error.name === 'AbortError' ? 'timeout' : text(error.message));
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
function populateStateOptions() {
  const select = byId('state-filter');
  const prev = select.value || 'all';
  const allOpt = element('option', lang === 'en' ? 'All States' : '全部状态');
  allOpt.value = 'all';
  const opts = [allOpt];
  for (const state of ['created','implementing','pending_verification','running','passed','failed','stale','review_failed','review_passed','cancelled','unknown','pending','in_progress','blocked','completed']) {
    const option = element('option',stateLabel(state));option.value = state;opts.push(option);
  }
  select.replaceChildren(...opts);
  select.value = prev;
}
byId('refresh').addEventListener('click',refresh);
byId('lang-toggle').addEventListener('click',() => {
  lang = lang === 'en' ? 'zh' : 'en';
  populateStateOptions();
  if (lastData) render(lastData); else applyChromeLang();
});
byId('close-document').addEventListener('click',closeDocument);
document.addEventListener('keydown',event => { if (event.key === 'Escape' && !byId('drawer').hidden) closeDocument(); });
byId('task-filter').addEventListener('input',() => renderTasks(taskValues));
for (const id of ['state-filter','tier-filter']) byId(id).addEventListener('change',() => renderTasks(taskValues));
byId('clear-filter').addEventListener('click',() => { byId('task-filter').value = '';byId('state-filter').value = 'all';byId('tier-filter').value = 'all';renderTasks(taskValues);byId('task-filter').focus(); });
applyChromeLang();
populateStateOptions();
refresh();
</script>
</body>
</html>'''
