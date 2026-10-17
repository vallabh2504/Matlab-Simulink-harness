"""Actual CLI/subprocess integrity probes; fixture envelopes are not live AI reviews."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from matlab_harness.project import Project, ProjectError, atomic_json, value_digest
from matlab_harness.workflow import execute, next_step, packet, start


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src/model.m").write_text("function y=model(x), y=x; end\n")
        (self.root / "AGENTS.md").write_text("Existing operator instructions")
        start(self.root, "Existing model", "fixture-builder", "fixture-owner", ["src"], "Inspect legacy behavior")
        self.project = Project(self.root)

    def config_command(self, response, identity="fixture-independent-reviewer"):
        envelope = {"status": "SUCCESS", "response": response, "session_id": identity,
                    "model": "diagnostic subprocess fixture, not live AI"}
        atomic_json(self.root / "fixture-envelope.json", envelope)
        # A reviewer envelope gets one synthetic probe written into the packet's scratch directory.
        (self.root / "fixture-command.py").write_text(
            "import json,os\nfrom pathlib import Path\n"
            "e=json.loads(Path('fixture-envelope.json').read_text()); r=e['response']\n"
            "if isinstance(r,dict) and 'independent_checks' in r:\n"
            "    s=Path(os.environ['MATLAB_HARNESS_SCRATCH']); s.mkdir(parents=True,exist_ok=True); (s/'probe.m').write_text('% fixture')\n"
            "    r['independent_checks']=[dict(id='IC-1',purpose='synthetic',requirements='all',command='none',expected='n/a',"
            "observed='n/a',result='PASS',artifact=str(s/'probe.m'),finding_ids='')]\n"
            "print(json.dumps(e))\n")
        self.project.configure_runtime("fixture-owner", runtime={"adapter": "command", "argv":
            [sys.executable, "-B", str(self.root / "fixture-command.py")]})

    def review_response(self, stage="requirements"):
        return {"checkpoint": stage, "verdict": "ACCEPT", "findings": [],
                "snapshot_digest": value_digest(self.project.snapshot()),
                "traceability": [{"requirement": r["id"], "status": "VERIFIED", "evidence": "synthetic fixture",
                                  "finding_ids": ""} for r in self.project.load()["requirements"]],
                "independent_checks": []}

    def test_start_preserves_user_files_and_manual_handoff(self):
        self.assertEqual((self.root / "AGENTS.md").read_text(), "Existing operator instructions")
        result = next_step(self.project)
        self.assertEqual(result["budgets"]["builder"], 3600)
        self.assertEqual(result["repairs_remaining"], 10)
        self.assertFalse(result["completed"])
        handoff = execute(self.project, "fixture-owner", "builder")
        self.assertEqual(handoff["status"], "MANUAL_HANDOFF")
        text = Path(handoff["packet"]["prompt"]).read_text()
        self.assertIn("actual user approval", text)
        self.assertIn("3600", json.dumps(result))
        with self.assertRaises(ProjectError):
            start(self.root, "new", "b", "o", ["src"])

    def test_legacy_views_supply_closure_identity_without_record_mutation(self):
        issue = {"id":"OLD-1", "severity":"MAJOR", "kind":"PROVEN DEFECT",
                 "artifact":"src/model.m", "evidence":"wrong dynamics", "impact":"bad prediction",
                 "repair":"correct equation", "closure":"native regression", "status":"OPEN"}
        report = {**self.review_response(), "verdict":"REJECT", "findings":[issue],
                  "reviewer_session":"fixture-independent-reviewer", "model":"synthetic diagnostic",
                  "independence":"independent-agent"}
        atomic_json(self.root / "review.json", report)
        self.project.review("fixture-owner", "requirements", "review.json")
        original = self.project.load()
        for shape in ("no-ledger", "no-origin"):
            data = json.loads(json.dumps(original))
            if shape == "no-ledger":
                data.pop("defects")
            else:
                data["defects"]["requirements:OLD-1"].pop("origin")
                data["defects"]["requirements:OLD-1"].pop("origin_digest")
            self.project._write_record(data)
            before = self.project.record.read_bytes()
            for view in (next_step(self.project), self.project.resume()):
                self.assertEqual(view["defects"]["requirements:OLD-1"]["origin_digest"], value_digest(issue))
            generated = packet(self.project, "reviewer")
            self.assertIn(value_digest(issue), Path(generated["prompt"]).read_text())
            self.assertFalse(self.project.gate("requirements")["accepted"])
            self.assertEqual(self.project.record.read_bytes(), before)

    def test_actual_subprocess_review_import_and_durable_resume(self):
        self.project.add_requirement("fixture-owner", "R-1", "Identity", "native oracle", "fixture user")
        self.project.approve("fixture-owner", "fixture-human", "diagnostic authorization")
        self.config_command(self.review_response())
        result = execute(self.project, "fixture-owner", "reviewer")
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertTrue(result["gate"]["accepted"])
        self.assertEqual(result["receipt"]["root_session_id"], "fixture-independent-reviewer")
        resumed = next_step(Project(self.root))
        self.assertEqual(resumed["next_action"], "accept requirements")
        self.assertEqual(resumed["reviews"]["requirements"]["model"], "diagnostic subprocess fixture, not live AI")
        self.assertTrue(self.project.resume()["runs"])

    def test_implementation_review_packet_has_review_criteria_without_build_instructions(self):
        generated = packet(self.project, "reviewer", "implementation", "Assess the seeded fault")
        prompt = Path(generated["prompt"]).read_text()
        self.assertIn("independent, read-only review", prompt)
        self.assertIn("Report defects for a separate repair worker", prompt)
        self.assertNotIn("Implement only the accepted", prompt)
        self.assertNotIn("Write governing equations", prompt)
        self.assertLess(prompt.index("Do not implement or repair"), prompt.index("Read requirements.md"))
        self.assertIn("scratch directory", prompt)
        self.assertIn("each issue ID appearing once", prompt)

    def test_actual_builder_identity_excluded_from_review(self):
        self.config_command("Builder completed diagnostic discovery", identity="fixture-shared-session")
        self.assertEqual(execute(self.project, "fixture-owner", "builder")["status"], "SUCCEEDED")
        self.config_command(self.review_response(), identity="fixture-shared-session")
        with self.assertRaisesRegex(ProjectError, "contributing"):
            execute(self.project, "fixture-owner", "reviewer")
        self.assertEqual(len(self.project.load()["runs"]), 2)
        self.assertFalse(self.project.load()["reviews"])

    def test_structured_review_binds_snapshot_but_rejects_a_wrong_response(self):
        self.config_command(self.review_response())
        first = execute(self.project, "fixture-owner", "reviewer")
        schema = json.loads(Path(first["receipt"]["artifacts"]["schema"]).read_text())
        self.assertEqual(schema["properties"]["checkpoint"]["enum"], ["requirements"])
        self.assertEqual(schema["properties"]["snapshot_digest"]["enum"],
                         [value_digest(self.project.snapshot())])
        self.assertEqual(schema["properties"]["verdict"]["enum"], ["ACCEPT", "REJECT", "INCOMPLETE"])
        old_reviews = self.project.load()["reviews"]
        wrong = self.review_response()
        wrong["snapshot_digest"] = wrong["snapshot_digest"][:-1]
        self.config_command(wrong)
        with self.assertRaisesRegex(ProjectError, "snapshot"):
            execute(self.project, "fixture-owner", "reviewer")
        self.assertEqual(self.project.load()["reviews"], old_reviews)

    def test_reviewer_artifact_edit_cannot_pass_freshness(self):
        self.config_command(self.review_response())
        (self.root / "fixture-command.py").write_text(
            "from pathlib import Path\nPath('src/model.m').write_text('changed')\n"
            "print(Path('fixture-envelope.json').read_text())\n")
        with self.assertRaisesRegex(ProjectError, "snapshot"):
            execute(self.project, "fixture-owner", "reviewer")
        self.assertEqual(len(self.project.load()["runs"]), 1)
        self.assertFalse(self.project.load()["reviews"])

    def test_reviewer_cannot_modify_artifacts_and_report_a_fresh_digest(self):
        self.config_command(self.review_response())
        (self.root / "fixture-command.py").write_text(
            "import json,sys\nfrom pathlib import Path\n"
            "sys.path.insert(0," + repr(str(Path(__file__).resolve().parents[2] / "src")) + ")\n"
            "from matlab_harness.project import Project,value_digest\n"
            "Path('src/model.m').write_text('rewritten during review')\n"
            "envelope=json.loads(Path('fixture-envelope.json').read_text())\n"
            "envelope['response']['snapshot_digest']=value_digest(Project('.').snapshot())\n"
            "print(json.dumps(envelope))\n")
        with self.assertRaisesRegex(ProjectError, "Reviewer modified"):
            execute(self.project, "fixture-owner", "reviewer")
        self.assertEqual(len(self.project.load()["runs"]), 1)
        self.assertFalse(self.project.load()["reviews"])

    def test_missing_actual_reviewer_identity_not_imported(self):
        self.config_command(self.review_response(), identity=None)
        result = execute(self.project, "fixture-owner", "reviewer")
        self.assertEqual(result["status"], "REVIEW_NOT_IMPORTED")
        self.assertFalse(self.project.load()["reviews"])

    def test_predispatch_project_ceiling_clips_without_rewriting_budgets(self):
        self.config_command("diagnostic discovery finished")
        result = execute(self.project,"fixture-owner","builder",remaining_seconds=30)
        self.assertEqual(result["receipt"]["timeout_seconds"],30)
        self.assertEqual(self.project.load()["budgets"]["builder"],3600)
        for remaining in (0,-1,float("nan"),True):
            with self.assertRaises(ProjectError):
                execute(self.project,"fixture-owner","builder",remaining_seconds=remaining)

    def test_handoff_edit_reopens_work_in_next_view(self):
        self.project.add_requirement("fixture-owner", "R-1", "Identity", "native oracle", "fixture user")
        self.project.approve("fixture-owner", "fixture-human", "diagnostic authorization")
        for stage in ("implementation", "verification", "handoff"):
            self.project.configure_checks("fixture-owner", stage, {"probe": [sys.executable,"-B","-c","pass"]})
        self.project.run_check("fixture-owner", "probe")
        for stage in ("requirements", "architecture", "implementation", "verification", "handoff"):
            if stage == "handoff":
                (self.root / "src/README.md").write_text("Traceability: R-1 identity, probe passed")
                self.project.run_check("fixture-owner", "probe")
            self.config_command(self.review_response(stage))
            execute(self.project, "fixture-owner", "reviewer")
            self.project.accept("fixture-owner", stage)
        self.assertTrue(next_step(self.project)["completed"])
        (self.root / "src/model.m").write_text("changed after delivery")
        result = next_step(self.project)
        self.assertFalse(result["completed"])
        self.assertIn("revise", result["next_action"])

    def test_cli_next_and_runtime_configuration(self):
        cli = Path(__file__).resolve().parents[2] / "matlab_harness.py"
        argv = [sys.executable, "-B", str(cli), "--project", str(self.root)]
        update = subprocess.run(argv + ["configure-runtime", "--owner", "fixture-owner",
            "--reviewer-seconds", "1800", "--repair-budget", "9"], capture_output=True, text=True)
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        result = subprocess.run(argv + ["next"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["budgets"]["reviewer"], 1800)
        self.assertEqual(json.loads(result.stdout)["repairs_remaining"], 9)
        handoff = packet(self.project, "reviewer", "requirements", "Challenge units")
        self.assertTrue(Path(handoff["prompt"]).is_file())


if __name__ == "__main__":
    unittest.main()
