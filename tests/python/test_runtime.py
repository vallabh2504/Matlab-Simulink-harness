"""Real child-process tests of transport; fixtures are not live AI evidence."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from matlab_harness.runtime import DEFAULT_TIMEOUTS, _arguments, execute_role


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evidence = self.root / "evidence"
        self.program = self.root / "provider_fixture.py"

    def run_fixture(self, source, schema=None, **config):
        self.program.write_text(source, encoding="utf-8")
        return execute_role(self.root, "reviewer", "Fixture prompt with units K and s",
                            {"adapter": "command", "argv": [sys.executable, str(self.program),
                              "{prompt_file}", "{project}", "{model}", "{schema_file}"],
                             "model": "requested-fixture-model", **config}, self.evidence, schema)

    def assert_durable(self, result):
        receipt = Path(result["artifacts"]["receipt"])
        self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")), result)
        for key in ("stdout", "stderr"):
            self.assertTrue(Path(result["artifacts"][key]).is_file())

    def test_success_actual_identity_and_prompt_file(self):
        result = self.run_fixture(
            "import json,sys\nfrom pathlib import Path\n"
            "assert 'units K and s' in Path(sys.argv[1]).read_text()\n"
            "assert Path(sys.argv[2]).resolve() == Path.cwd()\n"
            "assert sys.argv[3] == 'requested-fixture-model'\n"
            "print(json.dumps(dict(status='SUCCESS',model='observed-fixture-model',"
            "session_id='actual-fixture-session',response={'verdict':'REJECT'})))\n",
            {"type": "object"})
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["actual_model"], "observed-fixture-model")
        self.assertEqual(result["root_session_id"], "actual-fixture-session")
        self.assertEqual(result["response"]["verdict"], "REJECT")
        self.assertEqual(result["timeout_seconds"], 1800)
        self.assert_durable(result)

    def test_omitted_actual_identity_stays_unknown(self):
        result = self.run_fixture("print('{\"status\":\"SUCCESS\",\"response\":\"finished\"}')")
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertIsNone(result["actual_model"])
        self.assertIsNone(result["root_session_id"])

    def test_pretty_envelope_with_extra_event_key_and_single_event(self):
        generic = self.run_fixture("import json\nprint(json.dumps(dict(event='finished',status='SUCCESS',"
            "session_id='fixture-root',model='fixture-model',response={'verdict':'REJECT'}),indent=2))\n",
            {"type": "object"})
        event = self.run_fixture("import json\nprint(json.dumps(dict(event='result',result=dict("
            "conversation_id='fixture-root',status='SUCCESS',response={'verdict':'REJECT'})),indent=2))\n",
            {"type": "object"})
        for receipt in (generic, event):
            self.assertEqual(receipt["status"], "SUCCEEDED")
            self.assertEqual(receipt["root_session_id"], "fixture-root")
            self.assertEqual(receipt["response"]["verdict"], "REJECT")

    def test_timeout_preserves_partial_metadata_and_stops_root(self):
        result = self.run_fixture(
            "import json,time\n"
            "print(json.dumps(dict(event='init',conversation_id='root-fixture',"
            "init={'model':'actual-fixture'})),flush=True)\n"
            "time.sleep(60)\n", timeout=1)
        self.assertEqual(result["status"], "TIMED_OUT")
        self.assertEqual(result["root_session_id"], "root-fixture")
        self.assertTrue(result["cleanup"]["root_stopped"])
        self.assertIsNotNone(result["exit_code"])
        self.assertEqual(result["cleanup"]["external_service_cancellation"], "UNKNOWN")
        self.assertFalse(result["cleanup"]["descendant_stop_verified"])
        self.assert_durable(result)

    def test_child_result_cannot_complete_root(self):
        events = [{"event": "init", "conversation_id": "root", "init": {"model": "observed"}},
                  {"event": "step_update", "step_update": {"conversation_id": "child"}},
                  {"event": "result", "result": {"conversation_id": "child", "status": "SUCCESS",
                                                  "response": "child finished"}}]
        result = self.run_fixture("import json\nfor event in " + repr(events) + ": print(json.dumps(event))\n")
        self.assertEqual(result["status"], "MALFORMED")
        self.assertEqual(result["root_session_id"], "root")
        self.assertEqual(result["child_session_ids"], ["child"])
        self.assertIsNone(result["response"])

    def test_root_structured_result_and_missing_result_id(self):
        events = [{"event": "init", "conversation_id": "root", "init": {"model": "observed"}},
                  {"event": "result", "result": {"status": "SUCCESS", "response": "not authoritative",
                                                  "structured_output": {"verdict": "REJECT"}}}]
        result = self.run_fixture("import json\nfor event in " + repr(events) + ": print(json.dumps(event))\n",
                                  {"type": "object"})
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(result["response"], {"verdict": "REJECT"})
        self.assertEqual(result["root_session_id"], "root")

    def test_json_string_response_decoded_and_malformed_rejected(self):
        good = self.run_fixture("import json\nprint(json.dumps(dict(status='SUCCESS',"
                                "response=json.dumps({'verdict':'REJECT'}))))\n", {"type": "object"})
        bad = self.run_fixture("print('{\"status\":\"SUCCESS\",\"response\":\"not JSON\"}')",
                               {"type": "object"})
        self.assertEqual(good["status"], "SUCCEEDED")
        self.assertEqual(bad["status"], "MALFORMED")
        self.assertEqual(bad["raw_response"], "not JSON")
        self.assertNotEqual(good["attempt_id"], bad["attempt_id"])
        self.assert_durable(good)
        self.assert_durable(bad)

    def test_malformed_event_and_failure_exit_are_preserved(self):
        bad = self.run_fixture("print('{\"event\":\"init\",\"init\":null}')")
        failed = self.run_fixture("import sys\nprint('provider startup failed',file=sys.stderr)\nsys.exit(7)")
        self.assertEqual(bad["status"], "MALFORMED")
        self.assertIn("parse_error", bad)
        self.assertEqual(failed["status"], "FAILED")
        self.assertEqual(failed["exit_code"], 7)
        self.assertIn("startup failed", Path(failed["artifacts"]["stderr"]).read_text())

    def test_launch_failure_and_bad_configuration_are_durable(self):
        missing = execute_role(self.root, "builder", "prompt",
                               {"adapter": "command", "argv": [str(self.root / "missing.exe")]}, self.evidence)
        bad = execute_role(self.root, "builder", "prompt", {"adapter": "command", "argv": ["{secret}"]}, self.evidence)
        negative = execute_role(self.root, "builder", "prompt", {"timeout": -1}, self.evidence)
        self.assertEqual(missing["status"], "LAUNCH_FAILED")
        self.assertEqual(bad["status"], "CONFIG_ERROR")
        self.assertEqual(negative["status"], "CONFIG_ERROR")
        for result in (missing, bad, negative):
            self.assert_durable(result)

    def test_agy_arguments_default_generous_and_permissions_explicit(self):
        paths = {"project": "owned-project", "prompt_file": "prompt.md", "schema_file": "schema.json"}
        args = _arguments({"adapter": "agy", "model": "available-model"}, "actual prompt", paths, {})
        self.assertIn("--json-schema", args)
        self.assertEqual(args[-4:], ["--print-timeout", "0", "--print", "actual prompt"])
        self.assertNotIn("--dangerously-skip-permissions", args)
        self.assertEqual(DEFAULT_TIMEOUTS, {"builder": 3600, "reviewer": 1800, "repair": 3600})


if __name__ == "__main__":
    unittest.main()
