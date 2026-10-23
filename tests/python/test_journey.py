"""Observed child-process lifecycle tests; fixture responses are not AI evidence."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from matlab_harness.project import PHASES, Project
from matlab_harness.workflow import start
from matlab_harness.journey import _implementation_hashes

spec = importlib.util.spec_from_file_location("engineering_journey", Path(__file__).resolve().parents[2] / "scripts/run_engineering_journey.py")
journey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journey)


FIXTURE = '''import json,sys,time
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from matlab_harness.project import Project,value_digest
role=sys.argv[1]
def charter(p):
    import os
    s=Path(os.environ['MATLAB_HARNESS_SCRATCH']); s.mkdir(parents=True,exist_ok=True); (s/'probe.m').write_text('% synthetic fixture probe')
    return dict(traceability=[dict(requirement=r['id'],status='VERIFIED',evidence='synthetic fixture, not engineering evidence',finding_ids='') for r in p.load()['requirements']],
        independent_checks=[dict(id='IC-1',purpose='synthetic',requirements='all',command='none',expected='n/a',observed='n/a',result='PASS',artifact=str(s/'probe.m'),finding_ids='')])
p=Project(Path.cwd()); data=p.load(); stage=data['phase']
mode=Path('mode.txt').read_text() if Path('mode.txt').exists() else ''
if mode == 'slow': time.sleep(60)
if role in {'builder','repair'}:
    if stage == 'requirements': Path('requirements.md').write_text('# Proposed explicit thermal requirements')
    elif stage == 'architecture':
        Path('engineering/design.md').write_text('Identity equation y=x; units K')
        if mode == 'architecture-mutates': Path('engineering/model.m').write_text('changed before review')
    elif stage == 'implementation': Path('engineering/model.m').write_text('wrong' if mode == 'repair' and role == 'builder' else 'function y=model(x), y=x; end')
    elif stage == 'handoff': Path('engineering/README.md').write_text('Traceability: ID-1 identity, probe passed')
    if role == 'repair': Path('engineering/model.m').write_text('function y=model(x), y=x; end')
    response='Fixture stage completed'
else:
    findings=[]; verdict='ACCEPT'
    if mode == 'reviewer-mutates' and stage == 'architecture':
        Path('engineering/model.m').write_text('function y=model(x), y=x; end')
    if mode == 'corrupt-journey-lock' and stage == 'handoff':
        Path('.matlab-harness/journey.lock').write_text('[]')
    bad=(Path('engineering/model.m').read_text() == 'wrong')
    items={}; prior=data.get('defects',{}).get('implementation:F-1',{}).get('finding',{}).get('status') == 'OPEN'
    if stage == 'implementation' and (bad or mode == 'reject'):
        verdict='REJECT'
        if prior: items={'F-1':dict(status='STILL_OPEN',evidence='Actual fixture source is still wrong')}
        else: findings=[dict(id='F-1',severity='MAJOR',kind='PROVEN DEFECT',artifact='engineering/model.m',evidence='Actual fixture source is wrong',impact='Identity violated',repair='Restore identity',closure='Run independent identity probe',status='OPEN')]
    elif stage == 'implementation' and prior:
        items={'F-1':dict(status='CLOSED',evidence='IC-1: actual repaired fixture and probe agree')}
    if mode == 'control-finding' and stage == 'requirements':
        verdict='REJECT'; findings=[dict(id='C-1',severity='MAJOR',kind='EVIDENCE GAP',artifact='.matlab-harness/project.json',evidence='Approval counterevidence needed',impact='Cannot attest current authorization',repair='Orchestrator must clarify source',closure='Independent reassessment',status='OPEN')]
    response=dict(checkpoint=stage,verdict=verdict,findings=findings,open_items=items,snapshot_digest=value_digest(p.snapshot()),**charter(p))
print(json.dumps(dict(status='SUCCESS',model='synthetic protocol fixture; not AI',session_id='fixture-'+role,response=response)))
'''


class JourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "engineering").mkdir()
        (self.root / "engineering/model.m").write_text("function y=model(x), y=x; end")
        start(self.root, "Identity diagnostic", "orchestrator-builder", "owner", ["engineering"], proof_mode="legacy-attested")
        self.project = Project(self.root)
        self.project.add_requirement("owner", "ID-1", "Identity in K", "independent identity probe", "synthetic diagnostic task", "K")
        (self.root / "provider_fixture.py").write_text(FIXTURE)
        runtime = {"adapter": "command", "roles": {}}
        src = str(Path(__file__).resolve().parents[2] / "src")
        for role in ("builder", "reviewer", "repair"):
            runtime["roles"][role] = {"argv": [sys.executable, "-B", str(self.root / "provider_fixture.py"), role, src]}
        self.project.configure_runtime("owner", runtime=runtime)
        for phase in ("implementation", "verification", "handoff"):
            self.project.configure_checks("owner", phase, {phase + "-probe": [sys.executable, "-B", "-c",
                "from pathlib import Path; assert Path('engineering/model.m').read_text() == 'function y=model(x), y=x; end'"]})

    def approve(self):
        self.project.approve("owner", "fixture-human", "explicit diagnostic authorization; not live approval")

    def test_invalid_utf8_brief_retains_terminal_accounting_without_dispatch(self):
        self.approve()
        brief = self.root / ".matlab-harness/brief.md"
        brief.write_bytes(b"Invalid Windows text: \x97")
        result = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(result["status"], "INPUT_REQUIRED", result)
        self.assertIn("UTF-8", result["reason"])
        terminal = json.loads((Path(result["invocation"]) / "finished.json").read_text())
        self.assertEqual(terminal["status"], "INPUT_REQUIRED")
        self.assertGreaterEqual(terminal["wall_seconds"], 0)
        self.assertFalse((self.root / ".matlab-harness/journey.lock").exists())
        self.assertEqual(brief.read_bytes(), b"Invalid Windows text: \x97")
        self.assertFalse(self.project.load()["acceptances"])
        self.assertFalse(self.project.load().get("runs", []))
        declaration = (self.root / ".matlab-harness/journey/declaration.json").read_bytes()
        brief.write_text("Corrected actual brief", encoding="utf-8")
        resumed = journey.run_journey(self.root, "owner", 60, stop_after="requirements")
        self.assertEqual(resumed["status"], "CHECKPOINT_REACHED", resumed)
        started = json.loads((Path(resumed["invocation"]) / "started.json").read_text())
        self.assertEqual(started["prior_seconds"], terminal["wall_seconds"])
        self.assertEqual((self.root / ".matlab-harness/journey/declaration.json").read_bytes(), declaration)

    def test_full_actual_process_lifecycle_and_resume_no_duplicate_accept(self):
        self.approve()
        result = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(result["status"], "COMPLETED", result)
        data = self.project.load()
        self.assertEqual([a["checkpoint"] for a in data["acceptances"]], list(PHASES))
        # architecture, implementation, verification and handoff each produce content
        self.assertEqual(sum(r["role"] == "builder" for r in data["runs"]), 4)
        self.assertEqual(sum(r["role"] == "reviewer" for r in data["runs"]), 5)
        for item in data["runs"]:
            self.assertTrue(Path(item["receipt"]["artifacts"]["stdout"]).exists())
        resumed = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(resumed["status"], "COMPLETED")
        self.assertEqual(len(self.project.load()["acceptances"]), 5)

    def test_checkpoint_stop_resumes_distinct_invocation_with_original_budget(self):
        self.approve()
        first = journey.run_journey(self.root, "owner", 60, stop_after="architecture")
        self.assertEqual(first["status"], "CHECKPOINT_REACHED", first)
        self.assertEqual(first["accepted_checkpoint"], "architecture")
        self.assertEqual(self.project.load()["phase"], "implementation")
        self.assertEqual(len(self.project.load()["acceptances"]), 2)
        self.assertFalse(any(t["status"] == "ACTIVE" for t in self.project.load()["tasks"].values()))
        declaration = (self.root / ".matlab-harness/journey/declaration.json").read_bytes()
        second = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(second["status"], "COMPLETED", second)
        self.assertNotEqual(first["invocation"], second["invocation"])
        self.assertEqual((self.root / ".matlab-harness/journey/declaration.json").read_bytes(), declaration)
        started = json.loads((Path(second["invocation"]) / "started.json").read_text())
        self.assertEqual(started["prior_seconds"], first["wall_seconds"])
        self.assertEqual(len(self.project.load()["acceptances"]), 5)

    def test_reviewer_cannot_erase_seed_before_implementation_verification(self):
        self.approve()
        (self.root / "engineering/model.m").write_text("wrong")
        (self.root / "mode.txt").write_text("reviewer-mutates")
        result = journey.run_journey(self.root, "owner", 60, review_existing_implementation=True)
        # Each attempt's edit is undone, so the seeded fault survives for the implementation review.
        self.assertEqual(result["status"], "REVIEW_PROTOCOL_EXHAUSTED", result)
        self.assertEqual((self.root / "engineering/model.m").read_text(), "wrong")
        self.assertEqual(sum(d.get("source") == "reviewer boundary" for d in self.project.load()["decisions"]), 3)
        self.assertEqual(self.project.load()["phase"], "architecture")
        self.assertFalse(self.project.load()["evidence"])
        self.assertEqual(len(self.project.load()["acceptances"]), 1)

    def test_corrupted_cleanup_lock_retains_final_accounting_and_acceptance(self):
        self.approve()
        (self.root / "mode.txt").write_text("corrupt-journey-lock")
        result = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(result["status"], "INPUT_REQUIRED", result)
        self.assertEqual(result["completion_status"], "COMPLETED")
        self.assertEqual(result["cleanup"]["status"], "INSPECTION_REQUIRED")
        self.assertEqual((self.root / ".matlab-harness/journey.lock").read_text(), "[]")
        self.assertTrue((Path(result["invocation"]) / "finished.json").is_file())
        self.assertEqual(len(self.project.load()["acceptances"]), 5)
        self.assertGreater(result["wall_seconds"], 0)

    def test_control_record_finding_pauses_without_unauthorized_builder_repair(self):
        self.approve()
        (self.root / "mode.txt").write_text("control-finding")
        result = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(result["status"], "INPUT_REQUIRED", result)
        self.assertIn("orchestrator-owned", result["reason"])
        self.assertEqual(self.project.load()["repairs"], 0)
        self.assertFalse(any(item["role"] == "repair" for item in self.project.load()["runs"]))

    def test_control_artifact_location_spellings_are_recognized(self):
        for location in ("requirements.md:1", "./requirements.md", "./.matlab-harness/project.json:42:3",
                         str(self.root / "requirements.md") + ":12", ".matlab-harness\\project.json"):
            self.assertTrue(self.project.reserved_location(location), location)
        import os
        if os.name == "nt":
            self.assertTrue(self.project.reserved_location(".MATLAB-HARNESS/project.json"))
        self.assertFalse(self.project.reserved_location("engineering/model.m:4"))

    def test_unapproved_discovery_waits_and_does_not_repeat(self):
        first = journey.run_journey(self.root, "owner", 60)
        second = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(first["status"], "WAITING_FOR_USER_APPROVAL")
        self.assertEqual(second["status"], "WAITING_FOR_USER_APPROVAL")
        self.assertEqual(len(self.project.load()["runs"]), 1)
        self.assertFalse(self.project.load()["approvals"])
        self.assertFalse(self.project.load()["acceptances"])

    def test_changed_approval_never_reapproved_automatically(self):
        self.approve()
        (self.root / "requirements.md").write_text("Changed operating limit without authorization")
        result = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(result["status"], "WAITING_FOR_USER_APPROVAL")
        self.assertEqual(len(self.project.load()["approvals"]), 1)
        self.assertFalse(self.project.load().get("runs"))

    def test_seeded_fault_repaired_retested_and_explicitly_closed(self):
        self.approve()
        (self.root / "mode.txt").write_text("repair")
        result = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(result["status"], "COMPLETED", result)
        data = self.project.load()
        self.assertEqual(data["repairs"], 1)
        defect = data["defects"]["implementation:F-1"]
        self.assertFalse(defect["blocking"])
        self.assertEqual([i["finding"]["status"] for i in defect["history"]], ["OPEN", "CLOSED"])
        checks = [json.loads(p.read_text()) for p in (self.root / ".matlab-harness/evidence").glob("*.json")]
        self.assertIn("FAILED", [r["status"] for r in checks])
        self.assertIn("PASSED", [r["status"] for r in checks])

    def test_review_existing_observes_seed_before_any_implementation_builder(self):
        self.approve()
        (self.root / "engineering/model.m").write_text("wrong")
        (self.root / "mode.txt").write_text("repair")
        result = journey.run_journey(self.root, "owner", 60, review_existing_implementation=True)
        self.assertEqual(result["status"], "COMPLETED", result)
        data = self.project.load()
        self.assertFalse(any(r["role"] == "builder" and r["checkpoint"] == "implementation" for r in data["runs"]))
        self.assertEqual(sum(r["role"] == "builder" and r["checkpoint"] == "architecture" for r in data["runs"]), 1)
        steps = [json.loads(path.read_text()) for path in Path(result["invocation"]).glob("step-*-finished.json")]
        implementation_checks = [r for r in steps if r["kind"] == "check" and r["phase"] == "implementation"]
        self.assertEqual([r["status"] for r in implementation_checks], ["FAILED", "PASSED"])
        first_review = next(r for r in data["runs"] if r["role"] == "reviewer" and r["checkpoint"] == "implementation")
        self.assertEqual(first_review["receipt"]["response"]["verdict"], "REJECT")
        self.assertEqual(first_review["receipt"]["response"]["findings"][0]["status"], "OPEN")
        self.assertEqual(data["repairs"], 1)
        declaration = json.loads((self.root / ".matlab-harness/journey/declaration.json").read_text())
        self.assertTrue(declaration["review_existing_implementation"])
        same_mode = journey.run_journey(self.root, "owner", 60, review_existing_implementation=True)
        self.assertEqual(same_mode["status"], "COMPLETED")
        changed_mode = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(changed_mode["status"], "INPUT_REQUIRED")
        self.assertIn("same on resume", changed_mode["reason"])

    def test_review_existing_catches_architecture_overwrite(self):
        self.approve()
        (self.root / "engineering/model.m").write_text("wrong")
        (self.root / "mode.txt").write_text("architecture-mutates")
        result = journey.run_journey(self.root, "owner", 60, review_existing_implementation=True)
        self.assertEqual(result["status"], "INPUT_REQUIRED", result)
        self.assertIn("Document/design role changed", result["reason"])
        self.assertIn("engineering/model.m", result["changed_artifacts"])
        self.assertFalse(self.project.load()["evidence"])
        self.assertFalse(any(r["checkpoint"] == "implementation" for r in self.project.load()["runs"]))
        resumed = journey.run_journey(self.root, "owner", 60, review_existing_implementation=True)
        self.assertEqual(resumed["status"], "INPUT_REQUIRED")
        self.assertIn("Restore recorded document/design boundary", resumed["reason"])

    def test_explicit_revision_preserves_seed_evidence_and_protects_repaired_baseline(self):
        self.approve()
        (self.root / "engineering/model.m").write_text("wrong")
        (self.root / "mode.txt").write_text("repair")
        first = journey.run_journey(self.root, "owner", 120, review_existing_implementation=True)
        self.assertEqual(first["status"], "COMPLETED", first)
        declaration = self.root / ".matlab-harness/journey/declaration.json"
        original = declaration.read_bytes()
        original_record = json.loads(original)
        old_data = self.project.load()
        self.project.revise("owner", "Explicit new requirement cycle after verified repair")
        self.approve()
        second = journey.run_journey(self.root, "owner", 120,
            review_existing_implementation=True, stop_after="architecture")
        self.assertEqual(second["status"], "CHECKPOINT_REACHED", second)
        self.assertEqual(declaration.read_bytes(), original)
        started = json.loads((Path(second["invocation"]) / "started.json").read_text())
        self.assertEqual(started["prior_seconds"], first["wall_seconds"])
        self.assertNotEqual(original_record["initial_implementation_hashes"],
            _implementation_hashes(self.project))
        archive = next((self.root / ".matlab-harness/history").glob("baseline-*.json"))
        self.assertEqual(json.loads(archive.read_text()), old_data)
        self.assertEqual(self.project.load()["defects"]["implementation:F-1"]["origin_digest"],
            old_data["defects"]["implementation:F-1"]["origin_digest"])

    def test_revision_cannot_adopt_stale_or_unverified_implementation(self):
        self.approve()
        (self.root / "engineering/model.m").write_text("wrong")
        (self.root / "mode.txt").write_text("repair")
        first = journey.run_journey(self.root, "owner", 120, review_existing_implementation=True)
        self.assertEqual(first["status"], "COMPLETED", first)
        (self.root / "engineering/model.m").write_text("unverified after handoff")
        self.project.revise("owner", "Stale handoff cannot authorize this implementation")
        self.assertNotIn("implementation_baseline", self.project.load()["decisions"][-1])
        self.approve()
        resumed = journey.run_journey(self.root, "owner", 120, review_existing_implementation=True)
        self.assertEqual(resumed["status"], "INPUT_REQUIRED", resumed)
        self.assertIn("changed_artifacts", resumed)

    def test_revision_binding_rejects_post_revision_addition_and_archive_tampering(self):
        self.approve()
        (self.root / "engineering/model.m").write_text("wrong")
        (self.root / "mode.txt").write_text("repair")
        first = journey.run_journey(self.root, "owner", 120, review_existing_implementation=True)
        self.assertEqual(first["status"], "COMPLETED", first)
        self.project.revise("owner", "Verified repaired baseline for new cycle")
        self.approve()
        added = self.root / "engineering/extra.m"
        added.write_text("unreviewed implementation addition")
        resumed = journey.run_journey(self.root, "owner", 120, review_existing_implementation=True)
        self.assertEqual(resumed["status"], "INPUT_REQUIRED", resumed)
        self.assertIn("engineering/extra.m", resumed["changed_artifacts"])
        added.unlink()
        baseline = next(d["implementation_baseline"] for d in reversed(self.project.load()["decisions"])
            if "implementation_baseline" in d)
        archive = self.root / baseline["archive"]
        archive.write_text(archive.read_text() + " ")
        refused = journey.run_journey(self.root, "owner", 120, review_existing_implementation=True)
        self.assertEqual(refused["status"], "INPUT_REQUIRED", refused)
        self.assertIn("archive changed", refused["reason"])

    def test_missing_historical_declaration_never_rebases_repaired_seed(self):
        self.approve()
        (self.root / "engineering/model.m").write_text("wrong")
        (self.root / "mode.txt").write_text("repair")
        first = journey.run_journey(self.root, "owner", 120, review_existing_implementation=True)
        self.assertEqual(first["status"], "COMPLETED", first)
        declaration = self.root / ".matlab-harness/journey/declaration.json"
        declaration.unlink()
        refused = journey.run_journey(self.root, "owner", 120, review_existing_implementation=True)
        self.assertEqual(refused["status"], "INPUT_REQUIRED", refused)
        self.assertIn("Missing journey declaration", refused["reason"])
        self.assertFalse(declaration.exists())

    def test_invalid_declaration_shape_pauses_without_unhandled_exception(self):
        self.approve()
        first = journey.run_journey(self.root, "owner", 120, stop_after="architecture")
        self.assertEqual(first["status"], "CHECKPOINT_REACHED", first)
        declaration = self.root / ".matlab-harness/journey/declaration.json"
        declaration.write_text("[]")
        refused = journey.run_journey(self.root, "owner", 120)
        self.assertEqual(refused["status"], "INPUT_REQUIRED", refused)
        self.assertIn("Invalid journey declaration", refused["reason"])
        self.assertEqual(declaration.read_text(), "[]")

    def test_five_repairs_bounded_and_failures_retained(self):
        self.approve()
        self.project.configure_runtime("owner", repair_budget=5)
        (self.root / "mode.txt").write_text("reject")
        result = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(result["status"], "REPAIR_BUDGET_EXHAUSTED", result)
        self.assertEqual(self.project.load()["repairs"], 5)
        self.assertEqual(self.project.load()["phase"], "implementation")

    def test_missing_native_executable_returns_input_required(self):
        self.approve()
        self.project.configure_checks("owner", "implementation", {"missing": [str(self.root / "absent.exe")]})
        result = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(result["status"], "INPUT_REQUIRED", result)
        self.assertIn("Native check", result["reason"])
        self.assertEqual(result["checks"][0]["status"], "BLOCKED")

    def test_missing_implementation_plan_never_substitutes_easy_probe(self):
        self.approve()
        self.project.configure_checks("owner", "implementation", {})
        result = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(result["status"], "INPUT_REQUIRED", result)
        self.assertIn("task-specific executable", result["reason"])
        self.assertEqual(self.project.load()["phase"], "implementation")
        self.assertFalse(self.project.load()["evidence"])

    def test_active_lease_and_concurrent_runner_require_inspection(self):
        self.approve()
        self.project.lease("owner", "external-design", "actual-worker", ["engineering"], ["ID-1"], kind="design")
        result = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(result["status"], "INPUT_REQUIRED")
        self.assertIn("external-design", result["tasks"])
        self.assertEqual(self.project.load()["tasks"]["external-design"]["status"], "ACTIVE")
        (self.root / ".matlab-harness/journey.lock").write_text('{"pid":123,"token":"another-owner"}')
        concurrent = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(concurrent["status"], "INPUT_REQUIRED")
        self.assertTrue((self.root / ".matlab-harness/journey.lock").exists())

    def test_native_timeout_preserves_failure_and_predeclared_ceiling(self):
        self.approve()
        self.project.configure_runtime("owner", budgets={"native": 0.1})
        self.project.configure_checks("owner", "implementation", {"slow": [sys.executable, "-B", "-c", "import time; time.sleep(60)"]})
        result = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(result["status"], "INPUT_REQUIRED")
        self.assertEqual(result["checks"][0]["status"], "BLOCKED")
        declaration = json.loads((self.root / ".matlab-harness/journey/declaration.json").read_text())
        self.assertEqual(declaration["ceiling_seconds"], 60)
        self.assertEqual(declaration["budgets"]["builder"], 3600)
        before = (self.root / ".matlab-harness/journey/declaration.json").read_bytes()
        refused = journey.run_journey(self.root, "owner", 120)
        self.assertEqual(refused["status"], "INPUT_REQUIRED")
        self.assertEqual((self.root / ".matlab-harness/journey/declaration.json").read_bytes(), before)

    def test_manual_adapter_returns_actual_packet(self):
        self.approve()
        self.project.configure_runtime("owner", runtime={"adapter": "manual"})
        result = journey.run_journey(self.root, "owner", 60)
        self.assertEqual(result["status"], "INPUT_REQUIRED")
        self.assertTrue(Path(result["packet"]["prompt"]).is_file())
        self.assertFalse(self.project.load()["acceptances"])

    def test_small_ceiling_clips_actual_role_and_retains_timeout(self):
        (self.root / "mode.txt").write_text("slow")
        result = journey.run_journey(self.root, "owner", 1)
        self.assertEqual(result["status"], "TIMED_OUT", result)
        receipt = result["receipt"]
        self.assertLessEqual(receipt["timeout_seconds"], 1)
        self.assertEqual(self.project.load()["budgets"]["builder"], 3600)
        self.assertTrue(receipt["cleanup"]["root_stopped"])
        refused = journey.run_journey(self.root, "owner", 100)
        self.assertEqual(refused["status"], "INPUT_REQUIRED")
        self.assertIn("retrospectively", refused["reason"])


if __name__ == "__main__":
    unittest.main()
