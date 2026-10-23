"""Host-run independent probes with packet-bound, revalidated receipts.

This is evidence provenance, not an OS sandbox. The operator approves runner
executables; scripts run with that user's privileges in a separate process.
"""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from .project import ProjectError, atomic_json, digest, now, value_digest, inside
from .decoding import file_source

EXECUTED = {"implementation", "verification", "handoff"}
# Run proposals executed per reviewer answer; the brief states it.
PROBE_RUNS = 8


def proof_mode(data):
    return data.get("proof_policy", {}).get("mode", "legacy-attested")


def configure(project, owner, runners, reason):
    if not isinstance(reason,str) or not reason.strip() or not isinstance(runners,list):
        raise ProjectError("Probe runners require an operator reason and a list")
    approved = []
    for runner in runners:
        if not isinstance(runner,dict) or runner.get("kind") not in {"python","matlab"}:
            raise ProjectError("Probe runner kind must be python or matlab")
        executable = shutil.which(str(runner.get("executable", "")))
        if not executable or Path(executable).suffix.lower() in {".bat",".cmd"}:
            raise ProjectError("Probe runner must resolve to an executable, never a batch wrapper")
        try:
            fingerprint=digest(Path(executable))
        except OSError as exc:
            raise ProjectError("Probe runner cannot be fingerprinted; configure a readable installed executable rather than an OS alias") from exc
        approved.append({"kind":runner["kind"], "executable":str(Path(executable).resolve()), "sha256":fingerprint})
    with project.transaction(owner) as data:
        if any(a["checkpoint"] in EXECUTED for a in data["acceptances"]):
            raise ProjectError("Revise before changing accepted proof policy")
        data["proof_policy"]={"version":1,"mode":"executed","runners":approved,"reason":reason,"at":now()}
    return data["proof_policy"]


def _inputs(project, names):
    if not isinstance(names,list) or len(names)>1000 or any(not isinstance(x,str) for x in names):
        raise ProjectError("Probe inputs must be a bounded list of project paths")
    return {name:digest(inside(project.root,name)) for name in map(lambda x:_relative(project,x),names)}


def _relative(project, name):
    """A contained absolute path as its project-relative name; anything else unchanged."""
    if not Path(name).is_absolute():return name
    path,root=Path(name).resolve(),project.root.resolve()
    if os.path.normcase(str(path)).startswith(os.path.normcase(str(root))+os.sep):
        return Path(os.path.relpath(path,root)).as_posix()
    return name


def run(project, owner, packet_id, check_id, script, reviewer_session, runner=0, arguments=None, inputs=None, timeout=None):
    from .answer import latest_packet, _in_scratch
    handoff=latest_packet(project,packet_id)
    data=project.load()
    if handoff.get("role")!="reviewer" or handoff.get("checkpoint")!=data["phase"]:
        raise ProjectError("Probe requires a reviewer packet for the current checkpoint")
    if data["owner"] != owner:
        raise ProjectError("Only the claimed orchestrator can execute probes")
    if not isinstance(reviewer_session,str) or not reviewer_session.strip() or reviewer_session in {data["builder_session"],*data.get("contributors",[])}:
        raise ProjectError("A separate reviewer session is required")
    if not isinstance(check_id,str) or not check_id.strip():
        raise ProjectError("Probe check ID is required")
    if handoff["snapshot_digest"] != value_digest(project.snapshot(data)):
        raise ProjectError("Probe packet is stale")
    script_path=_in_scratch(project,Path(handoff["scratch"]),script)
    if script_path is None:
        raise ProjectError("Probe script must be a current packet scratch file")
    runners=data.get("proof_policy",{}).get("runners",[])
    if isinstance(runner,bool) or not isinstance(runner,int) or not 0<=runner<len(runners):
        raise ProjectError("No approved probe runner at this index; configure-probes first")
    approved=runners[runner]
    if digest(Path(approved["executable"])) != approved["sha256"]:
        raise ProjectError("Approved probe executable changed")
    arguments=[] if arguments is None else arguments
    if not isinstance(arguments,list) or len(arguments)>1000 or any(not isinstance(a,str) or '\0' in a for a in arguments):
        raise ProjectError("Probe arguments must be a bounded string list")
    if approved["kind"]=="python" and script_path.suffix.lower()==".py":
        argv=[approved["executable"],"-B",str(script_path),*arguments]
    elif approved["kind"]=="matlab" and script_path.suffix.lower()==".m" and not arguments:
        argv=[approved["executable"],"-batch","run('"+script_path.as_posix().replace("'","''")+"')"]
    else:
        raise ProjectError("Probe script/arguments do not match the approved runner kind")
    maximum=data.get("budgets",{}).get("native",1800)
    timeout=maximum if timeout is None else timeout
    if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or not 0<timeout<=maximum:
        raise ProjectError("Probe timeout must fit the original native budget")
    record={"version":1,"id":"P-"+uuid.uuid4().hex,"packet_id":Path(handoff["prompt"]).parent.name,
            "check_id":check_id,"checkpoint":handoff["checkpoint"],"reviewer_session":reviewer_session,"snapshot_digest":handoff["snapshot_digest"],
            "script":script_path.relative_to(project.root).as_posix(),"script_sha256":digest(script_path),
            "inputs":_inputs(project,inputs or []),"runner":approved,"argv":argv,"started_at":now(),"status":"STARTED"}
    directory=project.control/"probes"/record["id"]
    directory.mkdir(parents=True)
    receipt=directory/"receipt.json"
    atomic_json(receipt,record)
    # Intent commits before launch, so interruption cannot silently erase it.
    with project.transaction(owner) as locked:
        locked.setdefault("probe_receipts",{})[record["id"]]={"path":receipt.relative_to(project.root).as_posix(),"status":"STARTED"}
    from .execution import execute
    execution=execute(argv,project.root,directory,timeout)
    record.update({k:v for k,v in execution.items() if k not in {"argv","cwd","started_at"}})
    try:
        if (record["script_sha256"]!=digest(script_path) or record["inputs"]!=_inputs(project,list(record["inputs"]))
                or record["snapshot_digest"]!=value_digest(project.snapshot())):
            record["status"]="CHANGED_DURING_RUN"
    except (OSError,ProjectError) as exc:
        record.update(status="CHANGED_DURING_RUN",error=str(exc))
    atomic_json(receipt,record)
    with project.transaction(owner) as locked:
        locked["probe_receipts"][record["id"]].update(status=record["status"],sha256=digest(receipt))
    return record


def validate(project, scratch, check, reviewer_session=None):
    """False on missing, stale, failed, altered or wrong-identity receipt."""
    return receipt_problem(project, scratch, check, reviewer_session) is None


def receipt_problem(project, scratch, check, reviewer_session=None):
    """Why this check's host receipt does not prove it, or None. The reason goes back to the
    reviewer, so it says what to change, never only that the receipt is invalid."""
    from .answer import _in_scratch
    try:
        data=project.load()
        entry=data.get("probe_receipts",{}).get(check.get("receipt_id"))
        if not entry:return "no host receipt; include run:{script,...} so the host runs it"
        if entry.get("status")!="PASSED":return "its probe did not pass on the host ("+str(entry.get("status"))+")"
        path=inside(project.root,entry["path"])
        if not path.is_file() or digest(path)!=entry.get("sha256"):return "its receipt file changed after the run"
        record=json.loads(path.read_text(encoding="utf-8"))
        from .answer import latest_packet
        packet=latest_packet(project,Path(scratch).name)
        if packet.get("role")!="reviewer":return "its scratch is not a reviewer packet's scratch"
        if packet.get("checkpoint")!=data["phase"] or record.get("checkpoint")!=packet["checkpoint"]:
            return "the receipt belongs to another checkpoint"
        script=_in_scratch(project,Path(scratch),check.get("artifact"))
        if script is None or script.relative_to(project.root).as_posix()!=record["script"]:
            return f"its artifact is not the script its probe ran ({record['script']}); name that script as the artifact"
        if record["status"]!="PASSED" or record["exit_code"]!=0:return f"its probe exited {record['exit_code']}"
        if record["check_id"]!=check["id"]:return f"the receipt is for check {record['check_id']}"
        if record["packet_id"]!=Path(scratch).name:return "the receipt belongs to another review packet"
        if record["script_sha256"]!=digest(script):return "the script changed after it ran"
        if record["snapshot_digest"]!=value_digest(project.snapshot(data)):return "project files changed after the probe ran"
        if reviewer_session is not None and record["reviewer_session"]!=reviewer_session:
            return "another reviewer session ran it"
        if record["inputs"]!=_inputs(project,list(record["inputs"])):return "an input file changed after the probe ran"
        for key in ("stdout","stderr"):
            source=record[key]
            artifact=Path(source["artifact"]).resolve()
            if not artifact.is_relative_to(project.control.resolve()) or file_source(artifact)["sha256"]!=source["sha256"]:
                return "its recorded "+key+" changed"
        if digest(Path(record["runner"]["executable"]))!=record["runner"]["sha256"]:return "the runner executable changed"
        return None
    except ProjectError as exc:
        return "the receipt cannot be checked: "+str(exc)[:160]
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        return "the receipt or its packet cannot be read ("+type(exc).__name__+")"


def _receipt_record(project, receipt_id):
    """The host record a receipt id names; ProjectError when no receipt has that id."""
    entry=project.load().get("probe_receipts",{}).get(receipt_id) if isinstance(receipt_id,str) else None
    if not isinstance(entry,dict):raise ProjectError("no host receipt; include run:{script,...} so the host runs it")
    return json.loads(inside(project.root,entry["path"]).read_text(encoding="utf-8"))


def review_problems(project, report):
    if proof_mode(project.load())!="executed" or report.get("checkpoint") not in EXECUTED:return []
    from .answer import latest_packet
    try:
        if not isinstance(report.get("packet_id"),str) or not report["packet_id"]:raise ProjectError("Packet ID required")
        handoff=latest_packet(project,report["packet_id"])
        if (handoff.get("role")!="reviewer" or handoff.get("checkpoint")!=report["checkpoint"]
                or handoff["snapshot_digest"]!=report["snapshot_digest"]):raise ProjectError("Packet provenance mismatch")
    except (ProjectError,KeyError,OSError,ValueError):
        return ["Executed review requires an explicit matching current reviewer packet"]
    expected_scratch=Path(handoff["scratch"])
    checks=report.get("independent_checks",[])
    problems=[]
    scratches=set()
    # One line per reason, so many checks refused alike stay inside the correction brief.
    reasons={}
    for check in checks:
        if check.get("result")!="PASS":continue
        try:
            record=_receipt_record(project,check.get("receipt_id"))
            if record["packet_id"]!=Path(handoff["prompt"]).parent.name or record.get("checkpoint")!=report["checkpoint"]:
                problem=("its receipt_id is from an earlier review packet or checkpoint; keep run and drop receipt_id"
                         " so the host runs it for this packet")
            else:
                scratches.add(expected_scratch)
                problem=receipt_problem(project,expected_scratch,check,report.get("reviewer_session"))
        except ProjectError as exc:
            problem=str(exc)
        except (KeyError,ValueError,OSError,TypeError) as exc:
            problem="the receipt cannot be read ("+type(exc).__name__+")"
        if problem:reasons.setdefault(problem,[]).append(str(check.get("id")))
    for problem,ids in reasons.items():
        problems.append("Invalid host execution receipt for check"+("s " if len(ids)>1 else " ")+", ".join(ids)+": "+problem)
    if report.get("verdict")=="ACCEPT" and not any(c.get("result")=="PASS" and c.get("receipt_id") for c in checks):
        problems.append("At least one host-executed passing independent probe is required")
    from .answer import _proofs, _proved
    for finding in [*report.get("findings",[]),*report.get("protocol_dispositions",[])]:
        if finding.get("status")!="CLOSED":continue
        evidence=str(finding.get("evidence",""))+"; "+str(finding.get("closure",""))
        if not any(_proved(evidence,_proofs(project,scratch,checks,set())) for scratch in scratches):
            problems.append("Closed finding/allegation lacks bound passing proof: "+str(finding.get("id",finding.get("finding_digest"))))
    return problems


def execute_proposals(project, owner, handoff, response, session, seconds):
    """After model exit and lock release, run bounded explicitly proposed probes."""
    from .decoding import ReviewInput
    from .answer import _canonical_answer, _shape, _leaves, CHECK_FIELDS, _AnswerBoundaryError
    wrapped=isinstance(response,ReviewInput)
    if wrapped and response.problems:return response
    if proof_mode(project.load())!="executed" or handoff["checkpoint"] not in EXECUTED:return response
    try:
        answer=_canonical_answer(response.answer if wrapped else response)
    except _AnswerBoundaryError:
        return response
    shaped=_shape(answer,[])
    if shaped is None:return response
    deadline=time.monotonic()+seconds
    count=0
    packet_id=Path(handoff["prompt"]).parent.name
    for entry,keys in _leaves(shaped.get("independent_checks"),CHECK_FIELDS):
        if not isinstance(entry,dict) or "run" not in entry:continue
        if entry.get("receipt_id"):
            try:
                if _receipt_record(project,entry["receipt_id"])["packet_id"]==packet_id:continue
            except (ProjectError,OSError,ValueError,KeyError,TypeError):
                pass
            # A report copied from an earlier packet carries that packet's receipt; run it afresh here.
            entry.pop("receipt_id")
        count+=1
        try:
            if count>PROBE_RUNS:
                raise ProjectError(f"only {PROBE_RUNS} runs are executed per answer; put more cases in one script")
            if time.monotonic()>=deadline:
                raise ProjectError("Probe execution ceiling exhausted; no automatic budget extension")
            proposal=entry["run"]
            if not isinstance(proposal,dict):raise ProjectError("Probe run proposal must be an object")
            record=run(project,owner,Path(handoff["prompt"]).parent.name,entry.get("id"),proposal.get("script"),
                       session,proposal.get("runner",0),proposal.get("arguments",[]),proposal.get("inputs",[]),
                       min(deadline-time.monotonic(),project.load()["budgets"]["native"]))
            entry["receipt_id"]=record["id"]
            if record["status"]!="PASSED" and entry.get("result")=="PASS":
                entry["result"]="ERROR"
                entry["observed"]=str(entry.get("observed",""))+"; host execution: "+record["status"]
        except (ProjectError,OSError,ValueError,TypeError) as exc:
            entry["result"]="ERROR"
            entry["observed"]=str(entry.get("observed",""))+"; host probe refused: "+str(exc)
    if wrapped:
        response.answer=answer
        return response
    return answer
