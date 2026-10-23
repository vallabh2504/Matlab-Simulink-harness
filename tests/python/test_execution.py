import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from matlab_harness.execution import execute,recover
from matlab_harness.project import Project,ProjectError,atomic_json
from matlab_harness.workflow import start


class ExecutionTests(unittest.TestCase):
    def test_output_limit_retains_raw_bytes_and_nonpassing_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'emit.py').write_text("print('x'*2048)")
            result=execute([sys.executable,str(root/'emit.py')],root,root,5,max_bytes=1024)
            self.assertEqual(result['status'],'OUTPUT_LIMIT')
            self.assertGreater(result['stdout']['bytes'],1024)

    def test_interrupted_recovery_preserves_original_without_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'f.py').write_text('x=1')
            start(root,'recovery','builder','owner',['f.py']);p=Project(root)
            receipt=p.control/'probes/P-interrupted/receipt.json';receipt.parent.mkdir(parents=True)
            original={'status':'STARTED','id':'P-interrupted'};atomic_json(receipt,original)
            with p.transaction('owner') as data:
                data['probe_receipts']={'P-interrupted':{'status':'STARTED','path':receipt.relative_to(root).as_posix()}}
            with self.assertRaises(ProjectError):recover(p,'owner','probe','P-interrupted','','Inspected')
            result=recover(p,'owner','probe','P-interrupted','Verified recorded process is stopped','Inspected interrupted run')
            self.assertFalse(result['accepted']);self.assertEqual(result['status'],'INTERRUPTED')
            archive=root/result['recovery']['original_record']
            self.assertEqual(json.loads(archive.read_text()),original)
