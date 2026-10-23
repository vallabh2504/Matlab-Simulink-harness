import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from matlab_harness.project import Project, ProjectError
from matlab_harness.workflow import start
from matlab_harness.semantics import configure,run,problems


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source='def clamp(x):\n    return max(0, x)\n'
        (self.root/'model.py').write_text(self.source)
        (self.root/'good.py').write_text(self.source)
        (self.root/'suite.py').write_text("from model import clamp\nassert clamp(-1)==0, 'CLAMP_NEGATIVE'\nassert clamp(2)==2, 'CLAMP_POSITIVE'\n")
        start(self.root,'clamp adequacy','builder','owner',['model.py'])
        self.p=Project(self.root)
        self.p.add_requirement('owner','R-CLAMP','Clamp below zero','assert negative and positive cases','operator')
        self.p.configure_checks('owner','implementation',{'suite':[sys.executable,'-B','suite.py']})
        self.plan={'stages':['implementation'],'obligations':[{'id':'CLAMP','requirement':'R-CLAMP','check':'suite',
            'target':'model.py','reference':'good.py','mutants':[{'id':'no-clamp','find':'max(0, x)','replace':'x','failure_marker':'CLAMP_NEGATIVE'}]}]}

    def test_real_property_suite_passes_and_rejects_named_defect(self):
        configure(self.p,'owner',self.plan,'Operator-approved clamp obligation')
        before=(self.root/'model.py').read_bytes()
        result=run(self.p,'owner','implementation',20)
        self.assertEqual(result['status'],'PASSED',result)
        self.assertEqual([c['status'] for c in result['obligations'][0]['cases']],['PASSED','FAILED'])
        self.assertEqual(problems(self.p,self.p.load(),'implementation'),[])
        self.assertEqual((self.root/'model.py').read_bytes(),before)

    def test_finite_only_suite_survives_clamp_defect_and_blocks_gate(self):
        (self.root/'suite.py').write_text('import math\nfrom model import clamp\nassert math.isfinite(clamp(-1))\n')
        self.p.configure_checks('owner','implementation',{'suite':[sys.executable,'-B','suite.py']})
        configure(self.p,'owner',self.plan,'Required clamp behavior')
        result=run(self.p,'owner','implementation',20)
        self.assertEqual(result['status'],'INADEQUATE')
        self.assertFalse(result['obligations'][0]['cases'][1]['adequate'])
        self.assertTrue(any('semantic adequacy' in p for p in self.p.gate('implementation')['problems']))

    def test_syntax_crash_is_not_intended_detection(self):
        self.plan['obligations'][0]['mutants'][0]['replace']='('
        configure(self.p,'owner',self.plan,'Diagnostic crash control')
        result=run(self.p,'owner','implementation',20)
        self.assertEqual(result['status'],'INADEQUATE')
        self.assertFalse(result['obligations'][0]['cases'][1]['adequate'])

    def test_missing_dependency_is_not_detection(self):
        (self.root/'suite.py').write_text('import missing_semantic_fixture_dependency\n')
        self.p.configure_checks('owner','implementation',{'suite':[sys.executable,'-B','suite.py']})
        configure(self.p,'owner',self.plan,'Diagnostic dependency control')
        self.assertEqual(run(self.p,'owner','implementation',20)['status'],'INADEQUATE')

    def test_diagnostic_assertion_banner_cannot_turn_a_crash_into_detection(self):
        (self.root/'suite.py').write_text("from model import clamp\nprint('AssertionError: CLAMP_NEGATIVE')\nif clamp(-1)!=0: raise ZeroDivisionError('unrelated crash')\n")
        self.p.configure_checks('owner','implementation',{'suite':[sys.executable,'-B','suite.py']})
        configure(self.p,'owner',self.plan,'Banner/crash adversarial control')
        result=run(self.p,'owner','implementation',20)
        self.assertEqual(result['status'],'INADEQUATE')
        mutant=result['obligations'][0]['cases'][1]
        self.assertFalse(mutant['assertion']['is_assertion'])
        self.assertEqual(mutant['assertion']['type'],'builtins.ZeroDivisionError')

    def test_output_tamper_and_source_change_invalidate_evidence(self):
        configure(self.p,'owner',self.plan,'Clamp calibration')
        result=run(self.p,'owner','implementation',20)
        Path(result['obligations'][0]['cases'][0]['stdout']['artifact']).write_text('modified')
        self.assertTrue(problems(self.p,self.p.load(),'implementation'))
        (self.root/'good.py').write_text('changed reference')
        with self.assertRaises(ProjectError):configure(self.p,'owner',self.plan,'Invalid changed reference')

    def test_empty_plan_requires_explicit_rationale(self):
        with self.assertRaises(ProjectError):configure(self.p,'owner',{'obligations':[]},'No calibration')
        configure(self.p,'owner',{'obligations':[],'not_applicable':'Document-only deliverable; no executable behavior'},'Operator scope decision')
