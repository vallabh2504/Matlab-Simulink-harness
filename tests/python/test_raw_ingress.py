"""Untrusted raw review ingress: real imports/gates, restarts and reconciliation."""
from pathlib import Path
import io,json,os,subprocess,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from matlab_harness.decoding import decode_answer,decode_document,combine_answers
from matlab_harness.ingestion import authorize_reconciliation,open_gaps
from matlab_harness.project import Project,ProjectError,ReviewProtocolError
from matlab_harness.workflow import start,packet,submit_answer
from matlab_harness.mcp_server import serve
from matlab_harness.runtime import _parse_output

class RawReviewTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);(self.root/'f.py').write_text('value=1\n')
  start(self.root,'Raw intake','builder','owner',['f.py'],'Preserve findings.')
  self.p=Project(self.root);self.p.add_requirement('owner','R-1','One requirement','check','test')
  self.p.approve('owner','operator','Test fixture authorization')
  self.hand=packet(self.p,'reviewer')
  self.good={'verdict':'ACCEPT','findings':[],'traceability':{'R-1':{'status':'VERIFIED','evidence':'fixture'}}}
  self.issue={'id':'F-RAW','severity':'CRITICAL','kind':'PROVEN DEFECT','artifact':'f.py:1',
              'evidence':'Wrong value','impact':'Bad result','repair':'Fix value','closure':'Recheck','status':'OPEN'}
 def raw(self):
  return '{"verdict":"ACCEPT","traceability":'+json.dumps(self.good['traceability'])+',"findings":'+json.dumps([self.issue])+',"findings":[]}'
 def submit(self,value):
  return submit_answer(self.p,'owner',value,'reviewer','fixture')
 def test_duplicate_claim_retained_and_gap_blocks_after_restart(self):
  with self.assertRaises(ReviewProtocolError):self.submit(self.raw())
  d=self.p.load();self.assertTrue(open_gaps(d))
  self.assertTrue(self.p.pending_review_findings())
  self.assertFalse(Project(self.root).gate('requirements')['accepted'])
  for gap in open_gaps(d).values():
   for source in gap['sources']:
    self.assertEqual((self.root/source['path']).read_bytes(),self.raw().encode())
 def test_fenced_duplicate_blocks(self):
  with self.assertRaises(ReviewProtocolError):self.submit('Output:\n'+chr(96)*3+'json\n'+self.raw()+'\n'+chr(96)*3)
  self.assertFalse(self.p.gate('requirements')['accepted'])
  self.assertTrue(self.p.pending_review_findings())
 def test_new_packet_and_clean_accept_do_not_clear_gap(self):
  with self.assertRaises(ReviewProtocolError):self.submit(self.raw())
  packet(self.p,'reviewer')
  with self.assertRaises(ReviewProtocolError):self.submit(self.good)
  self.assertTrue(open_gaps(self.p.load()))
 def test_model_cannot_authorize_itself(self):
  with self.assertRaises(ReviewProtocolError):self.submit('{')
  h=packet(self.p,'reviewer');key,gap=next(iter(open_gaps(self.p.load()).items()))
  replacement={**self.good,'reconciliation':[{'gap_id':key,'source_sha256':gap['source_sha256'],'complete':True}]}
  with self.assertRaises(ReviewProtocolError):self.submit(replacement)
  self.assertTrue(open_gaps(self.p.load()))
 def test_owner_authorized_complete_opaque_correction_succeeds(self):
  with self.assertRaises(ReviewProtocolError):self.submit('{')
  h=packet(self.p,'reviewer');key,gap=next(iter(open_gaps(self.p.load()).items()));pid=Path(h['prompt']).parent.name
  authorize_reconciliation(self.p,'owner',key,gap['source_sha256'],pid,'Inspected malformed source; complete replacement requested.')
  replacement={**self.good,'reconciliation':[{'gap_id':key,'source_sha256':gap['source_sha256'],'complete':True}]}
  self.submit(replacement)
  self.assertFalse(open_gaps(self.p.load()))
  self.assertTrue(self.p.gate('requirements')['accepted'])
 def test_known_claim_survives_valid_reject_correction(self):
  with self.assertRaises(ReviewProtocolError):self.submit(self.raw())
  h=packet(self.p,'reviewer');key,gap=next(iter(open_gaps(self.p.load()).items()));pid=Path(h['prompt']).parent.name
  authorize_reconciliation(self.p,'owner',key,gap['source_sha256'],pid,'Inspect both branches; retain allegation.')
  replacement={**self.good,'verdict':'REJECT','open_items':{x:{'status':'STILL_OPEN','evidence':'Claim retained'} for x in h['open_handles']},
               'reconciliation':[{'gap_id':key,'source_sha256':gap['source_sha256'],'complete':True}]}
  self.submit(replacement)
  self.assertFalse(open_gaps(self.p.load()))
  self.assertFalse(self.p.gate('requirements')['accepted'])
  self.assertTrue(any(x['blocking'] for x in self.p.load()['defects'].values()))
 def test_wrong_source_or_stale_packet_authorization_refused(self):
  with self.assertRaises(ReviewProtocolError):self.submit('{')
  key,gap=next(iter(open_gaps(self.p.load()).items()))
  with self.assertRaises(ProjectError):authorize_reconciliation(self.p,'owner',key,gap['source_sha256'],Path(self.hand['prompt']).parent.name,'Inspected')
  h=packet(self.p,'reviewer')
  with self.assertRaises(ProjectError):authorize_reconciliation(self.p,'owner',key,'wrong',Path(h['prompt']).parent.name,'Inspected')
 def test_raw_structured_conflict_cannot_accept(self):
  parsed=_parse_output(json.dumps({'status':'SUCCESS','session_id':'reviewer','structured_output':self.good,
      'response':json.dumps({**self.good,'verdict':'REJECT','findings':[self.issue]})}),True)
  self.assertFalse(parsed['valid'])
  from matlab_harness.decoding import from_metadata
  with self.assertRaises(ReviewProtocolError):self.submit(from_metadata(parsed['response'],parsed['ingestion']))
  self.assertTrue(self.p.pending_review_findings())
 def test_equal_channels_are_not_conflicting_or_duplicated(self):
  reviewed=combine_answers(self.good,json.dumps(self.good))
  self.assertEqual(reviewed.answer,self.good);self.assertFalse(reviewed.problems)
 def test_agy_text_annotations_are_not_material_review_conflicts(self):
  annotated={**self.good,'toolAction':'Completing review','toolSummary':'Complete review and submit findings'}
  text=json.dumps({'event':'init','conversation_id':'reviewer','init':{'model':'fixture'}})+'\n'+json.dumps(
    {'event':'result','result':{'conversation_id':'reviewer','status':'SUCCESS','structured_output':self.good,'response':json.dumps(annotated)}})
  parsed=_parse_output(text,True)
  self.assertTrue(parsed['valid']);self.assertEqual(parsed['response'],self.good)
  self.assertTrue(parsed['ingestion']['sources'])
  self.assertTrue(combine_answers(self.good,json.dumps(annotated)).problems)
 def test_agy_annotations_cannot_hide_a_nested_claim_or_changed_verdict(self):
  for raw in ({**self.good,'toolSummary':{'findings':[self.issue]}},
              {**self.good,'verdict':'REJECT','toolAction':'Completing review'}):
   text=json.dumps({'event':'result','result':{'conversation_id':'reviewer','status':'SUCCESS',
        'structured_output':self.good,'response':json.dumps(raw)}})
   parsed=_parse_output(text,True)
   self.assertFalse(parsed['valid']);self.assertTrue(parsed['ingestion']['problems'])
   if isinstance(raw.get('toolSummary'),dict):self.assertIn('CRITICAL',json.dumps(parsed['response']))
 def test_nonfinite_overflow_surrogates_depth_and_size_refuse(self):
  for text in ('{"x":NaN}','{"x":1e309}','{"x":"\\ud800"}','['*100+'0'+']'*100,'{"x":"'+('a'*1_048_576)+'"}'):
   with self.subTest(text=text[:30]):
    self.assertTrue(decode_answer(text).problems)
 def test_complete_prefix_and_truncated_tail_is_not_safe(self):
  result=decode_answer(json.dumps(self.good)+'\n{"findings":[')
  self.assertTrue(result.problems)
 def test_escaped_duplicate_and_duplicate_severity_retained(self):
  for text in ('{"findings":[{"severity":"CRITICAL"}],"find\\u0069ngs":[]}',
               '{"findings":[{"id":"F","severity":"CRITICAL","severity":"MINOR","evidence":"Bad"}]}'):
   result=decode_answer(text);self.assertTrue(result.problems)
   self.assertIn('CRITICAL',json.dumps(result.answer))
 def test_mcp_raw_line_duplicate_and_report_text_conflict(self):
  for mode in ('object','text','both'):
   args={'reviewer_session':'reviewer','model':'fixture'}
   if mode=='object':args['report']='RAW'
   elif mode=='text':args['report_text']=self.raw()
   else:args.update(report=self.good,report_text=json.dumps({**self.good,'verdict':'REJECT','findings':[self.issue]}))
   line=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'harness_submit_review','arguments':args}})
   if mode=='object':line=line.replace('"RAW"',self.raw())
   out=io.StringIO();serve(self.root,'owner',io.StringIO(line+'\n'),out)
   reply=json.loads(out.getvalue());self.assertTrue(reply['result']['isError'])
   self.assertTrue(open_gaps(self.p.load()))
 def test_json_string_wrapped_duplicate_still_binds_gap_and_claim(self):
  with self.assertRaises(ReviewProtocolError):self.submit(json.dumps(self.raw()))
  self.assertTrue(open_gaps(self.p.load()));self.assertTrue(self.p.pending_review_findings())
 def test_malformed_json_event_beside_final_is_not_ignored(self):
  init=json.dumps({'event':'init','conversation_id':'reviewer','init':{'model':'fixture'}})
  final=json.dumps({'event':'result','result':{'conversation_id':'reviewer','status':'SUCCESS','response':json.dumps(self.good)}})
  for text in (init+'\n'+final+'\n'+'{"findings":[',init+'\n'+'{"event":'+'\n'+final):
   result=_parse_output(text,True);self.assertFalse(result['valid']);self.assertTrue(result['ingestion']['problems'])
 def test_multiple_root_results_retain_conflicting_serious_claim(self):
  init=json.dumps({'event':'init','conversation_id':'reviewer','init':{'model':'fixture'}})
  values=[{**self.good,'verdict':'REJECT','findings':[self.issue]},self.good]
  text=init+'\n'+'\n'.join(json.dumps({'event':'result','result':{'conversation_id':'reviewer','status':'SUCCESS','response':json.dumps(v)}}) for v in values)
  result=_parse_output(text,True)
  self.assertFalse(result['valid']);self.assertIn('CRITICAL',json.dumps(result['response']))
 def test_cross_field_duplicates_pin_serious_open_claim(self):
  value=json.dumps({**self.good,'findings':[self.issue]})
  value=value.replace('"severity": "CRITICAL"','"severity":"MINOR","severity":"CRITICAL"').replace('"status": "OPEN"','"status":"CLOSED","status":"OPEN"')
  with self.assertRaises(ReviewProtocolError):self.submit(value)
  self.assertTrue(self.p.pending_review_findings())
  h=packet(self.p,'reviewer');self.assertTrue(h['open_handles'])
 def test_cli_answer_preserves_raw_input(self):
  (self.root/'raw.json').write_text(self.raw())
  env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[2]/'src')
  proc=subprocess.run([sys.executable,'-m','matlab_harness.cli','--project',str(self.root),'answer','--owner','owner','raw.json','--reviewer-session','reviewer','--model','fixture'],cwd=self.root,env=env,capture_output=True,timeout=30)
  self.assertEqual(proc.returncode,2,proc.stderr)
  self.assertTrue(open_gaps(self.p.load()))
 def test_ambiguous_identity_terminal_intake_does_not_remain_interrupted(self):
  from matlab_harness.workflow import execute
  text=json.dumps({'status':'SUCCESS','session_id':'reviewer','model':'fixture','response':self.good})
  text=text.replace('"session_id": "reviewer"','"session_id":"reviewer","session_id":"other"')
  (self.root/'emit.py').write_text('print('+repr(text)+')')
  self.p.configure_runtime('owner',runtime={'adapter':'command','argv':[sys.executable,str(self.root/'emit.py')]})
  result=execute(self.p,'owner','reviewer')
  self.assertEqual(result['status'],'REVIEW_NOT_IMPORTED')
  self.assertTrue(open_gaps(self.p.load()));self.assertFalse(self.p.unfinished_review_imports())
 def test_mcp_ambiguous_identity_records_gap_without_crash(self):
  line=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'harness_submit_review',
     'arguments':{'reviewer_session':'reviewer','model':'fixture','report':self.good}}})
  line=line.replace('"reviewer_session": "reviewer"','"reviewer_session":"reviewer","reviewer_session":"other"')
  out=io.StringIO();serve(self.root,'owner',io.StringIO(line+'\n'),out)
  self.assertEqual(json.loads(out.getvalue())['error']['code'],-32700)
  self.assertTrue(open_gaps(self.p.load()))
 def test_oversized_mcp_request_is_retained_and_next_ping_served(self):
  source='{"findings":"'+('x'*1_048_576)+'"}\n'
  ping=json.dumps({'jsonrpc':'2.0','id':2,'method':'ping'})+'\n'
  out=io.StringIO();serve(self.root,'owner',io.StringIO(source+ping),out)
  replies=[json.loads(x) for x in out.getvalue().splitlines()]
  self.assertEqual(replies[0]['error']['code'],-32700);self.assertEqual(replies[1]['result'],{})
  gap=next(iter(open_gaps(self.p.load()).values()))
  self.assertEqual((self.root/gap['sources'][0]['path']).read_bytes(),source.encode())
 def test_mcp_invalid_utf8_is_retained_and_server_can_continue(self):
  source=b'{"method":"tools/call","params":{"name":"harness_submit_review","report":"\xff"}}\n'
  ping=json.dumps({'jsonrpc':'2.0','id':2,'method':'ping'}).encode()+b'\n'
  out=io.StringIO();serve(self.root,'owner',io.BytesIO(b'\n'+source+ping),out)
  replies=[json.loads(x) for x in out.getvalue().splitlines()]
  self.assertEqual(len(replies),2);self.assertEqual(replies[0]['error']['code'],-32700)
  self.assertEqual(replies[1]['result'],{})
  gap=next(iter(open_gaps(self.p.load()).values()))
  self.assertEqual((self.root/gap['sources'][0]['path']).read_bytes(),source)
if __name__=='__main__':unittest.main()
