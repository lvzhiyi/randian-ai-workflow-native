"""workflow_config.py 的回归测试：python3 -m unittest discover -s plugins/workflow-core/scripts"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('workflow_config', HERE / 'workflow_config.py')
workflow_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow_config)
parse = workflow_config.parse_yaml_subset
ConfigError = workflow_config.ConfigError

VALID = '''# 项目配置
version: 1
docs:
  product_root: docs/product   # 行尾注释
  cards_dir: "docs/product/任务"
  glossary: docs/product/术语表.md
review:
  base_branch: develop
verify:
  standard: python3 scripts/check.py full
  full:
    - python3 scripts/check.py full
    - flutter build apk --debug
platforms:
  default:
    - android
  excluded:
    - web
api:
  project: '班期课-APP'
notes:
  - 默认只验证 Android
'''


class ParseTests(unittest.TestCase):
    def test_parses_maps_lists_quotes_and_comments(self):
        data = parse(VALID)
        self.assertEqual(data['version'], '1')
        self.assertEqual(data['docs']['product_root'], 'docs/product')
        self.assertEqual(data['docs']['cards_dir'], 'docs/product/任务')
        self.assertEqual(data['verify']['full'], ['python3 scripts/check.py full',
                                                  'flutter build apk --debug'])
        self.assertEqual(data['api']['project'], '班期课-APP')
        self.assertEqual(data['notes'], ['默认只验证 Android'])

    def test_hash_inside_quotes_is_kept(self):
        self.assertEqual(parse('a: "x # y"\n')['a'], 'x # y')

    def test_booleans(self):
        self.assertEqual(parse('a: true\nb: false\n'), {'a': True, 'b': False})

    def test_unsupported_syntax_reports_line(self):
        cases = {
            'a: [x, y]\n': 1,
            'a: {b: 1}\n': 1,
            'a: |\n  text\n': 1,
            'a: &x 1\n': 1,
            '---\na: 1\n': 1,
            'a: 1\n\tb: 2\n': 2,
            'a:\n  - x\n  b: 1\n': 3,
            'a: 1\na: 2\n': 2,
            'just text\n': 1,
            'a:\n - x\n': 2,
        }
        for text, line in cases.items():
            with self.subTest(text=text):
                with self.assertRaises(ConfigError) as ctx:
                    parse(text)
                self.assertEqual(ctx.exception.line, line, str(ctx.exception))


class SchemaTests(unittest.TestCase):
    def test_valid_config_has_no_errors(self):
        self.assertEqual(workflow_config.validate(parse(VALID)), [])

    def test_unknown_keys_wrong_types_and_version(self):
        errors = workflow_config.validate(parse(
            'version: 2\ndocs:\n  product_rot: x\nreview: develop\nverify:\n  full: true\nextra: 1\n'))
        text = '\n'.join(errors)
        self.assertIn('version', text)
        self.assertIn('docs.product_rot', text)
        self.assertIn('review', text)
        self.assertIn('verify.full', text)
        self.assertIn('extra', text)

    def test_missing_version_is_error(self):
        self.assertTrue(any('version' in e for e in workflow_config.validate({'docs': {}})))


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def test_yaml_file_wins_over_markdown_section(self):
        self.write('ai-workflow.yaml', 'version: 1\ndocs:\n  product_root: yaml/product\n')
        self.write('AGENTS.md', '## 工作流配置\n\n- 产品文档根：`md/product/`\n')
        config = workflow_config.load(self.root)
        self.assertEqual(config.source, 'ai-workflow.yaml')
        self.assertEqual(config.get('docs.product_root'), 'yaml/product')

    def test_markdown_section_is_legacy_fallback(self):
        self.write('AGENTS.md', '## 工作流配置\n\n- 产品文档根：`md/product/`\n'
                                '- 工程规范：`eng/` 下的 coding\n')
        config = workflow_config.load(self.root)
        self.assertTrue(config.legacy)
        self.assertEqual(config.get('docs.product_root'), 'md/product')
        self.assertEqual(config.get('docs.dev_docs'), 'eng')

    def test_no_config_is_empty(self):
        config = workflow_config.load(self.root)
        self.assertEqual(config.source, '默认值')
        self.assertIsNone(config.get('docs.product_root'))

    def test_invalid_yaml_raises_with_file_and_line(self):
        self.write('ai-workflow.yaml', 'version: 1\ndocs: [a]\n')
        with self.assertRaises(ConfigError) as ctx:
            workflow_config.load(self.root)
        self.assertIn('ai-workflow.yaml:2', str(ctx.exception))

    def test_schema_error_raises(self):
        self.write('ai-workflow.yaml', 'version: 1\ndocz:\n  a: b\n')
        with self.assertRaises(ConfigError):
            workflow_config.load(self.root)

    def test_missing_paths_are_reported_and_placeholders_skipped(self):
        self.write('ai-workflow.yaml', 'version: 1\ndocs:\n  product_root: docs/product\n'
                                       '  glossary: 待确认\nhandoff:\n  default: docs/h/{task_id}.md\n'
                                       'code_rules_doc: docs/coding.md\n')
        self.write('docs/coding.md', '# x\n')
        missing = workflow_config.load(self.root).missing_paths()
        self.assertEqual(missing, ['docs.product_root: docs/product'])


if __name__ == '__main__':
    unittest.main()
