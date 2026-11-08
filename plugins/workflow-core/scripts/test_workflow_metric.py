"""workflow_metric.py 的回归测试：python3 -m unittest discover -s plugins/workflow-core/scripts"""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import workflow_metric as metric  # noqa: E402

REVIEW = {'task': 'AUTH-R03', 'tier': '标准', 'files': 3, 'sources': ['docs/development/coding.md'],
          'findings': [{'axis': 'standards', 'severity': '应修', 'rule': 'coding.md 中文注释'}]}
DELIVER = {'task': 'AUTH-R03', 'tier': '标准', 'status': '实施完成，待验证', 'code_changed': True, 'review': '已评审',
           'unverified': ['环境或工具问题'], 'resolutions': [{'rule': 'coding.md 中文注释', 'outcome': '已修复'}]}


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        patcher = mock.patch.dict(os.environ, {'WORKFLOW_METRICS_DIR': str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_record(self, kind, data):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = metric.record(kind, 's1', json.dumps(data) if not isinstance(data, str) else data, self.tmp.name)
        return code, out.getvalue()

    def records(self):
        path = self.root / 'records.jsonl'
        return [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def test_review_and_deliver_are_recorded(self):
        self.assertEqual(self.run_record('review', REVIEW)[0], 0)
        self.assertEqual(self.run_record('deliver', DELIVER)[0], 0)
        first, second = self.records()
        self.assertEqual((first['type'], first['findings'][0]['rule'], first['session_id']), ('review', 'coding.md 中文注释', 's1'))
        self.assertEqual((second['status'], second['unverified']), ('实施完成，待验证', ['环境或工具问题']))

    def test_rejects_unknown_fields_and_values(self):
        cases = [{**REVIEW, 'diff': 'secret code'}, {**REVIEW, 'tier': '大'}, {**REVIEW, 'files': -1},
                 {**REVIEW, 'findings': [{'axis': 'spec', 'severity': '阻塞', 'rule': '多行\n内容'}]},
                 {**REVIEW, 'findings': [{'axis': 'spec', 'severity': '阻塞', 'rule': 'x' * 121}]},
                 {**REVIEW, 'findings': [{'axis': 'spec', 'severity': '阻塞', 'rule': 'r', 'code': 'x'}]}]
        for case in cases:
            with self.subTest(case=str(case)[:60]):
                code, output = self.run_record('review', case)
                self.assertEqual(code, 1)
                self.assertIn('REJECTED', output)
        self.assertEqual(self.run_record('deliver', {**DELIVER, 'status': '完成'})[0], 1)
        self.assertEqual(self.run_record('review', 'not json')[0], 1)
        self.assertEqual(self.records(), [])

    def test_redacts_short_text(self):
        self.run_record('review', {**REVIEW, 'task': 'token=abcdef'})
        self.assertNotIn('abcdef', self.records()[0]['task'])

    def test_off_stops_writing_and_on_resumes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            metric.switch('off')
        self.assertIn('SKIPPED', self.run_record('review', REVIEW)[1])
        self.assertEqual(self.records(), [])
        with contextlib.redirect_stdout(io.StringIO()):
            metric.switch('on')
        self.run_record('review', REVIEW)
        self.assertEqual(len(self.records()), 1)


if __name__ == '__main__':
    unittest.main()
