"""Real child-process protocol regressions, not live AI or engineering evidence."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from matlab_harness.journey import run_journey
from matlab_harness.project import Project, ProjectError, atomic_json, value_digest
from matlab_harness.workflow import execute, packet, start


FIXTURE = '''import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[2])
from matlab_harness.project import Project,value_digest
def charter(p):
    import os
    s=Path(os.environ['MATLAB_HARNESS_SCRATCH']); s.mkdir(parents=True,exist_ok=True); (s/'probe.m').write_text('% synthetic fixture probe')
    return dict(traceability=[dict(requirement=r['id'],status='VERIFIED',evidence='synthetic fixture, not engineering evidence',finding_ids='') for r in p.load()['requirements']],
        independent_checks=[dict(id='IC-1',purpose='synthetic',requirements='all',command='none',expected='n/a',observed='n/a',result='PASS',artifact=str(s/'probe.m'),finding_ids='')])
p=Project('.');data=p.load();role=sys.argv[1];stage=data['phase']
mode=Path('mode.txt').read_text()
counter=Path('calls.json');calls=json.loads(counter.read_text()) if counter.exists() else []
calls.append({'role':role,'stage':stage});counter.write_text(json.dumps(calls))
attempt=sum(c['role']=='reviewer' and c['stage']==stage for c in calls)
if role!='reviewer':
    if mode.startswith('early-'): Path('engineering/early.'+mode[6:]).write_text('unapproved implementation or parameter data')
    elif stage=='architecture': Path('engineering/design.md').write_text('Proposed identity design; no implementation changes')
    elif stage=='implementation': Path('engineering/model.m').write_text('function y=model(x), y=x; end')
    response='Synthetic role completed'
else:
    from matlab_harness.answer import open_items
    findings=[];items={};verdict='ACCEPT'
    current=open_items(p,data,stage)
    for handle,item in current.items():
        if item['type']=='finding':
            items[handle]=dict(status='CLOSED',evidence='Observed isolated identity fixture source; diagnostic only')
    bad=stage=='requirements' and (mode=='protocol-always' or mode.startswith('protocol-') and attempt==1)
    if bad:
        verdict='REJECT'
        if mode.startswith('protocol-major'):
            findings.append(dict(id='NEW-1',severity='MAJOR',kind='POTENTIAL DEFECT',artifact='engineering/model.m',
                evidence='Unverified serious allegation in rejected diagnostic report',impact='Identity might be wrong',
                repair='Inspect actual fixture source',closure='Independent evidence or counterevidence',status='OPEN'))
    elif stage=='requirements' and mode in {'protocol-major-close','protocol-major-track'}:
        for handle,item in current.items():
            if item['type']=='allegation' and mode=='protocol-major-close':
                items[handle]=dict(status='CLOSED',evidence='Reopened fixture source is the identity function; alleged wrong equation is absent')
            elif item['type']=='allegation':
                items[handle]=dict(status='STILL_OPEN',evidence='Allegation still holds on current bytes');verdict='REJECT'
    if mode=='reject-moderate' and stage=='requirements':
        findings.append(dict(id='MOD-1',severity='MODERATE',kind='EVIDENCE GAP',artifact='engineering/model.m',
            evidence='Oracle tolerance unstated',impact='Ambiguous diagnostic evidence',repair='State the tolerance',
            closure='Tolerance documented',status='OPEN'))
        if attempt==1: verdict='REJECT'
    response=dict(checkpoint=stage,verdict=verdict,findings=findings,open_items=items,
        snapshot_digest=value_digest(p.snapshot()),**charter(p))
    if bad: response['verdict']='MAYBE'
print(json.dumps(dict(status='SUCCESS',session_id='synthetic-'+role+'-'+str(len(calls)),
    model='synthetic subprocess fixture, not AI',response=response)))
'''


class ReviewRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'engineering').mkdir()
        (self.root / 'engineering/model.m').write_text('function y=model(x), y=x; end')
        start(self.root, 'Protocol diagnostic', 'builder', 'owner', ['engineering'], proof_mode="legacy-attested")
        self.p = Project(self.root)
        self.p.add_requirement('owner', 'R1', 'Identity', 'Isolated diagnostic probe', 'synthetic fixture')
        self.p.approve('owner', 'fixture-human', 'Explicit synthetic authorization')
        (self.root / 'fixture.py').write_text(FIXTURE)
        (self.root / 'mode.txt').write_text('normal')
        src = str(Path(__file__).resolve().parents[2] / 'src')
        self.p.configure_runtime('owner', runtime={'adapter': 'command', 'roles': {
            role: {'argv': [sys.executable, '-B', str(self.root / 'fixture.py'), role, src]}
            for role in ['builder', 'reviewer', 'repair']}})

    def seed(self):
        finding = dict(id='OLD-1', severity='MODERATE', kind='EVIDENCE GAP',
            artifact='engineering/design.md; requirements.md', evidence='Contract needs a documented identity oracle',
            impact='Ambiguous diagnostic evidence', repair='Describe oracle in design',
            closure='Independently inspect the proposed oracle', status='OPEN')
        report = dict(checkpoint='requirements', verdict='INCOMPLETE', findings=[finding],
            reviewer_session='synthetic-original-reviewer', model='synthetic fixture',
            independence='independent-agent', snapshot_digest=value_digest(self.p.snapshot()))
        atomic_json(self.root / 'seed-review.json', report)
        self.p.review('owner', 'requirements', 'seed-review.json')
        return finding

    def mode(self, name):
        (self.root / 'mode.txt').write_text(name)

    def calls(self):
        p = self.root / 'calls.json'
        return json.loads(p.read_text()) if p.exists() else []

    def test_malformed_report_is_retained_then_reviewer_corrects_it(self):
        original = self.seed()
        self.mode('protocol-once')
        result = run_journey(self.root, 'owner', 60, stop_after='requirements')
        self.assertEqual(result['status'], 'CHECKPOINT_REACHED', result)
        self.assertEqual([c['role'] for c in self.calls()], ['reviewer', 'reviewer'])
        data = self.p.load()
        self.assertEqual(data['repairs'], 0)
        self.assertEqual(len(data['review_protocol_failures']), 1)
        rejected = next(iter(data['review_protocol_failures'].values()))
        raw = json.loads((self.root / rejected['path']).read_text())
        self.assertEqual(raw['verdict'], 'MAYBE')
        self.assertEqual(data['defects']['requirements:OLD-1']['origin'], original)
        self.assertEqual(data['defects']['requirements:OLD-1']['finding']['artifact'], original['artifact'])
        self.assertGreater(result['wall_seconds'], 0)
        self.assertLess(result['remaining_seconds'], 60)

    def test_a_reject_without_a_blocking_reason_is_corrected_not_repaired(self):
        self.mode('reject-moderate')
        result = run_journey(self.root, 'owner', 60, stop_after='requirements')
        self.assertEqual(result['status'], 'CHECKPOINT_REACHED', result)
        self.assertEqual([c['role'] for c in self.calls()], ['reviewer', 'reviewer'])
        data = self.p.load()
        self.assertEqual(data['repairs'], 0)
        refused = next(iter(data['review_protocol_failures'].values()))
        self.assertIn('REJECT needs a blocking reason', refused['reason'])
        self.assertEqual(data['defects']['requirements:MOD-1']['finding']['status'], 'OPEN')

    def test_protocol_retry_is_bounded_and_resume_cannot_reset_counter(self):
        self.seed(); self.mode('protocol-always')
        result = run_journey(self.root, 'owner', 60)
        self.assertEqual(result['status'], 'REVIEW_PROTOCOL_EXHAUSTED', result)
        self.assertEqual(len(self.calls()), 3)
        self.assertFalse(self.p.load()['acceptances'])
        resumed = run_journey(self.root, 'owner', 60)
        self.assertEqual(resumed['status'], 'REVIEW_PROTOCOL_EXHAUSTED', resumed)
        self.assertEqual(len(self.calls()), 3)
        self.assertEqual(self.p.load()['repairs'], 0)

    def test_external_failed_imports_count_without_a_journey_journal(self):
        self.seed(); self.mode('protocol-always')
        for _ in range(3):
            self.assertEqual(execute(self.p, 'owner', 'reviewer')['status'], 'REVIEW_NOT_IMPORTED')
        self.assertFalse((self.root / '.matlab-harness/journey').exists())
        result = run_journey(self.root, 'owner', 60)
        self.assertEqual(result['status'], 'REVIEW_PROTOCOL_EXHAUSTED', result)
        self.assertEqual(len(self.calls()), 3)

    def test_serious_allegation_cannot_disappear_in_an_accepting_retry(self):
        self.seed(); self.mode('protocol-major-drop')
        result = run_journey(self.root, 'owner', 60)
        self.assertEqual(result['status'], 'REVIEW_PROTOCOL_EXHAUSTED', result)
        self.assertTrue(self.p.pending_review_findings())
        self.assertFalse(self.p.load()['acceptances'])
        self.assertFalse(self.p.gate('requirements')['accepted'])

    def test_independent_counterevidence_can_explicitly_close_raw_allegation(self):
        self.seed(); self.mode('protocol-major-close')
        result = run_journey(self.root, 'owner', 60, stop_after='requirements')
        self.assertEqual(result['status'], 'CHECKPOINT_REACHED', result)
        self.assertFalse(self.p.pending_review_findings())
        pending = next(iter(self.p.load()['pending_review_findings'].values()))
        self.assertEqual(pending['classification'], 'UNIMPORTED_ALLEGATION')
        self.assertEqual(pending['disposition']['status'], 'CLOSED')
        self.assertTrue((self.root / pending['source_report']).is_file())
        self.assertTrue((self.root / pending['resolution_review']).is_file())

    def test_tracking_raw_allegation_preserves_normal_blocking_finding(self):
        self.seed(); self.mode('protocol-major-track')
        bad = execute(self.p, 'owner', 'reviewer')
        self.assertEqual(bad['status'], 'REVIEW_NOT_IMPORTED')
        corrected = execute(self.p, 'owner', 'reviewer')
        self.assertEqual(corrected['status'], 'SUCCEEDED')
        self.assertFalse(self.p.pending_review_findings())
        self.assertTrue(self.p.load()['defects']['requirements:NEW-1']['blocking'])
        self.assertFalse(corrected['gate']['accepted'])

    def test_pending_report_tampering_is_a_hard_failure(self):
        self.seed(); self.mode('protocol-major-drop')
        result = execute(self.p, 'owner', 'reviewer')
        report = self.root / result['report']
        report.write_text(report.read_text() + ' ')
        with self.assertRaisesRegex(ProjectError, 'source changed'):
            self.p.gate('requirements')

    def test_interrupted_import_blocks_new_dispatch_without_recovery(self):
        with patch.object(self.p, 'review', side_effect=OSError('Simulated host interruption during import')):
            with self.assertRaises(OSError):
                execute(self.p, 'owner', 'reviewer')
        result = run_journey(self.root, 'owner', 60)
        self.assertEqual(result['status'], 'INPUT_REQUIRED', result)
        self.assertIn('Interrupted review import', result['reason'])
        self.assertEqual(len(self.calls()), 1)

    def test_crash_before_raw_report_write_retains_import_intent_and_response(self):
        from matlab_harness import answer
        real_write = answer.atomic_json

        def interrupted_write(path, value):
            if Path(path).name == 'review.json':
                raise OSError('Simulated interruption before report file exists')
            return real_write(path, value)

        self.seed(); self.mode('protocol-major-drop')
        with patch.object(answer, 'atomic_json', side_effect=interrupted_write):
            with self.assertRaises(OSError):
                execute(self.p, 'owner', 'reviewer')
        run = self.p.load()['runs'][0]
        self.assertEqual(run['review_import']['status'], 'PENDING_REVIEW_IMPORT')
        self.assertTrue(any(f['severity']=='MAJOR' for f in run['receipt']['response']['findings']))
        self.mode('normal')
        self.assertEqual(execute(self.p, 'owner', 'reviewer')['status'], 'INPUT_REQUIRED')
        resumed = run_journey(self.root, 'owner', 60, stop_after='requirements')
        self.assertEqual(resumed['status'], 'INPUT_REQUIRED', resumed)
        self.assertFalse(self.p.gate('requirements')['accepted'])
        self.assertEqual(len(self.calls()), 1)

    def test_direct_execute_blocks_scripts_binary_and_parameter_data_early(self):
        for suffix in ['py', 'mexw64', 'txt']:
            with self.subTest(suffix=suffix):
                self.mode('early-' + suffix)
                result = execute(self.p, 'owner', 'repair')
                self.assertEqual(result['status'], 'INPUT_REQUIRED', result)
                self.assertIn('engineering/early.' + suffix, result['changed_artifacts'])
                self.assertTrue((self.root / ('engineering/early.' + suffix)).is_file())
                self.assertFalse(self.p.load()['acceptances'])
                # Explicitly restore each owned synthetic violation, preserving
                # its failed source in the temporary diagnostic archive.
                archive = self.root / ('archived-early.' + suffix)
                (self.root / ('engineering/early.' + suffix)).rename(archive)

    def test_stage_violation_cannot_be_adopted_by_resume_or_review_accept(self):
        self.mode('early-py')
        result = execute(self.p, 'owner', 'repair')
        self.assertEqual(result['status'], 'INPUT_REQUIRED')
        self.mode('normal')
        reviewed = execute(self.p, 'owner', 'reviewer')
        self.assertEqual(reviewed['status'], 'SUCCEEDED')
        self.assertFalse(reviewed['gate']['accepted'])
        with self.assertRaisesRegex(ProjectError, 'Unrestored engineering changes'):
            self.p.accept('owner', 'requirements')
        count = len(self.calls())
        resumed = run_journey(self.root, 'owner', 60, stop_after='requirements')
        self.assertEqual(resumed['status'], 'INPUT_REQUIRED', resumed)
        self.assertEqual(len(self.calls()), count)
        self.assertTrue((self.root / 'engineering/early.py').is_file())
        (self.root / 'engineering/early.py').rename(self.root / 'retained-early.py')
        restored = run_journey(self.root, 'owner', 60, stop_after='requirements')
        self.assertEqual(restored['status'], 'CHECKPOINT_REACHED', restored)
        self.assertTrue(all(i['status']=='RESTORED' for i in self.p.load()['stage_boundaries'].values()))
        # Later implementation changes cannot resurrect the closed early-stage
        # violation once exact restoration and checkpoint acceptance were recorded.
        (self.root / 'engineering/model.m').write_text('Legitimate later changed artifact, requires its own review')
        self.assertFalse(self.p.unrestored_stage_boundaries())

    def test_architecture_documentation_is_allowed_without_implementation_change(self):
        first = run_journey(self.root, 'owner', 60, stop_after='requirements')
        self.assertEqual(first['status'], 'CHECKPOINT_REACHED')
        before = (self.root / 'engineering/model.m').read_bytes()
        second = run_journey(self.root, 'owner', 60, stop_after='architecture')
        self.assertEqual(second['status'], 'CHECKPOINT_REACHED', second)
        self.assertEqual((self.root / 'engineering/model.m').read_bytes(), before)

    def test_combined_control_locations_and_stage_specific_packet(self):
        self.assertTrue(self.p.reserved_location('engineering/model.m; requirements.md; .matlab-harness/project.json:4'))
        self.assertFalse(self.p.reserved_location('engineering/model.m; engineering/design.md'))
        prompt = Path(packet(self.p, 'repair')['prompt']).read_text()
        self.assertIn('do not implement it', prompt)
        self.assertNotIn('add a meaningful regression probe', prompt)
        reviewed = Path(packet(self.p, 'reviewer')['prompt']).read_text()
        self.assertIn('Missing future implementation', reviewed)
        self.assertIn('open_items', reviewed)
        self.assertNotIn('snapshot_digest', reviewed)

    def test_focused_context_retains_truth_without_repeating_repair_transcripts(self):
        self.seed()
        self.p.decision('owner', 'Synthetic mass assumption', 'ASSUMED', 'diagnostic user scope')
        self.p.repair('owner', 'Large prior repair transcript ' + 'historical detail ' * 10000)
        before = self.p.record.read_bytes()
        generated = packet(self.p, 'reviewer')
        context_file = Path(generated['context'])
        context = json.loads(context_file.read_text())
        self.assertLess(len(context_file.read_bytes()), 15000)
        self.assertEqual(context['snapshot_digest'], value_digest(self.p.snapshot()))
        self.assertEqual(context['approvals'], self.p.load()['approvals'])
        self.assertTrue(any(d.get('text')=='Synthetic mass assumption' for d in context['decisions']))
        self.assertTrue(any(d.get('source')=='repair' for d in context['decisions']))
        self.assertIn('requirements:OLD-1', context['defects'])
        self.assertEqual(self.p.record.read_bytes(), before)
        self.assertIn(str(context_file.relative_to(self.root).as_posix()), Path(generated['prompt']).read_text())


if __name__ == '__main__':
    unittest.main()
