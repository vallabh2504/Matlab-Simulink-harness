"""Operator onboarding and durable role handoffs, independent of the agent provider."""
from __future__ import annotations

import json
import math
from pathlib import Path
import uuid

from .charter import CONTRACT_DISCIPLINE, PRODUCER_GUIDANCE, REVIEWER_CHARTER
from .project import DEFAULT_BUDGETS, PHASES, Project, ProjectError, ReviewProtocolError, atomic_json, digest, non_document_artifacts, now, value_digest
from .skills import select_for


STAGE_GUIDANCE = {
    "requirements": "Inspect existing files and clarify consequential ambiguity. Draft requirements.md with stable IDs, units, provenance and acceptance methods; register IDs. Obtain actual user approval before construction.",
    "architecture": "Write governing equations, dimensional checks, solver rationale, interfaces, parameter ownership and proportionate architecture. Declare implementation/verification check commands derived from the design before independent design acceptance.",
    "implementation": "Implement only the accepted requirements/design in owned files. Protect legacy behavior, run MATLAB or Simulink and inspect saved artifacts. Retain editable sources and executable engineering checks.",
    "verification": "Run declared checks against stable artifacts. Use independent analytical/numerical oracles, boundary cases, convergence and legacy regressions. Inspect actual outputs; a process exit alone is insufficient engineering evidence.",
    "handoff": "Reproduce from the project entry point. Deliver source, saved models when required, parameter provenance, traceability, results, reviewer findings and explicit limitations. Close or interrupt every task lease.",
}

REVIEW_GUIDANCE = {
    "requirements": "Assess the requirements for consequential ambiguity, dimensional consistency, provenance, acceptance methods and actual authorization.",
    "architecture": "Assess the governing equations, dimensional checks, solver rationale, interfaces, parameter ownership and declared downstream checks against the accepted requirements.",
    "implementation": "Assess the existing implementation against accepted requirements and design, including legacy behavior, editable sources and native engineering evidence. Report defects for a separate repair worker.",
    "verification": "Assess the declared check results, independent analytical/numerical oracles, boundary cases, convergence and legacy regressions. Inspect actual outputs and distinguish an engineering result from a process exit.",
    "handoff": "Assess reproducibility from the project entry point, source and saved models, parameter provenance, traceability, results, limitations and outstanding task leases.",
}

REVIEW_SCHEMA = {"type": "object", "properties": {
    "checkpoint": {"type": "string", "enum": list(PHASES)},
    "verdict": {"type": "string", "enum": ["ACCEPT", "REJECT", "INCOMPLETE"]},
    "snapshot_digest": {"type": "string"},
    "findings": {"type": "array", "items": {"type": "object", "properties": {
        field: {"type": "string"} for field in
        ("id", "severity", "kind", "artifact", "evidence", "impact", "repair", "closure", "status", "prior_finding_digest")},
        "required": ["id", "severity", "kind", "artifact", "evidence", "impact", "repair", "closure", "status"]}}},
    "required": ["checkpoint", "verdict", "snapshot_digest", "findings"]}
REVIEW_SCHEMA["properties"]["findings"]["items"]["properties"].update({
    "severity": {"type": "string", "enum": ["CRITICAL", "MAJOR", "MODERATE", "MINOR"]},
    "kind": {"type": "string", "enum": ["PROVEN DEFECT", "EVIDENCE GAP", "POTENTIAL DEFECT", "OPTIONAL IMPROVEMENT"]},
    "status": {"type": "string", "enum": ["OPEN", "CLOSED", "DISPUTED", "ACCEPTED-RISK"]},
})
for _field in REVIEW_SCHEMA["properties"]["findings"]["items"]["required"]:
    REVIEW_SCHEMA["properties"]["findings"]["items"]["properties"][_field]["minLength"] = 1


TRACE_STATUSES = ["VERIFIED", "PARTIAL", "FAILED", "UNVERIFIED"]
REVIEW_SCHEMA["properties"]["traceability"] = {"type": "array", "items": {
    "type": "object", "properties": {
        "requirement": {"type": "string", "minLength": 1}, "status": {"type": "string", "enum": TRACE_STATUSES},
        "evidence": {"type": "string", "minLength": 1}, "finding_ids": {"type": "string"}},
    "required": ["requirement", "status", "evidence", "finding_ids"]}}
REVIEW_SCHEMA["properties"]["independent_checks"] = {"type": "array", "items": {
    "type": "object", "properties": {
        **{field: {"type": "string", "minLength": 1} for field in
           ("id", "purpose", "requirements", "command", "expected", "observed", "artifact")},
        "result": {"type": "string", "enum": ["PASS", "FAIL", "ERROR"]}, "finding_ids": {"type": "string"}},
    "required": ["id", "purpose", "requirements", "command", "expected", "observed", "result", "artifact", "finding_ids"]}}
REVIEW_SCHEMA["required"] += ["traceability", "independent_checks"]
EXECUTED_CHECKPOINTS = {"implementation", "verification", "handoff"}


REVIEW_SCHEMA["properties"]["protocol_dispositions"] = {"type": "array", "items": {
    "type": "object", "properties": {
        "finding_digest": {"type": "string"}, "status": {"type": "string", "enum": ["CLOSED", "TRACKED"]},
        "finding_id": {"type": "string"}, "evidence": {"type": "string", "minLength": 1},
        "closure": {"type": "string", "minLength": 1}},
    "required": ["finding_digest", "status", "finding_id", "evidence", "closure"]}}


def start(directory, title, builder, owner, scope, brief="", runtime=None, budgets=None, repair_budget=10):
    project = Project.initialize(directory, title, builder, scope)
    project.claim(owner)
    project.configure_runtime(owner, budgets, repair_budget, runtime)
    for stage in ("requirements", "architecture"):
        project.configure_checks(owner, stage, {})
    # Control-local onboarding never overwrites the user's AGENTS.md or model.
    (project.control / "brief.md").write_text(brief or title, encoding="utf-8")
    guide = "# ENG project workflow\n\n" + "\n\n".join(
        f"## {stage}\n\n{STAGE_GUIDANCE[stage]}" for stage in PHASES)
    guide += "\n\nUse matlab-harness --project <root> next for current evidence and actionable steps. "
    guide += "Use packet --role builder|reviewer|repair to produce a durable task handoff. "
    guide += "Execution uses configured runtime adapters; manual packets work with native Codex/Claude agents. "
    guide += "Actual user approval is attested with approve; the harness cannot manufacture it.\n"
    (project.control / "workflow.md").write_text(guide, encoding="utf-8")
    return next_step(project)


def next_step(project):
    data = project.load()
    project._seed_defects(data)
    stage = data["phase"]
    gate = project.gate(stage)
    handed_off = "handoff" in {a["checkpoint"] for a in data["acceptances"]}
    completed = handed_off and gate["accepted"]
    reports = {}
    for checkpoint, item in data["reviews"].items():
        path = project.root / item["path"]
        if path.is_file() and digest(path) == item["sha256"]:
            reports[checkpoint] = json.loads(path.read_text(encoding="utf-8"))
    checks = []
    for name in data["required_checks"].get(stage, []):
        entry = data["evidence"].get(name)
        status = "MISSING"
        if entry:
            path = project.root / entry["path"]
            if path.is_file() and digest(path) == entry["sha256"]:
                evidence = json.loads(path.read_text(encoding="utf-8"))
                status = evidence["status"] if evidence["snapshot"] == project.snapshot(data) else "STALE"
            else:
                status = "TAMPERED_OR_MISSING"
        checks.append({"name": name, "status": status, "argv": data["commands"][name]})
    return {"project": str(project.root), "phase": stage, "completed": completed,
            "guidance": STAGE_GUIDANCE[stage], "gate": gate,
            "next_action": "Project accepted; use revise for changed requirements" if completed else
                           "Previously accepted handoff changed; inspect artifacts, revise and re-review" if handed_off else
                           f"accept {stage}" if gate["accepted"] else "Resolve the listed gate problems, then obtain independent checkpoint review",
            "checks": checks, "reviews": reports,
            "defects": data.get("defects", {}),
            "active_tasks": {k: t for k, t in data["tasks"].items() if t["status"] == "ACTIVE"},
            "budgets": {**DEFAULT_BUDGETS, **data.get("budgets", {})},
            "repairs_remaining": data["repair_budget"] - data["repairs"],
            "runtime": data.get("runtime", {"adapter": "manual"})}


def _clip(value, limit=300):
    return value if len(value) <= limit else value[:limit] + "..."


def _scratch_files(project, scratch):
    if not scratch.is_dir():
        return {}
    return {path.relative_to(project.root).as_posix(): digest(path)
            for path in sorted(scratch.rglob("*")) if path.is_file()}


def charter_problems(project, response, data, stage, scratch):
    """Structural minimum of the reviewer charter; it never supplies a verdict."""
    findings = {f.get("id") for f in response.get("findings", []) if isinstance(f, dict)}
    ids = [r["id"] for r in data["requirements"]]
    rows = response.get("traceability")
    if not isinstance(rows, list):
        return "traceability must list one row per registered requirement ID"
    seen = [row.get("requirement") for row in rows if isinstance(row, dict)]
    missing = [i for i in ids if i not in seen]
    if missing or len(seen) != len(rows) or len(set(seen)) != len(seen):
        return "traceability must list each registered requirement ID exactly once; missing: " + ", ".join(missing)
    for row in rows:
        cited = {item.strip() for item in str(row.get("finding_ids", "")).split(",") if item.strip()}
        if row.get("status") not in TRACE_STATUSES or not str(row.get("evidence", "")).strip():
            return "traceability row needs a valid status and evidence: " + str(row.get("requirement"))
        if response["verdict"] == "ACCEPT" and row["status"] == "FAILED":
            return "ACCEPT is inconsistent with FAILED requirement " + row["requirement"]
        if response["verdict"] == "ACCEPT" and row["status"] != "VERIFIED" and not (cited & findings):
            return "requirement " + row["requirement"] + " is " + row["status"] + " under ACCEPT without a finding in this report"
    checks = response.get("independent_checks")
    if not isinstance(checks, list):
        return "independent_checks must be a list"
    if stage in EXECUTED_CHECKPOINTS:
        root = scratch.resolve()
        existing = []
        for check in checks:
            if not isinstance(check, dict):
                continue
            location = Path(str(check.get("artifact", "")).strip().replace("\\", "/"))
            for candidate in ((location,) if location.is_absolute() else (project.root / location, scratch / location)):
                if candidate.is_file() and candidate.resolve().is_relative_to(root):
                    existing.append(check)
                    break
        if not existing:
            return ("no independent check names an existing artifact in the scratch directory " + str(scratch)
                    + "; re-running the builder's tests is not independent review")
    return None


def packet(project, role, checkpoint=None, task=""):
    if role not in {"builder", "reviewer", "repair"}:
        raise ProjectError("Unknown role")
    data = project.load()
    project._seed_defects(data)
    stage = checkpoint or data["phase"]
    if stage not in PHASES:
        raise ProjectError("Unknown checkpoint")
    snapshot = project.snapshot(data)
    identifier = uuid.uuid4().hex
    directory = project.control / "packets" / identifier
    scratch = project.control / "scratch" / identifier
    context_path = directory / "context.json"
    context_name = context_path.relative_to(project.root).as_posix()
    brief_path = project.control / "brief.md"
    brief = brief_path.read_text(encoding="utf-8") if brief_path.is_file() else data["title"]
    requirement_text = " ".join(r["text"] for r in data["requirements"])
    selected = select_for(stage, role, " ".join((data["title"], brief, requirement_text, task)))
    prompt = f"ENG {role} task; project root: {project.root}\nCheckpoint: {stage}\n"
    if role == "reviewer":
        prompt += "Your role is independent, read-only review. Do not implement or repair anything, including an obvious defect. Do not rewrite requirements, design, source or results. Return findings for the orchestrator to assign to a separate repair worker.\n"
        prompt += REVIEW_GUIDANCE[stage] + "\n"
        prompt += REVIEWER_CHARTER
    elif role == "repair":
        prompt += "Repair only the recorded findings in owned engineering files, preserving accepted scope and prior evidence.\n"
        prompt += CONTRACT_DISCIPLINE
    else:
        prompt += STAGE_GUIDANCE[stage] + "\n"
        prompt += PRODUCER_GUIDANCE.get(stage, "")
        prompt += CONTRACT_DISCIPLINE
    prompt += (f"Scratch directory for every probe, temporary script, copied source and output of yours: {scratch}. "
               "Write nothing else outside owned scope; out-of-scope project files are restored and new executable files there are quarantined after your role.\n")
    prompt += f"Read requirements.md, .matlab-harness/brief.md and {context_name}, inspect actual artifacts, and read each selected skill file before starting. "
    prompt += "The generated context is a focused view of current project truth. Full .matlab-harness/project.json and archived reports remain available for a specific history question; avoid repeatedly reading all prior run receipts and repair transcripts. Do not edit the generated context. "
    prompt += "Use native MATLAB/Simulink tools and primary documentation when useful. Discovery and reversible checks are encouraged. "
    prompt += "Preserve existing files and private data. Keep engineering truth, independent review and honest unsupported classifications mandatory.\n"
    prompt += "The orchestrator owns mutations of project records, approval, registered check execution and checkpoint acceptance. "
    prompt += "Do not issue mutating matlab-harness commands or edit .matlab-harness/project.json during this role. "
    prompt += "Return unresolved approval needs and check-plan proposals; never manufacture approval.\n"
    if stage in {"requirements", "architecture"}:
        prompt += "This is a document/design checkpoint. Do not create or change MATLAB/Simulink implementation, saved models, data or results. Propose executable checks in the design for later implementation; do not implement those probes now. "
        prompt += "Preserve the approved requirements contract. Record consequential corrections as proposals for the orchestrator rather than silently imposing new schemas, interfaces or acceptance obligations.\n"
    prompt += f"Owned engineering scope: {json.dumps(data['scope'])}\n"
    prompt += f"User approval records: {json.dumps(data['approvals'])}\n"
    prompt += f"Declared check plan: {json.dumps(data['required_checks'].get(stage, []))}\n"
    prompt += f"Snapshot digest: {value_digest(snapshot)}\n"
    prompt += f"Selected skills: {json.dumps([{'name': e['name'], 'path': e['path']} for e in selected])}\n"
    prior = {k: {"verdict_record": v["path"]} for k, v in data["reviews"].items()}
    prompt += f"Prior review records: {json.dumps(prior)}\nTask detail: {task}\n"
    defect_context = {k: {"finding": v["finding"], "blocking": v["blocking"],
                           "origin_artifact": v["origin"]["artifact"],
                           "origin_digest": v.get("origin_digest")}
                      for k, v in data.get("defects", {}).items() if k.startswith(stage + ":")}
    carried = {k: {field: _clip(v["finding"].get(field, "")) for field in ("severity", "kind", "artifact", "evidence", "repair")}
               for k, v in data.get("defects", {}).items()
               if not k.startswith(stage + ":") and v["finding"]["status"] == "OPEN"}
    prompt += f"Durable findings for this checkpoint (complete history is in project records): {json.dumps(defect_context)}\n"
    if carried:
        prompt += (f"Open findings carried from other checkpoints: {json.dumps(carried)}\n"
                   "Address each where your role allows; every one must be dispositioned by ID in the handoff documentation. "
                   + ("If one still holds now, report it as a current finding with a new ID that cites the original key.\n" if role == "reviewer" else "\n"))
    if role == "reviewer":
        pending = {key: item for key, item in project.pending_review_findings(data).items()
                   if item["checkpoint"] == stage}
        if pending:
            prompt += f"Pending serious allegations from rejected reports (not established engineering truth): {json.dumps(pending)}\n"
            prompt += "Before ACCEPT, explicitly disposition every pending allegation by finding_digest in protocol_dispositions: CLOSED requires observed closure or counterevidence in evidence/closure; TRACKED must name an unresolved CRITICAL/MAJOR finding in this report via finding_id. For CLOSED use an empty finding_id when no ordinary finding is needed. Do not erase an allegation by omission, or treat a malformed report as proof that its engineering allegations are true.\n"
        else:
            prompt += "Return protocol_dispositions as an empty list.\n"
        if stage in {"requirements", "architecture"}:
            prompt += "Assess whether this checkpoint's contract/design supports the requested engineering work. Missing future implementation, simulation results or final delivery artifacts alone do not make this document checkpoint incomplete. Do flag actual contradictions or consequential ambiguities using the exact contract text. "
            prompt += "Do not invent a required metadata representation when the contract explicitly allows equivalent forms. Optional specification improvements can remain nonblocking findings; choose your verdict independently from the actual checkpoint obligations.\n"
        prompt += "Return findings for this checkpoint only, with each issue ID appearing once. Do not copy closed findings from other checkpoints into this report; those closures are already retained under their own checkpoints. Assess any current cross-cutting defect as a current finding with concrete evidence.\n"
        prompt += "Your execution must leave scoped artifacts unchanged; generated outputs go to the scratch directory. If reproduction necessarily changes scoped artifacts, propose that check instead of executing it during review.\n"
        prompt += "Requirements and architecture may have empty executable check plans: their independent review is the declared checkpoint obligation. Implementation, verification and handoff require native checks. Do not invent a universal executable check for a document. "
        prompt += "User approval is an attestation of actual authorization, not cryptographic authentication. Distinguish authorized task scope and explicitly labeled experiment assumptions from unapproved consequential user requirements. Evaluate supplied authorization evidence and counterevidence rather than demanding repeated permission for already authorized work. "
        if (project.control / "counterevidence.md").is_file():
            prompt += "Read .matlab-harness/counterevidence.md and reassess prior claims against its concrete evidence before closure or further blocking. "
        prompt += "Review independently. Do not modify scoped artifacts. Return a JSON object with checkpoint, verdict (ACCEPT/REJECT/INCOMPLETE), snapshot_digest, findings, traceability, independent_checks and protocol_dispositions. "
        prompt += "Each finding requires id, severity (CRITICAL/MAJOR/MODERATE/MINOR), kind (PROVEN DEFECT/EVIDENCE GAP/POTENTIAL DEFECT/OPTIONAL IMPROVEMENT), artifact, evidence, impact, repair, closure, status (OPEN/CLOSED/DISPUTED/ACCEPTED-RISK). "
        prompt += "All required finding fields must be nonempty. For an OPEN finding, closure describes the specific future check that would demonstrate resolution; it does not claim that resolution already happened. For CLOSED findings, closure records observed resolution evidence. "
        prompt += "Require reproducible evidence and classify uncertainty honestly; score or style preference cannot outweigh a demonstrated engineering defect.\n"
        prompt += "For EVERY prior finding you include, keep its ID and origin_artifact string EXACTLY, including order and punctuation, for OPEN as well as CLOSED records. Additional repair files belong in evidence and closure, not in the identity's artifact field. Use a new ID for a different issue. "
        prompt += "Close prior blocking findings explicitly using that exact identity, status CLOSED and prior_finding_digest equal to its origin_digest; provide current closure evidence. A proposed repair or a protocol correction does not prove closure.\n"
    elif role == "repair":
        if stage in {"requirements", "architecture"}:
            prompt += "Clarify only the recorded document/design issue in owned documentation. Describe a future regression check; do not implement it. Read the original contract before proposing a schema. Return consequential contract corrections for orchestrator disposition and independent review.\n"
        else:
            prompt += "Repair specific recorded findings; retain failed evidence, add a meaningful regression probe, rerun checks and request independent closure.\n"
    directory.mkdir(parents=True)
    decisions = []
    for index, decision in enumerate(data["decisions"]):
        if decision.get("source") == "repair":
            decisions.append({"project_record_index": index, "source": "repair", "at": decision.get("at"),
                              "note": "Full repair transcript remains in project.json; current actionable findings are in this packet."})
        else:
            decisions.append(decision)
    context = {"project": str(project.root), "project_id": data["id"], "phase": stage,
               "snapshot_digest": value_digest(snapshot), "requirements": data["requirements"],
               "approvals": data["approvals"], "scope": data["scope"], "decisions": decisions,
               "checks": data["required_checks"], "commands": data["commands"],
               "evidence": data["evidence"],
               "reviews": {k: {"path": v["path"], "sha256": v["sha256"], "recorded": v["recorded"]} for k, v in data["reviews"].items()},
               "defects": defect_context, "carried_open_findings": {k: data["defects"][k]["finding"] for k in carried},
               "active_tasks": {k: v for k, v in data["tasks"].items() if v["status"] == "ACTIVE"},
               "full_record": ".matlab-harness/project.json"}
    atomic_json(context_path, context)
    path = directory / "prompt.md"
    path.write_text(prompt, encoding="utf-8")
    scratch.mkdir(parents=True)
    record = {"role": role, "checkpoint": stage, "created": now(), "snapshot_digest": value_digest(snapshot),
              "prompt": str(path), "prompt_sha256": digest(path), "selected_skills": selected, "scratch": str(scratch),
              "context": str(context_path), "context_sha256": digest(context_path)}
    atomic_json(directory / "packet.json", record)
    return record


def execute(project, owner, role, checkpoint=None, task="", remaining_seconds=None):
    from .runtime import execute_role
    data = project.load()
    if data["owner"] != owner:
        raise ProjectError("Only the claimed orchestrator may execute a role")
    stage = checkpoint or data["phase"]
    if stage != data["phase"] or "handoff" in {a["checkpoint"] for a in data["acceptances"]}:
        raise ProjectError("Execute roles for the current unaccepted checkpoint")
    unfinished = project.unfinished_review_imports(data)
    if unfinished:
        return {"status": "INPUT_REQUIRED", "reason": "Interrupted review import requires inspection before another role dispatch",
                "unfinished_review_imports": unfinished}
    boundaries = project.unrestored_stage_boundaries(data)
    if role != "reviewer" and boundaries:
        return {"status": "INPUT_REQUIRED", "reason": "Restore recorded document/design boundary violations before further construction",
                "stage_boundary_violations": boundaries}
    if role != "reviewer" and stage in {"implementation", "verification", "handoff"}:
        project._approval_current(data)
        if not {"requirements", "architecture"} <= {a["checkpoint"] for a in data["acceptances"]}:
            raise ProjectError("Construction requires accepted requirements and architecture")
    config = dict(data.get("runtime", {"adapter": "manual"}))
    roles = config.pop("roles", {})
    config.update(roles.get(role, {}))
    config["timeout"] = data.get("budgets", DEFAULT_BUDGETS).get(role, DEFAULT_BUDGETS[role])
    if remaining_seconds is not None:
        if isinstance(remaining_seconds, bool) or not isinstance(remaining_seconds, (int, float)) or not math.isfinite(remaining_seconds) or remaining_seconds <= 0:
            raise ProjectError("Remaining execution seconds must be finite and positive")
        config["timeout"] = min(config["timeout"], remaining_seconds)
    if config.get("adapter") == "manual":
        return {"status": "MANUAL_HANDOFF", "packet": packet(project, role, stage, task)}
    if role == "repair":
        project.repair(owner, task or "Repair actual recorded reviewer findings")
    handoff = packet(project, role, stage, task)
    directory = Path(handoff["prompt"]).parent / "execution"
    prompt = Path(handoff["prompt"]).read_text(encoding="utf-8")
    before = project.snapshot()
    boundary = None
    review_schema = None
    if role == "reviewer":
        # Structured runtimes can prevent transcription errors without supplying
        # the reviewer's verdict or findings. Import still verifies the live tree.
        review_schema = json.loads(json.dumps(REVIEW_SCHEMA))
        review_schema["properties"]["checkpoint"]["enum"] = [stage]
        review_schema["properties"]["snapshot_digest"]["enum"] = [handoff["snapshot_digest"]]
    # Keep workflow state serialized while an external role is using its contract.
    scratch = Path(handoff["scratch"])
    with project.transaction(owner) as locked:
        support_before = project.support_state(locked) if "support_baseline" in locked else {}
        receipt = execute_role(project.root, role, prompt, config, directory,
                               review_schema, {"MATLAB_HARNESS_SCRATCH": str(scratch)})
        # Out-of-scope edits are undone before any evidence is compared.
        support = project.enforce_support(locked, support_before, directory / "quarantine")
        if support:
            locked["decisions"].append({"assertion": "VERIFIED", "source": "support enforcement", "at": now(),
                                        "text": f"{role} at {stage} changed out-of-scope files; restored or quarantined",
                                        **support})
        if role != "reviewer" and stage in {"requirements", "architecture"}:
            protected, actual = non_document_artifacts(before), non_document_artifacts(project.snapshot(locked))
            changed = {name: {"expected": protected.get(name), "actual": actual.get(name)}
                       for name in sorted(set(protected) | set(actual)) if protected.get(name) != actual.get(name)}
            if changed:
                boundary = {"status": "INPUT_REQUIRED", "reason": "Document/design role changed non-document engineering artifacts before requirements and architecture acceptance; preserve and inspect the changes",
                            "baseline": protected, "changed_artifacts": changed}
                evidence = directory / "stage-boundary.json"
                atomic_json(evidence, boundary)
                locked.setdefault("stage_boundaries", {})[evidence.relative_to(project.root).as_posix()] = {
                    "checkpoint": stage, "sha256": digest(evidence), "status": "OPEN"}
        run = {"role": role, "checkpoint": stage, "receipt": receipt,
               "packet": handoff, "stage_boundary": boundary, "support_enforcement": support, "recorded": now()}
        if role == "reviewer" and receipt["status"] == "SUCCEEDED":
            # Commit intent alongside the complete response, before any later
            # report-file write can be interrupted.
            run["review_import"] = {"status": "PENDING_REVIEW_IMPORT"}
        locked.setdefault("runs", []).append(run)
        identity = receipt.get("root_session_id")
        if role != "reviewer" and identity:
            contributors = locked.setdefault("contributors", [])
            if identity not in contributors:
                contributors.append(identity)
    if digest(Path(handoff["context"])) != handoff["context_sha256"]:
        raise ProjectError("Role modified its orchestrator-owned context packet; retain the run and inspect changes")
    if boundary:
        return {**boundary, "status": "INPUT_REQUIRED" if receipt["status"] == "SUCCEEDED" else receipt["status"],
                "receipt": receipt, "gate": project.gate(stage)}
    if role == "reviewer" and receipt.get("status") == "SUCCEEDED":
        if project.snapshot() != before:
            raise ProjectError("Reviewer modified the scoped artifact snapshot during independent review; retain the execution and inspect changes")
        response = receipt.get("response")
        if not isinstance(response, dict) or not identity or not receipt.get("actual_model"):
            return {"status": "REVIEW_NOT_IMPORTED", "reason": "Actual reviewer identity/model or structured response absent", "receipt": receipt}
        response = {**response, "reviewer_session": identity, "model": receipt["actual_model"],
                    "independence": "independent-agent",
                    "scratch_manifest": _scratch_files(project, scratch)}
        data = project.load()
        contributors = {data["builder_session"], *data.get("contributors", []),
                        *(t["worker"] for t in data["tasks"].values())}
        if identity in contributors:
            raise ProjectError("Reviewer session must differ from every contributing builder/worker session")
        if response.get("snapshot_digest") != handoff["snapshot_digest"]:
            raise ProjectError("Reviewer did not inspect current artifact snapshot")
        report = directory / "review.json"
        atomic_json(report, response)
        report_name = report.relative_to(project.root).as_posix()
        import_record = directory / "review-import.json"
        atomic_json(import_record, {"status": "PENDING_REVIEW_IMPORT", "report": report_name,
                                  "snapshot_digest": handoff["snapshot_digest"], "checkpoint": stage})
        try:
            problem = charter_problems(project, response, project.load(), stage, scratch)
            if problem:
                raise ReviewProtocolError("Review charter: " + problem)
            project.review(owner, stage, report_name, identity_source="runtime-receipt")
        except ReviewProtocolError as exc:
            project.record_review_protocol_failure(owner, stage, report_name, str(exc))
            failure = {"status": "REVIEW_NOT_IMPORTED", "retryable": True,
                       "reason": str(exc), "report": report_name,
                       "snapshot_digest": handoff["snapshot_digest"]}
            atomic_json(import_record, failure)
            return {**failure, "receipt": receipt, "gate": project.gate(stage)}
        atomic_json(import_record, {"status": "IMPORTED", "report": report_name,
                                  "snapshot_digest": handoff["snapshot_digest"]})
    return {"status": receipt["status"], "receipt": receipt, "gate": project.gate(stage)}
