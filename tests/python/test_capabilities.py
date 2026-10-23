import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))

from matlab_harness.capabilities import capabilities, preflight, role_config
from matlab_harness.project import Project, ProjectError
from matlab_harness.workflow import start, packet, execute


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'f.py').write_text('x=1')
        start(self.root, 'small model', 'builder', 'owner', ['f.py'], 'A complete brief')
        self.p = Project(self.root)

    def test_impossible_capacity_refuses_before_launch(self):
        self.p.configure_runtime('owner', runtime={'adapter':'command', 'argv':['never-launch'], 'context_budget':128})
        with patch('matlab_harness.runtime.execute_role') as launch:
            with self.assertRaisesRegex(ProjectError, 'Context preflight refused'):
                execute(self.p, 'owner', 'reviewer')
            launch.assert_not_called()
        self.assertEqual(self.p.load().get('runs', []), [])

    def test_feasible_profiles_keep_complete_task_and_brief(self):
        task = 'full task ' * 700
        brief = 'full brief ' * 100
        (self.p.control/'brief.md').write_text(brief)
        for capacity in (4096,8192,16384):
            with self.subTest(capacity=capacity):
                h = packet(self.p, 'builder', task=task, budget=capacity)
                text = Path(h['prompt']).read_text()
                self.assertIn(task, text); self.assertIn(brief.strip(), text)
                self.assertLessEqual(h['context_preflight']['total'],capacity)
                self.assertEqual(h['context_preflight']['reserved_output'],1024)

    def test_schema_and_mandatory_reads_and_reserves_count(self):
        h=packet(self.p,'reviewer')
        record=h['context_preflight']
        self.assertGreater(record['schema'],0);self.assertGreater(record['mandated_reads'],0)
        self.assertEqual(record['total'],sum(record[k] for k in ('prompt','schema','mandated_reads','reserved_output','host_overhead','tool_tokens')))
        with self.assertRaises(ProjectError):packet(self.p,'reviewer',budget=sum(record[k] for k in ('schema','mandated_reads','reserved_output','host_overhead','tool_tokens'))-1)

    def test_invalid_profile_rejected_without_mutation(self):
        before=self.p.record.read_bytes()
        for supplied in ({'context_window':True},{'reserved_output':-1},{'response_mode':'unchecked'}, {'unknown':1}):
            with self.assertRaises(ProjectError):self.p.configure_runtime('owner',runtime={'adapter':'manual','capabilities':supplied})
        self.assertEqual(self.p.record.read_bytes(),before)

    def test_role_overrides_merge_explicit_capabilities(self):
        config=role_config({'adapter':'manual','capabilities':{'context_window':8192,'host_overhead':900},
                            'roles':{'reviewer':{'capabilities':{'response_mode':'json'}}}},'reviewer')
        self.assertEqual(capabilities(config)['context_window'],8192)
        self.assertEqual(capabilities(config)['response_mode'],'json')
