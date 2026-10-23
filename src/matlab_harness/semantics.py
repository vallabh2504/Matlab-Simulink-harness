"""Required, operator-declared semantic test adequacy in isolated project copies.

Unlike generic mutation sampling, these named defects are acceptance obligations.
A failure only counts when the declared property assertion reports its marker;
timeouts, syntax errors and missing dependencies never count as defect detection.
"""
from __future__ import annotations
import copy
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid
from .project import PHASES, ProjectError, atomic_json, digest, inside, now, value_digest
from .decoding import file_source

STAGES={"implementation","verification","handoff"}
IGNORE=shutil.ignore_patterns('.matlab-harness','.git','__pycache__','slprj','*.slxc','*.pyc')


def configure(project,owner,plan,reason):
    if not isinstance(plan,dict) or not isinstance(reason,str) or not reason.strip():
        raise ProjectError("Semantic plan and operator approval reason are required")
    data=project.load();plan=copy.deepcopy(plan)
    stages=plan.get('stages',['verification','handoff'])
    obligations=plan.get('obligations')
    if not isinstance(stages,list) or not stages or not set(stages)<=STAGES:
        raise ProjectError("Semantic stages must be executed checkpoints")
    if not isinstance(obligations,list) or len(obligations)>100:
        raise ProjectError("Semantic obligations must be a bounded list")
    if not obligations and not str(plan.get('not_applicable','')).strip():
        raise ProjectError("An empty semantic plan needs an explicit not-applicable rationale")
    ids=set();requirements={r['id'] for r in data['requirements']}
    for obligation in obligations:
        if not isinstance(obligation,dict) or not {'id','requirement','check','target','reference','mutants'}<=obligation.keys():
            raise ProjectError("Semantic obligation is incomplete")
        identifier=obligation['id']
        if not isinstance(identifier,str) or not identifier.strip() or identifier in ids:
            raise ProjectError("Semantic obligation IDs must be unique text")
        ids.add(identifier)
        if obligation['requirement'] not in requirements or obligation['check'] not in data['commands']:
            raise ProjectError("Semantic obligation must name a registered requirement and declared check")
        target=inside(project.root,obligation['target'])
        if not any(target==inside(project.root,s) or target.is_relative_to(inside(project.root,s)) for s in data['scope']):
            raise ProjectError("Semantic target must be inside engineering scope")
        reference=inside(project.root,obligation['reference'])
        if not reference.is_file():raise ProjectError("Semantic reference file is missing")
        obligation['reference_sha256']=digest(reference)
        obligation['argv']=data['commands'][obligation['check']]
        obligation.setdefault('failure_kind','python-assertion')
        if obligation['failure_kind'] not in {'python-assertion','matlab-assertion'}:
            raise ProjectError("Unsupported semantic assertion kind")
        if obligation['failure_kind']=='matlab-assertion' and (
                not isinstance(obligation.get('assertion_id'),str) or not re.fullmatch(r'[A-Za-z]\w*(?::[A-Za-z]\w*)+',obligation['assertion_id'])):
            raise ProjectError("MATLAB semantic assertions require an explicit property assertion_id used by the approved suite")
        mutants=obligation['mutants'];mids=set()
        if not isinstance(mutants,list) or not 1<=len(mutants)<=50:raise ProjectError("Each obligation needs named intended defects")
        original=reference.read_text(encoding='utf-8')
        for mutant in mutants:
            if not isinstance(mutant,dict) or any(not isinstance(mutant.get(k),str) or not mutant[k] for k in ('id','find','replace','failure_marker')):
                raise ProjectError("Mutant needs id/find/replace/failure_marker text")
            if mutant['id'] in mids or original.count(mutant['find'])!=1 or mutant['find']==mutant['replace']:
                raise ProjectError("Mutant must change one unambiguous reference site and have a unique ID")
            mids.add(mutant['id'])
    plan.update(version=1,stages=stages,reason=reason,approved_at=now())
    with project.transaction(owner) as locked:
        if any(a['checkpoint'] in STAGES for a in locked['acceptances']):
            raise ProjectError("Revise before changing accepted semantic obligations")
        locked['semantic_plan']=plan
    return plan


def _case(argv,root,workspace,directory,timeout,failure_kind,assertion_id=None):
    """Run the declared suite, retaining raw output and owned-process cleanup."""
    from .execution import execute
    actual=[arg.replace(str(root),str(workspace)).replace(root.as_posix(),workspace.as_posix()) for arg in argv]
    if Path(actual[0]).suffix.lower() in {'.bat','.cmd'}:raise ProjectError("Semantic checks require an executable, not a batch wrapper")
    proof=directory/'assertion.json'
    if failure_kind=='python-assertion':
        index=1
        while index<len(actual) and actual[index] in {'-B','-u','-I'}:index+=1
        if index>=len(actual) or actual[index].startswith('-'):
            raise ProjectError("python-assertion requires an approved Python script command, not -c/-m")
        script=Path(actual[index])
        if not script.is_absolute():script=workspace/script
        script=script.resolve()
        if not script.is_relative_to(workspace.resolve()) or script.suffix.lower()!='.py' or not script.is_file():
            raise ProjectError("Semantic Python suite must be a copied project script")
        runner=Path(__file__).with_name('assertion_runner.py').resolve()
        command=[actual[0],*actual[1:index],str(runner),str(script),str(proof),*actual[index+1:]]
    else:
        if len(actual)!=3 or actual[1]!='-batch':raise ProjectError("matlab-assertion requires an approved matlab -batch expression")
        runner=directory/'harness_semantic_case.m'
        q=lambda value:"'"+str(value).replace('\\','/').replace("'","''")+"'"
        write="fid=fopen("+q(proof)+",'w'); fwrite(fid,jsonencode(payload),'char'); fclose(fid);"
        runner.write_text("function harness_semantic_case\ntry\n  eval("+q(actual[2])+");\n"
          +"  payload=struct('version',1,'ok',true,'is_assertion',false,'type','','message','');\n"
          +"catch err\n  payload=struct('version',1,'ok',false,'is_assertion',strcmp(err.identifier,"+q(assertion_id)+"),'type',err.identifier,'message',err.message);\n"
          +"  "+write+"\n  rethrow(err);\nend\n"+write+"\nend\n",encoding='utf-8')
        command=[actual[0],'-batch',"addpath("+q(directory)+"); harness_semantic_case"]
    record=execute(command,workspace,directory,timeout)
    record['declared_argv']=actual
    record['assertion_runner']=file_source(runner,'semantic-assertion-runner')
    if proof.is_file() and proof.stat().st_size<=1_048_576:
        record['assertion_proof']=file_source(proof,'semantic-assertion')
        try:record['assertion']=json.loads(proof.read_text(encoding='utf-8'))
        except (ValueError,UnicodeError):pass
    record['workspace']=str(workspace)
    return record


def _intended_failure(record,obligation,marker):
    if record['status']!='FAILED':return False
    assertion=record.get('assertion',{})
    return (assertion.get('ok') is False and assertion.get('is_assertion') is True
            and assertion.get('message')==marker and record.get('exit_code')!=0)


def _signals(directory,count=3):
    """The first error lines of a case's streams; a suite that collects failures prints them there."""
    from .compact import NOISE,SIGNAL
    lines=[]
    for name in ('stderr.bin','stdout.bin'):
        try:text=(directory/name).read_bytes()[-262144:].decode('utf-8','replace')
        except OSError:continue
        lines+=[line.strip() for line in text.splitlines() if not NOISE.match(line.strip()) and SIGNAL.match(line.strip())]
    return list(dict.fromkeys(lines))[:count]


def _diagnose(case,obligation,mutant,directory):
    """Why one case is inadequate, from what the suite raised. Never names the mutant's edit."""
    assertion=case.get('assertion') or {}
    raised=f"{assertion.get('type') or 'error'}: {assertion.get('message')}" if assertion.get('ok') is False else None
    if mutant is None:
        found=[raised] if raised else []
        found+=[line for line in _signals(directory) if line not in found]
        if case['status']!='FAILED' or not found:
            # A timeout or a launch failure says nothing about the tests; do not point at either side.
            return f"good reference did not complete the suite (status {case['status']}, exit {case.get('exit_code')}, no error line)"
        # The reference meets the contract, so the suite asserts more than it requires. Say what to
        # change: a small model otherwise "fixes" the source or adds more of the same assertions.
        return ('good reference failed the suite, so these tests assert more than requirements.md requires: '
                'relax each to the stated contract and do not change the source to satisfy them; if a test checks '
                'only what requirements.md states, say so in your report. Failures: '+' | '.join(found))[:500]
    else:
        observed=raised or ('the suite passed' if case['status']=='PASSED' else f"status {case['status']}, exit {case.get('exit_code')}")
        text=(f"mutant {mutant['id']} (requirement {obligation['requirement']}) not detected by marker "
              f"{mutant['failure_marker']!r}; observed {observed}")
    return text[:300]


def run(project,owner,stage=None,timeout=None):
    data=project.load();stage=stage or data['phase'];plan=data.get('semantic_plan')
    if not plan or stage not in plan['stages']:raise ProjectError("No required semantic plan for this checkpoint")
    maximum=data['budgets']['native'];timeout=maximum if timeout is None else timeout
    if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or not 0<timeout<=maximum:
        raise ProjectError("Semantic execution must fit original native budget")
    current=value_digest(project.snapshot(data))
    directory=project.control/'semantics'/uuid.uuid4().hex;directory.mkdir(parents=True)
    receipt=directory/'receipt.json'
    result={'version':1,'stage':stage,'snapshot_digest':current,'plan_sha256':value_digest(plan),'status':'STARTED','obligations':[],'diagnosis':[],'started_at':now()}
    atomic_json(receipt,result)
    with project.transaction(owner) as locked:
        locked.setdefault('semantic_results',{})[stage]={'path':receipt.relative_to(project.root).as_posix(),'status':'STARTED'}
    deadline=time.monotonic()+timeout
    try:
        for obligation in plan['obligations']:
            reference=inside(project.root,obligation['reference'])
            if digest(reference)!=obligation['reference_sha256']:raise ProjectError("Approved semantic reference changed")
            row={'id':obligation['id'],'requirement':obligation['requirement'],'cases':[]}
            result['obligations'].append(row)
            original=reference.read_text(encoding='utf-8')
            cases=[None,*obligation['mutants']]
            for mutant in cases:
                left=deadline-time.monotonic()
                if left<=0:raise ProjectError("Semantic execution ceiling exhausted")
                case_dir=directory/f'case-{sum(len(x["cases"]) for x in result["obligations"]):04d}'
                case_dir.mkdir();workspace=case_dir/'project'
                try:
                    shutil.copytree(project.root,workspace,ignore=IGNORE,symlinks=True)
                    if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in workspace.rglob('*')):
                        raise ProjectError("Semantic copies cannot contain filesystem links")
                    target=inside(workspace,obligation['target']);target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_text(original if mutant is None else original.replace(mutant['find'],mutant['replace']),encoding='utf-8')
                    item=_case(obligation['argv'],project.root,workspace,case_dir,max(.001,deadline-time.monotonic()),obligation['failure_kind'],obligation.get('assertion_id'))
                    item['target_sha256']=digest(target)
                finally:
                    # The copy holds the operator's reference source; proof and streams stay in case_dir.
                    shutil.rmtree(workspace,ignore_errors=True)
                item['workspace_removed']=not workspace.exists()
                item['id']='good-reference' if mutant is None else mutant['id']
                item['adequate']=item['status']=='PASSED' if mutant is None else _intended_failure(item,obligation,mutant['failure_marker'])
                if not item['adequate'] and len(result['diagnosis'])<8:
                    line=_diagnose(item,obligation,mutant,case_dir)
                    # One failing reference is shared by every obligation; say it once.
                    if line not in result['diagnosis']:
                        result['diagnosis'].append(line)
                row['cases'].append(item)
                atomic_json(receipt,result)
            row['adequate']=all(c['adequate'] for c in row['cases'])
        result['status']='PASSED' if all(r['adequate'] for r in result['obligations']) else 'INADEQUATE'
        if current!=value_digest(project.snapshot()):
            result['status']='CHANGED_DURING_RUN';result['diagnosis'].insert(0,'project files changed during the semantic run; rerun it')
    except (ProjectError,OSError,ValueError,subprocess.SubprocessError) as exc:
        result.update(status='ERROR',error=str(exc));result['diagnosis'].insert(0,('semantic run error: '+str(exc))[:300])
    result['finished_at']=now();atomic_json(receipt,result)
    with project.transaction(owner) as locked:
        locked['semantic_results'][stage]={'path':receipt.relative_to(project.root).as_posix(),'sha256':digest(receipt),'status':result['status'],
                                          'snapshot_digest':current,'plan_sha256':value_digest(plan),'diagnosis':result['diagnosis'][:8]}
    return result


def problems(project,data,stage):
    if stage not in STAGES:return []
    plan=data.get('semantic_plan')
    if not plan:
        return ['Declare approved semantic adequacy obligations (or explicit non-applicability)'] if stage in {'verification','handoff'} and data.get('proof_policy',{}).get('mode')=='executed' else []
    if stage not in plan['stages']:return []
    entry=data.get('semantic_results',{}).get(stage)
    if not entry:return ['Required semantic adequacy evidence missing']
    if entry.get('status')!='PASSED':
        if entry.get('snapshot_digest')!=value_digest(project.snapshot(data)):
            return ['Required semantic adequacy did not pass ('+str(entry.get('status'))+') and is stale (snapshot changed)']
        # Read from the sealed record, never the receipt file, so edited receipt text cannot reach a prompt.
        reason='; '.join(str(line) for line in entry.get('diagnosis') or [])
        return ['Required semantic adequacy did not pass ('+str(entry.get('status'))+')'+(': '+reason[:900] if reason else '')]
    try:
        path=inside(project.root,entry['path'])
        if not path.is_file() or digest(path)!=entry.get('sha256'):
            return ['Required semantic adequacy evidence changed']
        record=json.loads(path.read_text(encoding='utf-8'))
        if record['snapshot_digest']!=value_digest(project.snapshot(data)) or record['plan_sha256']!=value_digest(plan):
            return ['Required semantic adequacy evidence is stale']
        for obligation in plan['obligations']:
            if digest(inside(project.root,obligation['reference']))!=obligation['reference_sha256']:
                return ['Approved semantic reference changed']
        for row in record['obligations']:
            for case in row['cases']:
                for key in ('stdout','stderr'):
                    source=case[key];artifact=Path(source['artifact']).resolve()
                    if not artifact.is_relative_to(project.control.resolve()) or file_source(artifact)['sha256']!=source['sha256']:
                        return ['Required semantic output evidence changed']
                for key in ('assertion_runner','assertion_proof'):
                    source=case.get(key)
                    if not source or file_source(source['artifact'])['sha256']!=source['sha256']:
                        return ['Required semantic assertion evidence changed or is missing']
        return []
    except (KeyError,OSError,ValueError,ProjectError):return ['Required semantic adequacy evidence unreadable']
