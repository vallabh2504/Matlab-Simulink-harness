"""Real subprocess proof receipts; no live AI assertions are made here."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from matlab_harness.project import Project, ProjectError, ReviewProtocolError
from matlab_harness.workflow import start, packet, submit_answer, execute
from matlab_harness import probes
from matlab_harness.probes import configure, execute_proposals, receipt_problem, review_problems, run, validate


def readable_python():
    """This interpreter as a file a probe runner can fingerprint. A Microsoft Store Python's
    sys.executable is an App Execution Alias that cannot be read; its real binary can."""
    for candidate in (Path(sys.executable), Path(sys.base_prefix) / Path(sys.executable).name):
        try:
            candidate.read_bytes()
            return str(candidate)
        except OSError:
            pass
    raise unittest.SkipTest("no readable Python interpreter to approve as a probe runner")


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'f.py').write_text('x=1')
        start(self.root,'strict proof','builder','owner',['f.py'])
        self.p=Project(self.root)
        configure(self.p,'owner',[{'kind':'python','executable':readable_python()}],'Approved Python diagnostic probes')
        self.p.add_requirement('owner','R-1','x is one','assert x == 1','operator')
        self.p.approve('owner','operator','Diagnostic authorization')
        self.good={'verdict':'ACCEPT','findings':[],'traceability':{'R-1':{'status':'VERIFIED','evidence':'analytical contract'}},'independent_checks':[]}
        for stage in ('requirements','architecture'):
            packet(self.p,'reviewer');submit_answer(self.p,'owner',self.good,'reviewer','fixture')
            self.p.accept('owner',stage)
        self.p.configure_checks('owner','implementation',{'native':[sys.executable,'-c','assert True']})
        self.p.run_check('owner','native')
        self.h=packet(self.p,'reviewer');self.pid=Path(self.h['prompt']).parent.name
        self.script=Path(self.h['scratch'])/'probe.py'
        self.script.write_text("from pathlib import Path\nassert 'x=1' in Path('f.py').read_text()\nprint('independent x oracle passed')")
        self.check={'id':'CHK-1','command':'python probe.py','observed':'x==1','result':'PASS','artifact':str(self.script)}

    def probe(self,**kwargs):
        return run(self.p,'owner',self.pid,'CHK-1',str(self.script),'reviewer',timeout=10,**kwargs)

    def test_real_execution_receipt_accepts_and_output_tamper_reblocks(self):
        receipt=self.probe();self.assertEqual(receipt['status'],'PASSED')
        check={**self.check,'receipt_id':receipt['id']}
        self.assertTrue(validate(self.p,Path(self.h['scratch']),check,'reviewer'))
        result=submit_answer(self.p,'owner',{**self.good,'independent_checks':[check]},'reviewer','fixture',self.pid)
        self.assertTrue(result['gate']['accepted'],result['gate'])
        Path(receipt['stdout']['artifact']).write_text('changed')
        self.assertFalse(self.p.gate('implementation')['accepted'])

    def test_fake_pass_and_forged_receipt_refuse(self):
        for receipt_id in ('','P-forged'):
            with self.assertRaises(ReviewProtocolError):
                submit_answer(self.p,'owner',{**self.good,'independent_checks':[{**self.check,'receipt_id':receipt_id}]},'reviewer','fixture',self.pid)
        self.assertFalse(self.p.gate('implementation')['accepted'])

    def test_changed_script_wrong_session_and_other_packet_refuse(self):
        receipt=self.probe();check={**self.check,'receipt_id':receipt['id']}
        self.assertFalse(validate(self.p,Path(self.h['scratch']),check,'other'))
        second=packet(self.p,'reviewer')
        self.assertFalse(validate(self.p,Path(second['scratch']),check,'reviewer'))
        self.script.write_text('assert True')
        self.assertFalse(validate(self.p,Path(self.h['scratch']),check,'reviewer'))

    def test_a_receipt_says_why_it_does_not_prove_the_check(self):
        receipt=self.probe()
        other=Path(self.h['scratch'])/'mut'/'f.py';other.parent.mkdir();other.write_text('x=2')
        check={**self.check,'receipt_id':receipt['id'],'artifact':str(other)}
        problem=receipt_problem(self.p,Path(self.h['scratch']),check,'reviewer')
        self.assertIn('is not the script its probe ran',problem)
        self.assertIn('probe.py',problem)
        self.assertFalse(validate(self.p,Path(self.h['scratch']),check,'reviewer'))
        report={**self.good,'checkpoint':'implementation','packet_id':self.pid,'snapshot_digest':self.h['snapshot_digest'],
                'reviewer_session':'reviewer','independent_checks':[check]}
        self.assertTrue(any('name that script as the artifact' in line for line in review_problems(self.p,report)),
                        review_problems(self.p,report))
        self.assertIsNone(receipt_problem(self.p,Path(self.h['scratch']),{**self.check,'receipt_id':receipt['id']},'reviewer'))

    def test_runs_beyond_the_cap_are_refused_by_name(self):
        rows=[{**self.check,'id':f'CHK-{n}','run':{'script':str(self.script)}} for n in (1,2)]
        with patch.object(probes,'PROBE_RUNS',1):
            answer=execute_proposals(self.p,'owner',self.h,{**self.good,'independent_checks':rows},'reviewer',60)
        first,second=answer['independent_checks']
        self.assertTrue(first.get('receipt_id'))
        self.assertEqual(second['result'],'ERROR')
        self.assertIn('only 1 runs are executed per answer; put more cases in one script',second['observed'])

    def test_a_copied_report_with_an_earlier_receipt_is_run_afresh_for_this_packet(self):
        old=self.probe()
        second=packet(self.p,'reviewer');script=Path(second['scratch'])/'probe.py'
        script.write_text(self.script.read_text())
        row={**self.check,'artifact':str(script),'receipt_id':old['id'],'run':{'script':str(script)}}
        answer=execute_proposals(self.p,'owner',second,{**self.good,'independent_checks':[row]},'reviewer',60)
        fresh=answer['independent_checks'][0]['receipt_id']
        self.assertNotEqual(fresh,old['id'])
        record=json.loads((self.root/self.p.load()['probe_receipts'][fresh]['path']).read_text(encoding='utf-8'))
        self.assertEqual(record['packet_id'],Path(second['prompt']).parent.name)
        # A receipt this packet already issued is not run twice.
        again=execute_proposals(self.p,'owner',second,answer,'reviewer',60)
        self.assertEqual(again['independent_checks'][0]['receipt_id'],fresh)

    def test_an_earlier_receipt_without_a_run_says_how_to_fix_it_once_for_all_its_checks(self):
        old=self.probe()
        second=packet(self.p,'reviewer')
        rows=[{**self.check,'id':name,'receipt_id':old['id']} for name in ('CHK-1','CHK-2')]
        report={**self.good,'checkpoint':'implementation','packet_id':Path(second['prompt']).parent.name,
                'snapshot_digest':second['snapshot_digest'],'reviewer_session':'reviewer','independent_checks':rows}
        problems=review_problems(self.p,report)
        lines=[line for line in problems if 'keep run and drop receipt_id' in line]
        self.assertEqual(len(lines),1,problems)
        self.assertIn('for checks CHK-1, CHK-2:',lines[0])

    def test_the_brief_states_the_artifact_rule_and_the_run_cap(self):
        prompt=Path(self.h['prompt']).read_text(encoding='utf-8')
        self.assertIn('with that same script as its artifact',prompt)
        self.assertIn(f'only {probes.PROBE_RUNS} runs are executed per answer',prompt)

    def test_failed_execution_is_not_passing_proof(self):
        self.script.write_text("raise AssertionError('intended failure')")
        receipt=self.probe();self.assertEqual(receipt['status'],'FAILED')
        self.assertFalse(validate(self.p,Path(self.h['scratch']),{**self.check,'receipt_id':receipt['id']},'reviewer'))

    def test_declared_input_hash_is_revalidated(self):
        (self.root/'input.txt').write_text('one')
        receipt=self.probe(inputs=['input.txt'])
        check={**self.check,'receipt_id':receipt['id']}
        self.assertTrue(validate(self.p,Path(self.h['scratch']),check,'reviewer'))
        (self.root/'input.txt').write_text('two')
        self.assertFalse(validate(self.p,Path(self.h['scratch']),check,'reviewer'))

    def test_builder_identity_and_unapproved_runner_refuse(self):
        with self.assertRaises(ProjectError):run(self.p,'owner',self.pid,'CHK-1',str(self.script),'builder')
        with self.assertRaises(ProjectError):self.probe(runner=5)

    def test_wrong_checkpoint_packet_cannot_issue_receipt(self):
        wrong=packet(self.p,'reviewer','requirements')
        script=Path(wrong['scratch'])/'p.py';script.write_text('assert True')
        with self.assertRaisesRegex(ProjectError,'current checkpoint'):
            run(self.p,'owner',Path(wrong['prompt']).parent.name,'CHK-1',str(script),'reviewer',timeout=10)

    def test_complete_record_requires_explicit_matching_packet(self):
        from matlab_harness.project import atomic_json,value_digest
        receipt=self.probe()
        report={**self.good,'checkpoint':'implementation','reviewer_session':'reviewer','model':'fixture',
                'independence':'independent-agent','snapshot_digest':value_digest(self.p.snapshot()),
                'independent_checks':[{**self.check,'receipt_id':receipt['id']}]}
        for packet_id in (None,'missing'):
            value=dict(report)
            if packet_id is not None:value['packet_id']=packet_id
            atomic_json(self.root/'full.json',value)
            with self.assertRaises(ReviewProtocolError):self.p.review('owner','implementation','full.json')
        report['packet_id']=self.pid;atomic_json(self.root/'full.json',report)
        self.p.review('owner','implementation','full.json')

    def test_launch_failure_is_terminal_and_does_not_leave_interrupted_intent(self):
        with patch('matlab_harness.execution.subprocess.Popen',side_effect=OSError('injected unavailable executable')):
            receipt=self.probe()
        self.assertEqual(receipt['status'],'LAUNCH_FAILED')
        self.assertEqual(self.p.load()['probe_receipts'][receipt['id']]['status'],'LAUNCH_FAILED')
        self.assertFalse(any('Interrupted probe' in x for x in self.p.gate('implementation')['problems']))

    def test_timeout_stops_owned_probe_and_does_not_count_as_proof(self):
        self.script.write_text('import time\ntime.sleep(10)')
        receipt=run(self.p,'owner',self.pid,'CHK-1',str(self.script),'reviewer',timeout=.1)
        self.assertEqual(receipt['status'],'TIMED_OUT')
        self.assertTrue(receipt['cleanup']['root_stopped'])
        self.assertFalse(validate(self.p,Path(self.h['scratch']),{**self.check,'receipt_id':receipt['id']},'reviewer'))

    def test_runtime_proposal_is_executed_after_role_lock_release(self):
        provider=self.root/'provider.py'
        provider.write_text("import json,os\nfrom pathlib import Path\ns=Path(os.environ['MATLAB_HARNESS_SCRATCH'])/'p.py'\ns.write_text('assert 1+1 == 2')\n"
          +"r="+repr(self.good)+"\nr['independent_checks']=[dict(id='CHK-1',command='python p.py',observed='oracle passed',result='PASS',artifact=str(s),run=dict(script=str(s)))]\n"
          +"print(json.dumps(dict(status='SUCCESS',model='fixture',session_id='reviewer',response=r)))")
        self.p.configure_runtime('owner',runtime={'adapter':'command','argv':[sys.executable,str(provider)]})
        result=execute(self.p,'owner','reviewer')
        self.assertEqual(result['status'],'SUCCEEDED',result)
        self.assertTrue(result['gate']['accepted'],result['gate'])
        self.assertTrue(self.p.load()['probe_receipts'])
