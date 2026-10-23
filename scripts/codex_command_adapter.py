"""Codex CLI transport for the harness's generic command envelope; evidence stays in a local folder.

Model provenance comes from the exact new emitted thread's local turn_context,
never the requested model or agent's reply. No engineering verdict is invented.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse, hashlib, json, math, os, subprocess, sys, uuid


EXECUTED_CHECKPOINTS={'implementation','verification','handoff'}


def packet_scratch(root, scratch):
    """The one packet scratch directory a reviewer may write, relative to the project, or None."""
    if not scratch:
        return None
    relative=Path(os.path.abspath(scratch)).relative_to(Path(os.path.abspath(root)))
    if len(relative.parts)!=3 or relative.parts[:2]!=('.matlab-harness','scratch'):
        raise ValueError('Reviewer scratch must be one .matlab-harness/scratch/<packet> directory')
    return relative.parts


def packet_checkpoint(root, prompt_file, scratch=None):
    """The checkpoint of the packet a prompt belongs to; the runtime writes each attempt's prompt at
    .matlab-harness/packets/<packet>/execution/<attempt>/prompt.md."""
    packets=Path(os.path.abspath(root))/'.matlab-harness'/'packets'
    relative=Path(os.path.abspath(prompt_file)).relative_to(packets)
    if len(relative.parts)<2:
        raise ValueError('Reviewer prompt must sit inside one .matlab-harness/packets/<packet> directory')
    if scratch and scratch[2]!=relative.parts[0]:
        raise ValueError('Reviewer scratch belongs to a different packet than the prompt')
    record=json.loads((packets/relative.parts[0]/'packet.json').read_text(encoding='utf-8'))
    if not isinstance(record,dict):
        raise ValueError('packet.json is not one JSON object')
    return record.get('checkpoint')


def review_inventory(root, scratch=None):
    """Guard source and durable controls, excluding the parent's active packets and this packet's scratch."""
    result={}
    for directory,names,files in os.walk(root,topdown=True,followlinks=False):
        kept=[]
        for name in sorted(names):
            folder=Path(directory)/name
            if folder.is_symlink() or getattr(folder.lstat(),'st_file_attributes',0)&0x400:
                raise ValueError('Read-only review inventory refuses link/reparse traversal')
            relative=folder.relative_to(root)
            if relative.parts==('.git',) or relative.parts==('.matlab-harness','packets') or relative.parts==scratch:
                continue
            kept.append(name)
        names[:]=kept
        for name in sorted(files):
            file=Path(directory)/name
            if file.is_symlink() or getattr(file.lstat(),'st_file_attributes',0)&0x400:
                raise ValueError('Read-only review inventory refuses link/reparse traversal')
            relative=file.relative_to(root)
            if relative.parts==('.git',):
                continue
            result[relative.as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
    return result


def validate_schema_definition(schema):
    allowed={'type','properties','required','additionalProperties','items','enum',
             'minLength','maxLength','minimum','maximum','minItems','maxItems','title','description','$schema'}
    if not isinstance(schema,dict) or set(schema)-allowed:
        raise ValueError('Unsupported schema definition/constraints')
    if 'additionalProperties' in schema and not isinstance(schema['additionalProperties'],bool):
        raise ValueError('Subschema-valued additionalProperties is unsupported')
    for child_schema in schema.get('properties',{}).values():
        validate_schema_definition(child_schema)
    if 'items' in schema:
        validate_schema_definition(schema['items'])


def validate_schema(value, schema, location='$'):
    """Validate the explicit finite schema subset used by these role packets."""
    supported = {'type','properties','required','additionalProperties','items','enum',
                 'minLength','maxLength','minimum','maximum','minItems','maxItems',
                 'title','description','$schema'}
    unknown = set(schema) - supported
    if unknown:
        raise ValueError('Unsupported schema constraints: ' + ','.join(sorted(unknown)))
    if isinstance(value,float) and not math.isfinite(value):
        raise ValueError(location + ': nonfinite number cannot establish structured transport')
    types = {'object':lambda v:isinstance(v,dict), 'array':lambda v:isinstance(v,list),
             'string':lambda v:isinstance(v,str), 'boolean':lambda v:isinstance(v,bool),
             'number':lambda v:isinstance(v,(int,float)) and not isinstance(v,bool),
             'integer':lambda v:isinstance(v,int) and not isinstance(v,bool), 'null':lambda v:v is None}
    declared = schema.get('type')
    if declared is not None:
        declared = declared if isinstance(declared,list) else [declared]
        if any(t not in types for t in declared):
            raise ValueError('Unsupported schema type')
        if not any(types[t](value) for t in declared):
            raise ValueError(location + ': wrong JSON type')
    if 'enum' in schema and not any(value == item and (type(value) is type(item) or
            isinstance(value,(int,float)) and not isinstance(value,bool) and isinstance(item,(int,float)) and not isinstance(item,bool)) for item in schema['enum']):
        raise ValueError(location + ': unknown enum value')
    if isinstance(value,dict):
        properties = schema.get('properties',{})
        if any(key not in value for key in schema.get('required',[])):
            raise ValueError(location + ': required field absent')
        if schema.get('additionalProperties') is False and set(value)-set(properties):
            raise ValueError(location + ': extra field')
        for key,child in value.items():
            if key in properties:
                validate_schema(child,properties[key],location+'.'+key)
    if isinstance(value,list):
        for index,child in enumerate(value):
            if 'items' in schema:
                validate_schema(child,schema['items'],location+'['+str(index)+']')
        if len(value)<schema.get('minItems',0) or len(value)>schema.get('maxItems',float('inf')):
            raise ValueError(location + ': array length outside declared bounds')
    if isinstance(value,str) and (len(value)<schema.get('minLength',0) or len(value)>schema.get('maxLength',float('inf'))):
        raise ValueError(location + ': string length outside declared bounds')
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        if value<schema.get('minimum',-float('inf')) or value>schema.get('maximum',float('inf')):
            raise ValueError(location + ': number outside declared bounds')


def utc():
    return datetime.now(timezone.utc)


def same_path(first, second):
    return os.path.normcase(str(Path(first).resolve())) == os.path.normcase(str(Path(second).resolve()))


def context_reasoning_effort(payload):
    """Keep absent local metadata UNKNOWN; reject contradictory observations."""
    mode = payload.get('collaboration_mode')
    settings = mode.get('settings', {}) if isinstance(mode, dict) else {}
    values = [payload.get('reasoning_effort'), payload.get('effort'),
              settings.get('reasoning_effort') if isinstance(settings, dict) else None]
    known = {value for value in values if isinstance(value, str) and value}
    if len(known) > 1:
        raise ValueError('Contradictory local reasoning-effort observations')
    return next(iter(known)) if known else None


def observed_model(home, identity, project, start, end, evidence):
    if not identity:
        return None, [], 'No emitted thread identity'
    try:
        uuid.UUID(identity)
    except ValueError:
        return None, [], 'Malformed emitted thread identity'
    files = list((home / 'sessions').rglob('*' + identity + '*.jsonl'))
    if len(files) != 1:
        return None, [], 'Exact thread rollout absent or ambiguous'
    file = files[0]
    raw = file.read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    (evidence / 'rollout-observed.jsonl').write_bytes(raw)
    if hashlib.sha256(file.read_bytes()).hexdigest() != source_sha256:
        return None, [], 'Matched rollout changed while provenance was captured'
    events = []
    for line in raw.decode('utf-8').splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            return None, [], 'Malformed matched rollout'
    headers = [e.get('payload', {}) for e in events if e.get('type') == 'session_meta']
    if len(headers) != 1 or headers[0].get('id') != identity or headers[0].get('session_id',identity) != identity or not same_path(headers[0].get('cwd', ''), project):
        return None, [], 'Rollout session header does not bind this thread/project'
    try:
        created = datetime.fromisoformat(headers[0]['timestamp'].replace('Z', '+00:00'))
    except (KeyError, ValueError):
        return None, [], 'Rollout creation timestamp missing or invalid'
    if not start <= created <= end:
        return None, [], 'Rollout was not created during this native invocation'
    observations = []
    for event in events:
        payload = event.get('payload', {})
        if event.get('type') != 'turn_context' or not isinstance(payload, dict) or not payload.get('model'):
            continue
        try:
            timestamp = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
        except (KeyError, ValueError):
            return None, [], 'Model observation timestamp missing or invalid'
        if not start <= timestamp <= end:
            return None, [], 'Model observation outside this native invocation'
        if payload.get('cwd') is not None and not same_path(payload['cwd'],project):
            return None, [], 'Model context cwd does not bind this project'
        observations.append({'model':payload['model'], 'timestamp':event['timestamp'],
            'source':str(file), 'source_sha256':source_sha256, 'preserved_source':str(evidence / 'rollout-observed.jsonl'),
            'event_type':'turn_context', 'session_id':identity, 'session_cwd':headers[0]['cwd'],
            'model_provider':headers[0].get('model_provider'), 'cli_version':headers[0].get('cli_version'),
            'reasoning_effort':context_reasoning_effort(payload), 'sandbox_policy':payload.get('sandbox_policy'),
            'turn_id':payload.get('turn_id'),'root_turn_id':payload.get('root_turn_id'),
            'context_cwd':payload.get('cwd'),'permission_profile':payload.get('permission_profile'),
            'approval_policy':payload.get('approval_policy')})
    models = {item['model'] for item in observations}
    if len(models) != 1:
        return None, observations, 'Observed model absent or changed during invocation'
    return next(iter(models)), observations, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prompt-file', required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--schema-file')
    parser.add_argument('--model', required=True)
    parser.add_argument('--reasoning-effort', choices=['none','minimal','low','medium','high','xhigh','max'])
    parser.add_argument('--role', choices=['builder', 'reviewer', 'repair'], required=True)
    parser.add_argument('--reviewer-access',choices=['sandbox-read-only','scope-guarded-native'],default='sandbox-read-only')
    parser.add_argument('--evidence-root', required=True)
    parser.add_argument('--node', required=True)
    parser.add_argument('--codex-js', required=True)
    parser.add_argument('--codex-home', required=True)
    parser.add_argument('--scratch', help='this packet\'s scratch directory, the one place a reviewer writes')
    args = parser.parse_args()
    source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    project = Path(args.project).resolve()
    evidence = Path(args.evidence_root).resolve() / uuid.uuid4().hex
    evidence.mkdir(parents=True, exist_ok=False)
    prompt = Path(args.prompt_file).read_text(encoding='utf-8')
    argv = [args.node, args.codex_js, 'exec', '--ignore-user-config', '--skip-git-repo-check',
            '--json', '-C', str(project), '--model', args.model,
            '--output-last-message', str(evidence / 'last-message.txt')]
    if args.reasoning_effort is not None:
        argv += ['-c', 'model_reasoning_effort=' + json.dumps(args.reasoning_effort)]
    argv += ['--sandbox', 'read-only'] if args.role == 'reviewer' and args.reviewer_access=='sandbox-read-only' else ['--dangerously-bypass-approvals-and-sandbox']
    schema = Path(args.schema_file) if args.schema_file else None
    if schema is not None and not schema.is_file():
        envelope={'status':'FAILED','session_id':None,'model':None,'response':None,
                  'failure':'Supplied schema file is absent','raw_evidence':str(evidence)}
        (evidence/'receipt.json').write_text(json.dumps(envelope,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(envelope)); return 1
    structured = schema is not None and schema.is_file()
    if structured:
        try:
            original_schema = json.loads(schema.read_text(encoding='utf-8'))
            validate_schema_definition(original_schema)
        except (OSError,ValueError,TypeError,AttributeError) as exc:
            envelope={'status':'FAILED','session_id':None,'model':None,'response':None,
                      'failure':'Invalid/unsupported response schema: '+str(exc),'raw_evidence':str(evidence)}
            (evidence/'receipt.json').write_text(json.dumps(envelope,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(envelope)); return 1
        strict_schema = json.loads(json.dumps(original_schema))
        def strict_objects(value):
            if isinstance(value, dict):
                if value.get('type') == 'object':
                    value['additionalProperties'] = False
                    value['required'] = list(value.get('properties', {}))
                for child_value in value.values():
                    strict_objects(child_value)
            elif isinstance(value, list):
                for child_value in value:
                    strict_objects(child_value)
        strict_objects(strict_schema)
        effective_schema = evidence / 'native-output-schema.json'
        effective_schema.write_text(json.dumps(strict_schema, indent=2)+'\n', encoding='utf-8')
        (evidence / 'original-output-schema.json').write_text(json.dumps(original_schema,indent=2)+'\n',encoding='utf-8')
        prompt += '\nNative structured output requires all declared fields. For an inapplicable optional string field such as impact or closure, emit an empty string. No field or verdict is supplied by the wrapper.\n'
        argv += ['--output-schema', str(effective_schema)]
    argv += ['-']
    started = utc()
    try:
        scratch=packet_scratch(project,args.scratch) if args.role=='reviewer' else None
        checkpoint=packet_checkpoint(project,args.prompt_file,scratch) if args.role=='reviewer' else None
        if args.role=='reviewer' and args.reviewer_access=='sandbox-read-only' and checkpoint in EXECUTED_CHECKPOINTS:
            raise ValueError('executed checkpoints need a writable scratch: use --reviewer-access scope-guarded-native')
        review_before=review_inventory(project,scratch) if args.role=='reviewer' else None
    except (OSError,ValueError) as exc:
        envelope={'status':'FAILED','session_id':None,'model':None,'response':None,
                  'failure':'Reviewer inventory unavailable before dispatch: '+str(exc),
                  'raw_evidence':str(evidence),'transport_source_sha256':source_sha256}
        (evidence/'receipt.json').write_text(json.dumps(envelope,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(envelope)); return 1
    child = None
    failure = None
    cleanup = {'requested':False,'root_stopped':None,'descendant_stop_verified':False,'backend_cancellation':'UNKNOWN'}
    with (evidence / 'stdout.ndjson').open('w', encoding='utf-8') as stdout, (evidence / 'stderr.txt').open('w', encoding='utf-8') as stderr:
        try:
            child = subprocess.Popen(argv, cwd=project, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                text=True, encoding='utf-8')
            child.communicate(prompt)
        except (OSError, KeyboardInterrupt) as exc:
            failure = type(exc).__name__ + ': ' + str(exc)
            if child is not None and child.poll() is None:
                cleanup.update(requested=True,pid=child.pid)
                try:
                    stop=subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True, timeout=10,check=False)
                    cleanup['tree_command_exit_code']=stop.returncode
                    child.wait(timeout=10)
                except (OSError,subprocess.TimeoutExpired) as stop_error:
                    cleanup['error']=str(stop_error)
                cleanup['root_stopped']=child.poll() is not None
    ended = utc()
    events = []
    for line in (evidence / 'stdout.ndjson').read_text(encoding='utf-8').splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            failure = failure or 'Malformed native JSON event'
    roots = {e.get('thread_id') for e in events if e.get('type') == 'thread.started'} - {None}
    identity = next(iter(roots)) if len(roots) == 1 else None
    try:
        model, observations, provenance_error = observed_model(Path(args.codex_home), identity, project, started, ended, evidence)
    except (OSError,ValueError,TypeError,KeyError,UnicodeError) as exc:
        model,observations,provenance_error=None,[],type(exc).__name__+': '+str(exc)
    if model is not None and model != args.model:
        failure = failure or 'Observed native model differs from the requested model'
    efforts = {item['reasoning_effort'] for item in observations if item.get('reasoning_effort')}
    if len(efforts) > 1:
        failure = failure or 'Observed native reasoning effort changed during invocation'
    if args.reasoning_effort is not None and efforts and efforts != {args.reasoning_effort}:
        failure = failure or 'Observed native reasoning effort differs from the requested setting'
    messages = [e.get('item', {}).get('text') for e in events
                if e.get('type') == 'item.completed' and e.get('item', {}).get('type') == 'agent_message']
    final = (evidence / 'last-message.txt').read_text(encoding='utf-8') if (evidence / 'last-message.txt').is_file() else None
    completed = [e for e in events if e.get('type') == 'turn.completed']
    native_errors = []
    for event in events:
        if event.get('type') not in {'turn.failed', 'error'}:
            continue
        error = event.get('error', event.get('message'))
        if isinstance(error, dict):
            message = error.get('message')
        else:
            message = error
        if not isinstance(message, str) or not message.strip():
            message = 'Native event reported failure without a message'
        native_errors.append({'type': event['type'], 'message': message})
    native_failed = bool(native_errors)
    if native_failed:
        failure = failure or 'Native runtime failure: ' + '; '.join(
            dict.fromkeys(item['message'] for item in native_errors))
    elif child is not None and child.returncode != 0:
        failure = failure or 'Native command exited with code ' + str(child.returncode)
    response = final
    if structured and final is not None:
        try:
            response = json.loads(final,parse_constant=lambda token:(_ for _ in ()).throw(ValueError('Nonfinite JSON constant '+token)))
            validate_schema(response,original_schema)
            validate_schema(response,strict_schema)
        except (ValueError,TypeError) as exc:
            response = None
            failure = failure or 'Structured response invalid: '+str(exc)
    success = (child is not None and child.returncode == 0 and completed and not native_failed
               and final is not None and messages and final.strip() == messages[-1].strip()
               and response is not None and not failure and model is not None and identity is not None)
    source_unchanged = hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == source_sha256
    if not source_unchanged:
        success = False
        failure = failure or 'Transport source changed during this invocation'
    review_unchanged=None
    if review_before is not None:
        try:
            review_unchanged=review_inventory(project,scratch)==review_before
        except (OSError,ValueError) as review_error:
            review_unchanged=False
            failure=failure or 'Reviewer inventory unavailable: '+str(review_error)
        if not review_unchanged:
            success=False
            failure=failure or 'Reviewer changed source or durable controls'
    envelope = {'status':'SUCCESS' if success else 'FAILED', 'session_id':identity, 'model':model,
        'response':response, 'usage':completed[-1].get('usage') if completed else None,
        'native_exit_code':child.returncode if child else None, 'pid':child.pid if child else None,
        'started_at':started.isoformat(), 'ended_at':ended.isoformat(), 'argv':argv,
        'requested_model':args.model, 'model_observations':observations, 'provenance_error':provenance_error,
        'requested_reasoning_effort':args.reasoning_effort,
        'observed_reasoning_effort':next(iter(efforts)) if len(efforts)==1 else None,
        'reasoning_effort_provenance':'OBSERVED_LOCAL_CONTEXT' if observations and all(item.get('reasoning_effort') for item in observations) and len(efforts)==1 else 'UNKNOWN_LOCAL_CONTEXT',
        'transport_source':str(Path(__file__).resolve()),'transport_source_sha256':source_sha256,'transport_source_unchanged':source_unchanged,
        'reviewer_access':args.reviewer_access,'reviewer_inventory_unchanged':review_unchanged,
        'reviewer_guard_scope':'Whole project except .git, parent-owned .matlab-harness/packets and this packet\'s scratch; post-execution evidence guard, not OS sandbox',
        'failure':failure, 'native_errors':native_errors, 'cleanup':cleanup, 'raw_evidence':str(evidence), 'child_context_coverage':'UNKNOWN',
        'claim':'Native transport completion only; project import and independent acceptance remain separate'}
    (evidence / 'receipt.json').write_text(json.dumps(envelope, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(envelope))
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
