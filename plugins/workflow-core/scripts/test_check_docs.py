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

COMPLETE = ('### DEMO-R01 示例\n\n- [ ] 子需求完成\n- 负责人：待指定\n'
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
        self.assertEqual(len(errors), 4)
        self.assertTrue(all('DEMO-R01 缺少字段' in error for error in errors))

    def test_next_chapter_is_not_counted_as_card_field(self):
        errors = self.cards('### DEMO-R01 示例\n\n## 4. 其他\n\n' + COMPLETE.split('\n', 2)[2])
        self.assertEqual(len(errors), 4)

    def test_structured_pending_item_requires_all_keys(self):
        errors = self.cards(COMPLETE + '- 待确认：缺设计｜影响：R01｜负责人：待指定\n')
        self.assertEqual(len(errors), 1)
        self.assertIn('恢复条件：/来源：', errors[0])

    def test_legacy_free_text_pending_item_is_tolerated(self):
        self.assertEqual(self.cards(COMPLETE + '- 待确认：是否记住上次 Tab。\n'), [])

    def test_shared_ui_heading_is_not_a_requirement(self):
        self.assertEqual(self.cards('### AUTH-UI01 登录页共享 UI\n\n- 目标：示例\n'), [])


class LinkTests(ProjectTestCase):
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
    CONFIG = ('# 项目\n\n## 工作流配置（ai-dev-workflow）\n\n'
              '- 产品文档根：`product/`（项目首页：`product/首页.md`）\n'
              '- 任务卡目录 / 总览：`product/cards/` / `product/cards/总览.md`\n'
              '- 工程规范：`eng/` 下的 coding\n\n## 其他\n\n- 产品文档根：`wrong/`\n')

    YAML = ('version: 1\ndocs:\n  product_root: product\n  cards_dir: product/cards\n'
            '  dev_docs: eng\n')

    def test_legacy_markdown_config_still_works_with_hint(self):
        self.write('AGENTS.md', self.CONFIG)
        self.write('product/cards/x.md', '### DEMO-R01 示例\n')
        code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn('路径来源：工作流配置（Markdown 旧格式）', output)
        self.assertIn('建议运行 /workflow-core:init 迁移', output)
        self.assertIn('DEMO-R01 缺少字段', output)

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

    def test_cli_overrides_config(self):
        self.write('AGENTS.md', self.CONFIG)
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
