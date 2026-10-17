"""Execute native roles without inventing provider identities or review results.

This transport is deliberately independent of project acceptance. A successful
process result does not establish engineering correctness or reviewer independence.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import string
import subprocess
import time
import uuid


DEFAULT_TIMEOUTS = {"builder": 3600, "reviewer": 1800, "repair": 3600}


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _arguments(config: dict, prompt: str, paths: dict, schema: object) -> list[str]:
    adapter = config.get("adapter", "agy")
    if adapter == "agy":
        arguments = [str(config.get("executable", "agy"))]
        if config.get("new_project", True):
            arguments.append("--new-project")
        if config.get("model"):
            arguments += ["--model", str(config["model"])]
        if config.get("effort"):
            if config["effort"] not in {"low", "medium", "high", "xhigh", "max"}:
                raise ValueError("Unsupported AGY effort")
            arguments += ["--effort", config["effort"]]
        if config.get("skip_permissions", False):
            arguments.append("--dangerously-skip-permissions")
        arguments += ["--disable-slash-commands", "--output-format", "stream-json"]
        if schema is not None:
            arguments += ["--json-schema", paths["schema_file"]]
        return arguments + ["--print-timeout", "0", "--print", prompt]
    if adapter != "command":
        raise ValueError("Adapter must be agy or command")
    template = config.get("argv")
    if not isinstance(template, list) or not template or not all(isinstance(v, str) for v in template):
        raise ValueError("Command adapter requires a nonempty argv list of strings")
    values = {**paths, "model": str(config.get("model") or "")}
    arguments = []
    formatter = string.Formatter()
    for argument in template:
        for _, field, format_spec, conversion in formatter.parse(argument):
            if field is not None and (field not in values or format_spec or conversion):
                raise ValueError("Only prompt_file, project, model, schema_file and scratch placeholders are supported")
        arguments.append(argument.format_map(values))
    if not arguments[0]:
        raise ValueError("Command executable is empty")
    return arguments


def _parse_output(text: str, structured: bool) -> dict:
    """Decode the observed AGY NDJSON or the documented generic JSON envelope."""
    parsed = {"actual_model": None, "root_session_id": None,
              "child_session_ids": [], "response": None, "raw_response": None,
              "provider_status": None, "usage": None, "parse_warnings": 0}
    events = []
    try:
        whole = json.loads(text)
    except (ValueError, TypeError):
        whole = None
    if isinstance(whole, dict) and ("status" in whole or "event" not in whole):
        result = whole
        parsed["root_session_id"] = result.get("session_id") or result.get("conversation_id")
        parsed["actual_model"] = result.get("model")
    else:
        if isinstance(whole, dict):
            events.append(whole)
        for line in ([] if isinstance(whole, dict) else text.splitlines()):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                parsed["parse_warnings"] += 1
                continue
            if isinstance(event, dict):
                events.append(event)
            else:
                parsed["parse_warnings"] += 1
        initial = next((event for event in events if event.get("event") == "init"), None)
        if initial:
            parsed["root_session_id"] = initial.get("conversation_id")
            parsed["actual_model"] = initial.get("init", {}).get("model")
        # A child result must never stand in for the unfinished root result.
        candidates = [event.get("result", {}) for event in events if event.get("event") == "result"]
        root = parsed["root_session_id"]
        candidates = [value for value in candidates if isinstance(value, dict)
                      and (not root or value.get("conversation_id") in {None, root})]
        result = candidates[-1] if candidates else {}
        parsed["root_session_id"] = root or result.get("conversation_id")
        for event in events:
            for payload in (event, event.get("step_update", {}), event.get("result", {})):
                if isinstance(payload, dict):
                    identity = payload.get("conversation_id")
                    if identity and identity != parsed["root_session_id"] and identity not in parsed["child_session_ids"]:
                        parsed["child_session_ids"].append(identity)
        parsed["actual_model"] = parsed["actual_model"] or result.get("model")
    parsed["provider_status"] = result.get("status")
    parsed["usage"] = result.get("usage")
    parsed["raw_response"] = result.get("response")
    if "structured_output" in result and result["structured_output"] is not None:
        parsed["response"] = result["structured_output"]
    else:
        response = result.get("response")
        if structured and isinstance(response, str):
            try:
                response = json.loads(response)
            except ValueError:
                response = None
        parsed["response"] = response
    parsed["valid"] = (parsed["provider_status"] == "SUCCESS" and parsed["response"] is not None)
    if structured and not isinstance(parsed["response"], (dict, list)):
        parsed["valid"] = False
    return parsed


def _contain(process: subprocess.Popen):
    """Bind a role's process tree to a Windows job so leftovers die with it."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_uint64 * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        if not kernel32.AssignProcessToJobObject(job, int(process._handle)):
            kernel32.CloseHandle(job)
            return None
        return job
    except (OSError, AttributeError, ValueError):
        return None


def _release(process: subprocess.Popen, job) -> dict:
    """After the root exits, stop any descendant it left running."""
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return {"lingering_descendants": "process group signalled"}
        except OSError:
            return {"lingering_descendants": 0}
    if job is None:
        return {"lingering_descendants": "UNCONTAINED"}
    import ctypes
    from ctypes import wintypes

    class Accounting(ctypes.Structure):
        _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                    ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                    ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                    ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    accounting = Accounting()
    kernel32.QueryInformationJobObject(job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None)
    lingering = int(accounting.ActiveProcesses)
    if lingering:
        kernel32.TerminateJobObject(job, 1)
    kernel32.CloseHandle(job)
    return {"lingering_descendants": lingering}


def _stop_owned_process(process: subprocess.Popen) -> dict:
    cleanup = {"requested": True, "pid": process.pid, "method": None,
               "root_stopped": False, "external_service_cancellation": "UNKNOWN",
               "descendant_stop_verified": False}
    try:
        if os.name == "nt":
            cleanup["method"] = "taskkill-owned-pid-tree"
            stopped = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                     capture_output=True, timeout=10, check=False)
            cleanup["tree_command_exit_code"] = stopped.returncode
        else:
            cleanup["method"] = "kill-owned-process-group"
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        cleanup["error"] = str(exc)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            cleanup["root_error"] = str(exc)
    cleanup["root_stopped"] = process.poll() is not None
    return cleanup


def execute_role(project_root, role, prompt, config, evidence_dir, response_schema=None, environment=None) -> dict:
    """Run one configured native role and return its durable execution receipt.

    config is a per-role dictionary, not a provider credential store. Attempts
    receive unique subdirectories under evidence_dir. Generic command adapters
    must emit the JSON envelope documented in docs/runtime-protocol.md.
    """
    project = Path(project_root).resolve()
    evidence = Path(evidence_dir).resolve()
    attempt_id = uuid.uuid4().hex
    attempt = evidence / attempt_id
    attempt.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    receipt = {"schema": 1, "attempt_id": attempt_id, "role": role,
               "adapter": config.get("adapter", "agy") if isinstance(config, dict) else None,
               "project": str(project), "started_at": _utc(), "status": "ATTEMPT_STARTED",
               "requested_model": config.get("model") if isinstance(config, dict) else None,
               "actual_model": None, "root_session_id": None, "child_session_ids": [],
               "pid": None, "exit_code": None, "response": None,
               "cleanup": {"requested": False, "external_service_cancellation": "NOT_REQUESTED"},
               "artifacts": {"receipt": str(attempt / "receipt.json"),
                             "prompt": str(attempt / "prompt.md"),
                             "stdout": str(attempt / "stdout.txt"),
                             "stderr": str(attempt / "stderr.txt")}}
    receipt_path = attempt / "receipt.json"
    _write_json(receipt_path, receipt)
    for name in ("stdout.txt", "stderr.txt"):
        (attempt / name).touch()
    process = None
    try:
        if not isinstance(config, dict):
            raise ValueError("Role configuration must be an object")
        if role not in DEFAULT_TIMEOUTS:
            raise ValueError("Role must be builder, reviewer or repair")
        if not project.is_dir() or not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Existing project directory and nonempty prompt are required")
        timeout = config.get("timeout", DEFAULT_TIMEOUTS[role])
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout must be a finite positive number of seconds")
        receipt["timeout_seconds"] = timeout
        (attempt / "prompt.md").write_text(prompt, encoding="utf-8")
        schema_file = attempt / "response-schema.json"
        if response_schema is not None:
            if not isinstance(response_schema, dict):
                raise ValueError("Response schema must be an object")
            _write_json(schema_file, response_schema)
            receipt["artifacts"]["schema"] = str(schema_file)
        paths = {"project": str(project), "prompt_file": str(attempt / "prompt.md"),
                 "schema_file": str(schema_file) if response_schema is not None else "",
                 "scratch": (environment or {}).get("MATLAB_HARNESS_SCRATCH", "")}
        arguments = _arguments(config, prompt, paths, response_schema)
        # Retain the exact argv in private project evidence, not public telemetry.
        receipt["argv"] = arguments
        with (attempt / "stdout.txt").open("wb") as stdout, (attempt / "stderr.txt").open("wb") as stderr:
            process = subprocess.Popen(arguments, cwd=project, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, shell=False,
                                       start_new_session=os.name != "nt",
                                       env={**os.environ, **(environment or {})})
            job = _contain(process)
            receipt["pid"] = process.pid
            _write_json(receipt_path, receipt)
            try:
                process.wait(timeout=timeout)
                receipt["status"] = "SUCCEEDED" if process.returncode == 0 else "FAILED"
            except subprocess.TimeoutExpired:
                receipt["status"] = "TIMED_OUT"
                receipt["cleanup"] = _stop_owned_process(process)
            except KeyboardInterrupt:
                receipt["status"] = "INTERRUPTED"
                receipt["cleanup"] = _stop_owned_process(process)
            receipt["cleanup"].update(_release(process, job))
        receipt["exit_code"] = process.poll()
        output = (attempt / "stdout.txt").read_text(encoding="utf-8", errors="replace")
        try:
            parsed = _parse_output(output, response_schema is not None)
            valid = parsed.pop("valid")
            receipt.update(parsed)
            if receipt["status"] == "SUCCEEDED" and not valid:
                receipt["status"] = "FAILED" if parsed["provider_status"] not in {None, "SUCCESS"} else "MALFORMED"
        except (ValueError, TypeError, AttributeError) as exc:
            receipt["parse_error"] = str(exc)
            if receipt["status"] == "SUCCEEDED":
                receipt["status"] = "MALFORMED"
    except ValueError as exc:
        receipt["status"] = "CONFIG_ERROR"
        receipt["error"] = str(exc)
    except OSError as exc:
        receipt["status"] = "LAUNCH_FAILED" if process is None else "FAILED"
        receipt["error"] = str(exc)
        if process is not None and process.poll() is None:
            receipt["cleanup"] = _stop_owned_process(process)
    finally:
        receipt["finished_at"] = _utc()
        receipt["wall_seconds"] = round(time.monotonic() - started, 6)
        _write_json(receipt_path, receipt)
    return receipt
