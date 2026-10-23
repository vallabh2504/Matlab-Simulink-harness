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
import re
import signal
import string
import subprocess
import time
import uuid

from .project import loads


DEFAULT_TIMEOUTS = {"builder": 3600, "reviewer": 1800, "repair": 3600}


def classify_failure(receipt):
    """Classify observed failures without substituting models or restarting budgets."""
    status=receipt["status"]
    if status=="SUCCEEDED":return None
    text=str(receipt.get("provider_status", ""))+" "+str(receipt.get("provider_error", ""))+" "+str(receipt.get("error", ""))
    stderr=Path(receipt["artifacts"]["stderr"])
    if stderr.is_file():
        with stderr.open("rb") as handle:text+=" "+handle.read(65536).decode("utf-8",errors="replace")
    if receipt.get("ingestion",{}).get("problems"):category="unread_source"
    elif status=="CONFIG_ERROR":category="configuration"
    elif re.search(r'\b(?:401|403)\b|unauthorized|authentication|permission denied',text,re.I):category="permanent_authentication"
    elif re.search(r'\b404\b|model[^\n]{0,80}not found|unknown model',text,re.I):category="permanent_model_unavailable"
    elif status in {"TIMED_OUT","INTERRUPTED"}:category=status.lower()
    # A usage limit lasts until its reset, so retrying inside the journey cannot help.
    elif re.search(r'hit your (?:session |weekly |daily |usage )?limit|\b(?:session|weekly|daily|5-hour|usage) limits? (?:reached|exceeded)|reached your (?:specified )?(?:api )?usage limits?|out of (?:extra )?usage',text,re.I):category="provider_usage_limit"
    elif re.search(r'\b(?:429|502|503|504)\b|connection reset|temporarily unavailable',text,re.I):category="transient_transport"
    elif status=="LAUNCH_FAILED":category="configuration"
    elif status=="MALFORMED":category="protocol_or_identity"
    else:category="unclassified_failure"
    return {"category":category,"transient":category=="transient_transport",
            "automatic_transport_attempts":1,"automatic_fallback":False,
            "retry_policy":"stop; any explicit retry retains the original journey ceiling"}


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


def _json_in(text: str):
    # Compatibility view for decoded callers; raw ingress uses the full result.
    from .decoding import decode_answer
    return decode_answer(text).answer


def _parse_output(text: str, structured: bool) -> dict:
    """Decode the agy NDJSON stream or the documented generic JSON envelope."""
    parsed = {"actual_model": None, "root_session_id": None,
              "child_session_ids": [], "response": None, "raw_response": None,
              "provider_status": None, "provider_error": None, "usage": None, "parse_warnings": 0}
    from .decoding import decode_document, combine_answers, source_record
    events, transport_problems, transport_sources, transport_answers = [], [], [], []
    agy_transport = False

    def review_channels(candidate, agy=False):
        return combine_answers(candidate.get("structured_output"), candidate.get("response"),
                               ignore_scalar_fields=("toolAction", "toolSummary") if agy else ())

    def envelope(raw, is_line=False):
        decoded = decode_document(raw, "transport-envelope")
        value = decoded.answer
        if value is None and is_line and raw.lstrip().startswith(("{", "[")):
            transport_problems.extend(["Malformed JSON transport event: " + p for p in decoded.problems])
            transport_sources.extend(decoded.sources)
        if value is not None and decoded.problems:
            transport_problems.extend(decoded.problems)
            transport_sources.extend(decoded.sources)
            def variants(item):
                if isinstance(item, dict) and set(item) == {"answer_sources"}:
                    return item["answer_sources"]
                return [item]
            for outer in variants(value):
                if not isinstance(outer, dict):
                    continue
                candidates = variants(outer.get("result")) if outer.get("event") == "result" else (
                    [outer] if "status" in outer else [])
                for candidate in candidates:
                    if isinstance(candidate, dict):
                        recovered = review_channels(candidate, outer.get("event") == "result")
                        if recovered.answer is not None:
                            transport_answers.append(recovered.answer)
                        transport_problems.extend(recovered.problems)
        # Ambiguous transport is never valid. Use its first coherent branch only
        # to retain available identity/answer claims, alongside a durable gap.
        while isinstance(value, dict) and set(value) == {"answer_sources"}:
            value = value["answer_sources"][0]
        return value

    whole = envelope(text)
    if isinstance(whole, dict) and ("status" in whole or "event" not in whole):
        result = whole
        parsed["root_session_id"] = result.get("session_id") or result.get("conversation_id")
        parsed["actual_model"] = result.get("model")
        children = result.get("child_session_ids")
        if isinstance(children, list):
            parsed["child_session_ids"] = list(dict.fromkeys(
                c for c in children if isinstance(c, str) and c and c != parsed["root_session_id"]))
    else:
        agy_transport = True
        if isinstance(whole, dict):
            events.append(whole)
        for line in ([] if isinstance(whole, dict) else text.splitlines()):
            if not line.strip():
                continue
            try:
                event = envelope(line, is_line=True)
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
        if len(candidates) > 1:
            transport_problems.append("Multiple terminal root results require reconciliation")
            transport_sources.append(source_record(text, "multiple-root-results"))
            for candidate in candidates:
                recovered = review_channels(candidate, True)
                if recovered.answer is not None:
                    transport_answers.append(recovered.answer)
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
    parsed["provider_error"] = result.get("error")
    parsed["usage"] = result.get("usage")
    parsed["raw_response"] = result.get("response")
    if structured:
        reviewed = review_channels(result, agy_transport)
        reviewed.problems.extend(transport_problems)
        reviewed.sources.extend(transport_sources)
        if transport_answers:
            reviewed.answer = [reviewed.answer, *transport_answers]
        if any(".conversation_id" in p or ".session_id" in p for p in transport_problems):
            parsed["root_session_id"] = None
        if any(".model" in p for p in transport_problems):
            parsed["actual_model"] = None
        parsed["response"] = reviewed.answer
        parsed["ingestion"] = reviewed.metadata()
    else:
        parsed["response"] = result.get("structured_output", result.get("response"))
    parsed["valid"] = (parsed["provider_status"] == "SUCCESS" and parsed["response"] is not None)
    if structured and (not isinstance(parsed["response"], (dict, list))
                       or parsed["ingestion"]["problems"]):
        parsed["valid"] = False
    return parsed


def _wait_for_result(process: subprocess.Popen, stdout: Path, timeout: float, grace: float, structured: bool, max_bytes=1_048_576) -> bool:
    """Wait for exit; True when a valid root result was written but the process outlived the grace.

    Raises subprocess.TimeoutExpired when neither happens within timeout.
    """
    deadline = time.monotonic() + timeout
    settled = None
    while True:
        now = time.monotonic()
        stderr=stdout.parent/'stderr.txt'
        if stdout.stat().st_size + (stderr.stat().st_size if stderr.exists() else 0) > max_bytes:
            raise ValueError("Response byte limit exceeded")
        if now >= deadline:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            process.wait(timeout=min(1.0, deadline - now))
            return False
        except subprocess.TimeoutExpired:
            pass
        if settled is None:
            try:
                if _parse_output(stdout.read_text(encoding="utf-8", errors="strict"), structured)["valid"]:
                    settled = time.monotonic()
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        elif time.monotonic() - settled >= grace:
            return True


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
        from .capabilities import capabilities
        profile = capabilities(config)
        receipt["capabilities"] = profile
        structured = response_schema is not None
        if role not in DEFAULT_TIMEOUTS:
            raise ValueError("Role must be builder, reviewer or repair")
        if not project.is_dir() or not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Existing project directory and nonempty prompt are required")
        timeout = config.get("timeout", DEFAULT_TIMEOUTS[role])
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout must be a finite positive number of seconds")
        receipt["timeout_seconds"] = timeout
        grace = config.get("result_grace", 30)
        if isinstance(grace, bool) or not isinstance(grace, (int, float)) or not math.isfinite(grace) or grace < 0:
            raise ValueError("result_grace must be a finite non-negative number of seconds")
        (attempt / "prompt.md").write_text(prompt, encoding="utf-8")
        schema_file = attempt / "response-schema.json"
        if response_schema is not None:
            if not isinstance(response_schema, dict):
                raise ValueError("Response schema must be an object")
            _write_json(schema_file, response_schema)
            receipt["artifacts"]["schema"] = str(schema_file)
        paths = {"project": str(project), "prompt_file": str(attempt / "prompt.md"),
                 "schema_file": str(schema_file) if response_schema is not None and profile["response_mode"] == "native-schema" else "",
                 "scratch": (environment or {}).get("MATLAB_HARNESS_SCRATCH", "")}
        arguments = _arguments(config, prompt, paths, response_schema if profile["response_mode"] == "native-schema" else None)
        if os.name == "nt" and Path(arguments[0]).suffix.lower() in {".bat", ".cmd"}:
            raise ValueError("Windows batch launchers are unsupported; configure the executable directly")
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
                if _wait_for_result(process, attempt / "stdout.txt", timeout, grace, structured, profile["max_response_bytes"]):
                    # The root result is final; a CLI that lingers after it only burns the budget.
                    receipt["stopped_after_result"] = True
                    receipt["cleanup"] = _stop_owned_process(process)
                    receipt["status"] = "SUCCEEDED"
                else:
                    receipt["status"] = "SUCCEEDED" if process.returncode == 0 else "FAILED"
            except subprocess.TimeoutExpired:
                receipt["status"] = "TIMED_OUT"
                receipt["cleanup"] = _stop_owned_process(process)
            except KeyboardInterrupt:
                receipt["status"] = "INTERRUPTED"
                receipt["cleanup"] = _stop_owned_process(process)
            except ValueError as exc:
                receipt["status"] = "MALFORMED"
                receipt["parse_error"] = str(exc)
                receipt["cleanup"] = _stop_owned_process(process)
            receipt["cleanup"].update(_release(process, job))
        receipt["exit_code"] = process.poll()
        try:
            if sum((attempt/name).stat().st_size for name in ("stdout.txt","stderr.txt")) > profile["max_response_bytes"]:
                raise ValueError("Response byte limit exceeded; complete source retained on disk")
            output = (attempt / "stdout.txt").read_text(encoding="utf-8", errors="strict")
            parsed = _parse_output(output, structured)
            valid = parsed.pop("valid")
            receipt.update(parsed)
            if receipt["status"] == "SUCCEEDED" and not valid:
                receipt["status"] = "FAILED" if parsed["provider_status"] not in {None, "SUCCESS"} else "MALFORMED"
        except (ValueError, TypeError, AttributeError) as exc:
            receipt["parse_error"] = str(exc)
            if structured:
                from .decoding import file_source
                receipt["ingestion"] = {"version": 1, "problems": ["Transport envelope could not be examined: " + str(exc)],
                                        "sources": [file_source(attempt / "stdout.txt", "transport-error")],
                                        "assurance": "raw-invalid-v1"}
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
        receipt["failure"] = classify_failure(receipt)
        _write_json(receipt_path, receipt)
    return receipt
