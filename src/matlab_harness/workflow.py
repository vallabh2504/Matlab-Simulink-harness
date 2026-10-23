"""Operator onboarding and durable role handoffs, independent of the agent provider."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import uuid

from .answer import EXECUTED_CHECKPOINTS, answer_schema, import_answer, latest_packet, open_items
from .charter import CONTRACT_DISCIPLINE, PRODUCER_GUIDANCE, REVIEWER_CHARTER
from .project import DEFAULT_BUDGETS, PHASES, Project, ProjectError, ReviewProtocolError, atomic_json, digest, non_document_artifacts, now, value_digest
from .compact import matlab_digest
from .mutation import mutation_summary
from .probes import PROBE_RUNS
from .skills import cards_for, select_for


STAGE_GUIDANCE = {
    "requirements": "Inspect existing files and clarify consequential ambiguity. Draft requirements.md with stable IDs, units, provenance and acceptance methods; register IDs. Obtain actual user approval before construction.",
    "architecture": "Write governing equations, dimensional checks, solver rationale, interfaces, parameter ownership and proportionate architecture. Declare implementation/verification check commands derived from the design before independent design acceptance.",
    "implementation": "Implement only the accepted requirements/design in owned files. Protect legacy behavior, run MATLAB or Simulink and inspect saved artifacts. Retain editable sources and executable engineering checks.",
    "verification": "Run declared checks against stable artifacts. Use independent analytical/numerical oracles, boundary cases, convergence and legacy regressions. Inspect actual outputs; a process exit alone is insufficient engineering evidence.",
    "handoff": "Reproduce from the project entry point. Deliver source, saved models when required, parameter provenance, traceability, results, reviewer findings and explicit limitations. Close or interrupt every task lease.",
}

REVIEW_GUIDANCE = {
    "requirements": ("The requirements are an approved contract: check that they can be built and tested as written, "
                     "with consistent units, provenance and actual authorization. Where requirements.md leaves something "
                     "open, file an OPEN finding that names the readings you see, at the severity the difference makes: "
                     "it does not block this checkpoint, and the design must answer it."),
    "architecture": "Assess the governing equations, dimensional checks, solver rationale, interfaces, parameter ownership and declared downstream checks against the accepted requirements.",
    "implementation": "Assess the existing implementation against accepted requirements and design, including legacy behavior, editable sources and native engineering evidence. Report defects for a separate repair worker.",
    "verification": "Assess the declared check results, independent analytical/numerical oracles, boundary cases, convergence and legacy regressions. Inspect actual outputs and distinguish an engineering result from a process exit.",
    "handoff": "Assess reproducibility from the project entry point, source and saved models, parameter provenance, traceability, results, limitations and outstanding task leases.",
}

def start(directory, title, builder, owner, scope, brief="", runtime=None, budgets=None, repair_budget=10, proof_mode="executed"):
    project = Project.initialize(directory, title, builder, scope, proof_mode=proof_mode)
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
    return value if limit is None or len(value) <= limit else value[:limit] + "..."


COMMON_RULES = (
    "Rules: write every probe, temporary script, copied source and output of yours in the scratch directory "
    "named below, and nothing else outside owned scope; out-of-scope files are restored and new executable files "
    "there are quarantined after your role. Preserve existing files and private data. The orchestrator owns "
    "project records, approval, registered check execution and checkpoint acceptance: do not run mutating "
    "matlab-harness commands or edit .matlab-harness/. Return approval needs and check-plan proposals; never "
    "manufacture approval. Use native MATLAB/Simulink tools; keep engineering truth and honest classifications.\n")
DOCUMENT_RULES = (
    "This is a document/design checkpoint. Do not create or change MATLAB/Simulink implementation, saved models, "
    "data or results. Propose executable checks for later implementation; do not implement them now. Preserve the "
    "approved requirements; return consequential corrections as proposals rather than imposing new schemas, "
    "interfaces or acceptance obligations.\n")
REVIEW_RULES = (
    "Return findings for this checkpoint only, each issue ID appearing once. Your execution must leave scoped "
    "artifacts unchanged. Requirements and architecture need no executable check; implementation, verification and "
    "handoff do. Approval is an attestation of authorization: evaluate it, do not demand repeated permission for "
    "authorized work. Score or style preference never outweighs a demonstrated engineering defect.\n")
DOCUMENT_REVIEW = (
    "Assess whether this contract/design supports the requested work. Missing future implementation or results do "
    "not make a document checkpoint incomplete. Flag real contradictions or consequential ambiguities with the exact "
    "contract text; optional improvements stay nonblocking.\n")
REVIEW_OUTPUT = (
    "Return one JSON object: verdict (ACCEPT/REJECT/INCOMPLETE); findings: your new findings [{id, severity CRITICAL/"
    "MAJOR/MODERATE/MINOR, kind PROVEN DEFECT/EVIDENCE GAP/POTENTIAL DEFECT/OPTIONAL IMPROVEMENT, artifact (file:line), "
    "evidence (probe, observed vs expected), repair, status OPEN/CLOSED/DISPUTED/ACCEPTED-RISK, impact, closure (the "
    "check that proves the fix), user_decision (true only when no design choice can resolve it, such as a "
    "release or toolbox choice; the harness then stops for the user instead of repairing. A finding on "
    "requirements.md is answered by the design, not by this flag), contract_text and design_text (only to keep a "
    "CRITICAL or MAJOR finding on requirements.md open after the requirements checkpoint: the requirements.md "
    "sentence and the design's own sentence that conflict, each copied exactly)}]; traceability: {requirement ID: {status VERIFIED/PARTIAL/FAILED/UNVERIFIED, evidence, "
    "finding_ids}} for every requirement; independent_checks: [{id, command, observed, result PASS/FAIL/ERROR, artifact "
    "(scratch file)}]; open_items, only if this task lists open items: {handle: {status CLOSED/STILL_OPEN/NOT_CHECKED, "
    "evidence}}. The harness records checkpoint, snapshot and every identity. Example: "
    '{"verdict":"REJECT","findings":[{"id":"F-1","severity":"MAJOR","kind":"PROVEN DEFECT","artifact":"src/f.m:42",'
    '"evidence":"p1.m: f(0) returned 1, contract says 0","repair":"clamp before the lookup","status":"OPEN"}],'
    '"traceability":{"R-1":{"status":"FAILED","evidence":"p1.m","finding_ids":"F-1"}},'
    '"independent_checks":[{"id":"P1","command":"matlab -batch p1","observed":"f(0)=1","result":"FAIL",'
    '"artifact":"p1.m"}]}\n')
REPAIR_DOCUMENT = ("Clarify only the recorded document/design issue in owned documentation. Describe a future "
                   "regression check; do not implement it.\n")
REPAIR_CODE = ("Fix the cause of the findings and failed checks in the owned file, keep a regression test for each fixed finding, and rerun the "
               "declared checks before you finish.\n")


def _static_text(role, stage, cards):
    """Role text that is identical across calls, placed first so prompt caches reuse it."""
    if role == "reviewer":
        text = ("ENG reviewer. Your role is independent, read-only review. Do not implement or repair anything, "
                "including an obvious defect. Do not rewrite requirements, design, source or results. Return findings "
                "for the orchestrator to assign to a separate repair worker.\n" + REVIEW_GUIDANCE[stage] + "\n"
                + REVIEWER_CHARTER + REVIEW_RULES)
        if stage in {"requirements", "architecture"}:
            text += DOCUMENT_REVIEW
    elif role == "repair":
        text = ("ENG repair. Repair only the recorded findings in owned engineering files, preserving accepted "
                "scope and prior evidence.\n" + CONTRACT_DISCIPLINE
                + (REPAIR_DOCUMENT if stage in {"requirements", "architecture"} else REPAIR_CODE))
    else:
        text = ("ENG builder.\n" + STAGE_GUIDANCE[stage] + "\n" + PRODUCER_GUIDANCE.get(stage, "")
                + CONTRACT_DISCIPLINE)
    text += COMMON_RULES
    if stage in {"requirements", "architecture"}:
        text += DOCUMENT_RULES
    for card in cards:
        text += "\n" + card["text"].strip() + "\n"
    if role == "reviewer":
        text += "\n" + REVIEW_OUTPUT
    return text


def _finding_view(finding, limit):
    return {field: _clip(str(finding.get(field, "")), limit)
            for field in ("severity", "kind", "status", "artifact", "evidence", "repair")}


SEVERITY_ORDER = {"CRITICAL": 0, "MAJOR": 1, "MODERATE": 2, "MINOR": 3}
# Prompt size of the carried view outside handoff; the full text stays in context.json.
CARRIED_CHARS = 2000


def _carried_view(carried, limit, full):
    """Carried open findings by key. Handoff must disposition each, so it sees all of them."""
    if full:
        return {k: _finding_view(v, limit) for k, v in carried.items()}
    keys = sorted(carried, key=lambda k: (SEVERITY_ORDER.get(carried[k].get("severity"), 4), k))
    clip = 160 if limit is None else min(limit, 160)
    view = {}
    for k in keys:
        entry = {field: _clip(str(carried[k].get(field, "")), clip)
                 for field in ("severity", "kind", "status", "artifact", "evidence")}
        if view and len(json.dumps({**view, k: entry})) > CARRIED_CHARS:
            break
        view[k] = entry
    if len(view) < len(keys):
        view["more"] = f"+{len(keys) - len(view)} more in context.json carried_open_findings"
    return view


def _check_view(project, data, stage):
    """Latest registered check results, compressed to the MATLAB error that matters."""
    views = {}
    current = project.snapshot(data)
    for name in data["required_checks"].get(stage, []):
        entry = data["evidence"].get(name)
        path = project.root / entry["path"] if entry else None
        if not path or not path.is_file() or digest(path) != entry["sha256"]:
            continue
        evidence = json.loads(path.read_text(encoding="utf-8"))
        views[name] = {"status": evidence["status"] if evidence["snapshot"] == current else "STALE",
                       "output": matlab_digest(evidence.get("stdout", ""), evidence.get("stderr", ""))}
    semantic = data.get("semantic_results", {}).get(stage)
    if semantic and semantic.get("snapshot_digest") == value_digest(current) and semantic.get("status") != "STARTED":
        views["semantic-adequacy"] = {"status": semantic["status"], "output": "; ".join(semantic.get("diagnosis") or [])[:900]}
    mutation = data.get("mutation_results", {}).get(stage)
    if mutation and mutation.get("snapshot_digest") == value_digest(current):
        views["harness-mutation"] = mutation_summary(mutation)
    return views


def estimate_tokens(text):
    # About four characters per token for English and MATLAB; exact counts need the model's tokenizer.
    return math.ceil(len(text) / 4)


def packet(project, role, checkpoint=None, task="", budget=None, admit_only=False):
    """Write a role packet. admit_only composes and preflights it with no file or record written."""
    if role not in {"builder", "reviewer", "repair"}:
        raise ProjectError("Unknown role")
    data = project.load()
    project._seed_defects(data)
    stage = checkpoint or data["phase"]
    if stage not in PHASES:
        raise ProjectError("Unknown checkpoint")
    from .capabilities import capabilities, role_config, preflight
    try:
        profile = capabilities(role_config(data.get("runtime", {}), role))
    except ValueError as exc:
        raise ProjectError(str(exc)) from exc
    budget = profile.get("context_window") if budget is None else budget
    snapshot = project.snapshot(data)
    identifier = uuid.uuid4().hex
    directory = project.control / "packets" / identifier
    scratch = project.control / "scratch" / identifier
    context_path = directory / "context.json"
    context_name = context_path.relative_to(project.root).as_posix()
    brief_path = project.control / "brief.md"
    brief = brief_path.read_text(encoding="utf-8") if brief_path.is_file() else data["title"]
    requirement_text = " ".join(r["text"] for r in data["requirements"])
    signals = " ".join((data["title"], brief, requirement_text, task))
    selected = select_for(stage, role, signals)
    cards = cards_for(stage, role, signals)
    requirements_file = project.root / "requirements.md"
    mandated = (estimate_tokens(requirements_file.read_text(encoding="utf-8", errors="replace"))
                if requirements_file.is_file() else 0)
    counterevidence = project.control / "counterevidence.md"
    if role == "reviewer" and counterevidence.is_file():
        mandated += estimate_tokens(counterevidence.read_text(encoding="utf-8"))
    defect_context = {k: {"finding": v["finding"], "blocking": v["blocking"],
                           "origin_artifact": v["origin"]["artifact"]}
                      for k, v in data.get("defects", {}).items() if k.startswith(stage + ":")}
    carried = {k: v["finding"] for k, v in data.get("defects", {}).items()
               if not k.startswith(stage + ":") and v["finding"]["status"] == "OPEN"}
    items = open_items(project, data, stage) if role == "reviewer" else {}
    # Open questions on the approved contract that this checkpoint's design answers: raised at
    # requirements, or filed on requirements.md since.
    questions = [k.split(":", 1)[1] for k, v in data.get("defects", {}).items()
                 if k.startswith(stage + ":") and stage != "requirements" and v["finding"]["status"] != "CLOSED"
                 and (v.get("raised_at") or project.reserved_location(v["origin"]["artifact"]) == "contract")]
    checks = _check_view(project, data, stage) if stage in EXECUTED_CHECKPOINTS else {}
    try:
        project._approval_current(data)
        approval_current = True
    except ProjectError:
        approval_current = False
    trimmed = []

    def build(limit, chosen, task_limit):
        prompt = _static_text(role, stage, chosen)
        prompt += f"\n## This task\nProject root: {project.root}\nCheckpoint: {stage}\nScratch directory: {scratch}\n"
        prompt += (f"Read requirements.md and inspect the actual artifacts before starting. {context_name} holds the "
                   "full current record if you need history; do not edit it. Leave .matlab-harness/ out of searches: "
                   "it holds harness records, not deliverables.\n")
        prompt += "Brief: " + brief.strip() + "\n"
        prompt += f"Owned engineering scope: {json.dumps(data['scope'])}\n"
        prompt += (f"User approval records: {json.dumps(data['approvals'])}; approval_current: "
                   f"{json.dumps(approval_current)}. document_digest is the harness digest of the approved "
                   "requirement records plus requirements.md, not the file's sha256.\n")
        plan = data["required_checks"].get(stage, [])
        prompt += f"Declared checks: {json.dumps({name: data['commands'][name] for name in plan})}\n"
        if checks:
            prompt += f"Latest check results: {json.dumps(checks)}\n"
        if role == "reviewer" and stage in EXECUTED_CHECKPOINTS and data.get("proof_policy", {}).get("mode") == "executed":
            prompt += ("Independent PASS/closure requires a host execution receipt. Write a probe in scratch, then "
                       "include run:{script:absolute scratch path, runner:index, arguments:[], inputs:[project files, relative or absolute inside the project]} "
                       "in its independent_checks row, with that same script as its artifact. The host runs it after your "
                       f"response and binds receipt_id; only {PROBE_RUNS} runs are executed per answer, so one script may "
                       "check many cases and print a line for each. A label or existing file alone is not proof. Approved runners: "
                       + json.dumps(data["proof_policy"].get("runners", [])) + "\n")
        if selected:
            prompt += "Longer skill guides, only if needed: " + ", ".join(e["path"] for e in selected) + "\n"
        recorded = {k.split(":", 1)[1]: {**_finding_view(v["finding"], limit), "blocking": v["blocking"]}
                    for k, v in defect_context.items() if v["finding"]["status"] != "CLOSED"}
        if recorded and role != "reviewer":
            prompt += "Open findings at this checkpoint: " + json.dumps(recorded) + "\n"
        if questions and role != "reviewer":
            prompt += ("Contract questions " + ", ".join(questions) + " ask how to read requirements.md. Answer each "
                       "by ID in the design: one reading, the requirements.md text it rests on, and what tests may "
                       "not assert. Only if no reading fits the contract, write 'USER QUESTION <ID>:' and the "
                       "requirements.md sentences that conflict; the harness then stops for the user.\n")
        if carried:
            prompt += (f"Open findings carried from other checkpoints: {json.dumps(_carried_view(carried, limit, stage == 'handoff'))}\n"
                       "Address each where your role allows; the handoff documentation must disposition every one by ID. "
                       + ("" if stage == "handoff" else f"Full text: {context_name} carried_open_findings. ")
                       + ("These stay tracked under their keys until handoff: do not re-report them. Cite a key in "
                          "finding_ids where a row depends on it. File a new finding only for a new defect, or one that "
                          "is now more severe.\n" if role == "reviewer" else "\n"))
        if items:
            prompt += ("Open items at this checkpoint, by handle. An allegation came from a refused or unfinished "
                       "report and is not established; re-run its probes first. "
                       + json.dumps({h: {**_finding_view(item["finding"], limit), "blocks_acceptance": item["required"],
                                         **({"allegation": True, "probes": item["probes"],
                                             **({"more_probes": item["more_probes"]} if item["more_probes"] else {})}
                                            if item["type"] == "allegation" else {})}
                                     for h, item in items.items()})
                       + "\nAnswer each handle in open_items: CLOSED only with evidence from a check you ran now"
                       + (", naming the artifact file or ID of one of your independent_checks with result PASS"
                          if stage in EXECUTED_CHECKPOINTS else "")
                       + ", STILL_OPEN if it still holds, NOT_CHECKED otherwise. ACCEPT needs every item that blocks "
                       "acceptance CLOSED. Report a new defect as a new finding with a new ID.\n"
                       + (f"{', '.join(questions)} question the approved contract. Each is CLOSED when the design's "
                          "reading contradicts no requirements.md sentence; that the contract could say more is no "
                          "reason to keep it open. Keep one STILL_OPEN only with contract_text and design_text in its "
                          "open_items answer: the requirements.md sentence and the design's own sentence that "
                          "conflict, each copied exactly. The design is then repaired, unless it says "
                          "'USER QUESTION <ID>:', which stops the work for the user.\n" if questions else ""))
        if role == "reviewer" and (project.control / "counterevidence.md").is_file():
            prompt += "Read .matlab-harness/counterevidence.md and reassess prior claims against it before closure or further blocking.\n"
        from .ingestion import open_gaps
        gaps = open_gaps(data, stage)
        if gaps:
            prompt += ("Unread source gaps require trusted owner authorization before correction: "
                       + json.dumps({k: {"source_sha256": v["source_sha256"], "problems": v["problems"]}
                                     for k, v in gaps.items()}) + "\n"
                       + "A complete corrected answer must include reconciliation: "
                       + "[{gap_id, source_sha256, complete:true}] and explicitly disposition every open handle.\n")
        prompt += "Task detail: " + _clip(task, task_limit) + (
            " (task text clipped to fit the context window)" if task_limit and len(task) > task_limit else "") + "\n"
        return prompt

    limit, chosen, task_limit = None, list(cards), None
    prompt = build(limit, chosen, task_limit)
    schema_tokens = estimate_tokens(json.dumps(answer_schema(data, items))) if role == "reviewer" else 0
    def fit():
        try:
            return preflight(profile, estimate_tokens(prompt), mandated, schema_tokens, budget)
        except ValueError as exc:
            raise ProjectError(str(exc)) from exc
    while not fit()["fits"] and chosen:
        trimmed.append("card " + chosen.pop()["name"])
        prompt = build(limit, chosen, task_limit)
    # Finding views go first; the task text keeps a head with its reason, diagnosis and brief.
    for limit, task_limit in ((600, None), (200, None), (200, 4000), (200, 2000)):
        if fit()["fits"]:
            break
        trimmed.append(f"finding views {limit} chars" + (f", task {task_limit} chars" if task_limit else ""))
        prompt = build(limit, chosen, task_limit)
    context_preflight = fit()
    if not context_preflight["fits"]:
        raise ProjectError("Context preflight refused before dispatch: essential context and reserves require "
                           + str(context_preflight["total"]) + " estimated tokens, capacity " + str(budget))
    if admit_only:
        return {"admitted": True, "context_preflight": context_preflight, "trimmed": trimmed}
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
               "defects": defect_context, "carried_open_findings": carried, "open_items": items,
               "active_tasks": {k: v for k, v in data["tasks"].items() if v["status"] == "ACTIVE"},
               "full_record": ".matlab-harness/project.json"}
    atomic_json(context_path, context)
    path = directory / "prompt.md"
    path.write_text(prompt, encoding="utf-8")
    scratch.mkdir(parents=True)
    record = {"role": role, "checkpoint": stage, "created": now(), "snapshot_digest": value_digest(snapshot),
              "prompt": str(path), "prompt_sha256": digest(path), "selected_skills": selected,
              "cards": [c["name"] for c in chosen], "scratch": str(scratch),
              "context": str(context_path), "context_sha256": digest(context_path),
              "estimated_tokens": {"prompt": estimate_tokens(prompt), "mandated_reads": mandated,
                                   "static_prefix": estimate_tokens(_static_text(role, stage, chosen))},
              "budget": budget, "trimmed": trimmed, "capabilities": profile, "context_preflight": context_preflight}
    if role == "reviewer":
        # The exact answer this packet expects; runtimes enforce it, hosts can show it to the model.
        atomic_json(directory / "answer-schema.json", answer_schema(data, items))
        record["answer_schema"] = str(directory / "answer-schema.json")
    from .ingestion import open_gaps
    record["ingestion_gaps"] = {k: {"source_sha256": v["source_sha256"]} for k, v in open_gaps(data, stage).items()}
    record["open_handles"] = sorted(items)
    atomic_json(directory / "packet.json", record)
    return record


PRIOR_FILES, PRIOR_BYTES = 200, 1_048_576


def _copy_prior(prior, scratch, report=None):
    """A refused report and its scratch files, copied into a correction packet's scratch. The copies
    earn nothing: a probe counts only when this packet's report proposes it and the host runs it."""
    chosen = {}
    for source in sorted(prior.rglob("*")) if prior is not None and prior.is_dir() else []:
        relative = source.relative_to(prior)
        if relative.parts == ("prior-report.json",) or source.is_symlink() or not source.is_file():
            continue
        # A correction of a correction keeps one level, and the prior reviewer's own file
        # replaces an inherited copy of the same name.
        inherited = relative.parts[0] == "prior-probes" and len(relative.parts) > 1
        target = Path(*relative.parts[1:]) if inherited else relative
        if not (inherited and target in chosen):
            chosen[target] = (inherited, source)
    # The prior reviewer's own files go first, so the cap drops inherited copies.
    ordered = sorted(chosen.items(), key=lambda item: (item[1][0], item[0]))[:PRIOR_FILES]
    pairs = ([(Path("prior-report.json"), report)] if report is not None else []) \
        + [(Path("prior-probes") / target, source) for target, (_, source) in ordered]
    copied = []
    for name, source in pairs:
        try:
            if name.parts[0] == "prior-probes" and source.stat().st_size > PRIOR_BYTES:
                continue
            (scratch / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, scratch / name)
        except OSError:
            # A locked or unreadable file is a lost convenience, never a stopped review.
            continue
        copied.append(name.as_posix())
    return copied


def execute(project, owner, role, checkpoint=None, task="", remaining_seconds=None, prior=None):
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
    from .capabilities import role_config
    config = role_config(data.get("runtime", {"adapter": "manual"}), role)
    config["timeout"] = data.get("budgets", DEFAULT_BUDGETS).get(role, DEFAULT_BUDGETS[role])
    if remaining_seconds is not None:
        if isinstance(remaining_seconds, bool) or not isinstance(remaining_seconds, (int, float)) or not math.isfinite(remaining_seconds) or remaining_seconds <= 0:
            raise ProjectError("Remaining execution seconds must be finite and positive")
        config["timeout"] = min(config["timeout"], remaining_seconds)
    if config.get("adapter") == "manual":
        return {"status": "MANUAL_HANDOFF", "packet": packet(project, role, stage, task)}
    if role == "repair":
        # A packet that cannot fit is refused before the repair budget is charged.
        packet(project, role, stage, task, admit_only=True)
        project.repair(owner, task or "Repair actual recorded reviewer findings")
    handoff = packet(project, role, stage, task)
    directory = Path(handoff["prompt"]).parent / "execution"
    prompt = Path(handoff["prompt"]).read_text(encoding="utf-8")
    before = project.snapshot()
    kept = directory / "reviewed-artifacts"
    baseline = _keep_artifacts(project, data, kept) if role == "reviewer" else None
    boundary, restored, unrestored = None, [], None
    review_schema = json.loads(Path(handoff["answer_schema"]).read_text(encoding="utf-8")) if role == "reviewer" else None
    # Keep workflow state serialized while an external role is using its contract.
    scratch = Path(handoff["scratch"])
    copied = None
    if prior and role == "reviewer":
        source = project.control / "scratch" / prior["packet"] if prior.get("packet") else None
        copied = _copy_prior(source, scratch, project.root / prior["report"])
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
        if baseline is not None:
            restored, unrestored = _restore_artifacts(project, locked, baseline, kept, directory / "reviewer-changes")
            if restored:
                locked["decisions"].append({"assertion": "VERIFIED" if not unrestored else "UNVERIFIED",
                                            "source": "reviewer boundary", "at": now(),
                                            "text": f"reviewer at {stage} changed scoped artifacts; "
                                                    + ("restored the reviewed bytes" if not unrestored else
                                                       "could not restore them: " + unrestored)
                                                    + ", its versions kept in execution/reviewer-changes",
                                            "changed": restored})
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
               "packet": handoff, "stage_boundary": boundary, "support_enforcement": support, "recorded": now(),
               **({"prior_copied": copied} if copied is not None else {})}
        if role == "reviewer" and (receipt["status"] == "SUCCEEDED" or unrestored or receipt.get("ingestion", {}).get("problems")):
            # Commit intent alongside the complete response, before any later
            # report-file write can be interrupted. A tree the harness could not put back
            # holds every dispatch the same way until someone inspects it.
            run["review_import"] = {"status": "PENDING_REVIEW_IMPORT"}
        locked.setdefault("runs", []).append(run)
        if role != "reviewer":
            # A builder's subagents are the builder too; only transports that report them (agy) list them.
            contributors = locked.setdefault("contributors", [])
            for identity in [receipt.get("root_session_id"), *receipt.get("child_session_ids", [])]:
                if identity and identity not in contributors:
                    contributors.append(identity)
    if digest(Path(handoff["context"])) != handoff["context_sha256"]:
        raise ProjectError("Role modified its orchestrator-owned context packet; retain the run and inspect changes")
    if boundary:
        return {**boundary, "status": "INPUT_REQUIRED" if receipt["status"] == "SUCCEEDED" else receipt["status"],
                "receipt": receipt, "gate": project.gate(stage)}
    if role == "reviewer":
        result = _import_review(project, owner, stage, receipt, handoff, directory, restored, unrestored,
                                max(0, config["timeout"] - receipt.get("wall_seconds", config["timeout"])))
        if not unrestored:
            # A completed refusal is not an interrupted import. Its unread gap
            # remains the durable blocker and can be explicitly reconciled.
            with project.transaction(owner) as locked:
                for run in locked.get("runs", []):
                    if (run.get("receipt", {}).get("attempt_id") == receipt["attempt_id"]
                            and run.get("review_import", {}).get("status") == "PENDING_REVIEW_IMPORT"):
                        run["review_import"] = {"status": "REJECTED_INPUT", "reason": result.get("reason", result["status"])}
        return result
    return {"status": receipt["status"], "receipt": receipt, "gate": project.gate(stage)}


def _keep_artifacts(project, data, kept):
    """Copies of the files a reviewer is about to read, so its changes can be undone. Returns
    what it reads (see _reviewed_files)."""
    baseline = _reviewed_files(project, data)
    for name, value in baseline.items():
        if value != "dir" and not value.startswith("link:"):
            (kept / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(project.root / name, kept / name)
    return baseline


def _linked(path):
    # st_reparse_tag is available on supported older Windows Python versions;
    # Path.is_junction itself was only added in Python 3.12.
    return path.is_symlink() or bool(getattr(path.lstat(), "st_reparse_tag", 0))


def _reviewed_files(project, data):
    """Everything the snapshot hashes, so everything a reviewer reads: the scope and the
    requirements document. Each file, link and directory by name: a file's digest, "link:" and
    a link's target (so a link that stands in for a file is a change even when it points at the
    same bytes), or "dir"."""
    found = {}
    for relative in (*data["scope"], "requirements.md"):
        top = project.root / relative
        entries = [top] if os.path.lexists(top) else []
        if top.is_dir() and not _linked(top):
            entries = []
            for directory, dirs, files in os.walk(top):
                found[Path(directory).relative_to(project.root).as_posix()] = "dir"
                links = [d for d in dirs if _linked(Path(directory, d))]
                dirs[:] = sorted(set(dirs) - set(links))
                entries += [Path(directory, name) for name in (*files, *links)]
        for path in entries:
            found[path.relative_to(project.root).as_posix()] = "link:" + os.readlink(path) if _linked(path) else digest(path)
    return found


def _move_aside(path, target):
    while os.path.lexists(target):
        target = target.with_name(target.name + "~")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(path, target)  # a link moves as a link


def _restore_artifacts(project, data, baseline, kept, moved):
    """Undo a reviewer's changes to what it read: whatever it left moves to moved, and what it
    reviewed comes back from kept, so the next role sees what was reviewed. Never raises, so
    the run is always recorded. Returns the changed names and, when the tree could not be put
    back, why; the kept copies then stay for whoever inspects it."""
    changed = []
    try:
        current = _reviewed_files(project, data)
        changed = sorted(n for n in set(baseline) | set(current) if baseline.get(n) != current.get(n))
        # Deepest first, so a directory the reviewer made is empty by the time it is removed.
        for name in sorted(changed, key=lambda n: n.count("/"), reverse=True):
            path = project.root / name
            if current.get(name) == "dir":
                path.rmdir()
            elif name in current:
                _move_aside(path, moved / name)
        # A directory sorts before what is in it.
        for name in changed:
            if name in baseline:
                path, value = project.root / name, baseline[name]
                if value == "dir":
                    path.mkdir(parents=True, exist_ok=True)
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                if value.startswith("link:"):
                    os.symlink(value[len("link:"):], path)
                elif digest(kept / name) != value:
                    return changed, "the kept copy of " + name + " changed during review"
                else:
                    shutil.copy2(kept / name, path)
        if _reviewed_files(project, data) != baseline:
            return changed, "the reviewed files still differ from the kept ones"
    except (OSError, shutil.Error, ProjectError) as exc:
        return changed, f"{type(exc).__name__}: {exc}"
    shutil.rmtree(kept, ignore_errors=True)
    return changed, None


def _independence(data, model):
    """A separate session of a builder's own model is weaker independence; it is recorded as such.
    Before any builder has run (requirements), the configured builder and repair models count."""
    models = {run["receipt"].get("actual_model") for run in data.get("runs", [])
              if run["role"] != "reviewer" and isinstance(run.get("receipt"), dict)}
    runtime = data.get("runtime", {})
    models |= {runtime.get("roles", {}).get(name, {}).get("model", runtime.get("model")) for name in ("builder", "repair")}
    return "same-model-separate-session" if model in models - {None} else "independent-agent"


def _import_review(project, owner, stage, receipt, handoff, directory, restored, unrestored, probe_seconds=0):
    """Import the answer a reviewer run returned, whatever became of the run. An answer from a
    run that did not finish, that changed scoped files (restored by now), or whose model the
    runtime did not report is not imported; its serious claims bind as open items for the next
    reviewer. A run that only failed in transport (stream drop, timeout) is not counted as a
    protocol attempt. Only an answer without a reviewer session cannot bind: nothing shows
    it came from someone other than a builder."""
    finished = receipt["status"] == "SUCCEEDED"
    response, session, model = receipt.get("response"), receipt.get("root_session_id"), receipt.get("actual_model")
    result = {"status": receipt["status"], "receipt": receipt}
    if receipt.get("ingestion"):
        from .decoding import from_metadata
        response = from_metadata(response, receipt["ingestion"])
    if restored:
        result["restored_reviewer_changes"] = restored
    if unrestored:
        return {**result, "status": "INPUT_REQUIRED", "gate": project.gate(stage),
                "reason": "The reviewer changed scoped files and the harness could not put them back (" + unrestored
                          + "). The reviewed copies are in " + str(directory / "reviewed-artifacts") + " and the "
                          "reviewer's versions in " + str(directory / "reviewer-changes") + "; restore the files, then "
                          "inspect this run"}
    if not session:
        if receipt.get("ingestion", {}).get("problems"):
            from .ingestion import record_gap
            record_gap(project, owner, handoff, response)
            return {**result, "status": "REVIEW_NOT_IMPORTED", "gate": project.gate(stage),
                    "reason": "Ambiguous review transport retained; reviewer identity unavailable, unread source blocks acceptance"}
        if finished:
            return {**result, "status": "REVIEW_NOT_IMPORTED", "reason": "The runtime did not report the reviewer session"}
        return {**result, "gate": project.gate(stage)}
    refusals = []
    if restored:
        refusals.append("you changed scoped artifacts (" + ", ".join(restored[:5]) + "); they were restored. "
                        "A reviewer changes nothing outside its scratch directory")
    if not finished:
        category = (receipt.get("failure") or {}).get("category")
        said = str(receipt.get("error") or receipt.get("provider_error") or "")[:200]
        cause = (f" ({category}: {said})" if said else f" ({category})") \
            if category and category != "unclassified_failure" else ""
        refusals.append(f"reviewer attempt ended {receipt['status']}{cause} after returning this answer")
    elif not model:
        refusals.append("the runtime did not report which model reviewed")
    report = directory / "review.json"
    name = report.relative_to(project.root).as_posix()
    marker = directory / "review-import.json"
    if finished:
        atomic_json(marker, {"status": "PENDING_REVIEW_IMPORT", "report": name,
                             "snapshot_digest": handoff["snapshot_digest"], "checkpoint": stage})
    identity = {"reviewer_session": session, "model": model or "unknown",
                "independence": _independence(project.load(), model), "identity_source": "runtime-receipt"}
    if finished and not refusals:
        from .probes import execute_proposals
        response = execute_proposals(project, owner, handoff, response, session, probe_seconds)
    try:
        imported = import_answer(project, owner, handoff, response, report, identity, "; ".join(refusals) or None,
                                 kind="protocol" if finished or restored else "unfinished")
    except ReviewProtocolError as exc:
        if not finished:
            return {**result, "reason": str(exc), "bound_allegations_from": name, "gate": project.gate(stage)}
        failure = {"status": "REVIEW_NOT_IMPORTED", "retryable": not bool(receipt.get("ingestion", {}).get("problems")), "reason": str(exc), "report": name,
                   "snapshot_digest": handoff["snapshot_digest"]}
        atomic_json(marker, failure)
        return {**result, **failure, "gate": project.gate(stage)}
    except ProjectError as exc:
        if finished:
            raise
        # Provenance failed (the session also built, or the files moved on): nothing binds.
        return {**result, "reason": "answer neither imported nor bound: " + str(exc), "gate": project.gate(stage)}
    atomic_json(marker, {"status": "IMPORTED", "report": name, "snapshot_digest": handoff["snapshot_digest"]})
    return {**result, "notes": imported["notes"], "gate": project.gate(stage)}


def submit_answer(project, owner, answer, reviewer_session, model, packet_id=None):
    """Import a reviewer answer from any host (MCP, CLI). The host reports who reviewed, so
    the record says host-reported, never verified. The answer belongs to a reviewer packet,
    the newest for this checkpoint unless one is named, and is kept under that packet."""
    if not str(reviewer_session or "").strip() or not str(model or "").strip():
        raise ProjectError("Reviewer session and model are required")
    handoff = latest_packet(project, packet_id)
    report = Path(handoff["prompt"]).parent.name
    report = project.control / "packets" / report / f"answer-{uuid.uuid4().hex[:12]}.json"
    imported = import_answer(project, owner, handoff, answer, report,
                             {"reviewer_session": reviewer_session, "model": model,
                              "independence": "host-reported", "identity_source": "self-attested"})
    return {**imported, "gate": project.gate(handoff["checkpoint"])}
