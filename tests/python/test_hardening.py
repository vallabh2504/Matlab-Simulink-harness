"""Defences added after the 2026-10-17 workflow audit: record seal, protected support
files, reviewer charter minimum, runtime-attested reviews, handoff obligations,
skill selection and prompt size."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from matlab_harness.project import Project, ProjectError, atomic_json, cites, value_digest
from matlab_harness.skills import select_for
from matlab_harness.workflow import charter_problems, packet, start

CHECK = "function tests = oracle_test, tests = functiontests(localfunctions); end\n"


class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src/model.m").write_text("function y=model(x), y=x; end\n")
        (self.root / "checks").mkdir()
        (self.root / "checks/oracle_test.m").write_text(CHECK)
        start(self.root, "Identity", "fixture-builder", "owner", ["src"], "Identity model")
        self.project = Project(self.root)
        self.project.add_requirement("owner", "ID-1", "Identity", "closed form", "user brief")
        self.project.add_requirement("owner", "ID-10", "Scalar input", "closed form", "user brief")
        self.project.configure_checks("owner", "implementation", {"oracle": [sys.executable, "-c", "pass"]})

    def import_review(self, checkpoint, findings=(), verdict="ACCEPT"):
        atomic_json(self.root / "review.json", {
            "reviewer_session": "independent-test-agent", "model": "test record, no live AI claim",
            "independence": "independent-agent", "checkpoint": checkpoint, "verdict": verdict,
            "findings": list(findings), "snapshot_digest": value_digest(self.project.snapshot())})
        self.project.review("owner", checkpoint, "review.json")

    # Record seal
    def test_record_edit_outside_transaction_is_refused(self):
        self.assertEqual(self.project.record_seal(), "VERIFIED")
        data = json.loads(self.project.record.read_text())
        data["approval"] = {"approver": "forged", "basis": "edited by hand"}
        atomic_json(self.project.record, data)
        with self.assertRaisesRegex(ProjectError, "outside a harness transaction"):
            self.project.load()

    def test_transaction_write_keeps_seal_valid(self):
        self.project.add_requirement("owner", "ID-2", "Vector input", "closed form", "user brief")
        self.assertIn("ID-2", [r["id"] for r in self.project.load()["requirements"]])

    # Protected support files
    def test_role_edit_of_check_script_restored_and_shadow_quarantined(self):
        data = self.project.load()
        before = self.project.support_state(data)
        (self.root / "checks/oracle_test.m").write_text("% weakened: always passes\n")
        (self.root / "model.m").write_text("function y=model(x), y=x+0; end\n")  # shadows src/model.m
        quarantine = self.root / ".matlab-harness/quarantine-test"
        result = self.project.enforce_support(data, before, quarantine)
        self.assertEqual(result["restored"], ["checks/oracle_test.m"])
        self.assertEqual(result["quarantined"], ["model.m"])
        self.assertEqual((self.root / "checks/oracle_test.m").read_text(), CHECK)
        self.assertFalse((self.root / "model.m").exists())
        self.assertTrue((quarantine / "model.m").is_file())

    def test_orchestrator_file_added_between_roles_is_not_quarantined(self):
        (self.root / "helper.m").write_text("% orchestrator helper\n")
        data = self.project.load()
        before = self.project.support_state(data)
        self.assertEqual(self.project.enforce_support(data, before, self.root / "q"), {})
        self.assertTrue((self.root / "helper.m").is_file())

    def test_gate_refuses_weakened_check_script(self):
        (self.root / "checks/oracle_test.m").write_text("% weakened\n")
        problems = self.project.gate("requirements")["problems"]
        self.assertIn("Protected out-of-scope file changed since the orchestrator check baseline: checks/oracle_test.m",
                      problems)

    def test_snapshot_binds_check_script(self):
        before = value_digest(self.project.snapshot())
        (self.root / "checks/oracle_test.m").write_text("% weakened\n")
        self.assertNotEqual(value_digest(self.project.snapshot()), before)

    # Review identity
    def test_self_attested_review_insufficient_when_reviewer_runtime_configured(self):
        self.project.configure_runtime("owner", runtime={"adapter": "command", "argv": [sys.executable, "-c", "pass"]})
        self.import_review("requirements")
        problems = self.project.gate("requirements")["problems"]
        self.assertTrue(any("self-attested" in p for p in problems), problems)

    # Reviewer charter minimum
    def response(self, verdict="ACCEPT", rows=None, checks=None, findings=()):
        return {"verdict": verdict, "findings": list(findings),
                "traceability": rows if rows is not None else [
                    {"requirement": i, "status": "VERIFIED", "evidence": "probe", "finding_ids": ""}
                    for i in ("ID-1", "ID-10")],
                "independent_checks": checks if checks is not None else []}

    def test_charter_requires_every_requirement_once(self):
        scratch = self.root / ".matlab-harness/scratch/t"
        data = self.project.load()
        rows = [{"requirement": "ID-1", "status": "VERIFIED", "evidence": "probe", "finding_ids": ""}]
        self.assertIn("ID-10", charter_problems(self.project, self.response(rows=rows), data, "requirements", scratch))
        self.assertIsNone(charter_problems(self.project, self.response(), data, "requirements", scratch))

    def test_charter_accept_needs_finding_for_unverified_row(self):
        scratch = self.root / ".matlab-harness/scratch/t"
        data = self.project.load()
        rows = [{"requirement": "ID-1", "status": "VERIFIED", "evidence": "probe", "finding_ids": ""},
                {"requirement": "ID-10", "status": "PARTIAL", "evidence": "scalar only", "finding_ids": ""}]
        self.assertIn("without a finding", charter_problems(self.project, self.response(rows=rows), data,
                                                            "requirements", scratch))
        rows[1]["status"] = "FAILED"
        self.assertIn("FAILED", charter_problems(self.project, self.response(rows=rows), data, "requirements", scratch))

    def test_charter_executed_checkpoint_needs_scratch_probe(self):
        scratch = self.root / ".matlab-harness/scratch/t"
        data = self.project.load()
        builder_test = {"id": "IC-1", "artifact": str(self.root / "checks/oracle_test.m")}
        problem = charter_problems(self.project, self.response(checks=[builder_test]), data, "implementation", scratch)
        self.assertIn("not independent review", problem)
        scratch.mkdir(parents=True)
        (scratch / "probe.m").write_text("% independent oracle\n")
        probe = {"id": "IC-1", "artifact": str(scratch / "probe.m")}
        self.assertIsNone(charter_problems(self.project, self.response(checks=[probe]), data, "implementation", scratch))

    # Handoff obligations
    def test_handoff_obligations_cite_whole_ids(self):
        (self.root / "src/README.md").write_text("| ID-10 | scalar | passed |\n")
        obligations = self.project.handoff_obligations(self.project.load())
        self.assertTrue(any("ID-1" in o and "ID-10" not in o for o in obligations), obligations)
        self.assertFalse(cites("ID-10", "ID-1"))
        (self.root / "src/README.md").write_text("| ID-1 | identity | passed |\n| ID-10 | scalar | passed |\n")
        self.assertEqual(self.project.handoff_obligations(self.project.load()), [])

    def test_open_finding_must_be_dispositioned_at_handoff(self):
        issue = {"id": "REQ-7", "severity": "MINOR", "kind": "EVIDENCE GAP", "artifact": "src/model.m",
                 "evidence": "no NaN case", "impact": "unknown NaN handling", "repair": "add a NaN case",
                 "closure": "NaN regression", "status": "OPEN"}
        self.import_review("requirements", [issue])
        (self.root / "src/README.md").write_text("ID-1 and ID-10 verified\n")
        self.assertTrue(any("REQ-7" in o for o in self.project.handoff_obligations(self.project.load())))
        (self.root / "src/README.md").write_text("ID-1 and ID-10 verified. REQ-7: accepted risk, NaN out of contract.\n")
        self.assertEqual(self.project.handoff_obligations(self.project.load()), [])

    # Skills
    def test_simulink_skill_only_when_task_names_it(self):
        names = [s["name"] for s in select_for("implementation", "builder", "MATLAB function for cooling")]
        self.assertNotIn("engineering-simulink-engineering", names)
        names = [s["name"] for s in select_for("implementation", "reviewer", "Update the Simulink model plant.slx")]
        self.assertIn("engineering-simulink-engineering", names)
        self.assertIn("engineering-review-continuity", names)
        self.assertLessEqual(len(names), 3)

    # Prompts stay small for open models
    def test_prompts_stay_within_budget_and_carry_clipped_findings(self):
        long_evidence = "x" * 2000
        issue = {"id": "REQ-9", "severity": "MINOR", "kind": "EVIDENCE GAP", "artifact": "src/model.m",
                 "evidence": long_evidence, "impact": "gap", "repair": "add case", "closure": "case passes",
                 "status": "OPEN"}
        self.import_review("requirements", [issue])
        for role in ("builder", "reviewer", "repair"):
            prompt = Path(packet(self.project, role, "implementation")["prompt"]).read_text(encoding="utf-8")
            self.assertLess(len(prompt.encode("utf-8")), 12000, role)
            if role != "reviewer":
                self.assertIn("REQ-9", prompt)
                self.assertNotIn(long_evidence, prompt)


if __name__ == "__main__":
    unittest.main()
