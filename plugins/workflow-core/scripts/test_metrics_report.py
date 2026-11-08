"""metrics_report.py 的回归测试：python3 -m unittest discover -s plugins/workflow-core/scripts"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import metrics_report as report  # noqa: E402


def review(sources, findings=()):
    return {'type': 'review', 'sources': sources,
            'findings': [{'axis': 'standards', 'severity': s, 'rule': r} for r, s in findings]}


def args(**extra):
    return argparse.Namespace(**{'all': False, 'days': 90, 'min_reviews': 20, **extra})


class RuleTests(unittest.TestCase):
    def test_codex_report_labels_unavailable_trigger_rate(self):
        output = report.render(args(), 'sample', None, [review(['docs/ui.md'])], [])
        self.assertIn('Codex 暂无技能触发率数据', output)
        self.assertIn('规则命中表', output)
        self.assertNotIn('review 触发率低于', output)

    def test_actions_follow_hits_and_outcomes(self):
        reviews = [review(['a.md'], [('a.md 注释', '应修'), ('a.md 颜色', '应修'), ('b.md 少', '建议')]) for _ in range(3)]
        reviews[0]['findings'].pop()
        delivers = [{'resolutions': [{'rule': 'a.md 注释', 'outcome': '已修复'}] * 2 + [{'rule': 'a.md 颜色', 'outcome': '接受例外'}] * 2}]
        actions = {r['rule']: r['action'] for r in report.rule_table(reviews, delivers)}
        self.assertIn('有效', actions['a.md 注释'])
        self.assertIn('例外', actions['a.md 颜色'])
        self.assertEqual(actions['b.md 少'], '观察')

    def test_zero_hit_needs_enough_checks(self):
        many = [review(['docs/ui.md'])] * 20
        self.assertEqual(report.deletion_candidates(many, [], 20)['candidates'][0][0], 'docs/ui.md')
        self.assertEqual(report.deletion_candidates(many[:5], [], 20)['candidates'], [])
        self.assertEqual(report.deletion_candidates(many[:5], [], 20)['watching'][0][2], 5)

    def test_hit_source_is_not_candidate(self):
        many = [review(['docs/ui.md'], [('ui.md 颜色', '应修')])] * 20
        self.assertEqual(report.deletion_candidates(many, [], 20)['candidates'], [])

    def test_security_rules_are_protected(self):
        found = report.deletion_candidates([review(['docs/安全规范.md'])] * 30, [], 20)
        self.assertEqual(found['candidates'], [])
        self.assertEqual(found['protected'][0][0], 'docs/安全规范.md')

    def test_old_rule_silent_in_window_is_candidate(self):
        found = report.deletion_candidates([review(['docs/ui.md'])] * 20, [review(['docs/ui.md'], [('ui.md 旧规则', '建议')])], 20)
        self.assertIn('ui.md 旧规则', [c[0] for c in found['candidates']])


class TriggerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def transcript(self, name, *blocks):
        path = Path(self.tmp.name) / f'{name}.jsonl'
        lines = [{'type': 'user', 'timestamp': '2026-11-01T00:00:00Z', 'cwd': self.tmp.name, 'message': {'content': '任务'}},
                 {'type': 'assistant', 'timestamp': '2026-11-01T00:00:01Z', 'message': {'content': [
                     {'type': 'tool_use', 'id': f'{name}{i}', 'name': n, 'input': d} for i, (n, d) in enumerate(blocks)]}}]
        path.write_text('\n'.join(json.dumps(l, ensure_ascii=False) for l in lines), encoding='utf-8')
        return path

    def test_rates_use_code_sessions_as_denominator(self):
        edit = ('Edit', {'file_path': '/x/a.dart'})
        usages = [report.session_usage(self.transcript('s1', edit, ('Skill', {'skill': 'workflow-core:review'}))),
                  report.session_usage(self.transcript('s2', edit)),
                  report.session_usage(self.transcript('s3', ('Skill', {'skill': 'workflow-core:deliver'})))]
        stats = report.trigger_stats(usages, [{'type': 'deliver', 'session_id': 's1'}])
        self.assertEqual((stats['total'], stats['any'], stats['review'], stats['deliver'], stats['recorded']), (2, 1, 1, 0, 1))


class RenderTests(unittest.TestCase):
    def test_empty_data_renders_and_warns(self):
        text = report.render(args(), 'demo', [], [], [])
        self.assertIn('样本不足', text)
        self.assertIn('暂无评审命中记录', text)
        self.assertIn('暂无候选', text)

    def test_low_trigger_hides_candidates(self):
        usages = [{'id': 's', 'code_changed': True, 'skills': set()}]
        records = [dict(review(['docs/ui.md']), type='review')] * 20
        text = report.render(args(), 'demo', usages, records, [])
        self.assertIn('暂不列为候选', text)

    def test_fixed_without_block_is_ignored(self):
        records = [{'type': 'stop_block', 'session_id': 'a', 'outcome': 'fixed'}, {'type': 'stop_block', 'session_id': 'b', 'outcome': 'blocked'},
                   {'type': 'stop_block', 'session_id': 'b', 'outcome': 'fixed'}]
        self.assertIn('1 次，重试后修好 1', report.render(args(), 'demo', [], records, []))

    def test_spec_findings_stay_out_of_rule_table(self):
        spec = {'type': 'review', 'sources': [], 'findings': [{'axis': 'spec', 'severity': '阻塞', 'rule': '验收甲'}]}
        self.assertEqual(report.rule_table([spec], []), [])
        self.assertIn('1 项，其中阻塞 1', report.render(args(), 'demo', [], [spec], []))

    def test_review_without_code_change_is_explained(self):
        usages = [{'id': 's', 'code_changed': False, 'skills': {'review', 'deliver'}}]
        self.assertIn('review 1 次、deliver 1 次', report.render(args(), 'demo', usages, [], []))

    def test_pipe_in_rule_is_escaped(self):
        text = report.render(args(), 'demo', [], [review(['a.md'], [('a|b', '建议')])], [])
        self.assertIn('a\\|b', text)


if __name__ == '__main__':
    unittest.main()
