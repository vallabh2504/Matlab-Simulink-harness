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

    def test_json_only_capability_keeps_review_decoder(self):
        result=self.run_fixture("import json,sys\nassert sys.argv[4]==''\nprint(json.dumps(dict(status='SUCCESS',session_id='r',model='fixture',response='```json\\n{\"verdict\":\"REJECT\"}\\n```')))\n",
                                {'type':'object'},capabilities={'response_mode':'json'})
        self.assertEqual(result['status'],'SUCCEEDED');self.assertEqual(result['response']['verdict'],'REJECT')
        self.assertIn('ingestion',result)

    def test_invalid_utf8_is_retained_as_unread_source(self):
        result=self.run_fixture("import sys\nsys.stdout.buffer.write(b'\\xff')\n",{'type':'object'})
        self.assertEqual(result['status'],'MALFORMED')
        self.assertTrue(result['ingestion']['problems'])
        self.assertEqual(Path(result['ingestion']['sources'][0]['artifact']).read_bytes(),b'\xff')

    def test_response_size_limit_stops_without_accepting_prefix(self):
        result=self.run_fixture("print('x'*2048)\n",{'type':'object'},capabilities={'max_response_bytes':1024})
        self.assertEqual(result['status'],'MALFORMED');self.assertEqual(result['failure']['category'],'unread_source')
        self.assertGreater(result['ingestion']['sources'][0]['bytes'],1024)

    def test_provider_failures_classified_without_fallback(self):
        for code,category in ((404,'permanent_model_unavailable'),(401,'permanent_authentication'),(503,'transient_transport')):
            result=self.run_fixture("import sys\nprint('provider HTTP "+str(code)+"',file=sys.stderr)\nsys.exit(1)\n")
            self.assertEqual(result['failure']['category'],category)
            self.assertFalse(result['failure']['automatic_fallback'])
            self.assertIsNone(result['usage'])
    def test_a_usage_limit_is_named_and_not_retried(self):
        message="Provider result: success You've hit your session limit · resets 9:30am"
        result=self.run_fixture("import json,sys\nprint(json.dumps(dict(status='FAILED',session_id='r',model='fixture',response=None,error="
                                +repr(message)+")))\nsys.exit(1)\n",{'type':'object'})
        self.assertEqual(result['failure']['category'],'provider_usage_limit')
        self.assertFalse(result['failure']['transient'])
        for message in ("Provider result: error_during_execution 429 Weekly limit reached - resets Mon",
                        "5-hour limit reached","You have reached your specified API usage limits"):
            result=self.run_fixture("import json,sys\nprint(json.dumps(dict(status='FAILED',session_id='r',model='fixture',response=None,error="
                                    +repr(message)+")))\nsys.exit(1)\n",{'type':'object'})
            self.assertEqual(result['failure']['category'],'provider_usage_limit',message)
    def test_command_envelope_children_are_cleaned(self):
        result=self.run_fixture("import json\nprint(json.dumps(dict(status='SUCCEEDED',session_id='r',model='fixture',response={'verdict':'REJECT'},"
                                "child_session_ids=['c1','r',3,'','c1','c2'])))\n",{'type':'object'})
        self.assertEqual(result['child_session_ids'],['c1','c2'])
        result=self.run_fixture("import json\nprint(json.dumps(dict(status='SUCCEEDED',session_id='r',model='fixture',response={'verdict':'REJECT'},"
                                "child_session_ids='c1')))\n",{'type':'object'})
        self.assertEqual(result['child_session_ids'],[])
    def test_provider_error_field_is_retained_and_classified(self):
        result=self.run_fixture("import json\nprint(json.dumps(dict(event='result',result=dict(status='ERROR',error='UNAVAILABLE code 503',conversation_id='r',response={'verdict':'REJECT'}))))\n",{'type':'object'})
        self.assertEqual(result['status'],'FAILED')
        self.assertEqual(result['provider_error'],'UNAVAILABLE code 503')
        self.assertEqual(result['failure']['category'],'transient_transport')
        self.assertFalse(result['failure']['automatic_fallback'])

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

    def test_process_lingering_after_root_result_is_stopped_and_succeeds(self):
        events = [{"event": "init", "conversation_id": "root", "init": {"model": "observed"}},
                  {"event": "result", "result": {"conversation_id": "root", "status": "SUCCESS",
                                                  "structured_output": {"verdict": "ACCEPT"}}}]
        result = self.run_fixture("import json,time\nfor event in " + repr(events) + ": print(json.dumps(event),flush=True)\n"
                                  "time.sleep(60)\n", {"type": "object"}, timeout=30, result_grace=0)
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertTrue(result["stopped_after_result"])
        self.assertTrue(result["cleanup"]["root_stopped"])
        self.assertEqual(result["response"], {"verdict": "ACCEPT"})
        self.assertLess(result["wall_seconds"], 20)
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
