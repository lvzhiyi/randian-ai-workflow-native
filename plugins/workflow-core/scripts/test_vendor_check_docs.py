"""vendor_check_docs.py 单文件自包含导出与沙箱隔离测试。"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS_DIR = Path(__file__).resolve().parent
VENDOR = SCRIPTS_DIR / 'vendor_check_docs.py'


class VendorCheckDocsTests(unittest.TestCase):
    def test_exported_script_runs_standalone_without_plugin_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / 'consumer'
            out_script = project / 'scripts/check_docs.py'

            # 1. 导出单文件脚本
            res = subprocess.run(
                [sys.executable, str(VENDOR), '--output', str(out_script)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue(out_script.is_file())

            # 2. --check 校验一致
            chk = subprocess.run(
                [sys.executable, str(VENDOR), '--check', str(out_script)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(chk.returncode, 0, chk.stderr)

            # 3. 脱离插件目录、无 PYTHONPATH，仅用导出单文件运行
            (project / 'ai-workflow.yaml').write_text(
                'version: 1\ndocs:\n  product_root: docs/product\n  cards_dir: docs/product/任务\n'
                '  dev_docs: docs/development\n',
                encoding='utf-8',
            )
            cards = project / 'docs/product/任务'
            cards.mkdir(parents=True)
            (project / 'docs/development').mkdir(parents=True)
            card = cards / '登录.md'
            card.write_text(
                '### AUTH-R01 登录\n\n- [ ] 子需求完成\n- 协作状态：待处理\n'
                '- 来源：PRD 第 1 节\n- 验收：登录成功\n',
                encoding='utf-8',
            )
            env = {'PATH': '/usr/bin:/bin'}
            run_ok = subprocess.run(
                [sys.executable, str(out_script), '--root', str(project), '--check-config'],
                cwd=project, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(run_ok.returncode, 0, run_ok.stdout + run_ok.stderr)
            self.assertIn('status=PASS', run_ok.stdout)

            # 4. 验证状态与勾选冲突会被单文件脚本拦截
            card.write_text(
                '### AUTH-R01 登录\n\n- [x] 子需求完成\n- 协作状态：评审通过，待人工验收\n'
                '- 来源：PRD 第 1 节\n- 验收：登录成功\n',
                encoding='utf-8',
            )
            run_fail = subprocess.run(
                [sys.executable, str(out_script), '--root', str(project)],
                cwd=project, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(run_fail.returncode, 1, run_fail.stdout + run_fail.stderr)
            self.assertIn('完成勾选框已勾选，但协作状态仍为非终态', run_fail.stderr)


if __name__ == '__main__':
    unittest.main()
