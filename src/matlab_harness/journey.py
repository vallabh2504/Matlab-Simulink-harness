"""Run an already configured ENG project, retaining honest pause/failure states."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
import re
import subprocess
from pathlib import Path
import sys
import time
import uuid

from .project import DEFAULT_BUDGETS, PHASES, SERIOUS, Project, ProjectError, atomic_json, cites, digest, inside, read_json, value_digest
from .compact import check_summary
from .mutation import run_mutation
from .answer import _packet_id
from .workflow import _clip, execute, next_step


def _write_once(path, record):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _implementation_hashes(project):
    return _implementation_artifacts(project.snapshot())


def _implementation_artifacts(snapshot):
    suffixes = {".m", ".mlx", ".slx", ".mdl", ".sldd", ".mat", ".csv", ".json", ".xml"}
    return {name: fingerprint for name, fingerprint in snapshot["artifacts"].items()
            if fingerprint is not None and Path(name).suffix.lower() in suffixes}


def _implementation_changes(project, protected):
    actual = _implementation_hashes(project)
    return {name: {"expected": protected.get(name), "actual": actual.get(name)}
            for name in sorted(set(protected) | set(actual)) if actual.get(name) != protected.get(name)}


def _for_user(project, stage, finding, asked):
    """Whether only the user can act on a blocking finding: one on a control record; one on the
    contract once the design says no reading answers it ("USER QUESTION <ID>:"), or at
    requirements, which has no design to answer it; another the reviewer marks a user decision.
    A contract finding the design has not given up on is the design's to repair."""
    location = project.reserved_location(finding["artifact"])
    if location == "contract":
        return stage == "requirements" or finding["id"].casefold() in asked
    return location == "control" or (finding.get("user_decision") is True and finding.get("kind") != "PROVEN DEFECT")


def _gate_text(problems, checks, total=4000, each=600):
    """Distinct gate problems for repair, without the failed checks the summary already shows."""
    shown = {"Check not passed: " + name for name in checks}
    kept = [p for p in dict.fromkeys(problems) if p not in shown
            and not ("semantic-adequacy" in checks and p.startswith("Required semantic adequacy did not pass"))]
    text, used = [], 0
    for index, problem in enumerate(kept):
        item = _clip(problem, each)
        if used + len(item) > total:
            text.append(f"(+{len(kept) - index} more in gate record)")
            break
        text.append(item)
        used += len(item)
    return ("Gate problems: " + " | ".join(text) + ".") if text else ""


class Journey:
    def __init__(self, project, owner, ceiling, review_existing_implementation=False, journey_lock_token=None, stop_after=None):
        self.project, self.owner = project, owner
        self.started = time.monotonic()
        if isinstance(ceiling, bool) or not isinstance(ceiling, (int, float)) or not math.isfinite(ceiling) or ceiling <= 0:
            raise ProjectError("Journey ceiling must be finite positive seconds")
        if not isinstance(review_existing_implementation, bool):
            raise ProjectError("Review-existing implementation mode must be boolean")
        self.review_existing_implementation = review_existing_implementation
        if stop_after is not None and stop_after not in PHASES:
            raise ProjectError("Checkpoint stop must name a lifecycle phase")
        self.stop_after = stop_after
        data = project.load()
        if data["owner"] != owner:
            raise ProjectError("Journey requires the current claimed orchestrator")
        self.directory = project.control / "journey"
        self.directory.mkdir(exist_ok=True)
        declaration = self.directory / "declaration.json"
        if not declaration.exists():
            if any(self.directory.iterdir()) or any("implementation_baseline" in d for d in data["decisions"]):
                raise ProjectError("Missing journey declaration with existing history; preserve original seed/budget evidence and inspect recovery")
            _write_once(declaration, {"schema": 1, "ceiling_seconds": ceiling,
                "declared_at": _utc(), "project_id": data["id"], "owner": owner,
                "review_existing_implementation": review_existing_implementation,
                "initial_implementation_hashes": _implementation_hashes(project) if review_existing_implementation else {},
                "budgets": {**DEFAULT_BUDGETS, **data.get("budgets", {})},
                "accounting": "Active invocation wall time, including setup, roles, native checks and cleanup"})
        self.declaration = read_json(declaration)
        if (not isinstance(self.declaration, dict) or self.declaration.get("schema") != 1
                or not isinstance(self.declaration.get("project_id"), str)
                or isinstance(self.declaration.get("ceiling_seconds"), bool)
                or not isinstance(self.declaration.get("ceiling_seconds"), (int, float))
                or not math.isfinite(self.declaration["ceiling_seconds"]) or self.declaration["ceiling_seconds"] <= 0
                or not isinstance(self.declaration.get("review_existing_implementation", False), bool)
                or not isinstance(self.declaration.get("initial_implementation_hashes"), dict)
                or any(not isinstance(name, str) or not isinstance(fingerprint, str)
                       or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
                       for name, fingerprint in self.declaration["initial_implementation_hashes"].items())):
            raise ProjectError("Invalid journey declaration; preserve original evidence and inspect recovery")
        if self.declaration["project_id"] != data["id"] or self.declaration["ceiling_seconds"] != ceiling:
            raise ProjectError("Predeclared project journey ceiling cannot be changed retrospectively")
        if self.declaration.get("review_existing_implementation", False) != review_existing_implementation:
            raise ProjectError("Predeclared review-existing implementation mode must remain the same on resume")
        self.protected_implementation_hashes = self.declaration["initial_implementation_hashes"]
        if review_existing_implementation:
            for decision in data["decisions"]:
                baseline = decision.get("implementation_baseline")
                if baseline is None:
                    continue
                if (decision.get("source") != "baseline revision" or not isinstance(baseline, dict)
                        or baseline.get("declaration_sha256") != digest(declaration)):
                    raise ProjectError("Revision implementation baseline has invalid declaration binding")
                archive_name = baseline.get("archive", "")
                if not isinstance(archive_name, str) or not re.fullmatch(r"\.matlab-harness/history/baseline-[0-9a-f]{32}\.json", archive_name):
                    raise ProjectError("Revision implementation baseline has invalid archive location")
                archive_path = inside(project.root, archive_name)
                if digest(archive_path) != baseline.get("archive_sha256"):
                    raise ProjectError("Revision implementation baseline archive changed")
                archived = read_json(archive_path)
                snapshot = baseline.get("snapshot")
                if (not isinstance(snapshot, dict) or not isinstance(snapshot.get("artifacts"), dict)
                        or archived.get("id") != data["id"] or archived.get("owner") != baseline.get("revision_owner")
                        or archived.get("phase") != "handoff"
                        or not any(a.get("checkpoint") == "handoff" and a.get("snapshot_digest") == value_digest(snapshot)
                                   for a in archived.get("acceptances", []))):
                    raise ProjectError("Revision implementation baseline lacks matching accepted handoff evidence")
                self.protected_implementation_hashes = _implementation_artifacts(snapshot)
        self.prior_seconds = 0.0
        self.history = []
        for attempt in sorted(self.directory.glob("attempt-*")):
            if (not attempt.is_dir() or attempt.is_symlink()
                    or attempt.resolve() != attempt.absolute()
                    or attempt.resolve().parent != self.directory.resolve()):
                raise ProjectError("Unsafe journey journal requires inspection: " + str(attempt))
            final = attempt / "finished.json"
            if not final.is_file():
                raise ProjectError("Unfinished journey invocation requires inspection: " + str(attempt))
            record = read_json(final)
            if record.get("status") == "INTERRUPTED_RECOVERED":
                recovery_id = record.get("recovery_id")
                matching = [item for item in data["decisions"]
                            if recovery_id and item.get("recovery_id") == recovery_id]
                if (len(matching) != 1
                        or matching[0].get("terminal_record") != final.relative_to(project.root).as_posix()
                        or matching[0].get("terminal_sha256") != digest(final)
                        or record.get("declaration_sha256") != digest(declaration)):
                    raise ProjectError("Recovered invocation lacks matching committed recovery evidence; inspect it before resuming: " + str(attempt))
            self.prior_seconds += record["wall_seconds"]
            self.history += [read_json(path) for path in sorted(attempt.glob("step-*-finished.json"))]
        self.attempt = self.directory / ("attempt-" + uuid.uuid4().hex)
        self.attempt.mkdir()
        _write_once(self.attempt / "started.json", {"started_at": _utc(), "owner": owner,
            "prior_seconds": self.prior_seconds, "declaration_sha256": digest(declaration),
            "journey_pid": os.getpid(), "journey_lock_token": journey_lock_token, "stop_after": stop_after})
        self.steps = []

    def remaining(self):
        return max(0.0, self.declaration["ceiling_seconds"] - self.prior_seconds - (time.monotonic() - self.started))

    def dispatch_floor(self, budget):
        """Below this much remaining time a role or semantic run cannot finish; stop instead."""
        return min(120.0, budget, 0.1 * self.declaration["ceiling_seconds"])

    def step(self, kind, stage, name, action, limit):
        remaining = self.remaining()
        if remaining <= 0:
            raise TimeoutError("Predeclared journey ceiling exhausted")
        if kind in {"role", "semantic"} and remaining < self.dispatch_floor(limit):
            raise TimeoutError("Remaining journey time below dispatch floor")
        limit = min(limit, remaining)
        number = len(self.steps)
        base = self.attempt / f"step-{number:04d}"
        started = time.monotonic()
        _write_once(base.with_name(base.name + "-started.json"), {"kind": kind, "phase": stage,
            "name": name, "started_at": _utc(), "ceiling_seconds": limit,
            "remaining_before": remaining})
        try:
            result = action(limit)
        except (ProjectError, OSError, KeyboardInterrupt) as exc:
            record = {"kind": kind, "phase": stage, "name": name, "status": "INTERRUPTED" if isinstance(exc, KeyboardInterrupt) else "FAILED",
                      "error": str(exc), "wall_seconds": time.monotonic() - started}
            _write_once(base.with_name(base.name + "-finished.json"), record)
            self.steps.append(record)
            raise
        record = {"kind": kind, "phase": stage, "name": name, "result": result,
                  "status": result.get("status"), "finished_at": _utc(),
                  "wall_seconds": time.monotonic() - started,
                  "snapshot_digest_after": value_digest(self.project.snapshot())}
        _write_once(base.with_name(base.name + "-finished.json"), record)
        self.steps.append(record)
        return result

    def already_built(self, stage):
        current = value_digest(self.project.snapshot())
        return any(item.get("kind") == "role" and item.get("name") in {"builder", "repair"}
                   and item.get("phase") == stage and item.get("status") == "SUCCEEDED"
                   and item.get("snapshot_digest_after") == current
                   for item in self.history + self.steps)

    def approval_current(self):
        try:
            self.project._approval_current(self.project.load())
            return True
        except ProjectError:
            return False

    def role(self, role, stage, detail, prior=None):
        data = self.project.load()
        active = [name for name, task in data["tasks"].items() if task["status"] == "ACTIVE"]
        if active:
            return {"status": "INPUT_REQUIRED", "reason": "Inspect existing active ownership before dispatch", "tasks": active}
        budget = data.get("budgets", DEFAULT_BUDGETS).get(role, DEFAULT_BUDGETS[role])
        if self.remaining() < self.dispatch_floor(budget):
            raise TimeoutError("Remaining journey time below dispatch floor")
        leased = None
        if role != "reviewer" and self.approval_current():
            leased = "journey-" + uuid.uuid4().hex
            kind = "discovery" if stage == "requirements" else "design" if stage == "architecture" else "repair" if role == "repair" else "implementation"
            self.project.lease(self.owner, leased, leased, data["scope"],
                               [r["id"] for r in data["requirements"]], kind=kind)
        try:
            result = self.step("role", stage, role,
                lambda limit: execute(self.project, self.owner, role, stage, detail, remaining_seconds=limit,
                                      prior=prior), budget)
        except (ProjectError, OSError, TimeoutError):
            # Nothing is still running; an interrupted role may be, so KeyboardInterrupt keeps the lease.
            if leased:
                try:
                    self.project.finish_task(self.owner, leased, "FAILED")
                except (ProjectError, OSError) as release:
                    # The dispatch error is the one to report; the lease stays ACTIVE for inspection.
                    self.steps.append({"kind": "lease-release", "name": leased, "status": "FAILED", "error": str(release)})
            raise
        if leased and result["status"] not in {"TIMED_OUT", "INTERRUPTED"}:
            self.project.finish_task(self.owner, leased, "DONE" if result["status"] == "SUCCEEDED" else "FAILED")
        if result["status"] == "MANUAL_HANDOFF":
            return {**result, "status": "INPUT_REQUIRED", "reason": "Configured role requires native/manual execution"}
        return result

    def review(self, stage, checked=None):
        """Retry only rejected report protocol, never a negative verdict or trust failure.

        Three total attempts per unchanged checkpoint snapshot, counted from the
        durable failure ledger across invocations. All elapsed time stays in the journey
        ceiling; no engineering repair or acceptance is manufactured here.
        """
        while True:
            current = value_digest(self.project.snapshot())
            data = self.project.load()
            recorded = data.get("review_protocol_failures", {})
            failures = [item for item in recorded.values()
                        if item["checkpoint"] == stage and item["snapshot_digest"] == current]
            for item in failures:
                if digest(inside(self.project.root, item["path"])) != item["sha256"]:
                    raise ProjectError("Rejected review report changed")
            # A transport-unfinished report binds its allegations but is not a protocol attempt.
            # The store sorts keys, so order by time: failures[-1] must be the newest report.
            failures = sorted((item for item in failures if item.get("kind", "protocol") == "protocol"),
                              key=lambda item: item.get("recorded", ""))
            for run in data.get("runs", []):
                if "packet" not in run and "review_import" not in run:
                    # Historical records predate durable import intents.
                    continue
                if (run["role"] != "reviewer" or run["checkpoint"] != stage
                        or run["packet"]["snapshot_digest"] != current):
                    continue
                packet_root = Path(run["packet"]["prompt"]).parent
                status_path = inside(self.project.root, (packet_root / "execution/review-import.json").relative_to(self.project.root).as_posix())
                if status_path.is_file():
                    status = read_json(status_path)
                    if status.get("status") == "PENDING_REVIEW_IMPORT" and status.get("report") not in recorded:
                        return {"status": "INPUT_REQUIRED", "reason": "Interrupted review import requires inspection before another reviewer dispatch", "record": str(status_path)}
            if len(failures) >= 3:
                return {"status": "REVIEW_PROTOCOL_EXHAUSTED", "reason": "Three independent review reports failed protocol for the unchanged checkpoint; inspect the retained records",
                        "attempts": len(failures), "last_failure": failures[-1]}
            detail = "Inspect the actual current artifacts and declared check evidence. Answer every open item by its handle. Do not modify artifacts."
            if checked and checked.get("status") == "FAILED":
                failed = [name for name, row in check_summary(checked)["checks"].items() if row["status"] != "PASSED"]
                detail += (" ACCEPT is impossible until the declared checks pass; failed: " + ", ".join(failed)
                           + " (output under Latest check results). Diagnose the cause and file it as a finding:"
                           " an implementation defect, an over-asserting test (one that rejects contract-compliant"
                           " behaviour), or a contract gap only the user can resolve (set user_decision).")
            prior = None
            if failures:
                # A correction pass: the artifacts are unchanged, so fix the report, not the review.
                previous = failures[-1]
                prior = {"report": previous["path"], "packet": _packet_id(previous["path"])}
                # The instructions come before the reason, so a clipped task loses only the reason's tail.
                detail += (" Your previous report " + previous["path"] + " was refused. It is copied to your scratch"
                           " directory as prior-report.json, and its scratch files under prior-probes/. Copy it, fix"
                           " only the points below, and resubmit the complete report. Re-propose each probe you rely"
                           " on (run: its path in your scratch) so the host executes it for this packet; a copied"
                           " probe that is not re-proposed proves nothing. Re-inspect only what the fix needs. Do not"
                           " drop findings, and do not assume closure; change the verdict only if the reason below"
                           " says to. It was refused only for: "
                           + previous["reason"] + ".")
            result = self.role("reviewer", stage, detail, prior=prior)
            if result.get("status") != "REVIEW_NOT_IMPORTED" or result.get("retryable") is not True:
                return result

    def decision(self, stage, findings):
        """Write-once record of what only the operator can decide, with the three ways forward."""
        path = self.attempt / f"decision-{len(self.steps):04d}.json"
        text = " ".join(str(finding.get(field, "")) for finding in findings for field in ("artifact", "evidence", "repair"))
        requirements = [r["id"] for r in self.project.load()["requirements"] if cites(text, r["id"])]
        _write_once(path, {"phase": stage, "created_at": _utc(), "cited_requirements": requirements,
            "findings": [{**{field: finding.get(field) for field in ("id", "severity", "artifact", "evidence", "repair")},
                          **{field: finding[field] for field in ("contract_text", "design_text") if field in finding}}
                         for finding in findings],
            "actions": ["Amend requirements.md to settle the question, then record user approval of the revised document",
                        "Write .matlab-harness/counterevidence.md rejecting the claim with evidence; reviewers read it",
                        "Revise the accepted baseline explicitly (matlab-harness revise) when an accepted checkpoint must change"]})
        return path.relative_to(self.project.root).as_posix()

    def mutation(self, stage, checked):
        """Plant defects in copies and run the configured test check, when configured for this stage."""
        config = self.project.load().get("runtime", {}).get("mutation") or {}
        if checked["status"] != "PASSED" or stage not in config.get("stages", ["verification"]) or not config.get("check"):
            return None
        data = self.project.load()
        current = value_digest(self.project.snapshot())
        if data.get("mutation_results", {}).get(stage, {}).get("snapshot_digest") == current:
            return None
        limit = config.get("seconds", data.get("budgets", DEFAULT_BUDGETS).get("native", DEFAULT_BUDGETS["native"]))
        def probe(left):
            # Advisory evidence: a probe that cannot run never blocks or fails the journey.
            try:
                return run_mutation(self.project, self.owner, stage, left)
            except (ProjectError, OSError, subprocess.SubprocessError) as exc:
                return {"status": "ERROR", "error": str(exc)}
        return self.step("mutation", stage, config["check"], probe, limit)

    def checks(self, stage):
        data = self.project.load()
        if stage not in data["required_checks"] or (stage in {"implementation", "verification", "handoff"}
                                                    and not data["required_checks"].get(stage)):
            return {"status": "INPUT_REQUIRED", "reason": "Declare task-specific executable checks for " + stage}
        results = []
        for name in data["required_checks"][stage]:
            result = self.step("check", stage, name,
                lambda limit, name=name: self.project.run_check(self.owner, name, timeout=limit),
                data.get("budgets", DEFAULT_BUDGETS).get("native", DEFAULT_BUDGETS["native"]))
            results.append(result)
            if result["status"] == "BLOCKED":
                return {"status": "INPUT_REQUIRED", "reason": "Native check unavailable or timed out; inspect owned processes before retry", "checks": results}
        if all(r["status"] == "PASSED" for r in results) and stage in data.get("semantic_plan", {}).get("stages", []):
            from .semantics import run as run_semantics
            semantic = self.step("semantic", stage, "semantic-adequacy", lambda limit: run_semantics(self.project, self.owner, stage, limit),
                                 data.get("budgets", DEFAULT_BUDGETS).get("native", DEFAULT_BUDGETS["native"]))
            results.append({**semantic, "name": "semantic-adequacy"})
        return {"status": "PASSED" if all(r["status"] == "PASSED" for r in results) else "FAILED", "checks": results}

    def run(self):
        while True:
            if self.remaining() <= 0:
                return {"status": "CEILING_EXHAUSTED"}
            state = next_step(self.project)
            stage = state["phase"]
            if state["gate"].get("unfinished_review_imports"):
                return {"status": "INPUT_REQUIRED", "reason": "Interrupted review import requires inspection before resuming",
                        "unfinished_review_imports": state["gate"]["unfinished_review_imports"]}
            if state["gate"].get("stage_boundary_violations"):
                return {"status": "INPUT_REQUIRED", "reason": "Restore recorded document/design boundary violations before resuming",
                        "stage_boundary_violations": state["gate"]["stage_boundary_violations"]}
            if stage == "architecture" and self.review_existing_implementation:
                changed = _implementation_changes(self.project, self.protected_implementation_hashes)
                if changed:
                    return {"status": "INPUT_REQUIRED", "reason": "Architecture modified existing implementation before initial verification; inspect the changes and preserve the original fault evidence", "changed_artifacts": changed}
            if state["completed"]:
                return {"status": "COMPLETED", "phase": stage, "gate": state["gate"]}
            if any(a["checkpoint"] == "handoff" for a in self.project.load()["acceptances"]):
                return {"status": "INPUT_REQUIRED", "reason": "Accepted handoff changed; revise explicitly", "gate": state["gate"]}
            if state["active_tasks"]:
                return {"status": "INPUT_REQUIRED", "reason": "Inspect active leases and owned processes", "tasks": state["active_tasks"]}
            if not self.approval_current():
                draft = None
                if stage == "requirements" and not self.already_built(stage) and not self.project.load()["approvals"]:
                    draft = self.role("builder", stage, "Discovery only: draft requirements.md and propose stable IDs/acceptance commands. Do not construct engineering artifacts, mutate project records or invent user approval.")
                    if draft["status"] != "SUCCEEDED":
                        return draft
                return {"status": "WAITING_FOR_USER_APPROVAL", "phase": stage,
                        "reason": "Register the agreed requirement IDs and record actual user approval of the current document; revise first if an accepted baseline changed", "discovery": draft}
            if state["gate"]["accepted"]:
                self.project.accept(self.owner, stage)
                if stage == self.stop_after and stage != "handoff":
                    return {"status": "CHECKPOINT_REACHED", "accepted_checkpoint": stage}
                continue
            # Verification and handoff need produced content (independent oracles,
            # traceability, limitations), not only a review of what already exists.
            build_needed = stage in {"architecture", "implementation", "verification", "handoff"} and not self.already_built(stage)
            if stage == "implementation" and self.review_existing_implementation:
                build_needed = False
            if build_needed:
                protected = {}
                detail = "Complete this stage from the approved brief and current artifacts. Preserve legacy behavior. Return check-plan proposals if required; orchestrator owns check registration."
                if self.review_existing_implementation and stage == "architecture":
                    detail += " This is an existing-implementation debugging journey. At architecture, document and inspect the existing equations/design only. Preserve existing MATLAB, Simulink and parameter implementation artifacts unchanged; their initial defects must first reach native verification and independent implementation review."
                    protected = self.protected_implementation_hashes
                    detail += " Existing implementation hashes that must remain unchanged: " + json.dumps(protected)
                result = self.role("builder", stage, detail)
                if result["status"] != "SUCCEEDED":
                    return result
                changed = _implementation_changes(self.project, protected) if self.review_existing_implementation and stage == "architecture" else {}
                if changed:
                    return {"status": "INPUT_REQUIRED", "reason": "Architecture modified existing implementation before initial verification; inspect the changes and preserve the original fault evidence", "changed_artifacts": changed}
                if not self.approval_current():
                    continue
            checked = self.checks(stage)
            if checked["status"] == "INPUT_REQUIRED":
                return checked
            self.mutation(stage, checked)
            reviewed = self.review(stage, checked)
            if reviewed["status"] != "SUCCEEDED":
                return reviewed
            if not self.approval_current():
                continue
            gate = self.project.gate(stage)
            if gate["accepted"]:
                self.project.accept(self.owner, stage)
                if stage == self.stop_after and stage != "handoff":
                    return {"status": "CHECKPOINT_REACHED", "accepted_checkpoint": stage}
                continue
            data = self.project.load()
            report = next_step(self.project)["reviews"].get(stage, {})
            asked = self.project.user_questions(data)
            reserved = [finding for finding in report.get("findings", [])
                        if finding["severity"] in SERIOUS and finding["status"] != "CLOSED"
                        and self.project.due(stage, finding, data.get("defects", {})) == stage
                        and _for_user(self.project, stage, finding, asked)]
            if reserved:
                return {"status":"INPUT_REQUIRED", "reason":"Blocking findings concern approval, a user decision, a contract question the design says no reading answers, or orchestrator-owned records; resolve authorization/counterevidence or check plans before construction repair",
                        "findings":reserved, "gate":gate, "decision": self.decision(stage, reserved)}
            if any(problem.startswith("Protected out-of-scope file changed") for problem in gate["problems"]):
                return {"status": "INPUT_REQUIRED", "reason": "Protected out-of-scope files changed and could not be restored; inspect them", "gate": gate}
            obligations = [problem for problem in gate["problems"] if problem.startswith("Handoff obligation:")]
            if not report.get("findings") and checked["status"] == "PASSED" and not obligations:
                return {"status": "INPUT_REQUIRED", "reason": "Reviewer supplied no actionable repair; resolve evidence or modeling questions", "gate": gate}
            if data["repairs"] >= data["repair_budget"]:
                return {"status": "REPAIR_BUDGET_EXHAUSTED", "gate": gate}
            # The packet already lists this checkpoint's findings; send only what is new.
            open_findings = [f["id"] for f in report.get("findings", []) if f["status"] != "CLOSED"]
            summary = check_summary(checked)
            result = self.role("repair", stage, "Target only the open review findings " + ", ".join(open_findings)
                               + " and failed native checks. " + _gate_text(gate["problems"], summary["checks"])
                               + " " + json.dumps({"verdict": report.get("verdict"), "checks": summary}))
            if result["status"] != "SUCCEEDED":
                return result
            # The successful repair record suppresses unnecessary rebuilding while
            # forcing native retesting and independent closure of actual findings.


def run_journey(project_root, owner, ceiling=14400, review_existing_implementation=False, stop_after=None):
    project = Project(project_root)
    lock = project.control / "journey.lock"
    token = uuid.uuid4().hex
    try:
        _write_once(lock, {"pid": os.getpid(), "token": token, "owner": owner, "created_at": _utc()})
    except FileExistsError:
        return {"status": "INPUT_REQUIRED", "reason": "Journey lock exists; inspect its owned process before recovery", "lock": str(lock)}
    except OSError as exc:
        return {"status": "INPUT_REQUIRED", "reason": "Cannot open initialized project journey lock: " + str(exc)}
    journey = None
    try:
        journey = Journey(project, owner, ceiling, review_existing_implementation, token, stop_after)
        lock_record = read_json(lock)
        if not isinstance(lock_record, dict) or lock_record.get("token") != token:
            raise ProjectError("Journey lock ownership changed before invocation binding")
        atomic_json(lock, {**lock_record, "attempt": journey.attempt.relative_to(project.root).as_posix(),
                          "project_id": project.load()["id"]})
        result = journey.run()
    except TimeoutError as exc:
        result = {"status": "CEILING_EXHAUSTED", "reason": str(exc)}
    except UnicodeError as exc:
        result = {"status": "INPUT_REQUIRED",
                  "reason": "Project text must use UTF-8; inspect and correct the original file before resuming: " + str(exc)}
    except (ProjectError, OSError) as exc:
        result = {"status": "INPUT_REQUIRED", "reason": str(exc)}
    except KeyboardInterrupt:
        result = {"status": "INTERRUPTED", "reason": "Inspect recorded executions and active leases before resuming"}
    finally:
        try:
            if lock.is_file():
                lock_record = read_json(lock)
                if not isinstance(lock_record, dict):
                    raise ProjectError("Journey lock is not an object; preserve it for inspection")
                if lock_record.get("token") != token:
                    raise ProjectError("Journey lock ownership changed; preserve it for inspection")
                lock.unlink()
        except (ProjectError, OSError) as exc:
            result["cleanup"] = {"status":"INSPECTION_REQUIRED", "reason":str(exc), "lock":str(lock)}
            if result.get("status") == "COMPLETED":
                result["completion_status"] = result["status"]
                result["status"] = "INPUT_REQUIRED"
    if journey is not None:
        result.update({"phase": project.load()["phase"], "invocation": str(journey.attempt),
                       "wall_seconds": time.monotonic() - journey.started,
                       "remaining_seconds": journey.remaining(), "steps": len(journey.steps)})
        _write_once(journey.attempt / "finished.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--ceiling", type=float, default=14400)
    parser.add_argument("--review-existing-implementation", action="store_true",
                        help="Check and independently review existing implementation before rebuilding it")
    parser.add_argument("--stop-after", choices=PHASES, help="Return after accepting this checkpoint; resume retains the original budget")
    args = parser.parse_args(argv)
    result = run_journey(args.project, args.owner, args.ceiling, args.review_existing_implementation, args.stop_after)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"COMPLETED", "CHECKPOINT_REACHED"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
