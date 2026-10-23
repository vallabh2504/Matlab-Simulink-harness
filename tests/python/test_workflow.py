"""Actual CLI/subprocess integrity probes; fixture envelopes are not live AI reviews."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from matlab_harness.project import Project, ProjectError, atomic_json, value_digest
from matlab_harness.answer import translate
from matlab_harness.workflow import execute, next_step, packet, start


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src/model.m").write_text("function y=model(x), y=x; end\n")
        (self.root / "AGENTS.md").write_text("Existing operator instructions")
        start(self.root, "Existing model", "fixture-builder", "fixture-owner", ["src"], "Inspect legacy behavior", proof_mode="legacy-attested")
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
            start(self.root, "new", "b", "o", ["src"], proof_mode="legacy-attested")

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
            # The digest is bookkeeping the harness restates, so the prompt shows only the handle to answer.
            self.assertNotIn(value_digest(issue), Path(generated["prompt"]).read_text())
            self.assertIn('"OLD-1"', Path(generated["prompt"]).read_text())
            record, problems = translate(self.project, data, "requirements", {
                "verdict": "ACCEPT", "findings": [], "traceability": {},
                "open_items": {"OLD-1": {"status": "CLOSED", "evidence": "native regression passes"}}},
                self.root / "no-scratch")
            closed, = record["findings"]
            self.assertEqual((closed["artifact"], closed["prior_finding_digest"]), ("src/model.m", value_digest(issue)))
            self.assertEqual(problems, [])
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

    def test_a_usage_limited_reviewer_is_reported_as_one(self):
        self.project.add_requirement("fixture-owner", "R-1", "Identity", "native oracle", "fixture user")
        self.project.approve("fixture-owner", "fixture-human", "diagnostic authorization")
        self.config_command(self.review_response())
        envelope = json.loads((self.root / "fixture-envelope.json").read_text())
        atomic_json(self.root / "fixture-envelope.json", {**envelope, "status": "FAILED",
                    "error": "Provider result: success You've hit your session limit"})
        result = execute(self.project, "fixture-owner", "reviewer")
        self.assertIn("ended FAILED (provider_usage_limit: Provider result: success You've hit your session limit)", result["reason"])
        self.assertFalse(result["gate"]["accepted"])

    def test_a_builders_subagent_cannot_review(self):
        self.config_command("Builder completed diagnostic discovery", identity="fixture-builder-root")
        envelope = json.loads((self.root / "fixture-envelope.json").read_text())
        atomic_json(self.root / "fixture-envelope.json", {**envelope, "child_session_ids": ["fixture-builder-child"]})
        self.assertEqual(execute(self.project, "fixture-owner", "builder")["status"], "SUCCEEDED")
        self.assertEqual(self.project.load()["contributors"], ["fixture-builder-root", "fixture-builder-child"])
        self.config_command(self.review_response(), identity="fixture-builder-child")
        with self.assertRaisesRegex(ProjectError, "contributing"):
            execute(self.project, "fixture-owner", "reviewer")
        self.assertFalse(self.project.load()["reviews"])

    def test_same_model_reviewer_is_labelled_honestly(self):
        self.config_command("Builder completed diagnostic discovery", identity="fixture-builder-session")
        self.assertEqual(execute(self.project, "fixture-owner", "builder")["status"], "SUCCEEDED")
        self.config_command(self.review_response(), identity="fixture-reviewer-session")
        self.assertEqual(execute(self.project, "fixture-owner", "reviewer")["status"], "SUCCEEDED")
        review = json.loads((self.root / self.project.load()["reviews"]["requirements"]["path"]).read_text())
        # Both envelopes name the same model, so the review is a separate session, not an independent agent.
        self.assertEqual(review["independence"], "same-model-separate-session")

    def test_reviewer_before_any_builder_compares_the_configured_builder_model(self):
        self.config_command(self.review_response())
        runtime = self.project.load()["runtime"]
        self.project.configure_runtime("fixture-owner", runtime={
            **runtime, "roles": {"builder": {"model": "diagnostic subprocess fixture, not live AI"}}})
        self.assertEqual(execute(self.project, "fixture-owner", "reviewer")["status"], "SUCCEEDED")
        review = json.loads((self.root / self.project.load()["reviews"]["requirements"]["path"]).read_text())
        self.assertEqual(review["independence"], "same-model-separate-session")

    def test_structured_review_records_the_snapshot_itself(self):
        self.config_command(self.review_response())
        first = execute(self.project, "fixture-owner", "reviewer")
        schema = json.loads(Path(first["receipt"]["artifacts"]["schema"]).read_text())
        # The model no longer copies the checkpoint or snapshot; the harness fills them.
        self.assertNotIn("checkpoint", schema["required"])
        self.assertNotIn("snapshot_digest", schema["required"])
        self.assertEqual(schema["properties"]["verdict"]["enum"], ["ACCEPT", "REJECT", "INCOMPLETE"])
        review = json.loads((self.root / self.project.load()["reviews"]["requirements"]["path"]).read_text())
        self.assertEqual(review["snapshot_digest"], value_digest(self.project.snapshot()))
        self.assertEqual(review["checkpoint"], "requirements")
        # A snapshot the answer echoes is not evidence of anything; the harness records its own.
        wrong = self.review_response()
        wrong["snapshot_digest"] = wrong["snapshot_digest"][:-1]
        self.config_command(wrong)
        second = execute(self.project, "fixture-owner", "reviewer")
        self.assertIn("ignored fields the harness records itself: checkpoint, snapshot_digest", second["notes"])
        review = json.loads((self.root / self.project.load()["reviews"]["requirements"]["path"]).read_text())
        self.assertEqual(review["snapshot_digest"], value_digest(self.project.snapshot()))

    def assert_reviewer_change_undone(self, result):
        self.assertEqual(result["status"], "REVIEW_NOT_IMPORTED")
        self.assertIn("you changed scoped artifacts (src/model.m)", result["reason"])
        self.assertEqual(result["restored_reviewer_changes"], ["src/model.m"])
        # The reviewed bytes are back for the next role; the reviewer's version is kept for inspection.
        self.assertEqual((self.root / "src/model.m").read_text(), "function y=model(x), y=x; end\n")
        kept = list(self.root.glob(".matlab-harness/packets/*/execution/reviewer-changes/src/model.m"))
        self.assertEqual(len(kept), 1)
        self.assertNotIn("reviewed-artifacts", {p.name for p in self.root.glob(".matlab-harness/packets/*/execution/*")})
        data = self.project.load()
        self.assertFalse(data["reviews"])
        self.assertEqual(data["decisions"][-1]["source"], "reviewer boundary")
        self.assertEqual([f["kind"] for f in data["review_protocol_failures"].values()], ["protocol"])

    def test_reviewer_artifact_edit_is_undone_and_not_imported(self):
        self.config_command(self.review_response())
        (self.root / "fixture-command.py").write_text(
            "from pathlib import Path\nPath('src/model.m').write_text('changed')\n"
            "print(Path('fixture-envelope.json').read_text())\n")
        self.assert_reviewer_change_undone(execute(self.project, "fixture-owner", "reviewer"))

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
        self.assert_reviewer_change_undone(execute(self.project, "fixture-owner", "reviewer"))

    def reviewer_does(self, code):
        self.config_command(self.review_response())
        (self.root / "fixture-command.py").write_text(
            "import glob,os\nfrom pathlib import Path\n" + code + "\nprint(Path('fixture-envelope.json').read_text())\n")
        return execute(self.project, "fixture-owner", "reviewer")

    def test_whatever_a_reviewer_leaves_in_place_of_a_file_is_undone(self):
        kept = "glob.glob('.matlab-harness/packets/*/execution/reviewed-artifacts/src/model.m')[0]"
        cases = [("os.remove('src/model.m'); os.mkdir('src/model.m'); Path('src/model.m/x.m').write_text('x')",
                  ["src/model.m", "src/model.m/x.m"]),
                 ("os.rename('src/model.m', 'src/Model.m')", ["src/Model.m", "src/model.m"]),
                 ("os.makedirs('src/probes/deep'); Path('src/probes/deep/x.m').write_text('x')",
                  ["src/probes", "src/probes/deep", "src/probes/deep/x.m"])]
        try:
            os.symlink(self.root / "AGENTS.md", self.root / "probe-link")
            cases.append(("os.remove('src/model.m'); os.symlink(os.path.abspath(" + kept + "), 'src/model.m')",
                          ["src/model.m"]))
        except OSError:
            pass  # this host cannot make links; the link case runs where it can
        if os.name == "nt":  # a junction needs no privilege, and points outside scope
            cases.append(("import _winapi; os.makedirs('elsewhere', exist_ok=True); Path('elsewhere/z.m').write_text('z'); "
                          "_winapi.CreateJunction(os.path.abspath('elsewhere'), 'src/sub')", ["src/sub"]))
        for code, changed in cases:
            result = self.reviewer_does(code)
            self.assertEqual((result["status"], result["restored_reviewer_changes"]), ("REVIEW_NOT_IMPORTED", changed), code)
            self.assertEqual([p.name for p in (self.root / "src").iterdir()], ["model.m"])
            self.assertFalse((self.root / "src/model.m").is_symlink())
            self.assertEqual((self.root / "src/model.m").read_text(), "function y=model(x), y=x; end\n")

    def test_a_reviewer_edit_to_the_requirements_is_undone_and_its_claims_bind(self):
        self.project.add_requirement("fixture-owner", "R-1", "Identity", "native oracle", "fixture user")
        reviewed = (self.root / "requirements.md").read_text()
        issue = {"id": "F-1", "severity": "MAJOR", "artifact": "src/model.m:1", "evidence": "model(2) returned 3",
                 "repair": "return x"}
        self.config_command({**self.review_response(), "verdict": "REJECT", "findings": [issue]})
        (self.root / "fixture-command.py").write_text(
            "from pathlib import Path\nPath('requirements.md').write_text('rewritten')\n"
            "print(Path('fixture-envelope.json').read_text())\n")
        result = execute(self.project, "fixture-owner", "reviewer")
        self.assertEqual((result["status"], result["restored_reviewer_changes"]), ("REVIEW_NOT_IMPORTED", ["requirements.md"]))
        self.assertEqual((self.root / "requirements.md").read_text(), reviewed)
        self.assertEqual([i["finding"]["id"] for i in self.project.pending_review_findings().values()], ["F-1"])

    def test_an_answer_inside_text_is_read(self):
        answer = {"verdict": "ACCEPT", "findings": [], "traceability": {}, "independent_checks": []}
        self.config_command("Here is my review:\n```json\n" + json.dumps(answer) + "\n```\nSee [1].")
        result = execute(self.project, "fixture-owner", "reviewer")
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertIn("requirements", self.project.load()["reviews"])

    def test_a_tree_the_harness_cannot_put_back_holds_every_dispatch(self):
        kept = "glob.glob('.matlab-harness/packets/*/execution/reviewed-artifacts/src/model.m')[0]"
        result = self.reviewer_does("Path('src/model.m').write_text('changed'); Path(" + kept + ").write_text('changed')")
        self.assertEqual(result["status"], "INPUT_REQUIRED")
        self.assertIn("could not put them back (the kept copy of src/model.m changed during review)", result["reason"])
        self.assertTrue(list(self.root.glob(".matlab-harness/packets/*/execution/reviewed-artifacts/src/model.m")))
        self.assertEqual(self.project.load()["decisions"][-1]["assertion"], "UNVERIFIED")
        self.assertIn("requires inspection", execute(self.project, "fixture-owner", "reviewer")["reason"])

    def test_a_reviewer_whose_model_is_unreported_still_binds(self):
        self.project.add_requirement("fixture-owner", "R-1", "Identity", "native oracle", "fixture user")
        issue = {"id": "F-1", "severity": "MAJOR", "artifact": "src/model.m:1", "evidence": "model(2) returned 3",
                 "repair": "return x"}
        self.config_command({**self.review_response(), "verdict": "REJECT", "findings": [issue]})
        envelope = json.loads((self.root / "fixture-envelope.json").read_text())
        envelope.pop("model")
        atomic_json(self.root / "fixture-envelope.json", envelope)
        result = execute(self.project, "fixture-owner", "reviewer")
        self.assertEqual((result["status"], result["retryable"]), ("REVIEW_NOT_IMPORTED", True))
        self.assertIn("the runtime did not report which model reviewed", result["reason"])
        self.assertEqual([i["finding"]["id"] for i in self.project.pending_review_findings().values()], ["F-1"])
        self.assertFalse(self.project.unfinished_review_imports())

    def test_serious_findings_of_a_reviewer_that_dropped_its_stream_still_bind(self):
        self.project.add_requirement("fixture-owner", "R-1", "Identity", "native oracle", "fixture user")
        issue = {"id": "F-1", "severity": "MAJOR", "kind": "PROVEN DEFECT", "artifact": "src/model.m:1",
                 "evidence": "probe.m: model(2) returned 3", "repair": "return x", "status": "OPEN"}
        self.config_command({**self.review_response(), "verdict": "REJECT", "findings": [issue]})
        envelope = json.loads((self.root / "fixture-envelope.json").read_text())
        atomic_json(self.root / "fixture-envelope.json", {**envelope, "status": "ERROR"})
        dropped = execute(self.project, "fixture-owner", "reviewer")
        self.assertEqual(dropped["status"], "FAILED")
        self.assertIn("bound_allegations_from", dropped)
        pending = list(self.project.pending_review_findings().values())
        self.assertEqual([item["finding"]["id"] for item in pending], ["F-1"])
        # The bound finding is one open item for the next reviewer, and it is not a protocol attempt.
        context = json.loads(Path(packet(self.project, "reviewer")["context"]).read_text())
        self.assertEqual([item["finding"]["id"] for item in context["open_items"].values()], ["F-1"])
        self.assertEqual([f["kind"] for f in self.project.load()["review_protocol_failures"].values()], ["unfinished"])
        # A fresh session that ACCEPTs without dispositioning the proven defect is refused.
        self.config_command(self.review_response())
        fresh = execute(self.project, "fixture-owner", "reviewer")
        self.assertEqual(fresh["status"], "REVIEW_NOT_IMPORTED")
        self.assertIn("ACCEPT needs every open item CLOSED", fresh["reason"])
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
