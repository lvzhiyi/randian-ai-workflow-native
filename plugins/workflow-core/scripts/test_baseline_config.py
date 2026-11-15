"""编码基线清单的配置与范围匹配回归。"""
from pathlib import Path
import tempfile
import unittest

from workflow_config import load, validate


class BaselineConfigTests(unittest.TestCase):
    def test_new_template_has_one_authoritative_baseline_list(self):
        from workflow_config import parse_yaml_subset
        template = Path(__file__).resolve().parents[1] / "templates" / "ai-workflow.yaml"
        config = parse_yaml_subset(template.read_text(encoding="utf-8"))
        self.assertNotIn("code_rules_doc", config)
        self.assertEqual(config["baseline"]["required"].count("docs/development/coding.md"), 1)

    def test_accepts_explicit_required_and_scoped_rules(self):
        self.assertEqual(validate({"version": "1", "baseline": {
            "required": ["docs/architecture.md"],
            "scoped": ["lib/**/*.dart => docs/flutter.md"],
        }}), [])

    def test_resolves_legacy_and_scoped_baselines_without_duplicates(self):
        from baseline_config import resolve_baselines
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ai-workflow.yaml").write_text("""version: 1
code_rules_doc: docs/coding.md
baseline:
  required:
    - docs/architecture.md
    - docs/coding.md
  scoped:
    - lib/**/*.dart => docs/flutter.md
    - src/*.py => docs/python.md
""", encoding="utf-8")
            result = resolve_baselines(root, ["lib/main.dart"], load(root))
            self.assertEqual(result, ["docs/coding.md", "docs/architecture.md", "docs/flutter.md"])

    def test_rejects_path_escape_and_malformed_scope(self):
        from baseline_config import resolve_baselines
        with tempfile.TemporaryDirectory() as directory:
            for config in ({"baseline": {"required": ["../outside.md"]}},
                           {"baseline": {"scoped": ["missing separator"]}}):
                with self.subTest(config=config), self.assertRaises(ValueError):
                    resolve_baselines(Path(directory), ["src/a.py"], config)

    def test_directory_scope_includes_descendant_rules(self):
        from baseline_config import resolve_baselines
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(resolve_baselines(Path(directory), ["lib"], {
                "baseline": {"scoped": ["lib/**/*.dart => docs/flutter.md"]}}),
                ["docs/flutter.md"])

    def test_validates_all_rules_even_when_scope_does_not_match(self):
        from baseline_config import resolve_baselines
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                resolve_baselines(Path(directory), ["src/a.py"], {
                    "baseline": {"scoped": ["lib/** => ../outside.md"]}})


if __name__ == "__main__":
    unittest.main()
