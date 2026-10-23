"""Protocol help for small models: reviewer answers by handle, host import, compressed
MATLAB output, harness-run mutation, skill cards, context budget and MCP."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from matlab_harness.answer import translate
from matlab_harness.compact import matlab_digest
from matlab_harness.mcp_server import Server, serve
from matlab_harness.mutation import candidates, choose, mutation_summary, run_mutation
from matlab_harness.project import Project, ProjectError, ReviewProtocolError, atomic_json, value_digest
from matlab_harness.skills import cards_for
from matlab_harness.workflow import estimate_tokens, packet, start, submit_answer

SOURCE = "function y = f(a, b)\nif a <= b\n    y = a + b; % a + b is the contract\nelse\n    y = max(a, b);\nend\nend\n"
# Fake test check: passes only while the sum on line 3 is intact.
CHECK = "import sys; sys.exit(0 if 'a + b;' in open('src/f.m').read() else 1)"


class SmallModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src/f.m").write_text(SOURCE)
        start(self.root, "Sum or max", "fixture-builder", "owner", ["src"], "Return a+b when a<=b", proof_mode="legacy-attested")
        self.project = Project(self.root)
        self.project.add_requirement("owner", "R-1", "Sum branch", "closed form", "brief")
        self.project.add_requirement("owner", "R-2", "Max branch", "closed form", "brief")

    def seed_blocking(self):
        issue = {"id": "F-1", "severity": "MAJOR", "kind": "PROVEN DEFECT", "artifact": "src/f.m:3",
                 "evidence": "f(1,2) returned 2", "impact": "wrong sum", "repair": "use a + b",
                 "closure": "f(1,2) == 3", "status": "OPEN"}
        atomic_json(self.root / "seed.json", {
            "reviewer_session": "seed-reviewer", "model": "test record", "independence": "independent-agent",
            "checkpoint": "requirements", "verdict": "REJECT", "findings": [issue],
            "snapshot_digest": value_digest(self.project.snapshot())})
        self.project.review("owner", "requirements", "seed.json")
        return issue

    def answer(self, packet_id=None, session="host-1", **fields):
        reply = {"verdict": "ACCEPT", "findings": [], "independent_checks": [],
                 "traceability": {"R-1": {"status": "VERIFIED", "evidence": "read"},
                                  "R-2": {"status": "VERIFIED", "evidence": "read"}}, **fields}
        return submit_answer(self.project, "owner", reply, session, "small-model", packet_id)

    # Reviewer answers by handle
    def test_an_answer_closes_a_prior_finding_by_its_handle_only(self):
        issue = self.seed_blocking()
        made = packet(self.project, "reviewer")
        prompt = Path(made["prompt"]).read_text()
        self.assertIn('"F-1"', prompt)
        self.assertIn('"blocks_acceptance": true', prompt)
        schema = json.loads(Path(made["answer_schema"]).read_text())
        self.assertEqual(schema["properties"]["open_items"]["required"], ["F-1"])
        self.assertEqual(schema["properties"]["traceability"]["required"], ["R-1", "R-2"])
        # A new finding that reuses the ID is a new finding: it gets its own ID and cannot touch F-1.
        typo = {"id": "F-1", "severity": "minor", "artifact": "README.md", "evidence": "typo in heading",
                "repair": "fix it", "status": "closed", "prior_finding_digest": "typed by the model", "answers": "F-1"}
        result = self.answer(verdict="accept", findings=[typo],
                             open_items={"F-1": {"status": "closed", "evidence": "probe.m: f(1,2) == 3"}})
        stored = json.loads((self.root / result["imported"]).read_text())
        prior, new = stored["findings"]
        self.assertEqual(stored["verdict"], "ACCEPT")
        self.assertEqual((prior["id"], prior["artifact"], prior["status"]), ("F-1", issue["artifact"], "CLOSED"))
        self.assertEqual(prior["prior_finding_digest"], value_digest(issue))
        self.assertEqual((prior["evidence"], prior["closure"]), ("probe.m: f(1,2) == 3",) * 2)
        self.assertEqual((new["id"], new["severity"], new["kind"]), ("F-1-r2", "MINOR", "POTENTIAL DEFECT"))
        self.assertNotIn("answers", new)
        self.assertNotIn("prior_finding_digest", new)
        defects = self.project.load()["defects"]
        self.assertFalse(defects["requirements:F-1"]["blocking"])
        self.assertEqual(defects["requirements:F-1"]["origin"], issue)
        self.assertFalse([p for p in self.project.gate("requirements")["problems"] if "blocking" in p])

    def test_accept_needs_every_blocking_item_closed(self):
        self.seed_blocking()
        made = packet(self.project, "reviewer")["prompt"]
        for items in ({}, {"F-1": {"status": "NOT_CHECKED", "evidence": "no time"}},
                      {"F-1": {"status": "CLOSED", "evidence": ""}}):
            with self.assertRaisesRegex(ReviewProtocolError, "not closed: F-1"):
                self.answer(open_items=items)
        self.assertEqual(len(self.project.load()["review_protocol_failures"]), 3)
        # Each refused answer keeps its own file, so none can change a pinned allegation source.
        self.assertEqual(len(list(Path(made).parent.glob("answer-[0-9a-f]*.json"))), 3)
        self.answer(verdict="REJECT", open_items={"F-1": {"status": "STILL_OPEN", "evidence": "f(1,2) is still 2"}})
        self.assertTrue(self.project.load()["defects"]["requirements:F-1"]["blocking"])
        self.assertIn("Unresolved blocking finding: F-1", self.project.gate("requirements")["problems"])

    def test_traceability_is_read_as_the_weakest_claim(self):
        packet(self.project, "reviewer")
        # ACCEPT needs a supported row for every requirement.
        with self.assertRaisesRegex(ReviewProtocolError, "missing: R-2"):
            self.answer(traceability={"R-1": {"status": "VERIFIED", "evidence": "read"},
                                      "R-9": {"status": "VERIFIED", "evidence": "not a requirement"}})
        with self.assertRaisesRegex(ReviewProtocolError, "missing: R-1, R-2"):
            self.answer(traceability={"R-1": "VERIFIED", "R-2": "VERIFIED"})
        twice = [{"requirement": "R-1", "status": "VERIFIED", "evidence": "a"},
                 {"requirement": "r-1", "status": "fail", "evidence": "b"},
                 {"requirement": "R-2", "status": "PASS", "evidence": "c"}]
        with self.assertRaisesRegex(ReviewProtocolError, "FAILED requirement R-1"):
            self.answer(traceability=twice)
        # The same rows under REJECT are an honest answer: merged to the weaker status, never refused.
        result = self.answer(verdict="rejected", traceability=twice[:2])
        stored = json.loads((self.root / result["imported"]).read_text())
        self.assertEqual(stored["verdict"], "REJECT")
        self.assertEqual([(r["requirement"], r["status"], r["evidence"]) for r in stored["traceability"]],
                         [("R-1", "FAILED", "a; b"), ("R-2", "UNVERIFIED", "not assessed by reviewer")])
        self.assertIn("R-1: 2 rows merged, keeping the weakest status", result["notes"])

    def test_a_loose_finding_is_normalized_not_refused(self):
        packet(self.project, "reviewer")
        loose = {"id": "", "severity": "High", "artifact": ["src/f.m:5", "src/f.m:6"], "evidence": "f(3,1) is 1"}
        result = self.answer(verdict="REJECT", findings=[loose, dict(loose)],
                             independent_checks=[{"command": "f(3,1)", "observed": "1", "result": "failed"}])
        stored = json.loads((self.root / result["imported"]).read_text())
        finding, = stored["findings"]
        self.assertEqual((finding["id"], finding["severity"], finding["kind"], finding["status"]),
                         ("F", "MAJOR", "POTENTIAL DEFECT", "OPEN"))
        self.assertEqual((finding["artifact"], finding["repair"]), ("src/f.m:5, src/f.m:6", "not stated by reviewer"))
        self.assertEqual((stored["independent_checks"][0]["id"], stored["independent_checks"][0]["result"]), ("C-1", "FAIL"))
        self.assertTrue(self.project.load()["defects"]["requirements:F"]["blocking"])

    def test_what_the_harness_cannot_read_is_refused_but_serious_claims_bind(self):
        packet(self.project, "reviewer")
        claim = {"id": "N-1", "severity": "urgent", "artifact": "src/f.m:5", "evidence": "f(3,1) is 1", "repair": "max"}
        with self.assertRaisesRegex(ReviewProtocolError, "N-1 needs severity .* not urgent.*now open items A-[0-9a-f]{8}"):
            self.answer(verdict="REJECT", findings=[claim])
        with self.assertRaisesRegex(ReviewProtocolError, "verdict must be ACCEPT, REJECT or INCOMPLETE, not nothing"):
            self.answer(verdict="", findings=[{**claim, "id": "N-2", "severity": "CRITICAL", "evidence": "f(2,1) is 1"}])
        pending = sorted((i["finding"]["id"], i["finding"]["severity"]) for i in self.project.pending_review_findings().values())
        self.assertEqual(pending, [("N-1", "MAJOR"), ("N-2", "CRITICAL")])

    def test_serious_allegations_become_one_open_item_with_their_probes(self):
        claim = {"id": "N-1", "severity": "MAJOR", "artifact": "src/f.m:5", "evidence": "probe_max.m: f(3,1) is 1",
                 "repair": "use max"}
        for name in ("probe_a.m", "probe_b.m"):
            made = packet(self.project, "reviewer")
            (Path(made["scratch"]) / name).write_text("assert(f(3,1) == 3)")
            with self.assertRaisesRegex(ReviewProtocolError, "verdict must be"):
                self.answer(verdict="MAYBE", findings=[claim])
        # The second attempt made the same claim again: one allegation, with both attempts' probes.
        self.assertEqual(len(self.project.pending_review_findings()), 1)
        made = packet(self.project, "reviewer")
        context = json.loads(Path(made["context"]).read_text())
        (handle, item), = context["open_items"].items()
        self.assertRegex(handle, "^A-[0-9a-f]{8}$")
        self.assertEqual(sorted(Path(p).name for p in item["probes"]), ["probe_a.m", "probe_b.m"])
        self.assertIn(handle, Path(made["prompt"]).read_text())
        with self.assertRaisesRegex(ReviewProtocolError, "not closed: " + handle):
            self.answer()
        # Handles are matched without regard to case; an unknown handle is noted, not refused.
        result = self.answer(open_items={handle.lower(): {"status": "fixed", "evidence": "probe_a.m: f(3,1) == 3 now"},
                                         "A-00000000": {"status": "CLOSED", "evidence": "x"}})
        self.assertIn(f"ignored open_items entry 'A-00000000', which names no single one of {handle}", result["notes"])
        self.assertFalse(self.project.pending_review_findings())
        self.assertTrue(self.project.gate("requirements")["problems"])  # approval is still missing, nothing else

    def test_a_still_open_allegation_is_tracked_as_the_reviewers_finding(self):
        claim = {"id": "F-1", "severity": "MAJOR", "artifact": "src/f.m:5", "evidence": "f(3,1) is 1", "repair": "use max"}
        self.seed_blocking()  # F-1 is taken by a different, recorded finding
        packet(self.project, "reviewer")
        with self.assertRaises(ReviewProtocolError):
            self.answer(verdict="MAYBE", findings=[claim])
        packet(self.project, "reviewer")
        handle = next(h for h in json.loads(Path(packet(self.project, "reviewer")["context"]).read_text())["open_items"]
                      if h.startswith("A-"))
        result = self.answer(verdict="REJECT", open_items={handle: {"status": "STILL_OPEN", "evidence": "f(3,1) is still 1"}})
        stored = json.loads((self.root / result["imported"]).read_text())
        tracked = next(f for f in stored["findings"] if f.get("answers") == handle)
        self.assertNotEqual(tracked["id"], "F-1")
        self.assertEqual(stored["protocol_dispositions"][0]["finding_id"], tracked["id"])
        self.assertFalse(self.project.pending_review_findings())
        self.assertTrue(self.project.load()["defects"]["requirements:" + tracked["id"]]["blocking"])
        # A restated item does not bind again when a later answer is refused.
        packet(self.project, "reviewer")
        with self.assertRaises(ReviewProtocolError):
            self.answer(verdict="MAYBE", open_items={tracked["id"]: {"status": "STILL_OPEN", "evidence": "still 1"}})
        self.assertFalse(self.project.pending_review_findings())

    def test_making_an_open_claim_again_keeps_it_open_once(self):
        claim = {"id": "N-1", "severity": "MAJOR", "artifact": "src/f.m:5", "evidence": "f(3,1) is 1", "repair": "use max"}
        packet(self.project, "reviewer")
        with self.assertRaises(ReviewProtocolError):
            self.answer(verdict="MAYBE", findings=[claim])
        packet(self.project, "reviewer")
        # The fresh reviewer does not answer the handle; it reports the same claim, citing its own ID.
        result = self.answer(verdict="REJECT", findings=[claim],
                             traceability={"R-2": {"status": "FAILED", "evidence": "f(3,1)", "finding_ids": "N-1"}})
        stored = json.loads((self.root / result["imported"]).read_text())
        finding, = stored["findings"]
        self.assertEqual(stored["protocol_dispositions"][0]["status"], "TRACKED")
        self.assertEqual(stored["traceability"][1]["finding_ids"], finding["id"])
        self.assertFalse(self.project.pending_review_findings())

    def test_a_closure_at_an_executed_checkpoint_names_its_probe(self):
        self.seed_blocking()
        data = self.project.load()
        item = data["defects"].pop("requirements:F-1")
        data["defects"]["implementation:F-1"] = {**item, "checkpoint": "implementation"}
        scratch = self.root / ".matlab-harness/scratch/t"
        scratch.mkdir(parents=True)
        (scratch / "probe_sum.m").write_text("assert(f(1,2) == 3)")
        check = {"id": "IC-7", "command": "matlab -batch probe_sum", "observed": "3", "result": "PASS",
                 "artifact": "probe_sum.m"}

        def close(evidence):
            reply = {"verdict": "ACCEPT", "findings": [], "independent_checks": [check],
                     "traceability": {"R-1": {"status": "VERIFIED", "evidence": "IC-7"},
                                      "R-2": {"status": "VERIFIED", "evidence": "IC-7"}},
                     "open_items": {"F-1": {"status": "CLOSED", "evidence": evidence}}}
            return translate(self.project, data, "implementation", reply, scratch)

        for unproved in ("f(1,2) == 3 now", "probe_sum.mat: 3", "see xprobe_sum.m"):
            record, problems = close(unproved)
            self.assertEqual(record["findings"], [])
            self.assertIn("not closed: F-1", " ".join(problems))
            self.assertIn("F-1: CLOSED reads as NOT_CHECKED", " ".join(record["harness_notes"]))
        for proved in ("probe_sum.m: f(1,2) == 3", "IC-7 returned 3", ".matlab-harness/scratch/t/probe_sum.m ok"):
            record, problems = close(proved)
            self.assertEqual((record["findings"][0]["status"], problems), ("CLOSED", []))

    def test_independence_is_attested_by_the_channel(self):
        packet(self.project, "reviewer")
        stored = json.loads((self.root / self.answer(independence="independent-agent")["imported"]).read_text())
        self.assertEqual(stored["independence"], "host-reported")
        packet(self.project, "reviewer")
        lowered = self.answer(session="host-2", independence="sequential-role-pass")
        self.assertEqual(json.loads((self.root / lowered["imported"]).read_text())["independence"], "sequential-role-pass")
        self.assertIn("Sequential self-review does not satisfy independent acceptance", lowered["gate"]["problems"])
        # A complete record attested by the operator keeps its own level.
        atomic_json(self.root / "human.json", {"reviewer_session": "jane", "model": "human", "independence": "external-human",
                                               "checkpoint": "requirements", "verdict": "ACCEPT", "findings": [],
                                               "snapshot_digest": value_digest(self.project.snapshot())})
        self.project.review("owner", "requirements", "human.json")
        self.assertNotIn("Independent reviewer checkpoint missing", self.project.gate("requirements")["problems"])

    def test_an_answer_needs_a_current_reviewer_packet(self):
        with self.assertRaisesRegex(ProjectError, "No reviewer packet"):
            self.answer()
        with self.assertRaisesRegex(ProjectError, "Unknown packet"):
            self.answer(packet_id="../../etc")
        made = packet(self.project, "reviewer")
        # The packet names the checkpoint; an answer that echoes another is noted, not believed.
        echoed = self.answer(checkpoint="architecture", session="host-0")
        self.assertIn("ignored fields the harness records itself: checkpoint", echoed["notes"])
        self.assertEqual(json.loads((self.root / echoed["imported"]).read_text())["checkpoint"], "requirements")
        with self.assertRaisesRegex(ProjectError, "Reviewer session and model"):
            submit_answer(self.project, "owner", {}, "", "small-model")
        with self.assertRaisesRegex(ProjectError, "contributing"):
            self.answer(session="fixture-builder")
        (self.root / "src/f.m").write_text(SOURCE + "% changed after the packet\n")
        with self.assertRaisesRegex(ProjectError, "new reviewer packet"):
            self.answer(packet_id=Path(made["prompt"]).parent.name)
        self.assertFalse(self.project.load().get("review_protocol_failures"))

    # Compressed MATLAB output
    def test_matlab_digest_keeps_the_error_and_drops_the_noise(self):
        stdout = "Running cellTest\n" + ".\n" * 40 + "Done cellTest\n" + "-" * 40 + "\n"
        stderr = ("Error using simulateCellET>checkInputs (line 12)\nInvalid input.\n"
                  "Error in simulateCellET (line 3)\n")
        digest = matlab_digest(stdout, stderr)
        self.assertIn("Error using simulateCellET>checkInputs (line 12) | Invalid input.", digest)
        self.assertNotIn("Running", digest)
        self.assertLessEqual(len(matlab_digest("x" * 5000)), 400)

    # Harness-run mutation
    def test_mutation_sites_skip_comments_and_strings_and_spread_operators(self):
        (self.root / "src/g.m").write_text("msg = 'a <= b'; % x - y\nz = p - q;\n")
        sites = candidates(self.root, ["src/g.m"])
        self.assertEqual([(s["line"], s["operator"]) for s in sites], [(2, "- to +")])
        picked = choose(candidates(self.root, ["src/f.m"]), 2, "seed")
        self.assertEqual(len({s["operator"] for s in picked}), 2)
        self.assertEqual(picked, choose(candidates(self.root, ["src/f.m"]), 2, "seed"))

    def test_mutation_records_killed_and_surviving_defects(self):
        self.project.configure_checks("owner", "implementation", {"unit": [sys.executable, "-c", CHECK]})
        self.project.configure_runtime("owner", runtime={"adapter": "manual", "mutation": {"check": "unit", "count": 10}})
        result = run_mutation(self.project, "owner", "implementation", 60)
        self.assertEqual((result["status"], result["baseline"]), ("COMPLETED", "PASSED"))
        outcome = {m["operator"]: m["result"] for m in result["mutants"]}
        self.assertEqual(outcome, {"+ to -": "KILLED", "<= to <": "SURVIVED", "max to min": "SURVIVED"})
        record = self.project.load()["mutation_results"]["implementation"]
        summary = mutation_summary(record)
        self.assertIn("caught 1 of 3", summary["status"])
        self.assertEqual(len(summary["survivors"]), 2)
        self.assertFalse(list((self.root / ".matlab-harness/mutation").glob("*/m*")))
        self.assertEqual((self.root / "src/f.m").read_text(), SOURCE)

    # Skill cards and context budget
    def test_cards_follow_the_task_and_stay_small(self):
        names = [c["name"] for c in cards_for("implementation", "builder", "MATLAB function with a plot")]
        self.assertIn("matlab-numerics", names)
        self.assertIn("plotting", names)
        names = [c["name"] for c in cards_for("implementation", "builder", "Build the Simulink model plant.slx")]
        self.assertIn("simulink-construction", names)
        for card in (Path(__file__).resolve().parents[2] / "skills" / "cards").glob("*.md"):
            self.assertLessEqual(estimate_tokens(card.read_text(encoding="utf-8")), 600, card.name)

    def test_packet_trims_to_the_context_budget(self):
        full = packet(self.project, "reviewer", "implementation", "x" * 5000)
        self.assertTrue(full["cards"])
        self.assertFalse(full["trimmed"])
        with self.assertRaisesRegex(ProjectError, "Context preflight refused"):
            packet(self.project, "reviewer", "implementation", "x" * 5000, budget=1000)
        prompt = Path(full["prompt"]).read_text(encoding="utf-8")
        self.assertTrue(prompt.startswith("ENG reviewer."))
        self.assertLess(prompt.index("## Card"), prompt.index("## This task"))

    # MCP
    def test_mcp_server_lists_tools_and_refuses_politely(self):
        stdin = io.StringIO("\n".join(json.dumps(m) for m in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "harness_status", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "harness_accept", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "no/such"},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "harness_packet", "arguments": {"role": 5}}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "harness_packet", "arguments": ["reviewer"]}},
            ["not", "a", "request"],
            {"jsonrpc": "2.0", "id": 8, "method": "ping"}]) + "\n")
        stdout = io.StringIO()
        serve(self.root, "owner", stdin, stdout)
        lines = list(map(json.loads, stdout.getvalue().splitlines()))
        replies = {r["id"]: r for r in lines if r["id"] is not None}
        # Wrong argument types are refused as answers, and the server keeps serving.
        self.assertEqual(sorted(replies), [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertIn("role must be builder or reviewer or repair", replies[6]["result"]["content"][0]["text"])
        self.assertIn("JSON object", replies[7]["result"]["content"][0]["text"])
        self.assertEqual([r["error"]["code"] for r in lines if r["id"] is None], [-32600])
        self.assertEqual(replies[1]["result"]["serverInfo"]["name"], "matlab-harness")
        self.assertIn("harness_submit_review", [t["name"] for t in replies[2]["result"]["tools"]])
        self.assertEqual(json.loads(replies[3]["result"]["content"][0]["text"])["phase"], "requirements")
        self.assertTrue(replies[4]["result"]["isError"])
        self.assertTrue(replies[4]["result"]["content"][0]["text"].startswith("Refused:"))
        self.assertEqual(replies[5]["error"]["code"], -32601)

    def test_mcp_review_submission_imports_through_the_packet(self):
        server = Server(self.root, "owner")
        made = server.call("harness_packet", {"role": "reviewer"})
        self.assertIn("ENG reviewer", made["prompt"])
        self.assertEqual(made["answer_schema"]["properties"]["traceability"]["required"], ["R-1", "R-2"])
        report = {"verdict": "ACCEPT", "findings": [], "independent_checks": [],
                  "traceability": [{"requirement": "R-1", "status": "VERIFIED", "evidence": "read"},
                                   {"requirement": "R-2", "status": "VERIFIED", "evidence": "read"}]}
        result = server.call("harness_submit_review", {"report": report, "reviewer_session": "opencode-2",
                                                       "model": "local-model", "packet_id": made["packet_id"]})
        self.assertTrue(result["imported"].startswith(".matlab-harness/packets/" + made["packet_id"] + "/answer-"))
        self.assertIn("gate", result)


if __name__ == "__main__":
    unittest.main()
