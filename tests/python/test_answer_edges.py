"""Edge cases of the answer channel: what proves a closure, hostile JSON, other shapes of the
same answer, and the handle namespace."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from matlab_harness import answer as channel
from matlab_harness.answer import open_items, translate
from matlab_harness.project import Project, ReviewProtocolError, atomic_json, digest, loads, value_digest
from matlab_harness.runtime import _json_in, _parse_output
from matlab_harness.workflow import packet, start, submit_answer

ISSUE = {"id": "F-1", "severity": "MAJOR", "kind": "PROVEN DEFECT", "artifact": "src/f.m:3",
         "evidence": "f(1,2) returned 2", "impact": "wrong sum", "repair": "use a + b",
         "closure": "f(1,2) == 3", "status": "OPEN"}
ROWS = {"R-1": {"status": "VERIFIED", "evidence": "read"}, "R-2": {"status": "VERIFIED", "evidence": "read"}}


class AnswerEdgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src/f.m").write_text("function y = f(a, b)\ny = a + b;\nend\n")
        start(self.root, "Sum", "fixture-builder", "owner", ["src"], "Return a+b", proof_mode="legacy-attested")
        self.project = Project(self.root)
        self.project.add_requirement("owner", "R-1", "Sum", "closed form", "brief")
        self.project.add_requirement("owner", "R-2", "Order", "closed form", "brief")
        self.scratch = self.root / ".matlab-harness/scratch/t"
        self.scratch.mkdir(parents=True)

    def seed(self, stage="requirements", issue=ISSUE):
        atomic_json(self.root / "seed.json", {
            "reviewer_session": "seed-reviewer", "model": "test record", "independence": "independent-agent",
            "checkpoint": "requirements", "verdict": "REJECT", "findings": [issue],
            "snapshot_digest": value_digest(self.project.snapshot())})
        self.project.review("owner", "requirements", "seed.json")
        data = self.project.load()
        if stage != "requirements":
            item = data["defects"].pop("requirements:" + issue["id"])
            data["defects"][stage + ":" + issue["id"]] = {**item, "checkpoint": stage}
        return data

    def translate(self, data, stage, **fields):
        reply = {"verdict": "ACCEPT", "findings": [], "independent_checks": [], "traceability": ROWS, **fields}
        return translate(self.project, data, stage, reply, self.scratch)

    def test_only_a_named_probe_or_a_passing_check_proves_a_closure(self):
        data = self.seed("implementation")
        (self.scratch / "p.m").write_text("assert(f(1,2) == 3)")
        (self.scratch / "q.m").write_text("assert(f(1,2) == 3)")
        (self.scratch / "fixed").write_text("a word, not a probe")
        checks = [{"id": "1", "command": "matlab -batch p", "observed": "3", "result": "PASS", "artifact": "p.m"},
                  {"id": "P", "command": "matlab -batch q", "observed": "2", "result": "FAIL", "artifact": "q.m"}]

        def closes(evidence, probe=None):
            reply = {"status": "CLOSED", "evidence": evidence, **({"probe": probe} if probe else {})}
            record, problems = self.translate(data, "implementation", independent_checks=checks,
                                              open_items={"F-1": reply})
            return not any("not closed: F-1" in p for p in problems)

        self.assertFalse(closes("f(1,2) == 3 on 1 try"))   # a bare number is not a check ID
        self.assertFalse(closes("P shows it"))             # a check that failed proves nothing
        self.assertFalse(closes("q.m: 3"))                 # nor does the probe only it ran
        self.assertFalse(closes("fixed"))                  # a file without a suffix is a word
        self.assertTrue(closes("p.m: f(1,2) == 3"))
        self.assertTrue(closes("f(1,2) == 3 now", probe="p.m"))

    def test_only_what_a_passing_check_ran_proves_a_closure(self):
        data = self.seed("implementation")
        for name in ("p.m", "f.m", "run.log", "q.m"):
            (self.scratch / name).write_text("x")
        checks = [{"id": "PR-1", "command": "matlab -batch p", "observed": "3", "result": "PASS", "artifact": "p.m"},
                  {"id": "LG-1", "command": "matlab -batch f", "observed": "2", "result": "FAIL", "artifact": "run.log"},
                  {"id": "a", "command": "matlab -batch q", "observed": "3", "result": "PASS", "artifact": "q.m"}]

        def closes(evidence):
            record, problems = self.translate(data, "implementation", independent_checks=checks,
                                              open_items={"F-1": {"status": "CLOSED", "evidence": evidence}})
            return not any("not closed: F-1" in p for p in problems)

        self.assertFalse(closes("src/f.m line 2 now reads y = a + b"))  # a copied source no check ran
        self.assertFalse(closes("fixed, see run.log"))                  # the log of a run that failed
        self.assertFalse(closes("uses a + b"))                          # a one-letter ID is a word
        self.assertTrue(closes("PR-1 shows f(1,2) == 3"))
        self.assertTrue(closes("see .matlab-harness/scratch/t/p.m:1"))
        self.assertTrue(closes("q.m passes"))                           # a passing check ran it, whatever its ID

    def test_a_question_is_not_the_value_it_asks_about(self):
        read = channel._read
        self.assertEqual([read(t, "verdict") for t in ("ACCEPT?", "Accept?!")], [None, None])
        self.assertEqual(read("Closed?", "answer", "NOT_CHECKED"), "NOT_CHECKED")
        self.assertEqual(read("PASS?", "result", "ERROR"), "ERROR")
        self.assertEqual(read("Verified?", "trace", "UNVERIFIED"), "UNVERIFIED")
        self.assertEqual(read("Resolved?", "status", "OPEN"), "OPEN")
        self.assertEqual(read("Closed \u2705", "answer", "NOT_CHECKED"), "CLOSED")

    def test_what_is_written_twice_reads_as_its_weakest_copy(self):
        good = {"verdict": "ACCEPT", "findings": [], "independent_checks": [], "traceability": ROWS}
        bad = {"verdict": "REJECT", "findings": [{**ISSUE, "id": "N-1", "severity": "CRITICAL"}]}
        for answer in ([good, bad], {"review": good, "final": bad}, _json_in(
                "Draft: " + json.dumps(good) + "\nFinal: " + json.dumps(bad))):
            record, problems = translate(self.project, self.project.load(), "requirements", answer, self.scratch)
            self.assertEqual((record["verdict"], [f["severity"] for f in record["findings"]]), ("REJECT", ["CRITICAL"]))
        # A quoted fragment that names no part does not stand in for the answer.
        record, problems = translate(self.project, self.project.load(), "requirements", _json_in(
            'Example: {"status": "CLOSED"}. My answer: ' + json.dumps(good)), self.scratch)
        self.assertEqual((record["verdict"], problems), ("ACCEPT", []))
        record, _ = self.translate(self.project.load(), "requirements",
                                   traceability=ROWS, trace={"R-1": {"status": "FAILED", "evidence": "p"}})
        self.assertEqual(record["traceability"][0]["status"], "FAILED")
        data = self.seed()
        for replies in ({"open_items": {"F-1": {"status": "CLOSED", "evidence": "x"}},
                         "items": {"F-1": {"status": "STILL_OPEN", "evidence": "x"}}},
                        {"open_items": {"F-1": {"status": "CLOSED", "result": "FAIL", "evidence": "x"}}}):
            record, problems = self.translate(data, "requirements", **replies)
            self.assertTrue(any("not closed: F-1" in p for p in problems), replies)

    def test_a_check_id_proves_only_when_it_is_no_word_and_no_claim(self):
        data = self.seed("implementation")
        (self.scratch / "p.m").write_text("x")
        (self.scratch / "q.m").write_text("a different failing probe")
        run = {"command": "matlab -batch p", "observed": "3", "artifact": "p.m"}
        checks = [{**run, "id": i, "result": "PASS"} for i in ("probe", "F-1", "src/f.m", "CHK-ORACLES", "C-2")]
        # Duplicate-ID failure vetoes that ID. It must not share the positive
        # control's file: any failure using p.m would veto p.m and CHK-ORACLES too.
        checks.append({**run, "id": "C-2", "result": "FAIL", "artifact": "q.m"})

        def closes(evidence):
            record, problems = self.translate(data, "implementation", independent_checks=checks,
                                              open_items={"F-1": {"status": "CLOSED", "evidence": evidence}})
            return not any("not closed: F-1" in p for p in problems)

        self.assertFalse(closes("no probe was run for this, looks fine"))
        self.assertFalse(closes("F-1 looks addressed by reading the diff"))
        self.assertFalse(closes("src/f.m line 2 now reads a + b"))
        self.assertFalse(closes("C-2 shows f(1,2) == 3"))        # another check with that ID failed
        self.assertTrue(closes("CHK-ORACLES shows f(1,2) == 3"))
        self.assertTrue(closes("**p.m** shows f(1,2) == 3"))
        self.assertTrue(closes("C-2/CHK-ORACLES"))

    def test_a_relative_artifact_names_the_project_file_first(self):
        data = self.seed("implementation")
        (self.scratch / "src").mkdir()
        (self.scratch / "src/f.m").write_text("copy of the builder's file")
        (self.scratch / "p.m").write_text("x")
        run = {"id": "CHK-1", "command": "matlab -batch t", "observed": "3", "result": "PASS"}
        record, problems = self.translate(data, "implementation", independent_checks=[{**run, "artifact": "src/f.m"}],
                                          open_items={"F-1": {"status": "CLOSED", "evidence": "CHK-1: src/f.m reads a + b"}})
        self.assertTrue(any("not closed: F-1" in p for p in problems))
        self.assertTrue(any("no independent check names an existing artifact" in p for p in problems))
        for artifact in ("scratch/p.m", "p.m (MATLAB probe)", "p.m, p.log"):
            record, problems = self.translate(data, "implementation", independent_checks=[{**run, "artifact": artifact}],
                                              open_items={"F-1": {"status": "CLOSED", "evidence": "CHK-1 shows 3"}})
            self.assertEqual(problems, [], artifact)

    def test_a_new_finding_is_closed_only_by_its_proof(self):
        (self.scratch / "p.m").write_text("x")
        check = {"id": "CHK-1", "command": "matlab -batch p", "observed": "3", "result": "PASS", "artifact": "p.m"}
        for closure, status in (("fixed, trust me", "OPEN"), ("p.m shows f(1,2) == 3", "CLOSED")):
            record, _ = self.translate(self.project.load(), "implementation", independent_checks=[check],
                                       findings=[{**ISSUE, "id": "N-1", "severity": "CRITICAL", "status": "CLOSED",
                                                  "closure": closure, "evidence": "f(1,2) was 2"}])
            self.assertEqual(record["findings"][0]["status"], status, closure)

    def test_an_answer_too_large_or_too_deep_is_refused_not_cut(self):
        record, problems = self.translate(self.project.load(), "requirements", verdict="REJECT",
                                          findings=["none"] * channel.BUDGET + ["CRITICAL: f(3,1) overflows"])
        self.assertIn("the answer is too large to read whole; report each finding and check once", problems)
        with self.assertRaises(ValueError):
            loads("[" * 50000)
        self.assertIsNone(_parse_output("[" * 50000, True)["response"])

    def test_an_entry_is_about_the_key_it_names_first(self):
        lines = ["R-1: FAILED, R-2 was not run", "see R-1 and R-2: VERIFIED", "R2: FAILED"]
        record, _ = self.translate(self.project.load(), "requirements", traceability=lines)
        self.assertEqual([r["status"] for r in record["traceability"]], ["FAILED", "FAILED"])
        self.assertTrue(any("ignored traceability entry 'see R-1 and R-2: VERIFIED'" in n for n in record["harness_notes"]))
        record, problems = self.translate(self.project.load(), "requirements",
                                          traceability=[{"R-1": ROWS["R-1"]}, {"R-2": ROWS["R-2"]}])
        self.assertEqual((problems, [r["status"] for r in record["traceability"]]), ([], ["VERIFIED", "VERIFIED"]))

    def test_a_severity_label_grades_a_text_finding(self):
        severity = channel._severity
        for text, expected in {"HIGH: x": "MAJOR", "[Low] x": "MINOR", "P1: crash": "MAJOR", "high priority": "MAJOR",
                               "Medium-High": "MAJOR", "error": "MAJOR", "**HIGH** x": "MAJOR",
                               "MINOR: comment typo near the major-axis code": "MINOR",
                               "MINOR (could be CRITICAL): x": "CRITICAL", "Issue: high memory use": None}.items():
            self.assertEqual(severity(text), expected, text)
        for nothing in ("None found", "There are no findings.", "No major issues."):
            record, problems = self.translate(self.project.load(), "requirements", findings=[nothing])
            self.assertEqual((record["findings"], problems), ([], []), nothing)
        record, _ = self.translate(self.project.load(), "requirements", verdict="REJECT",
                                   findings=["No bounds check: f(0) crashes"])
        self.assertEqual(len(record["findings"]), 1)

    def test_a_probe_path_is_judged_before_the_filesystem_is_touched(self):
        seen = []
        real = channel.os.path.isfile
        with mock.patch.object(channel.os.path, "isfile", side_effect=lambda p: seen.append(str(p)) or real(p)):
            for artifact in ("\\\\attacker\\share\\p.m", "//attacker/share/p.m", "../../../outside.m"):
                self.assertIsNone(channel._in_scratch(self.project, self.scratch, artifact))
        self.assertEqual(seen, [])

    def test_hostile_json_is_read_never_raised(self):
        deep = "x"
        for _ in range(900):
            deep = [deep]
        loose = {"id": "N-1", "severity": "MAJOR", "artifact": "src/f.m", "evidence": deep, "repair": "fix",
                 "score": float("nan"), "weight": float("inf")}
        check = {"id": "C-9", "command": "x", "observed": float("nan"), "result": "PASS", "artifact": "p.m",
                 "extra": float("-inf")}
        record, problems = self.translate(self.project.load(), "requirements", verdict="REJECT",
                                          findings=[loose], independent_checks=[check])
        json.dumps(record, allow_nan=False)  # the record carries no number a strict writer refuses
        self.assertEqual(problems, [])
        self.assertEqual(record["findings"][0]["evidence"], "x")
        self.assertNotIn("score", record["findings"][0])
        self.assertEqual(record["independent_checks"][0]["observed"], "nan")

    def test_other_shapes_of_the_same_answer_are_read(self):
        finding = {"severity": "Major (proven)", "location": "src/f.m:2", "description": "f(1,2) is 2",
                   "fix": "add"}
        cases = [
            {"review": {"verdict": "Reject.", "issues": [finding], "traceability": ROWS}},
            {"verdict": "REJECT - see findings", "findings": {"N-1": finding}, "traceability": ROWS},
            {"verdict": "rejected", "defects": [finding], "trace": ["R-1: VERIFIED by p.m", "R-2 failed"]},
        ]
        for answer in cases:
            record, problems = translate(self.project, self.project.load(), "requirements", answer, self.scratch)
            self.assertEqual((record["verdict"], problems), ("REJECT", []), answer)
            found, = record["findings"]
            self.assertEqual((found["severity"], found["artifact"], found["evidence"], found["repair"]),
                             ("MAJOR", "src/f.m:2", "f(1,2) is 2", "add"))
        self.assertEqual(record["findings"][0]["id"], "F")
        # A line that says more than VERIFIED is not a VERIFIED row; it is noted, and its words are evidence.
        self.assertEqual([(r["status"], r["evidence"]) for r in record["traceability"]],
                         [("UNVERIFIED", "R-1: VERIFIED by p.m"), ("FAILED", "not stated by reviewer")])
        self.assertIn("R-1: read as UNVERIFIED; VERIFIED counts only written alone, as in {\"R-1\": {\"status\": \"VERIFIED\", \"evidence\": \"...\"}}", record["harness_notes"])
        self.assertIn("read defects as findings", record["harness_notes"])
        record, _ = translate(self.project, self.project.load(), "requirements",
                              {"verdict": "major.", "findings": [], "concerns": "x"}, self.scratch)
        self.assertIn("ignored fields the harness does not read: concerns", record["harness_notes"])

    def test_a_finding_is_read_wherever_and_however_it_is_written(self):
        claim = "f(3,1) overflows"
        for text, severity in {"F-1 (MAJOR): " + claim: "MAJOR", "**MAJOR**: " + claim: "MAJOR",
                               "Severity: MAJOR - " + claim: "MAJOR", "[CRITICAL] " + claim: "CRITICAL",
                               "MINOR (could be CRITICAL): " + claim: "CRITICAL"}.items():
            record, problems = self.translate(self.project.load(), "requirements", verdict="REJECT", findings=[text])
            self.assertEqual((problems, [(f["severity"], f["evidence"]) for f in record["findings"]]),
                             ([], [(severity, text)]), text)
        finding = {"id": "N-1", "severity": "MAJOR", "artifact": "src/f.m:2", "evidence": claim, "repair": "add"}
        unnamed = {k: v for k, v in finding.items() if k not in ("id", "severity")}
        shapes = [{"verdict": "REJECT", "findings": "MAJOR: " + claim},
                  [{"verdict": "REJECT", "findings": [finding]}],
            {"review": {"verdict": "REJECT", "findings": [finding]}, "model": "fixture-model"},
                  {"verdict": "REJECT", "findings": {"MAJOR": [unnamed]}},
                  {"verdict": "REJECT", "findings": {"N-1": "MAJOR: " + claim}},
                  {"verdict": "REJECT", "findings": [{"finding": finding}]},
                  {"verdict": "REJECT", "findings": [{**unnamed, "priority": "high"}]}]
        for answer in shapes:
            record, problems = translate(self.project, self.project.load(), "requirements", answer, self.scratch)
            found, = record["findings"]
            self.assertEqual((record["verdict"], problems, found["severity"]), ("REJECT", [], "MAJOR"), answer)
            self.assertIn(claim, found["evidence"], answer)
        # Text that names no severity is kept as MAJOR and refused; text that says there is nothing is nothing.
        record, problems = self.translate(self.project.load(), "requirements", verdict="REJECT", findings=[claim])
        self.assertEqual([(f["severity"], f["evidence"]) for f in record["findings"]], [("MAJOR", claim)])
        self.assertIn("needs severity", problems[0])
        record, problems = self.translate(self.project.load(), "requirements", findings="None.")
        self.assertEqual((record["findings"], problems), ([], []))

    def test_text_that_says_more_never_reads_as_the_strong_value(self):
        read = channel._read
        for text in ("ACCEPT (if F-2 is fixed)", "Accept, pending the tolerance fix", "pass (with reservations)"):
            self.assertIsNone(read(text, "verdict"), text)
        for text in ("ACCEPT/REJECT", "ACCEPT? no - REJECT", "REJECT - see findings"):
            self.assertEqual(read(text, "verdict"), "REJECT", text)
        for text in ("accept", "**ACCEPT**", "Accept.", "approved"):
            self.assertEqual(read(text, "verdict"), "ACCEPT", text)
        for text in ("Fixed (partially)", "closed? not sure", "Resolved - pending rerun"):
            self.assertEqual(read(text, "answer", "NOT_CHECKED"), "NOT_CHECKED", text)
        self.assertEqual(read("still open: overflows", "answer"), "STILL_OPEN")
        self.assertEqual(read("VERIFIED (not yet run)", "trace", "UNVERIFIED"), "UNVERIFIED")
        self.assertEqual(read("PASS (partially)", "trace", "UNVERIFIED"), "PARTIAL")
        for text in ("Fixed? no", "resolved (not really)"):
            self.assertEqual(read(text, "status", "OPEN"), "OPEN", text)
        self.assertEqual(read("PASS (3 == 3)", "result", "ERROR"), "ERROR")
        self.assertEqual((channel._severity("Minor/Major"), channel._severity("low"), channel._severity("a low-level bug")),
                         ("MAJOR", "MINOR", None))
        # One reader: a row's status and a line of text with the same words read the same.
        for trace in ({"R-1": {"status": "VERIFIED (FAILED for b<a)", "evidence": "p"}, **{"R-2": ROWS["R-2"]}},
                      ["R-1 VERIFIED (FAILED for b<a)", "R-2: VERIFIED"]):
            record, problems = self.translate(self.project.load(), "requirements", traceability=trace)
            self.assertEqual(record["traceability"][0]["status"], "FAILED", trace)
            self.assertIn("ACCEPT is inconsistent with FAILED requirement R-1", problems)
        data = self.seed()
        record, problems = self.translate(data, "requirements", verdict="ACCEPT (if F-2 is fixed)",
                                          open_items={"F-1": {"status": "Fixed (partially)", "evidence": "x"}})
        self.assertIn("verdict must be ACCEPT, REJECT or INCOMPLETE written alone, not 'ACCEPT (if F-2 is fixed)'", problems)
        self.assertIn("F-1: read as NOT_CHECKED; CLOSED counts only written alone, as in {\"F-1\": {\"status\": \"CLOSED\", \"evidence\": \"...\"}}", record["harness_notes"])

    def test_ids_never_differ_by_case_alone(self):
        data = self.seed()
        record, _ = self.translate(data, "requirements", verdict="REJECT",
                                   findings=[{**ISSUE, "id": "f-1", "evidence": "f(3,1) overflows"}])
        self.assertEqual([f["id"] for f in record["findings"]], ["f-1-r2"])
        # Open items may be answered as lines; a line is a closure only when its status is written alone.
        record, problems = self.translate(data, "requirements", verdict="REJECT", open_items=["F-1: still open, f(1,2) is 2"],
                                          findings=[{"priority": "low", "artifact": "README.md", "evidence": "typo",
                                                     "repair": "fix"}])
        self.assertEqual(problems, [])
        self.assertEqual([(f["id"], f["severity"], f["status"]) for f in record["findings"]],
                         [("F-1", "MAJOR", "OPEN"), ("F", "MINOR", "OPEN")])
        record, _ = self.translate(data, "requirements", open_items=["F-1: CLOSED, p.m shows 3"])
        self.assertIn("F-1: read as NOT_CHECKED; CLOSED counts only written alone, as in {\"F-1\": {\"status\": \"CLOSED\", \"evidence\": \"...\"}}", record["harness_notes"])

    def test_a_bare_list_of_serious_findings_binds(self):
        packet(self.project, "reviewer")
        claim = {"id": "N-1", "severity": "MAJOR", "artifact": "src/f.m:2", "evidence": "f(1,2) is 2", "repair": "add"}
        with self.assertRaisesRegex(ReviewProtocolError, "verdict must be .*now open items A-[0-9a-f]{8}"):
            submit_answer(self.project, "owner", [claim], "host-1", "small-model")
        self.assertEqual([i["finding"]["id"] for i in self.project.pending_review_findings().values()], ["N-1"])

    def test_no_finding_takes_the_shape_of_a_handle(self):
        packet(self.project, "reviewer")
        record, _ = self.translate(self.project.load(), "requirements", verdict="REJECT", findings=[
            {"id": "A-3f09c2d1", "severity": "MINOR", "artifact": "src/f.m", "evidence": "style", "repair": "x"}])
        self.assertEqual(record["findings"][0]["id"], "A-3f09c2d1-r2")
        # A record from before handles were reserved can still collide; the handle grows instead of raising.
        claim = {"id": "N-1", "severity": "MAJOR", "artifact": "src/f.m:2", "evidence": "f(1,2) is 2", "repair": "add"}
        handle = "A-" + channel.claim_digest(channel.normalize_finding(claim)[0])[:8]
        self.seed(issue={**ISSUE, "id": handle})
        packet(self.project, "reviewer")
        with self.assertRaises(ReviewProtocolError):
            submit_answer(self.project, "owner", {"verdict": "MAYBE", "findings": [claim]}, "host-1", "small-model")
        items = open_items(self.project, self.project.load(), "requirements")
        self.assertEqual(sorted(len(h) for h in items), [len(handle), len(handle) + 8])

    def test_a_reject_needs_an_open_serious_finding_or_a_failed_requirement(self):
        moderate = {**ISSUE, "id": "N-1", "severity": "MODERATE"}

        def refused(data, stage="requirements", **fields):
            record, problems = self.translate(data, stage, verdict="REJECT", **fields)
            return [p for p in problems if p.startswith("REJECT needs a blocking reason")]

        data = self.project.load()
        self.assertIn("(open: N-1 (MODERATE))", refused(data, findings=[moderate])[0])
        self.assertIn("answer ACCEPT and keep them open", refused(data)[0])
        self.assertEqual(refused(data, findings=[moderate, ISSUE]), [])
        self.assertEqual(refused(data, findings=[moderate], traceability={
            "R-1": {"status": "FAILED", "evidence": "f(1,2) returned 2"}, "R-2": ROWS["R-2"]}), [])
        # A blocking item the report leaves open is its reason; one it closes is not.
        data = self.seed()
        self.assertEqual(refused(data, findings=[moderate]), [])
        self.assertTrue(refused(data, findings=[moderate],
                                open_items={"F-1": {"status": "CLOSED", "evidence": "f.m line 2 reads y = a + b"}}))

    def test_a_reject_may_rest_on_what_the_gate_refuses_whatever_the_review_says(self):
        moderate = {**ISSUE, "id": "N-1", "severity": "MODERATE"}

        def refused(data, stage):
            record, problems = self.translate(data, stage, verdict="REJECT", findings=[moderate])
            return any(p.startswith("REJECT needs a blocking reason") for p in problems)

        self.assertTrue(refused(self.project.load(), "architecture"))
        data = self.project.load()
        data["required_checks"]["implementation"] = ["native"]
        self.assertFalse(refused(data, "implementation"))  # a declared check that has not passed
        with mock.patch.object(Project, "handoff_obligations", return_value=["no document cites R-2"]):
            self.assertFalse(refused(self.project.load(), "handoff"))
        with mock.patch.object(Project, "handoff_obligations", return_value=[]):
            self.assertTrue(refused(self.project.load(), "handoff"))
        with mock.patch("matlab_harness.semantics.problems", return_value=["adequacy did not pass"]):
            self.assertFalse(refused(self.project.load(), "verification"))
        earlier = {"k": {"checkpoint": "requirements"}}
        with mock.patch.object(Project, "pending_review_findings", return_value=earlier):
            self.assertFalse(refused(self.project.load(), "architecture"))  # an earlier serious allegation
        self.assertFalse(refused(self.seed(), "architecture"))  # an earlier checkpoint's blocking finding

    def test_a_reject_at_an_executed_checkpoint_needs_a_reason_when_its_checks_pass(self):
        moderate = {**ISSUE, "id": "N-1", "severity": "MODERATE"}
        data = self.project.load()
        command = [sys.executable, "-c", "pass"]
        data["required_checks"]["implementation"] = ["native"]
        data.setdefault("commands", {})["native"] = command
        record = self.root / ".matlab-harness/evidence-native.json"

        def refused(**change):
            atomic_json(record, {"status": "PASSED", "exit_code": 0, "command": command,
                                 "snapshot": self.project.snapshot(data), **change})
            data["evidence"] = {"native": {"path": record.relative_to(self.root).as_posix(), "sha256": digest(record)}}
            reply = {"verdict": "REJECT", "findings": [moderate], "traceability": ROWS}
            return any(p.startswith("REJECT needs a blocking reason")
                       for p in translate(self.project, data, "implementation", reply, self.scratch)[1])

        self.assertTrue(refused())
        self.assertFalse(refused(snapshot={}))                 # a stale check
        self.assertFalse(refused(status="FAILED", exit_code=1))
        self.assertFalse(refused(command=["other"]))           # not the approved command
        refused()
        record.write_text("{}")                                # a changed record
        self.assertFalse(any(p.startswith("REJECT needs a blocking reason") for p in translate(
            self.project, data, "implementation", {"verdict": "REJECT", "findings": [moderate],
                                                   "traceability": ROWS}, self.scratch)[1]))

    def test_a_refused_reject_binds_nothing_and_changes_no_record(self):
        packet(self.project, "reviewer")
        before = self.project.load().get("defects", {})
        reply = {"verdict": "REJECT", "traceability": ROWS, "findings": [{**ISSUE, "severity": "MINOR"}]}
        with self.assertRaisesRegex(ReviewProtocolError, "REJECT needs a blocking reason"):
            submit_answer(self.project, "owner", reply, "independent-1", "test-model")
        self.assertEqual(self.project.load().get("defects", {}), before)
        self.assertNotIn("requirements", self.project.load()["reviews"])
        self.assertEqual(self.project.pending_review_findings(), {})


if __name__ == "__main__":
    unittest.main()
