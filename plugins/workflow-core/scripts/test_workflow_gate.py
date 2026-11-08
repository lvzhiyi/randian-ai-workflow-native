"""workflow_gate.py 的回归测试：python3 -m unittest discover -s plugins/workflow-core/scripts"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).parent


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.state = base / 'state'
        self.project = base / 'project'
        (self.project / '.git').mkdir(parents=True)
        (self.project / 'ai-workflow.yaml').write_text('version: 1\n', encoding='utf-8')

    def hook(self, name, cwd=None, **extra):
        payload = {'session_id': 's1', 'cwd': str(cwd or self.project), 'hook_event_name': name, **extra}
        env = {**os.environ, 'WORKFLOW_GATE_DIR': str(self.state)}
        result = subprocess.run([sys.executable, str(HERE / 'workflow_gate.py')], input=json.dumps(payload), text=True,
                                capture_output=True, env=env)
        self.assertEqual(result.returncode, 0)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def edit(self, path='lib/a.dart'):
        self.hook('PostToolUse', tool_name='Edit', tool_input={'file_path': path})

    def deliver(self):
        self.hook('PostToolUse', tool_name='Skill', tool_input={'skill': 'workflow-core:deliver'})

    def test_session_start_adds_context_only_for_workflow_projects(self):
        self.assertIn('workflow-core:workflow', self.hook('SessionStart')['hookSpecificOutput']['additionalContext'])
        other = Path(self.tmp.name) / 'other'
        (other / '.git').mkdir(parents=True)
        self.assertIsNone(self.hook('SessionStart', cwd=other))

    def test_stop_reminds_after_code_edit(self):
        self.edit()
        output = self.hook('Stop')
        self.assertEqual(output['hookSpecificOutput']['hookEventName'], 'Stop')
        self.assertIn('workflow-core:deliver', output['hookSpecificOutput']['additionalContext'])

    def test_no_reminder_without_edit_after_deliver_or_for_docs(self):
        self.assertIsNone(self.hook('Stop'))
        self.edit('docs/a.md')
        self.assertIsNone(self.hook('Stop'))
        self.edit()
        self.deliver()
        self.assertIsNone(self.hook('Stop'))

    def test_edit_after_deliver_reminds_again(self):
        self.edit()
        self.deliver()
        self.edit()
        self.assertIsNotNone(self.hook('Stop'))

    def test_slash_deliver_counts(self):
        self.edit()
        self.hook('UserPromptExpansion', expansion_type='slash_command', command_name='workflow-core:deliver')
        self.assertIsNone(self.hook('Stop'))

    def test_stop_hook_active_releases(self):
        self.edit()
        self.assertIsNone(self.hook('Stop', stop_hook_active=True))

    def test_bash_write_needs_existing_code_path(self):
        (self.project / 'lib').mkdir()
        (self.project / 'lib' / 'a.dart').write_text('', encoding='utf-8')
        self.hook('PostToolUse', tool_name='Bash', tool_input={'command': 'grep x lib/a.dart'})
        self.assertIsNone(self.hook('Stop'))
        self.hook('PostToolUse', tool_name='Bash', tool_input={'command': 'sed -i "" s/a/b/ missing/b.dart'})
        self.assertIsNone(self.hook('Stop'))
        self.hook('PostToolUse', tool_name='Bash', tool_input={'command': 'sed -i "" s/a/b/ lib/a.dart'})
        self.assertIsNotNone(self.hook('Stop'))

    def test_project_without_config_is_ignored(self):
        other = Path(self.tmp.name) / 'other'
        (other / '.git').mkdir(parents=True)
        self.hook('PostToolUse', cwd=other, tool_name='Edit', tool_input={'file_path': 'a.dart'})
        self.assertIsNone(self.hook('Stop', cwd=other))
        self.assertFalse(self.state.exists())

    def test_disabled_file_turns_off(self):
        self.state.mkdir()
        (self.state / 'disabled').touch()
        self.edit()
        self.assertIsNone(self.hook('Stop'))
        self.assertIsNone(self.hook('SessionStart'))

    def test_bad_input_is_ignored(self):
        env = {**os.environ, 'WORKFLOW_GATE_DIR': str(self.state)}
        result = subprocess.run([sys.executable, str(HERE / 'workflow_gate.py')], input='not json', text=True, capture_output=True, env=env)
        self.assertEqual((result.returncode, result.stdout), (0, ''))


if __name__ == '__main__':
    unittest.main()
