"""执行轨迹采集与还原的回归测试：python3 -m unittest discover -s plugins/workflow-core/scripts"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import trace_hook  # noqa: E402
import trace_server  # noqa: E402

CONFIG = [('python3 scripts/check.py full', 'verify.standard')]


def reduce(*events):
    return trace_server.reduce_events(list(events), lambda cwd: CONFIG)


def pre(tool_id, ts, tool='Bash', command='ls', **extra):
    return {'event': 'PreToolUse', 'ts': ts, 'tool_name': tool, 'tool_use_id': tool_id, 'cwd': '/tmp',
            'input': {'command': command}, **extra}


def post(tool_id, ts, output='ok', name='PostToolUse', **extra):
    return {'event': name, 'ts': ts, 'tool_name': 'Bash', 'tool_use_id': tool_id, 'cwd': '/tmp',
            'input': {'command': 'ls'}, 'output': output, **extra}


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, payload):
        env = {**os.environ, 'WORKFLOW_TRACE_DIR': str(self.root)}
        return subprocess.run([sys.executable, str(HERE / 'trace_hook.py')], input=payload, text=True, env=env).returncode

    def test_disabled_writes_nothing(self):
        self.assertEqual(self.run_hook('{"session_id":"s1","hook_event_name":"Stop"}'), 0)
        self.assertFalse((self.root / 'events').exists())

    def test_enabled_redacts_and_appends(self):
        (self.root / 'enabled').touch()
        payload = json.dumps({'session_id': 's1', 'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_use_id': 't',
                              'tool_input': {'command': 'curl -H "Authorization: Bearer abc123" x?token=zzz'}})
        self.assertEqual(self.run_hook(payload), 0)
        text = (self.root / 'events' / 's1.jsonl').read_text(encoding='utf-8')
        self.assertNotIn('abc123', text)
        self.assertNotIn('zzz', text)

    def test_bad_input_and_unsafe_session_are_ignored(self):
        (self.root / 'enabled').touch()
        self.assertEqual(self.run_hook('not json'), 0)
        self.assertEqual(self.run_hook('{"session_id":"../x","hook_event_name":"Stop"}'), 0)
        self.assertEqual(list((self.root).rglob('*.jsonl')), [])


class ReduceTests(unittest.TestCase):
    def step(self, state):
        return state['turns'][0]['steps'][0]

    def test_running_then_ok(self):
        self.assertEqual(self.step(reduce(pre('a', 1)))['status'], 'running')
        self.assertEqual(self.step(reduce(pre('a', 1), post('a', 2)))['status'], 'ok')

    def test_failure(self):
        step = self.step(reduce(pre('a', 1), post('a', 2, name='PostToolUseFailure', error='Exit code 1')))
        self.assertEqual((step['status'], step['output']), ('fail', 'Exit code 1'))

    def test_codex_patch_with_docs_first_counts_as_code_edit(self):
        command = '*** Begin Patch\n*** Add File: notes.md\n*** Update File: lib/a.dart\n*** End Patch'
        state = reduce(pre('a', 1, tool='apply_patch', command=command), post('a', 2),
                       {'event': 'Interrupt', 'ts': 3})
        step = self.step(state)
        self.assertEqual((step['kind'], step['title'], step['status']), ('edit', 'lib/a.dart', 'ok'))
        self.assertEqual(state['state'], 'idle')

    def test_codex_verification_without_exit_code_needs_success_evidence(self):
        state = reduce(pre('edit', 1, tool='apply_patch', command='*** Add File: main.py'), post('edit', 2),
                       pre('verify', 3, command='pytest'), post('verify', 4, output='no tests ran', host='codex'))
        step = state['turns'][0]['steps'][1]
        self.assertEqual(step['status'], 'unknown')
        checks = {label: result for result, label, _ in trace_server.build_checks(state['turns'][0]['steps'])}
        self.assertEqual(checks['测试'], 'warn')

    def test_codex_trace_counts_all_source_paths_after_clipping_patch(self):
        command = ('*** Add File: notes.md\n+' + 'x' * 2100
                   + '\n*** Add File: lib/a.py\n+a\n*** Add File: lib/b.py\n+b')
        event = trace_hook.build_event({'hook_event_name': 'PostToolUse', 'tool_use_id': 'patch',
                                        'tool_name': 'apply_patch', 'tool_input': {'command': command}}, 1)
        state = reduce(event)
        checks = {label: detail for _, label, detail in trace_server.build_checks(state['turns'][0]['steps'])}
        self.assertIn('2 个手写代码文件', checks['代码改动'])

    def test_post_without_pre_creates_step(self):
        self.assertEqual(self.step(reduce(post('a', 2)))['status'], 'ok')

    def test_stop_ends_cancelled_tool_but_not_subagent(self):
        state = reduce(pre('a', 1), pre('b', 2, agent_id='x', agent_type='Explore'), {'event': 'Stop', 'ts': 3})
        self.assertEqual([s['status'] for s in state['turns'][0]['steps']], ['pending', 'running'])
        self.assertEqual(state['state'], 'idle')

    def test_config_command_marks_verify(self):
        step = self.step(reduce(pre('a', 1, command='python3 scripts/check.py full')))
        self.assertEqual(step['kind'], 'verify')
        self.assertIn('verify.standard', step['group'])

    def test_agent_message_is_not_a_new_turn(self):
        state = reduce({'event': 'UserPromptSubmit', 'ts': 1, 'prompt': '任务'},
                       {'event': 'UserPromptSubmit', 'ts': 2, 'prompt': '<agent-message from="a">结果'}, pre('a', 3))
        self.assertEqual(len(state['turns']), 1)
        self.assertEqual(len(state['turns'][0]['steps']), 1)

    def test_background_agent_is_labelled(self):
        state = reduce(pre('a', 1, tool='Agent'), post('a', 2, output='{"status": "async_launched"}'))
        self.assertIn('后台', self.step(state)['group'])

    def test_internal_tools_hidden(self):
        self.assertEqual(reduce(pre('a', 1, tool='mcp__ccd_turn__wrap_up'))['turns'], [])

    def test_slash_before_or_after_submit_lands_in_turn(self):
        slash = {'event': 'UserPromptExpansion', 'expansion_type': 'slash_command', 'command_name': 'workflow-core:review'}
        submit = {'event': 'UserPromptSubmit', 'prompt': '/x'}
        for first, second in ((({**slash, 'ts': 1}), {**submit, 'ts': 2}), ({**submit, 'ts': 1}, {**slash, 'ts': 2})):
            state = reduce(first, second) if first['event'] == 'UserPromptExpansion' else reduce(first, second)
            self.assertEqual(state['turns'][0]['steps'][0]['title'], 'workflow-core:review')


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'events').mkdir()
        (self.root / 'events' / 's1.jsonl').write_text(json.dumps(pre('a', 1)) + '\n{broken', encoding='utf-8')
        self.server = trace_server.bind_server(str(self.root), 0)
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def get(self, path):
        with urlopen(self.base + path, timeout=3) as response:
            return json.load(response)

    def status(self, path, headers=None):
        try:
            with urlopen(Request(self.base + path, headers=headers or {}), timeout=3) as response:
                return response.status
        except HTTPError as error:
            return error.code

    def test_session_and_unchanged(self):
        data = self.get('/api/session?id=s1')
        self.assertEqual(data['turns'][0]['steps'][0]['status'], 'running')
        self.assertTrue(self.get(f'/api/session?id=s1&v={data["version"]}')['unchanged'])

    def test_running_verify_after_edit_does_not_break_checks(self):
        events = [pre('e', 1, tool='Edit'), post('e', 2), pre('v', 3, command='flutter analyze')]
        events[0]['input'] = {'file_path': '/tmp/a.dart'}
        (self.root / 'events' / 's2.jsonl').write_text('\n'.join(json.dumps(e) for e in events), encoding='utf-8')
        checks = {name: detail for _, name, detail in self.get('/api/session?id=s2')['checks']}
        self.assertEqual(checks['静态分析'], '正在运行')

    def test_rejects_bad_id_and_foreign_host(self):
        self.assertEqual(self.status('/api/session?id=..%2Fx'), 400)
        self.assertEqual(self.status('/api/ping', {'Host': 'evil.example'}), 403)

    def test_page_and_list(self):
        self.assertEqual(self.status('/'), 200)
        self.assertEqual(self.get('/api/sessions')['sessions'][0]['id'], 's1')


if __name__ == '__main__':
    unittest.main()
