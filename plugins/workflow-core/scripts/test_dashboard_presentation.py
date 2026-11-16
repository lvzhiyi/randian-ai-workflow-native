"""仪表盘业务投影及真实浏览器筛选函数的专属回归。"""
import json
import shutil
import subprocess
import unittest
from dashboard_projection import project_task
from dashboard_page import page_html


class PresentationTests(unittest.TestCase):
    def task(self, **updates):
        current = dict(id="r", state="implementing", phase="implementation", todos=[], attempts=[], evidence=[])
        current.update(updates)
        return project_task(dict(id="T1", protocol_version=2, current_round="r", baseline=["docs/a.md"], missing=["checks", "review", "baseline"], rounds=[current]), {})

    def test_phase_aware_missing_and_unknown(self):
        item = self.task()
        self.assertEqual(item["readiness"]["blocking"], ["基线尚未完成有效读取"])
        self.assertEqual(item["readiness"]["upcoming"], ["后续验证尚未完成", "后续双轴评审尚未完成"])
        self.assertNotIn("通过", self.task(state="nonsense")["summary"])

    def test_invalid_baseline_and_verification_only(self):
        item = self.task(evidence=[dict(kind="baseline", valid=False, data=dict(path="docs/a.md", complete=True))], attempts=[dict(stage="implementation", status="failed"), dict(stage="verification", status="error", failure="RUN_ERROR", results=[dict(id="lint", exit_code=2, reason="exit", stderr="bad")])])
        self.assertEqual(item["business"]["baseline"][0]["status"], "已失效")
        self.assertEqual(len(item["business"]["verification"]), 1)
        self.assertEqual(len(item["failures"]), 1)
        self.assertEqual(item["business"]["verification"][0]["checks"][0]["stderr"], "bad")

    def test_unread_and_deduplicated_invalidation(self):
        self.assertEqual(self.task()["business"]["baseline"][0]["status"], "未读")
        item = self.task(evidence=[dict(kind="review", valid=False, reason="changed"), dict(kind="review", valid=False, reason="changed")])
        self.assertEqual(len(item["business"]["invalidations"]), 1)

    def test_current_blockers_and_dual_review_are_not_pass_by_default(self):
        item = self.task(phase="review", missing=["checks", "review", "future_flag"], evidence=[dict(kind="review", valid=True, data=dict(axes=dict(spec=dict(conclusion="pass", findings=[]), standards=dict(conclusion="fail", findings=[dict(message="补充边界测试", required=True, resolved=False)]))))], required_findings=dict(standards={"f": False}))
        self.assertEqual(item["readiness"]["upcoming"], [])
        self.assertEqual(len(item["readiness"]["blocking"]), 3)
        self.assertEqual(item["business"]["review"][1]["unresolved"], 1)
        self.assertEqual(item["business"]["review"][1]["conclusion"], "fail")
        self.assertEqual(self.task()["business"]["review"][0]["conclusion"], "unknown")

    def test_pass_axis_with_unresolved_required_findings_is_not_pass(self):
        item = self.task(evidence=[dict(kind="review", data=dict(axes=dict(spec=dict(conclusion="pass", findings=[]))))], required_findings=dict(spec={"unresolved": False}))
        self.assertEqual(item["business"]["review"][0]["conclusion"], "fail")

    def test_baseline_binding_and_control_changes_invalidate(self):
        for change in ({"session_id": "new"}, {"control_digest": "new"}):
            item = self.task(**change, evidence=[dict(kind="baseline", valid=True, control_digest="old", data=dict(path="docs/a.md", complete=True, session_id="old"))])
            self.assertEqual(item["business"]["baseline"][0]["status"], "已失效")

    def test_page_security_and_collapsed_technical_details(self):
        page = page_html()
        self.assertNotIn("innerHTML", page)
        self.assertNotIn("setInterval", page)
        self.assertIn("if (polling) return", page)
        self.assertIn("技术详情 · 原始记录", page)
        self.assertNotIn("<details open", page)
        self.assertIn("raw.slice(0,16384)", page)
        self.assertIn("@media(max-width:600px)", page)

    @unittest.skipUnless(shutil.which("node"), "Node 不可用")
    def test_real_render_keeps_business_outside_closed_technical_details(self):
        task = dict(id="T2", protocol_version=2, current_round="r", goal="目标业务", scope="范围业务", acceptance=["验收业务"], proposal=dict(goal="方案业务", risk="风险业务", rollback="回滚业务"), plan=dict(checks=[dict(id="lint", argv=["python3", "-m", "unittest"], cwd=".")]), rounds=[dict(id="r", state="implementing", phase="implementation", todos=[dict(title="步骤甲", status="done"), dict(title="步骤乙", status="pending")], handoff=dict(next_step="交接业务"))])
        pending = [dict(question="确认业务", impact="影响业务", owner="负责人业务", resume="恢复业务", source="docs/card.md｜产品业务")]
        item = project_task(task, dict(pending=pending))
        self.assertEqual(item["pending"], pending)
        stub = r'''class Node {
          constructor(tag) { this.tag=tag;this.children=[];this.style={};this.dataset={};this.open=false;this.value='';this.content=''; }
          set textContent(v) { this.content=String(v);this.children=[]; }
          get textContent() { return this.content+this.children.map(n=>n.textContent).join(' '); }
          append(...nodes) { this.children.push(...nodes); }
          replaceChildren(...nodes) { this.content='';this.children=nodes; }
          addEventListener() {}
        }
        const nodes={}; const document={createElement:tag=>new Node(tag),getElementById:id=>nodes[id]||(nodes[id]=new Node('div'))};
        function visible(n, excludeTechnical=false) { if(excludeTechnical&&n.className==='technical')return '';if(n.tag==='details'&&!n.open)return n.children.filter(c=>c.tag==='summary').map(c=>visible(c,excludeTechnical)).join(' ');return n.content+' '+n.children.map(c=>visible(c,excludeTechnical)).join(' '); }
        function walk(n) { return [n,...n.children.flatMap(walk)]; }
        '''
        script = page_html().split("<script>")[1].split("</script>")[0].split("byId('refresh').addEventListener")[0]
        assertions = r'''
        nodes['state-filter']=new Node('select');nodes['state-filter'].value='all';nodes['tier-filter']=new Node('select');nodes['tier-filter'].value='all';
        renderTasks([fixture]); const card=nodes.tasks.children[0];const all=walk(card); const technical=all.find(n=>n.className==='technical');
        if(!technical||technical.open)throw Error('技术详情必须关闭');
        const initial=visible(card,true);
        for(const word of ['确认业务','影响业务','负责人业务','恢复业务','docs/card.md｜产品业务','步骤甲','步骤乙'])if(!initial.includes(word))throw Error('默认业务缺失：'+word);
        for(const d of all.filter(n=>n.tag==='details'&&n.className!=='technical'&&n.className!=='log'))d.open=true;
        const business=visible(card,true);
        for(const word of ['目标业务','范围业务','验收业务','方案业务','风险业务','回滚业务','python3 -m unittest','人工验收尚未发生','交接业务'])if(!business.includes(word))throw Error('业务详情缺失：'+word);
        if(business.includes('"goal":'))throw Error('业务区不得输出原始JSON');
        const internal=JSON.stringify(technicalRecord(fixture));
        for(const word of ['目标业务','验收业务','确认业务','交接业务'])if(internal.includes(word))throw Error('技术区混入业务字段：'+word);
        if(businessLines({goal:'可读目标',session_id:'私密会话',unknown_field:'原始隐藏'}).join(' ').includes('私密会话'))throw Error('业务字段白名单失败');
        '''
        result = subprocess.run(["node", "-e", stub + script + "\nconst fixture=" + json.dumps(item, ensure_ascii=False) + ";" + assertions], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node 不可用")
    def test_real_filter_combines_query_state_and_tier(self):
        script = page_html().split("<script>")[1].split("</script>")[0]
        script = script.split("byId('refresh').addEventListener")[0]
        cases = [{"id":"T1", "title":"搜索功能", "state":"implementing", "tier":"standard"}, {"id":"T2", "title":"搜索功能", "state":"failed", "tier":"full"}]
        script += "\nconst tasks=" + json.dumps(cases, ensure_ascii=False) + ";\n"
        script += "if(filterTasks(tasks,'搜索','implementing','standard').length!==1)throw Error('组合筛选'); if(filterTasks(tasks,'T2','implementing','all').length!==0)throw Error('交集'); if(filterTasks(tasks,'failed','all','all').length!==0)throw Error('只搜索编号标题'); if(filterTasks(tasks,'','all','all').length!==2)throw Error('清空');"
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
