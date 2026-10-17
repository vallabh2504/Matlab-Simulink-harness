"""Explicit interruption recovery; never infer successful execution from a dead PID."""
from __future__ import annotations

import ctypes
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
import uuid

from .project import Project, ProjectError, digest, read_json


def process_status(pid):
    """Read-only local PID query. UNKNOWN is not permission to recover."""
    if isinstance(pid, bool) or not isinstance(pid, int) or not 0 < pid <= 0xFFFFFFFF:
        return {"status": "UNKNOWN", "reason": "Invalid tracked PID"}
    if os.name == "nt":
        try:
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.GetExitCodeProcess.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            handle = kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION only
            if not handle:
                error = ctypes.get_last_error()
                return {"status": "STOPPED" if error == 87 else "UNKNOWN",
                        "method": "Windows OpenProcess/query", "winerror": error}
            try:
                code = wintypes.DWORD()
                if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return {"status": "UNKNOWN", "method": "Windows exit-code query",
                            "winerror": ctypes.get_last_error()}
                return {"status": "LIVE" if code.value == 259 else "STOPPED",
                        "method": "Windows exit-code query", "exit_code": code.value}
            finally:
                kernel.CloseHandle(handle)
        except (AttributeError, OSError) as exc:
            return {"status": "UNKNOWN", "reason": str(exc)}
    if os.name == "posix":
        try:
            result = subprocess.run(["ps", "-p", str(pid), "-o", "pid="],
                capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"status": "UNKNOWN", "reason": str(exc)}
        if result.returncode == 0 and result.stdout.strip() == str(pid):
            return {"status": "LIVE", "method": "read-only ps PID query"}
        if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
            return {"status": "STOPPED", "method": "read-only ps PID query"}
        return {"status": "UNKNOWN", "method": "read-only ps PID query",
                "returncode": result.returncode, "reason": result.stderr.strip()}
    return {"status": "UNKNOWN", "reason": "Unsupported OS process query"}


def _owned_control(project):
    root = project.root.resolve()
    control = project.control
    junction = getattr(control, "is_junction", lambda: False)()
    if control.is_symlink() or junction or not control.resolve().is_relative_to(root):
        raise ProjectError("Recovery control path is linked or escapes the owned project")
    journey = control / "journey"
    if (journey.is_symlink() or getattr(journey, "is_junction", lambda: False)()
            or not journey.resolve().is_relative_to(control.resolve())
            or not journey.resolve().is_relative_to(root)):
        raise ProjectError("Recovery journey path escapes owned control records")
    return journey


def _attempt_path(project, value):
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ProjectError("Explicit recovery attempt path is required")
    supplied = Path(value)
    if ".." in supplied.parts:
        raise ProjectError("Recovery attempt cannot contain traversal")
    path = supplied if supplied.is_absolute() else project.root / supplied
    journey = _owned_control(project)
    if journey.is_symlink() or path.is_symlink():
        raise ProjectError("Recovery journal paths cannot be symlinks")
    resolved = path.resolve()
    if resolved.parent != journey.resolve() or not re.fullmatch(r"attempt-[A-Za-z0-9_-]+", resolved.name):
        raise ProjectError("Name one attempt directly inside .matlab-harness/journey")
    if not resolved.is_dir() or not resolved.is_relative_to(project.control.resolve()):
        raise ProjectError("Recovery attempt must be an existing owned journal directory")
    return resolved


def _object(path):
    if path.is_symlink() or not path.is_file():
        raise ProjectError("Missing or unsafe recovery record: " + str(path))
    data = read_json(path)
    if not isinstance(data, dict):
        raise ProjectError("Recovery record must be an object: " + str(path))
    return data


def _seconds(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ProjectError("Invalid " + label)
    return float(value)


def _date(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProjectError("Recovery needs an observed timezone-aware start timestamp") from exc
    if result.tzinfo is None:
        raise ProjectError("Recovery start timestamp must include timezone")
    return result.astimezone(timezone.utc)


def _write_once(path, record):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def recover_journey(project, owner, attempt_directory, stopped_process_attestation, source,
                    expected_lock_token=None):
    """Append INTERRUPTED_RECOVERED after explicit stopped-process inspection.

    New starts must bind journey_pid and journey_lock_token to the exact lock.
    Unbound legacy locks remain inspection-required. Active leases stay active.
    """
    project = project if isinstance(project, Project) else Project(project)
    _owned_control(project)
    if not all(isinstance(v, str) and v.strip() for v in (owner, stopped_process_attestation, source)):
        raise ProjectError("Actual owner, stopped-process inspection attestation and source are required")
    data = project.load()
    if data["owner"] != owner:
        raise ProjectError("Only the current claimed orchestrator may recover its journey")
    mutation = project.control / "mutation.lock"
    if mutation.exists() or mutation.is_symlink():
        raise ProjectError("Mutation lock exists; inspect and recover it separately")
    attempt = _attempt_path(project, attempt_directory)
    final = attempt / "finished.json"
    if final.exists() or final.is_symlink():
        raise ProjectError("Attempt already has terminal evidence; never overwrite it")
    started_path = attempt / "started.json"
    declaration_path = attempt.parent / "declaration.json"
    started = _object(started_path)
    declaration = _object(declaration_path)
    started_sha, declaration_sha = digest(started_path), digest(declaration_path)
    if started.get("owner") != owner or declaration.get("owner") != owner or declaration.get("project_id") != data["id"]:
        raise ProjectError("Attempt/declaration ownership does not match this project")
    if started.get("declaration_sha256") != declaration_sha:
        raise ProjectError("Attempt does not bind the current immutable declaration")
    ceiling = _seconds(declaration.get("ceiling_seconds"), "immutable ceiling")
    if ceiling <= 0:
        raise ProjectError("Immutable ceiling must be positive")
    pid, token = started.get("journey_pid"), started.get("journey_lock_token")
    if not isinstance(token, str) or not token.strip():
        raise ProjectError("Legacy attempt lacks lock binding; preserve it for explicit inspection")
    if expected_lock_token is not None and expected_lock_token != token:
        raise ProjectError("Explicit journey lock token does not match attempt")
    observed = process_status(pid)
    if observed["status"] != "STOPPED":
        raise ProjectError("Tracked journey process is " + observed["status"] + "; inspection required")
    lock = project.control / "journey.lock"
    lock_sha = None
    if lock.exists() or lock.is_symlink():
        lock_data = _object(lock)
        if (lock_data.get("pid") != pid or lock_data.get("token") != token
                or lock_data.get("owner") != owner
                or lock_data.get("project_id") != data["id"]
                or _attempt_path(project, lock_data.get("attempt", "")) != attempt):
            raise ProjectError("Foreign or unbound journey lock remains intact")
        lock_sha = digest(lock)
    prior = 0.0
    for sibling in attempt.parent.glob("attempt-*"):
        if sibling == attempt:
            continue
        if (not sibling.is_dir() or sibling.is_symlink()
                or sibling.resolve() != sibling.absolute()
                or sibling.resolve().parent != attempt.parent.resolve()):
            raise ProjectError("Unsafe sibling journal remains inspection-required")
        terminal = _object(sibling / "finished.json")
        prior += _seconds(terminal.get("wall_seconds"), "prior invocation charge")
    prior = _seconds(prior, "total prior invocation charge")
    if abs(_seconds(started.get("prior_seconds"), "recorded prior charge") - prior) > 1e-6:
        raise ProjectError("Recorded prior budget does not match preserved terminal journals")
    began = _date(started.get("started_at"))
    step_charge = 0.0
    for path in attempt.glob("step-*-finished.json"):
        step_charge += _seconds(_object(path).get("wall_seconds"), "observed step time")
    step_charge = _seconds(step_charge, "total observed step time")
    recovery_id = uuid.uuid4().hex
    with project.transaction(owner) as locked:
        _owned_control(project)
        if digest(started_path) != started_sha or digest(declaration_path) != declaration_sha:
            raise ProjectError("Recovery inputs changed; preserve journals for inspection")
        if (lock_sha is not None and (not lock.is_file() or digest(lock) != lock_sha)
                or lock_sha is None and (lock.exists() or lock.is_symlink())):
            raise ProjectError("Journey lock ownership changed; preserve it")
        if process_status(pid)["status"] != "STOPPED":
            raise ProjectError("Tracked PID became live or inaccessible; preserve journals")
        recovered_at = datetime.now(timezone.utc)
        elapsed = (recovered_at - began).total_seconds()
        if elapsed < 0:
            raise ProjectError("Clock precedes recorded attempt start; inspection required")
        charge = math.ceil(max(elapsed, step_charge))
        result = {"status": "INTERRUPTED_RECOVERED", "recovery_id": recovery_id,
            "phase": locked["phase"], "invocation": str(attempt), "owner": owner,
            "wall_seconds": charge, "observed_elapsed_seconds": elapsed,
            "remaining_seconds": max(0.0, ceiling - prior - charge),
            "finished_at": recovered_at.isoformat(), "started_sha256": started_sha,
            "declaration_sha256": declaration_sha, "tracked_pid": pid,
            "process_query": observed, "stopped_process_attestation": stopped_process_attestation,
            "inspection_source": source, "active_tasks": [name for name, task in locked["tasks"].items()
                                                         if task["status"] == "ACTIVE"],
            "accounting": "Conservative start-to-recovery UTC wall time; includes human waiting and rounds upward",
            "external_service_cancellation": "UNKNOWN", "descendant_stop_verified": False,
            "observed_execution_outcome": "UNKNOWN; no successful role completion or approval inferred"}
        _write_once(final, result)
        terminal_sha = digest(final)
        locked["decisions"].append({"assertion": "ASSUMED",
            "text": "Explicit interrupted journey recovery; stopped resources attested by operator, successful execution not inferred",
            "source": source, "at": recovered_at.isoformat(), "recovery_id": recovery_id,
            "terminal_record": final.relative_to(project.root).as_posix(),
            "terminal_sha256": terminal_sha, "inspection": stopped_process_attestation,
            "charged_seconds": charge})
    if digest(final) != terminal_sha or not any(item.get("recovery_id") == recovery_id
                                              for item in project.load()["decisions"]):
        raise ProjectError("Recovery terminal/decision verification failed; preserve lock")
    if lock_sha is not None:
        _owned_control(project)
        if not lock.is_file() or lock.is_symlink() or digest(lock) != lock_sha:
            return {**result, "lock_cleanup": "INSPECTION_REQUIRED",
                    "reason": "Terminal retained; changed/foreign journey lock was preserved"}
        lock.unlink()
    return {**result, "lock_cleanup": "REMOVED_EXACT_OWNED_LOCK" if lock_sha is not None else "NO_LOCK_PRESENT"}

