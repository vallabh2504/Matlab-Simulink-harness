"""Direct engineering CLI. Outputs are JSON; failed gates return exit code 2."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

from .bridge import preflight
from .project import PHASES, Project, ProjectError, read_json, value_digest
from .skills import catalog, install, select
from .workflow import execute, next_step, packet, start, submit_answer


def parser():
    p = argparse.ArgumentParser(prog="matlab-harness", description="Evidence-driven MATLAB engineering")
    p.add_argument("--project", default=".", help="Engineering project root")
    commands = p.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("directory")
    init.add_argument("--title", required=True)
    init.add_argument("--builder", required=True, help="Actual builder session identifier")
    init.add_argument("--scope", nargs="+", required=True, help="Owned engineering artifact paths")
    onboarding = commands.add_parser("start", help="Initialize an operator-ready project without overwriting existing files")
    onboarding.add_argument("directory")
    onboarding.add_argument("--title", required=True)
    onboarding.add_argument("--builder", required=True)
    onboarding.add_argument("--owner", required=True)
    onboarding.add_argument("--scope", nargs="+", required=True)
    onboarding.add_argument("--brief", default="")
    commands.add_parser("next", help="Show current engineering obligations, evidence and findings")
    role_packet = commands.add_parser("packet", help="Create a durable task for a native agent")
    role_packet.add_argument("--role", choices=("builder", "reviewer", "repair"), required=True)
    role_packet.add_argument("--checkpoint", choices=PHASES)
    role_packet.add_argument("--task", default="")
    role_run = commands.add_parser("execute", help="Execute a configured role and retain actual provider evidence")
    role_run.add_argument("--owner", required=True)
    role_run.add_argument("--role", choices=("builder", "reviewer", "repair"), required=True)
    role_run.add_argument("--checkpoint", choices=PHASES)
    role_run.add_argument("--task", default="")
    journey = commands.add_parser("journey", help="Run configured engineering checkpoints with a predeclared total ceiling")
    journey.add_argument("--owner", required=True)
    journey.add_argument("--ceiling", type=float, default=14400)
    journey.add_argument("--review-existing-implementation", action="store_true")
    journey.add_argument("--stop-after", choices=PHASES)
    mcp = commands.add_parser("mcp", help="Serve this project's tools to an agent host over stdio (MCP)")
    mcp.add_argument("--owner", required=True)
    journey_recovery = commands.add_parser("recover-journey", help="Recover an inspected interrupted invocation without inferring successful execution")
    journey_recovery.add_argument("--owner", required=True)
    journey_recovery.add_argument("--attempt", required=True)
    journey_recovery.add_argument("--stopped-process-attestation", required=True)
    journey_recovery.add_argument("--source", required=True)
    journey_recovery.add_argument("--lock-token")
    for name in ("claim", "release", "approve", "requirement", "decision", "configure-checks", "lease",
                 "finish-task", "run-check", "review", "answer", "accept", "repair", "revise", "configure-runtime",
                 "mutation"):
        sub = commands.add_parser(name)
        sub.add_argument("--owner", required=True)
        if name == "approve":
            sub.add_argument("--actor", required=True)
            sub.add_argument("--source", required=True, help="Actual user authorization reference")
        elif name == "requirement":
            for field in ("id", "text", "acceptance", "source"):
                sub.add_argument("--" + field, required=True)
            sub.add_argument("--units")
        elif name == "decision":
            sub.add_argument("--text", required=True)
            sub.add_argument("--assertion", required=True)
            sub.add_argument("--source", required=True)
        elif name == "configure-checks":
            sub.add_argument("checkpoint", choices=PHASES)
            sub.add_argument("--plan", required=True, help="Project-relative JSON mapping check names to argv lists")
        elif name == "lease":
            sub.add_argument("task")
            sub.add_argument("--worker", required=True)
            sub.add_argument("--artifacts", nargs="+", required=True)
            sub.add_argument("--requirements", nargs="+", required=True)
            sub.add_argument("--kind", choices=("discovery", "design", "implementation", "repair"), default="implementation")
        elif name == "finish-task":
            sub.add_argument("task")
            sub.add_argument("--disposition", required=True)
        elif name == "run-check":
            sub.add_argument("name")
            sub.add_argument("--timeout", type=float, help="Override configured native-check seconds (default 1800)")
        elif name == "configure-runtime":
            for role in ("builder", "reviewer", "repair", "native"):
                sub.add_argument("--" + role + "-seconds", type=float)
            sub.add_argument("--repair-budget", type=int)
            sub.add_argument("--config", help="Project-relative runtime JSON; per-role models/adapters under roles")
        elif name == "review":
            sub.add_argument("checkpoint", choices=PHASES)
            sub.add_argument("report", help="Project-relative complete review record, attested by the operator")
        elif name == "answer":
            sub.add_argument("report", help="Project-relative reviewer answer to a reviewer packet")
            sub.add_argument("--reviewer-session", required=True, help="Reviewer session ID as the host reports it")
            sub.add_argument("--model", required=True, help="Reviewer model name as the host reports it")
            sub.add_argument("--packet", help="Reviewer packet ID; default is the newest for this checkpoint")
        elif name == "accept":
            sub.add_argument("checkpoint", choices=PHASES)
        elif name == "mutation":
            sub.add_argument("--seconds", type=float, help="Time limit; default is the native check budget")
        elif name in {"repair", "revise"}:
            sub.add_argument("--reason", required=True)
    reconcile = commands.add_parser("authorize-correction", help="Authorize a complete correction after inspecting an unread source")
    for field in ("owner", "gap", "source-sha256", "packet", "reason"):
        reconcile.add_argument("--" + field, required=True)
    probes = commands.add_parser("configure-probes", help="Approve executables for independent host-run probe scripts")
    probes.add_argument("--owner", required=True)
    probes.add_argument("--plan", required=True, help="Project JSON list of {kind,executable}")
    probes.add_argument("--reason", required=True)
    probe = commands.add_parser("run-probe", help="Execute a reviewer scratch script and issue a bound receipt")
    for field in ("owner", "packet", "check-id", "script", "reviewer-session"):
        probe.add_argument("--" + field, required=True)
    probe.add_argument("--runner",type=int,default=0)
    probe.add_argument("--arguments",nargs="*",default=[])
    probe.add_argument("--inputs",nargs="*",default=[])
    probe.add_argument("--timeout",type=float)
    semantic = commands.add_parser("configure-semantics", help="Approve required named-defect calibration obligations")
    for field in ("owner","plan","reason"):
        semantic.add_argument("--"+field,required=True)
    semantic_run=commands.add_parser("run-semantics", help="Run required semantic adequacy checks in isolated copies")
    semantic_run.add_argument("--owner",required=True)
    semantic_run.add_argument("--checkpoint",choices=PHASES)
    semantic_run.add_argument("--timeout",type=float)
    recovery=commands.add_parser("recover-execution",help="Resolve an inspected interrupted intent without claiming a passed execution")
    for field in ("owner","id","stopped-process-attestation","reason"):
        recovery.add_argument("--"+field,required=True)
    recovery.add_argument("--kind",choices=("probe","semantic"),required=True)
    gate = commands.add_parser("gate")
    gate.add_argument("checkpoint", choices=PHASES)
    commands.add_parser("resume")
    commands.add_parser("snapshot")
    commands.add_parser("status")
    recover = commands.add_parser("recover-lock")
    recover.add_argument("--token", required=True)
    recover.add_argument("--previous-process-stopped", action="store_true", required=True)
    recover = commands.add_parser("recover-owner")
    recover.add_argument("--previous", required=True)
    recover.add_argument("--owner", required=True)
    recover.add_argument("--reason", required=True)
    detection = commands.add_parser("preflight")
    detection.add_argument("--matlab")
    detection.add_argument("--root")
    detection.add_argument("--timeout", type=float, default=180)
    skills = commands.add_parser("skills")
    skills.add_argument("--task")
    skills.add_argument("--root")
    registration = commands.add_parser("install-skills")
    registration.add_argument("--target", required=True)
    registration.add_argument("--runtime", choices=("codex", "claude"), required=True)
    registration.add_argument("--root")
    return p


def dispatch(args):
    command = args.command
    if command == "init":
        project = Project.initialize(args.directory, args.title, args.builder, args.scope)
        return {"initialized": str(project.root)}, 0
    if command == "start":
        return start(args.directory, args.title, args.builder, args.owner, args.scope, args.brief), 0
    if command == "preflight":
        result = preflight(args.matlab, args.root, args.timeout)
        return result, 0 if result["matlab"]["status"] == "VERIFIED" else 2
    if command == "skills":
        return select(args.task, args.root) if args.task else catalog(args.root), 0
    if command == "install-skills":
        return install(args.target, args.runtime, args.root), 0
    if command == "mcp":
        from .mcp_server import serve
        serve(args.project, args.owner)
        return None, 0
    project = Project(args.project)
    if command == "next":
        return next_step(project), 0
    if command == "journey":
        from .journey import run_journey
        result = run_journey(args.project, args.owner, args.ceiling, args.review_existing_implementation, args.stop_after)
        return result, 0 if result["status"] in {"COMPLETED", "CHECKPOINT_REACHED"} else 3
    if command == "recover-journey":
        from .journey_recovery import recover_journey
        return recover_journey(project, args.owner, args.attempt, args.stopped_process_attestation,
                               args.source, args.lock_token), 0
    if command == "packet":
        return packet(project, args.role, args.checkpoint, args.task), 0
    if command == "execute":
        result = execute(project, args.owner, args.role, args.checkpoint, args.task)
        return result, 0 if result["status"] in {"SUCCEEDED", "MANUAL_HANDOFF"} else 2
    if command == "configure-runtime":
        from .project import inside
        budgets = {role: getattr(args, role + "_seconds") for role in ("builder", "reviewer", "repair", "native")
                   if getattr(args, role + "_seconds") is not None}
        runtime = read_json(inside(project.root, args.config)) if args.config else None
        project.configure_runtime(args.owner, budgets, args.repair_budget, runtime)
    elif command == "claim":
        project.claim(args.owner)
    elif command == "release":
        project.release(args.owner)
    elif command == "requirement":
        project.add_requirement(args.owner, args.id, args.text, args.acceptance, args.source, args.units)
    elif command == "approve":
        project.approve(args.owner, args.actor, args.source)
    elif command == "decision":
        project.decision(args.owner, args.text, args.assertion, args.source)
    elif command == "configure-checks":
        from .project import inside
        project.configure_checks(args.owner, args.checkpoint, read_json(inside(project.root,args.plan)))
    elif command == "lease":
        project.lease(args.owner, args.task, args.worker, args.artifacts, args.requirements, args.kind)
    elif command == "finish-task":
        project.finish_task(args.owner, args.task, args.disposition)
    elif command == "run-check":
        evidence = project.run_check(args.owner, args.name, timeout=args.timeout)
        return evidence, 0 if evidence["status"] == "PASSED" else 2
    elif command == "review":
        project.review(args.owner, args.checkpoint, args.report)
    elif command == "answer":
        from .project import inside
        from .decoding import decode_file
        return submit_answer(project, args.owner, decode_file(inside(project.root, args.report)),
                             args.reviewer_session, args.model, args.packet), 0
    elif command == "authorize-correction":
        from .ingestion import authorize_reconciliation
        return authorize_reconciliation(project, args.owner, args.gap, args.source_sha256, args.packet, args.reason), 0
    elif command == "configure-probes":
        from .project import inside
        from .probes import configure
        return configure(project,args.owner,read_json(inside(project.root,args.plan)),args.reason),0
    elif command == "configure-semantics":
        from .project import inside
        from .semantics import configure
        return configure(project,args.owner,read_json(inside(project.root,args.plan)),args.reason),0
    elif command == "run-semantics":
        from .semantics import run
        result=run(project,args.owner,args.checkpoint,args.timeout)
        return result,0 if result["status"]=="PASSED" else 2
    elif command == "recover-execution":
        from .execution import recover
        return recover(project,args.owner,args.kind,args.id,args.stopped_process_attestation,args.reason),0
    elif command == "run-probe":
        from .probes import run
        result=run(project,args.owner,args.packet,args.check_id,args.script,args.reviewer_session,args.runner,args.arguments,args.inputs,args.timeout)
        return result,0 if result["status"]=="PASSED" else 2
    elif command == "accept":
        return project.accept(args.owner, args.checkpoint), 0
    elif command == "mutation":
        from .mutation import mutation_summary, run_mutation
        data = project.load()
        result = run_mutation(project, args.owner, data["phase"], args.seconds or data["budgets"]["native"])
        return mutation_summary(project.load()["mutation_results"][data["phase"]]) | {"evidence": result["status"]}, 0
    elif command == "gate":
        result = project.gate(args.checkpoint)
        return result, 0 if result["accepted"] else 2
    elif command == "repair":
        project.repair(args.owner, args.reason)
    elif command == "revise":
        project.revise(args.owner, args.reason)
    elif command == "recover-lock":
        return project.recover_lock(args.token), 0
    elif command == "recover-owner":
        project.recover_owner(args.previous, args.owner, args.reason)
    elif command == "resume":
        return project.resume(), 0
    elif command == "snapshot":
        snapshot = project.snapshot()
        return {"snapshot": snapshot, "snapshot_digest": value_digest(snapshot)}, 0
    elif command == "status":
        data = project.load()
        gate = project.gate(data["phase"])
        return {"title": data["title"], "phase": data["phase"], "gate": gate,
                "independence": "attested, not authenticated", "owner": data["owner"]}, 0
    return {"action": command, "status": "RECORDED"}, 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result, code = dispatch(args)
    except (ProjectError, OSError, KeyError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        result, code = {"status": "BLOCKED", "reason": str(exc)}, 2
    if result is not None:
        print(json.dumps(result, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
