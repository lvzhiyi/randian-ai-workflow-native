"""check_docs.py 的回归测试：python3 -m unittest discover -s plugins/workflow-core/scripts"""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

import sys

sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location('check_docs', Path(__file__).with_name('check_docs.py'))
check_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_docs)

COMPLETE = ('### DEMO-R01 示例\n\n- [ ] 子需求完成\n- 协作状态：待处理\n'
            '- 来源：需求说明第 1 节\n- 验收：示例\n')


class ProjectTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = check_docs.main(['--root', str(self.root), *argv])
        return code, out.getvalue()


class CardTests(ProjectTestCase):
    def cards(self, content):
        self.write('docs/product/任务/示例.md', content)
        return check_docs.check_cards(self.root, self.root / 'docs/product/任务')

    def test_complete_card_passes(self):
        self.assertEqual(self.cards(COMPLETE), [])

    def test_missing_fields_are_reported(self):
        errors = self.cards('### DEMO-R01 示例\n\n- 目标：示例\n')
        self.assertEqual(len(errors), 3)
        self.assertTrue(all('DEMO-R01 缺少字段' in error for error in errors))

    def test_next_chapter_is_not_counted_as_card_field(self):
        errors = self.cards('### DEMO-R01 示例\n\n## 4. 其他\n\n' + COMPLETE.split('\n', 2)[2])
        self.assertEqual(len(errors), 3)

    def test_structured_pending_item_requires_core_keys(self):
        errors = self.cards(COMPLETE + '- 待确认：缺设计｜影响：R01\n')
        self.assertEqual(len(errors), 1)
        self.assertIn('恢复条件：', errors[0])
        self.assertEqual(self.cards(COMPLETE + '- 待确认：缺设计｜影响：R01｜恢复条件：补齐主稿\n'), [])

    def test_checked_box_conflicts_with_non_terminal_status(self):
        for status in ('待确认', '待验证', '实施中', '评审通过，待人工验收', '已取消'):
            card = COMPLETE.replace('- [ ] ', '- [x] ').replace('待处理', status)
            errors = self.cards(card)
            self.assertEqual(len(errors), 1, status)
            self.assertIn('完成勾选框已勾选，但协作状态仍为非终态', errors[0])
        combined = ('### DEMO-R02 组合栏\n\n- [x] 子需求完成\n'
                    '- 协作状态 / 优先级：待确认 / P0\n- 来源：需求\n- 验收：通过\n')
        errors = self.cards(combined)
        self.assertEqual(len(errors), 1)
        self.assertIn('非终态「待确认」', errors[0])

    def test_checked_box_allows_terminal_status(self):
        for status in ('已完成', '人工验收通过', '已交付'):
            card = COMPLETE.replace('- [ ] ', '- [x] ').replace('待处理', status)
            self.assertEqual(self.cards(card), [], status)

    def test_legacy_free_text_pending_item_is_tolerated(self):
        self.assertEqual(self.cards(COMPLETE + '- 待确认：是否记住上次 Tab。\n'), [])

    def test_shared_ui_heading_is_not_a_requirement(self):
        self.assertEqual(self.cards('### AUTH-UI01 登录页共享 UI\n\n- 目标：示例\n'), [])


class LinkTests(ProjectTestCase):
    def test_checks_links_in_change_proposals_and_handoffs(self):
        self.write('docs/development/changes/T1/proposal.md', '[设计](design.md)\n')
        self.write('docs/development/handoffs/T2.md', '[方案](../changes/T2/proposal.md)\n')
        code, output = self.run_main('--skip-cards')
        self.assertEqual(code, 1, output)
        self.assertIn('docs/development/changes/T1/proposal.md: 链接目标不存在 design.md', output)
        self.assertIn('docs/development/handoffs/T2.md: 链接目标不存在', output)

    def test_broken_link_and_missing_anchor(self):
        self.write('docs/product/b.md', '# 标题 一\n\n## 重复\n\n## 重复\n')
        self.write('docs/product/a.md', '[ok](b.md#标题-一) [dup](b.md#重复-1) '
                                        '[bad](b.md#不存在) [gone](c.md) [web](https://x.y/z)\n')
        errors = check_docs.check_links(self.root, [self.root / 'docs/product/a.md'])
        self.assertEqual(len(errors), 2)
        self.assertTrue(any('锚点不存在 b.md#不存在' in e for e in errors))
        self.assertTrue(any('链接目标不存在 c.md' in e for e in errors))

    def test_same_file_anchor(self):
        self.write('AGENTS.md', '# 入口\n\n[self](#入口) [bad](#没有)\n')
        errors = check_docs.check_links(self.root, [self.root / 'AGENTS.md'])
        self.assertEqual(errors, ['AGENTS.md: 锚点不存在 #没有'])


class ConfigTests(ProjectTestCase):
    YAML = ('version: 1\ndocs:\n  product_root: product\n  cards_dir: product/cards\n'
            '  dev_docs: eng\n')

    def test_yaml_config_is_used(self):
        self.write('ai-workflow.yaml', self.YAML)
        self.write('product/cards/x.md', COMPLETE)
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertIn('路径来源：ai-workflow.yaml', output)
        self.assertIn('任务卡=product/cards', output)

    def test_invalid_yaml_is_blocked_not_defaulted(self):
        self.write('ai-workflow.yaml', 'version: 1\ndocs: [product]\n')
        code, output = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn('status=BLOCKED', output)
        self.assertIn('ai-workflow.yaml:2', output)

    def test_check_config_reports_missing_paths(self):
        self.write('ai-workflow.yaml', self.YAML)
        code, output = self.run_main('--check-config')
        self.assertEqual(code, 1)
        self.assertIn('路径不存在 docs.product_root: product', output)

    def test_yaml_config_reports_card_errors(self):
        self.write('ai-workflow.yaml', self.YAML)
        self.write('product/cards/x.md', '### DEMO-R01 示例\n')
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn('DEMO-R01 缺少字段', output)

    def test_cli_overrides_config(self):
        self.write('ai-workflow.yaml', self.YAML)
        self.write('other/cards/x.md', COMPLETE)
        code, output = self.run_main('--cards-dir', 'other/cards')
        self.assertEqual(code, 0, output)

    def test_defaults_without_config_and_missing_dirs(self):
        code, output = self.run_main()
        self.assertEqual(code, 0, output)
        self.assertIn('路径来源：默认值', output)
        self.assertIn('任务卡目录不存在，跳过', output)

    def test_missing_root_is_blocked(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_docs.main(['--root', str(self.root / 'nope')])
        self.assertEqual(code, 2)
        self.assertIn('status=BLOCKED', out.getvalue())


class GlossaryTests(ProjectTestCase):
    def test_glossary_entries_need_definition_and_unique_names(self):
        self.write('ai-workflow.yaml', 'version: 1\ndocs:\n  glossary: docs/product/术语表.md\n')
        self.write('docs/product/术语表.md', '# 术语表\n\n### 模块卡\n\n- 定义：一个模块的产品任务卡。\n\n'
                                           '### 子需求\n\n- 避免：需求点\n\n### 模块卡\n\n- 定义：重复\n')
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn('词条「子需求」缺少「定义」', output)
        self.assertIn('词条重名「模块卡」', output)


if __name__ == '__main__':
    unittest.main()
