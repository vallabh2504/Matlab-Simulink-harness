import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from matlab_harness.project import Project, ProjectError, atomic_json, value_digest


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "temperature.m").write_text("function T=f(t), T=exp(-t); end\n")
        self.project = Project.initialize(self.root, "Cooling", "actual-builder", ["src"])
        self.project.claim("orchestrator")
        self.project.add_requirement("orchestrator", "TH-1", "Conserve thermal energy", "closed form", "user brief", "J")
        self.project.configure_checks("orchestrator", "requirements", {})
        self.project.configure_checks("orchestrator", "architecture", {})
        self.project.configure_checks("orchestrator", "implementation", {"oracle": [sys.executable, "-c", "print('actual process output')"]})
        self.project.configure_checks("orchestrator", "verification", {"oracle": [sys.executable, "-c", "print('actual process output')"]})
        self.project.configure_checks("orchestrator", "handoff", {"oracle": [sys.executable, "-c", "print('actual process output')"]})

    def approve(self):
        self.project.approve("orchestrator", "test-human", "explicit fixture authorization")

    def accept_design(self):
        for checkpoint in ("requirements", "architecture"):
            self.review(checkpoint)
            self.project.accept("orchestrator", checkpoint)

    def review(self, checkpoint="requirements", findings=None, reviewer="independent-test-agent", independence="independent-agent"):
        record = {"reviewer_session": reviewer, "model": "test record, no live AI claim",
                  "independence": independence, "checkpoint": checkpoint, "verdict": "ACCEPT",
                  "findings": findings or [], "snapshot_digest": value_digest(self.project.snapshot())}
        atomic_json(self.root / "review.json", record)
        self.project.review("orchestrator", checkpoint, "review.json")

    def test_no_approval_is_blocked(self):
        self.review()
        self.assertFalse(self.project.gate("requirements")["accepted"])

    def test_real_check_required_and_fresh(self):
        self.approve()
        self.accept_design()
        self.review("implementation")
        self.assertFalse(self.project.gate("implementation")["accepted"])
        result = self.project.run_check("orchestrator", "oracle")
        self.assertEqual(result["stdout"].strip(), "actual process output")
        self.assertTrue(self.project.gate("implementation")["accepted"])
        (self.root / "src" / "temperature.m").write_text("wrong dynamics")
        self.assertFalse(self.project.gate("implementation")["accepted"])

    def test_deleted_scoped_artifact_invalidates(self):
        self.approve()
        self.project.run_check("orchestrator", "oracle")
        self.review("implementation")
        (self.root / "src" / "temperature.m").unlink()
        self.assertFalse(self.project.gate("implementation")["accepted"])

    def test_command_substitution_rejected(self):
        with self.assertRaisesRegex(ProjectError, "substitute"):
            self.project.run_check("orchestrator", "oracle", [sys.executable, "-c", "pass"])

    def test_failed_check_cannot_be_compensated_by_review(self):
        self.project.configure_checks("orchestrator", "verification", {"wrong": [sys.executable, "-c", "raise RuntimeError('seeded')"]})
        self.approve()
        self.review("verification")
        result = self.project.run_check("orchestrator", "wrong")
        self.assertEqual(result["status"], "FAILED")
        self.assertFalse(self.project.gate("verification")["accepted"])

    def test_timeout_and_missing_executable_block(self):
        self.project.configure_checks("orchestrator", "verification", {
            "slow": [sys.executable, "-c", "import time; time.sleep(2)"],
            "absent": [str(self.root / "nonexistent.exe")]})
        self.assertEqual(self.project.run_check("orchestrator", "slow", timeout=0.1)["status"], "BLOCKED")
        self.assertEqual(self.project.run_check("orchestrator", "absent")["status"], "BLOCKED")
        for timeout in (True,float('nan'),float('inf')):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ProjectError):self.project.run_check('orchestrator','slow',timeout=timeout)

    def test_verification_mutating_source_fails(self):
        command = [sys.executable, "-c", "from pathlib import Path; Path('src/temperature.m').write_text('changed')"]
        self.project.configure_checks("orchestrator", "verification", {"mutation": command})
        self.assertEqual(self.project.run_check("orchestrator", "mutation")["status"], "FAILED")

    def test_timeout_stops_owned_check_descendant_and_keeps_receipt(self):
        # Real local non-AI child/descendant; no MATLAB or remote cancellation claim.
        marker=self.root/'late-descendant-write.txt'
        identity=self.root/'descendant-pid.txt'
        descendant="import time; from pathlib import Path; time.sleep(3); Path(%r).write_text('late owned writer')"%str(marker)
        parent=("import os,subprocess,sys,time; from pathlib import Path; "
                "child=subprocess.Popen([sys.executable,'-c',%r],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
                "Path(%r).write_text(str(child.pid)); print('owned child launched',flush=True); time.sleep(30)")%(descendant,str(identity))
        self.project.configure_checks('orchestrator','verification',{'owned-tree':[sys.executable,'-c',parent]})
        result=self.project.run_check('orchestrator','owned-tree',timeout=1.5)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertTrue(identity.is_file(),'Fixture did not actually launch its descendant')
        time.sleep(3)
        self.assertFalse(marker.exists(),'A timed-out native check left an owned writer alive')
        self.assertIsInstance(result['pid'],int)
        self.assertTrue(result['cleanup']['root_stopped'])
        self.assertEqual(result['cleanup']['external_service_cancellation'],'UNKNOWN')
        self.assertIn('owned child launched',result['stdout'])
        saved=self.project.load()['evidence']['owned-tree']['path']
        self.assertEqual(json.loads((self.root/saved).read_text(encoding='utf-8')),result)
        for name in ('stdout','stderr'):
            self.assertTrue((self.root/result['raw_output'][name]['path']).is_file())

    def test_critical_finding_blocks_and_self_review_rejected(self):
        self.approve()
        finding = {"id": "R-1", "severity": "MAJOR", "kind": "PROVEN DEFECT", "artifact": "src/temperature.m",
                   "evidence": "wrong sign probe", "impact": "unstable cooling", "repair": "correct sign",
                   "closure": "rerun independent oracle", "status": "OPEN"}
        self.review(findings=[finding])
        self.assertFalse(self.project.gate("requirements")["accepted"])
        with self.assertRaises(ProjectError):
            self.review(reviewer="actual-builder")

    def test_sequential_role_pass_is_honest_but_cannot_accept(self):
        self.approve()
        self.review(independence="sequential-role-pass")
        self.assertFalse(self.project.gate("requirements")["accepted"])

    def test_blocking_defect_requires_explicit_closure_even_after_revision(self):
        self.approve()
        finding = {"id":"D-1","severity":"MAJOR","kind":"PROVEN DEFECT","artifact":"src/temperature.m",
                   "evidence":"reproduced wrong sign","impact":"wrong dynamics","repair":"correct equation",
                   "closure":"native counterexample and regression rerun","status":"OPEN"}
        self.review(findings=[finding])
        with self.assertRaisesRegex(ProjectError,"explicitly close"):
            self.review()
        # A claimed downgrade or baseline reset cannot erase the open finding.
        report = {"reviewer_session":"independent-test-agent","model":"synthetic diagnostic, not live AI",
                  "independence":"independent-agent","checkpoint":"requirements","verdict":"REJECT",
                  "findings":[{**finding,"severity":"MINOR"}],"snapshot_digest":value_digest(self.project.snapshot())}
        atomic_json(self.root / "review.json",report)
        self.project.review("orchestrator","requirements","review.json")
        self.project.revise("orchestrator","authorized change")
        self.approve()
        with self.assertRaisesRegex(ProjectError,"explicitly close"):
            self.review()
        self.review(findings=[{**finding,"status":"CLOSED","evidence":"fresh independent native regression proof",
                              "prior_finding_digest":self.project.load()["defects"]["requirements:D-1"]["origin_digest"]}])
        self.assertTrue(self.project.gate("requirements")["accepted"])
        record = self.project.resume()["defects"]["requirements:D-1"]
        self.assertFalse(record["blocking"])
        self.assertEqual(len(record["history"]),3)

    def test_older_project_findings_migrate_before_review_or_revision(self):
        self.approve()
        finding = {"id":"OLD-1","severity":"MAJOR","kind":"EVIDENCE GAP","artifact":"src/temperature.m",
                   "evidence":"native execution absent","impact":"cannot trust output","repair":"execute native checks",
                   "closure":"independent actual results","status":"OPEN"}
        self.review(findings=[finding])
        with self.project.transaction("orchestrator") as data:
            data.pop("defects")  # Emulate an older schema1 project record.
        with self.assertRaisesRegex(ProjectError,"explicitly close"):
            self.review()
        self.project.revise("orchestrator","new approved domain")
        self.assertTrue(self.project.load()["defects"]["requirements:OLD-1"]["blocking"])
        self.assertTrue(any(d["source"] == "compatible record migration" for d in self.project.load()["decisions"]))

    def test_late_defect_survives_revision_without_deadlocking_redesign(self):
        self.approve()
        self.accept_design()
        issue = {"id":"LATE-1", "severity":"MAJOR", "kind":"PROVEN DEFECT",
                 "artifact":"src/temperature.m", "evidence":"wrong dynamics reproduced",
                 "impact":"invalid engineering result", "repair":"revise the governing design",
                 "closure":"independent regression and explicit origin-bound closure", "status":"OPEN"}
        report = {"reviewer_session":"independent-test-agent", "model":"synthetic fixture, not AI",
                  "independence":"independent-agent", "checkpoint":"implementation", "verdict":"REJECT",
                  "findings":[issue], "snapshot_digest":value_digest(self.project.snapshot())}
        atomic_json(self.root / "review.json", report)
        self.project.review("orchestrator", "implementation", "review.json")
        self.project.revise("orchestrator", "Authorized redesign to repair the late defect")
        self.approve()
        for phase in ("requirements", "architecture"):
            self.review(phase)
            self.assertTrue(self.project.gate(phase)["accepted"], self.project.gate(phase))
            self.project.accept("orchestrator", phase)
        self.assertTrue(self.project.load()["defects"]["implementation:LATE-1"]["blocking"])
        self.assertTrue(any("LATE-1" in p for p in self.project.gate("handoff")["problems"]))
        with self.assertRaisesRegex(ProjectError, "explicitly close"):
            self.review("implementation")
        origin = self.project.load()["defects"]["implementation:LATE-1"]["origin_digest"]
        self.review("implementation", [{**issue, "status":"CLOSED", "prior_finding_digest":origin,
                                        "evidence":"actual synthetic fixture repair evidence"}])
        self.project.run_check("orchestrator", "oracle")
        self.assertTrue(self.project.gate("implementation")["accepted"])

    def test_unrelated_closed_issue_cannot_reuse_blocking_id(self):
        self.approve()
        issue = {"id":"D-1","severity":"MAJOR","kind":"PROVEN DEFECT","artifact":"src/temperature.m",
                 "evidence":"wrong dynamics","impact":"unphysical cooling","repair":"fix sign",
                 "closure":"independent native regression","status":"OPEN"}
        self.review(findings=[issue])
        with self.assertRaisesRegex(ProjectError,"exact original artifact"):
            self.review(findings=[{**issue,"artifact":"plot.png","severity":"MINOR","status":"CLOSED"}])
        with self.assertRaisesRegex(ProjectError,"prior finding digest"):
            self.review(findings=[{**issue,"status":"CLOSED"}])
        self.assertTrue(self.project.load()["defects"]["requirements:D-1"]["blocking"])

    def test_record_tamper_detected_and_original_review_archived(self):
        self.approve()
        self.accept_design()
        self.project.run_check("orchestrator", "oracle")
        self.review("implementation")
        (self.root / "review.json").write_text("overwritten input")
        self.assertTrue(self.project.gate("implementation")["accepted"])
        item = self.project.load()["evidence"]["oracle"]
        (self.root / item["path"]).write_text("fake green log")
        self.assertFalse(self.project.gate("implementation")["accepted"])

    def test_requirement_revision_resets_review_and_keeps_history(self):
        self.approve()
        self.review()
        self.project.accept("orchestrator", "requirements")
        with self.assertRaises(ProjectError):
            self.project.add_requirement("orchestrator", "NEW", "new", "probe", "user")
        (self.root / "requirements.md").write_text("changed requirement")
        with self.assertRaises(ProjectError):
            self.approve()
        self.project.revise("orchestrator", "user changed operating envelope")
        self.assertEqual(self.project.load()["phase"], "requirements")
        self.assertTrue(list((self.root / ".matlab-harness/history").glob("baseline-*.json")))
        self.assertFalse(self.project.gate("requirements")["accepted"])

    def test_owner_lease_collision_recovery_and_resume(self):
        self.approve()
        with self.assertRaises(ProjectError):
            self.project.claim("racing-orchestrator")
        self.project.lease("orchestrator", "build", "worker-1", ["src"], ["TH-1"], kind="discovery")
        with self.assertRaises(ProjectError):
            self.project.lease("orchestrator", "other", "worker-2", ["src/temperature.m"], ["TH-1"], kind="discovery")
        with self.assertRaises(ProjectError):
            self.project.release("orchestrator")
        fresh_process = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / "matlab_harness.py"),
                                       "--project", str(self.root), "resume"], capture_output=True, text=True)
        self.assertEqual(fresh_process.returncode, 0, fresh_process.stderr)
        self.assertEqual(json.loads(fresh_process.stdout)["tasks"]["build"]["worker"], "worker-1")
        self.project.recover_owner("orchestrator", "new-session", "old worker stopped, inspected artifacts")
        self.project.finish_task("new-session", "build", "INTERRUPTED")
        self.project.release("new-session")

    def test_stale_lock_never_silently_removed(self):
        atomic_json(self.root / ".matlab-harness/mutation.lock", {"token": "interrupted-real-token", "pid": 0, "created": "old"})
        with self.assertRaises(ProjectError):
            self.project.claim("other")
        with self.assertRaises(ProjectError):
            self.project.recover_lock("wrong")
        self.project.recover_lock("interrupted-real-token")
        self.assertTrue(list((self.root / ".matlab-harness/history").glob("recovered-lock-*.json")))

    def test_corrupt_lock_preserves_primary_exception_and_unknown_lock(self):
        lock=self.root/'.matlab-harness/mutation.lock'
        for content in ('corrupted while transaction active','[]'):
            with self.subTest(lock_content=content):
                with self.assertRaisesRegex(RuntimeError,'primary failure'):
                    with self.project.transaction('orchestrator'):
                        lock.write_text(content)
                        raise RuntimeError('primary failure')
                self.assertEqual(lock.read_text(),content)
                # This test owns the fixture lock; emulate inspected recovery.
                lock.unlink()
        with self.assertRaisesRegex(ProjectError,'may be committed'):
            with self.project.transaction('orchestrator') as data:
                data['test_committed']=True
                lock.write_text('corrupted before cleanup')
        self.assertTrue(self.project.load()['test_committed'])
        self.assertTrue(lock.exists())

    def test_path_escapes_and_root_scope_rejected(self):
        with self.assertRaises(ProjectError):
            self.project.lease("orchestrator", "bad", "worker", ["../outside"], ["TH-1"])
        with self.assertRaises(ProjectError):
            Project.initialize(self.root / "other", "bad", "builder", ["."])

    @unittest.skipUnless(os.name == 'nt','Windows case-insensitive artifact ownership')
    def test_future_case_aliases_cannot_acquire_two_leases(self):
        self.approve()
        self.project.lease('orchestrator','first','worker-1',['src/Future.m'],['TH-1'],kind='discovery')
        with self.assertRaisesRegex(ProjectError,'collision'):
            self.project.lease('orchestrator','second','worker-2',['src/FUTURE.m'],['TH-1'],kind='discovery')
        with self.assertRaises(ProjectError):
            Project.initialize(self.root/'control-alias','bad','builder',['.MATLAB-HARNESS'])

    def test_accepted_obligations_frozen_and_ordered(self):
        self.approve()
        self.review()
        self.project.accept("orchestrator", "requirements")
        with self.assertRaises(ProjectError):
            self.project.configure_checks("orchestrator", "requirements", {})
        self.project.configure_checks("orchestrator", "verification", {"later": [sys.executable,"-c","pass"]})
        with self.assertRaises(ProjectError):
            self.project.accept("orchestrator", "handoff")

    def test_repair_budget_is_bounded(self):
        self.project.configure_runtime("orchestrator", repair_budget=2)
        for _ in range(2):
            self.project.repair("orchestrator", "independent finding")
        with self.assertRaises(ProjectError):
            self.project.repair("orchestrator", "infinite repair")

    def test_worker_cannot_review_and_implementation_needs_design(self):
        self.approve()
        with self.assertRaisesRegex(ProjectError, "accepted requirements"):
            self.project.lease("orchestrator", "premature", "worker", ["src"], ["TH-1"])
        self.project.lease("orchestrator", "inspect", "worker", ["src"], ["TH-1"], kind="discovery")
        self.project.finish_task("orchestrator", "inspect", "DONE")
        with self.assertRaisesRegex(ProjectError, "contributing"):
            self.review(reviewer="worker")
        self.accept_design()
        self.project.lease("orchestrator", "build", "worker", ["src"], ["TH-1"])

    def test_readiness_order_and_handoff_cannot_accept_twice(self):
        self.approve()
        self.project.run_check("orchestrator", "oracle")
        self.review("handoff")
        self.assertFalse(self.project.gate("handoff")["accepted"])
        for checkpoint in ("requirements", "architecture", "implementation", "verification", "handoff"):
            if checkpoint == "handoff":
                (self.root / "src/README.md").write_text("Traceability: TH-1 energy balance, closed form passed")
                self.project.run_check("orchestrator", "oracle")
            self.review(checkpoint)
            self.project.accept("orchestrator", checkpoint)
        with self.assertRaisesRegex(ProjectError, "already accepted"):
            self.project.accept("orchestrator", "handoff")
        self.assertEqual(len(self.project.load()["acceptances"]), 5)

    def test_malformed_review_is_a_controlled_error(self):
        for value in ([], None, {"checkpoint": "requirements"}):
            atomic_json(self.root / "review.json", value)
            with self.assertRaises(ProjectError):
                self.project.review("orchestrator", "requirements", "review.json")

    def test_lenient_budgets_configurable_and_revision_retains_history(self):
        self.assertEqual(self.project.load()["budgets"]["reviewer"], 1800)
        self.project.configure_runtime("orchestrator", {"builder": 3600}, repair_budget=8)
        for _ in range(6):
            self.project.repair("orchestrator", "diagnostic finding")
        with self.assertRaises(ProjectError):
            self.project.configure_runtime("orchestrator", repair_budget=5)
        with self.assertRaises(ProjectError):
            self.project.configure_runtime("orchestrator", {"reviewer": float("nan")})
        self.project.revise("orchestrator", "new authorized baseline")
        self.assertEqual(self.project.load()["repairs"], 0)
        history = list((self.root / ".matlab-harness/history").glob("baseline-*.json"))
        self.assertEqual(json.loads(history[0].read_text())["repairs"], 6)

    def test_init_preserves_existing_requirements_and_never_overwrites(self):
        text = (self.root / "requirements.md").read_text()
        with self.assertRaises(ProjectError):
            Project.initialize(self.root, "different", "builder", ["src"])
        self.assertEqual((self.root / "requirements.md").read_text(), text)


if __name__ == "__main__":
    unittest.main()
