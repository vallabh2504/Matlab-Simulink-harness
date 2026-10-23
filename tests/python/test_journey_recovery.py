"""Actual local PID/process and recovery tests; model responses are synthetic fixtures."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from matlab_harness.project import Project, ProjectError, atomic_json, digest
from matlab_harness.journey import run_journey
from matlab_harness.journey_recovery import process_status, recover_journey


class JourneyRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src/model.m").write_text("function y=model(x),y=x;end")
        self.project = Project.initialize(self.root, "Recovery diagnostic", "fixture-origin", ["src"], proof_mode="legacy-attested")
        self.project.claim("owner")
        self.project.add_requirement("owner", "R-1", "Identity", "actual fixture file probe", "synthetic test")
        self.project.approve("owner", "fixture-human", "explicit synthetic test authorization; not live approval")
        for phase in ("requirements", "architecture"):
            self.project.configure_checks("owner", phase, {})
        for phase in ("implementation", "verification", "handoff"):
            self.project.configure_checks("owner", phase, {"probe": [sys.executable, "-B", "-c",
                "from pathlib import Path; assert Path('src/model.m').read_text() == 'function y=model(x),y=x;end'"]})
        exited = subprocess.Popen([sys.executable, "-B", "-c", "pass"])
        exited.wait(timeout=10)
        self.stopped_pid = exited.pid
        self.token = uuid.uuid4().hex
        self.attempt = self.project.control / "journey" / ("attempt-" + uuid.uuid4().hex)
        self.attempt.mkdir(parents=True)
        self.declaration = self.attempt.parent / "declaration.json"
        data = self.project.load()
        atomic_json(self.declaration, {"schema":1,"project_id":data["id"],"owner":"owner","ceiling_seconds":120,
            "review_existing_implementation":False,"initial_implementation_hashes":{}})
        self.started = {"owner":"owner","started_at":(datetime.now(timezone.utc)-timedelta(seconds=2)).isoformat(),
            "declaration_sha256":digest(self.declaration),"prior_seconds":0,
            "journey_pid":self.stopped_pid,"journey_lock_token":self.token}
        atomic_json(self.attempt/"started.json",self.started)
        self.lock = self.project.control/"journey.lock"
        self.lock_record = {"pid":self.stopped_pid,"token":self.token,"owner":"owner","project_id":data["id"],
            "attempt":self.attempt.relative_to(self.root).as_posix()}
        atomic_json(self.lock,self.lock_record)

    def recover(self, **kwargs):
        return recover_journey(self.project,"owner",self.attempt,
            "Observed owned diagnostic child exited; no provider/backend process was launched",
            "Actual Python Popen.wait observed exit in transport fixture",**kwargs)

    def test_actual_stopped_and_current_live_pid_queries(self):
        self.assertEqual(process_status(self.stopped_pid)["status"],"STOPPED")
        self.assertEqual(process_status(os.getpid())["status"],"LIVE")

    def test_recovery_preserves_originals_and_charges_elapsed(self):
        started_bytes=(self.attempt/"started.json").read_bytes()
        declaration_bytes=self.declaration.read_bytes()
        atomic_json(self.attempt/"step-0000-started.json",{"actual_interruption_fixture":True})
        atomic_json(self.attempt/"step-0000-finished.json",{"wall_seconds":1,"status":"FAILED"})
        step_bytes=(self.attempt/"step-0000-finished.json").read_bytes()
        result=self.recover(expected_lock_token=self.token)
        self.assertEqual(result["status"],"INTERRUPTED_RECOVERED")
        self.assertGreaterEqual(result["wall_seconds"],2)
        self.assertEqual(result["remaining_seconds"],max(0,120-result["wall_seconds"]))
        self.assertEqual(result["external_service_cancellation"],"UNKNOWN")
        self.assertFalse(result["descendant_stop_verified"])
        self.assertFalse(self.lock.exists())
        self.assertEqual((self.attempt/"started.json").read_bytes(),started_bytes)
        self.assertEqual(self.declaration.read_bytes(),declaration_bytes)
        self.assertEqual((self.attempt/"step-0000-finished.json").read_bytes(),step_bytes)
        self.assertTrue(any(d.get("recovery_id")==result["recovery_id"] for d in self.project.load()["decisions"]))
        self.assertFalse(self.project.load()["acceptances"])
        self.assertFalse(self.project.load()["reviews"])
        self.assertFalse(self.project.load().get("runs"))
        with self.assertRaisesRegex(ProjectError,"terminal evidence"):
            self.recover()

    def test_live_pid_refuses_without_deleting_any_records(self):
        self.started["journey_pid"]=os.getpid()
        self.lock_record["pid"]=os.getpid()
        atomic_json(self.attempt/"started.json",self.started)
        atomic_json(self.lock,self.lock_record)
        before=self.lock.read_bytes()
        with self.assertRaisesRegex(ProjectError,"LIVE"):
            self.recover()
        self.assertEqual(self.lock.read_bytes(),before)
        self.assertFalse((self.attempt/"finished.json").exists())

    def test_unknown_query_requires_inspection(self):
        with patch("matlab_harness.journey_recovery.process_status",return_value={"status":"UNKNOWN","reason":"access denied fixture"}):
            with self.assertRaisesRegex(ProjectError,"UNKNOWN"):
                self.recover()
        self.assertTrue(self.lock.exists())
        self.assertFalse((self.attempt/"finished.json").exists())

    def test_foreign_mutation_lock_is_preserved(self):
        mutation=self.project.control/"mutation.lock"
        mutation.write_text('{"token":"foreign-mutation","pid":123}')
        before=mutation.read_bytes()
        with self.assertRaisesRegex(ProjectError,"Mutation lock"):
            self.recover()
        self.assertEqual(mutation.read_bytes(),before)
        self.assertTrue(self.lock.exists())

    def test_foreign_unreadable_and_unbound_journey_locks_are_preserved(self):
        for text in ("not JSON","[]",json.dumps({**self.lock_record,"token":"foreign"}),
                     json.dumps({**self.lock_record,"attempt":".matlab-harness/journey/attempt-other"}),
                     json.dumps({**self.lock_record,"project_id":"foreign-project"}),
                     json.dumps({"pid":self.stopped_pid,"token":self.token}),
                     json.dumps({**self.lock_record,"attempt":None})):
            self.lock.write_text(text)
            before=self.lock.read_bytes()
            with self.assertRaises(ProjectError):
                self.recover()
            self.assertEqual(self.lock.read_bytes(),before)
            self.assertFalse((self.attempt/"finished.json").exists())

    def test_lock_change_after_terminal_is_preserved(self):
        observed=process_status(self.stopped_pid)
        calls=[]
        def query(pid):
            calls.append(pid)
            if len(calls)==2:
                atomic_json(self.lock,{**self.lock_record,"token":"new-foreign-owner"})
            return observed
        with patch("matlab_harness.journey_recovery.process_status",side_effect=query):
            result=self.recover()
        self.assertEqual(result["status"],"INTERRUPTED_RECOVERED")
        self.assertEqual(result["lock_cleanup"],"INSPECTION_REQUIRED")
        self.assertEqual(json.loads(self.lock.read_text())["token"],"new-foreign-owner")
        self.assertTrue((self.attempt/"finished.json").exists())

    def test_missing_journey_lock_still_requires_bound_stopped_pid(self):
        self.lock.unlink()
        result=self.recover()
        self.assertEqual(result["lock_cleanup"],"NO_LOCK_PRESENT")
        self.assertEqual(result["status"],"INTERRUPTED_RECOVERED")

    def test_paths_ownership_and_attestation_refused(self):
        for attempt in (self.root,self.root/".matlab-harness/journey/../journey"/self.attempt.name,
                        self.root/".matlab-harness/history/attempt-foreign"):
            with self.assertRaises(ProjectError):
                recover_journey(self.project,"owner",attempt,"actual stopped inspection","fixture source")
        with self.assertRaisesRegex(ProjectError,"orchestrator"):
            recover_journey(self.project,"foreign",self.attempt,"inspection","source")
        with self.assertRaisesRegex(ProjectError,"attestation"):
            recover_journey(self.project,"owner",self.attempt,"","source")
        with self.assertRaisesRegex(ProjectError,"token"):
            self.recover(expected_lock_token="wrong")
        self.assertTrue(self.lock.exists())

    def link_directory(self, destination, target):
        try:
            if os.name == "nt":
                result=subprocess.run(["powershell","-NoProfile","-Command",
                    "& { param($destination,$target) New-Item -ItemType Junction -Path $destination -Target $target -ErrorAction Stop | Out-Null }",
                    str(destination),str(target)],capture_output=True,text=True,timeout=15)
                if result.returncode:
                    self.skipTest("OS junction creation unavailable: "+result.stderr.strip())
            else:
                destination.symlink_to(target,target_is_directory=True)
        except (OSError,subprocess.TimeoutExpired) as exc:
            self.skipTest("OS directory link creation unavailable: "+str(exc))
        self.addCleanup(destination.unlink if destination.is_symlink() else destination.rmdir)

    def test_replaced_control_link_cannot_edit_foreign_journal(self):
        original=self.project.control
        foreign_temp=tempfile.TemporaryDirectory(prefix="engineering-recovery-foreign-")
        self.addCleanup(foreign_temp.cleanup)
        foreign=Path(foreign_temp.name)/"control"
        self.assertTrue(original.resolve().is_relative_to(self.root.resolve()))
        self.assertTrue(foreign.resolve().is_relative_to(Path(foreign_temp.name).resolve()))
        original.rename(foreign)
        self.link_directory(original,foreign)
        lock_before=(foreign/"journey.lock").read_bytes()
        project_before=(foreign/"project.json").read_bytes()
        with self.assertRaisesRegex(ProjectError,"control path"):
            self.recover()
        self.assertEqual((foreign/"journey.lock").read_bytes(),lock_before)
        self.assertEqual((foreign/"project.json").read_bytes(),project_before)
        self.assertFalse((foreign/"journey"/self.attempt.name/"finished.json").exists())

    def test_replaced_journey_link_cannot_edit_foreign_journal(self):
        foreign_temp=tempfile.TemporaryDirectory(prefix="engineering-recovery-foreign-journey-")
        self.addCleanup(foreign_temp.cleanup)
        original=self.project.control/"journey"
        foreign=Path(foreign_temp.name)/"journey"
        self.assertTrue(original.resolve().is_relative_to(self.root.resolve()))
        self.assertTrue(foreign.resolve().is_relative_to(Path(foreign_temp.name).resolve()))
        original.rename(foreign)
        self.link_directory(original,foreign)
        before=(foreign/self.attempt.name/"started.json").read_bytes()
        with self.assertRaisesRegex(ProjectError,"journey path"):
            self.recover()
        self.assertEqual((foreign/self.attempt.name/"started.json").read_bytes(),before)
        self.assertFalse((foreign/self.attempt.name/"finished.json").exists())

    def test_changed_declaration_and_future_start_refused(self):
        original=self.declaration.read_bytes()
        atomic_json(self.declaration,{"owner":"owner","project_id":self.project.load()["id"],"ceiling_seconds":9999})
        with self.assertRaisesRegex(ProjectError,"immutable declaration"):
            self.recover()
        self.declaration.write_bytes(original)
        self.started["started_at"]=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
        atomic_json(self.attempt/"started.json",self.started)
        with self.assertRaisesRegex(ProjectError,"Clock"):
            self.recover()
        self.assertFalse((self.attempt/"finished.json").exists())
        self.assertTrue(self.lock.exists())

    def test_active_leases_remain_active(self):
        self.project.lease("owner","owned-design","fixture-worker",["src"],["R-1"],kind="design")
        result=self.recover()
        self.assertEqual(result["active_tasks"],["owned-design"])
        self.assertEqual(self.project.load()["tasks"]["owned-design"]["status"],"ACTIVE")
        resumed=run_journey(self.root,"owner",120)
        self.assertEqual(resumed["status"],"INPUT_REQUIRED")
        self.assertIn("owned-design",resumed["tasks"])

    def test_overcounted_wait_exhausts_original_ceiling(self):
        self.started["started_at"]=(datetime.now(timezone.utc)-timedelta(seconds=180)).isoformat()
        atomic_json(self.attempt/"started.json",self.started)
        result=self.recover()
        self.assertEqual(result["remaining_seconds"],0)
        declaration_bytes=self.declaration.read_bytes()
        resumed=run_journey(self.root,"owner",120)
        self.assertEqual(resumed["status"],"CEILING_EXHAUSTED")
        self.assertEqual(self.declaration.read_bytes(),declaration_bytes)

    def test_recovered_attempt_continues_actual_fixture_processes_same_declaration(self):
        fixture=self.root/"protocol_fixture.py"
        fixture.write_text((
            "import json,sys\\nfrom pathlib import Path\\n"
            "sys.path.insert(0,sys.argv[2])\\n"
            "from matlab_harness.project import Project,value_digest\\n"
            "p=Project(Path.cwd()); role=sys.argv[1]\\n"
            + "def charter(p):\\n    import os\\n    s=Path(os.environ['MATLAB_HARNESS_SCRATCH']); s.mkdir(parents=True,exist_ok=True); (s/'probe.m').write_text('% synthetic fixture probe')\\n    return dict(traceability=[dict(requirement=r['id'],status='VERIFIED',evidence='synthetic fixture, not engineering evidence',finding_ids='') for r in p.load()['requirements']],\\n        independent_checks=[dict(id='IC-1',purpose='synthetic',requirements='all',command='none',expected='n/a',observed='n/a',result='PASS',artifact=str(s/'probe.m'),finding_ids='')])\\n"
            + "if role!='reviewer' and p.load()['phase']=='handoff': Path(p.load()['scope'][0]).mkdir(exist_ok=True); (Path(p.load()['scope'][0])/'HANDOFF.md').write_text(' '.join(r['id'] for r in p.load()['requirements']))\\n"
            "response='Diagnostic builder response' if role!='reviewer' else dict(checkpoint=p.load()['phase'],verdict='ACCEPT',findings=[],snapshot_digest=value_digest(p.snapshot()),**charter(p))\\n"
            "print(json.dumps(dict(status='SUCCESS',session_id='synthetic-fixture-'+role,model='synthetic transport fixture; not AI',response=response)))\\n")
            .replace("\\n","\n"))
        src=str(Path(__file__).resolve().parents[2]/"src")
        self.project.configure_runtime("owner",runtime={"adapter":"command","roles":
            {role:{"argv":[sys.executable,"-B",str(fixture),role,src]} for role in ("builder","reviewer","repair")}})
        before=self.declaration.read_bytes()
        recovered=self.recover()
        resumed=run_journey(self.root,"owner",120)
        self.assertEqual(resumed["status"],"COMPLETED",resumed)
        self.assertEqual(self.declaration.read_bytes(),before)
        self.assertEqual(len(self.project.load()["acceptances"]),5)
        self.assertGreaterEqual(len(self.project.load()["runs"]),7)
        started=json.loads((Path(resumed["invocation"])/"started.json").read_text())
        self.assertEqual(started["prior_seconds"],recovered["wall_seconds"])


if __name__=="__main__":
    unittest.main()

