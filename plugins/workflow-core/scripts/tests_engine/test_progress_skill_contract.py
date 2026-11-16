"""静态核对技能安全同步协议，不模拟或宣称宿主端到端同步成功。"""
from pathlib import Path
import unittest

SKILLS = Path(__file__).resolve().parents[2] / 'skills'


class ProgressSkillContractTests(unittest.TestCase):
    def test_cursor_schema_and_no_fake_items(self):
        text = (SKILLS / 'workflow/SKILL.md').read_text(encoding='utf-8')
        for clause in ('merge 必填', 'todos 至少 2 项', '单项或空清单',
                       '不得凑假 todo', '没有读取现有列表的 API'):
            with self.subTest(clause=clause):
                self.assertIn(clause, text)

    def test_unknown_list_and_old_round_cannot_be_destructively_synced(self):
        text = (SKILLS / 'workflow/SKILL.md').read_text(encoding='utf-8')
        for clause in ('未知已有清单时不得 merge=false', 'merge=true 不能删除旧轮次',
                       '不能安全清理旧项', '工具拒绝', '不得声称原生同步成功',
                       '不提供自动 UI bridge', 'CLI 只提供只读投影'):
            with self.subTest(clause=clause):
                self.assertIn(clause, text)

    def test_lifecycle_skills_defer_to_safe_sync_and_chat_fallback(self):
        for name in ('implement', 'handoff', 'verify', 'review'):
            text = (SKILLS / name / 'SKILL.md').read_text(encoding='utf-8')
            with self.subTest(skill=name):
                self.assertIn('安全同步', text)
                self.assertIn('聊天清单', text)


if __name__ == '__main__':
    unittest.main()
