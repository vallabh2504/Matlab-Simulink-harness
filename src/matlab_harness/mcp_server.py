"""MCP server over stdio, standard library only, so any agent host can drive one project.

    matlab-harness --project <root> mcp --owner <orchestrator>

Hosts such as OpenCode, Codex or Claude Code start this as a stdio MCP server and their
model calls the tools. The host runs the model; the harness keeps the records, runs the
checks and gates acceptance. A reviewer answers its packet; the harness turns the answer
into the strict review record. Reviewer identity arrives from the host and is recorded as
host-reported: the harness cannot verify which model or session wrote a review.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import uuid

from .compact import matlab_digest
from .mutation import run_mutation, mutation_summary
from .project import DEFAULT_BUDGETS, Project, ProjectError, loads
from .workflow import next_step, packet, submit_answer
from .decoding import ReviewInput, decode_document, combine_answers, MAX_BYTES, file_source
from . import __version__

PROTOCOL = "2025-06-18"
ROLES = ["builder", "reviewer", "repair"]


def _schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required)}


TOOLS = [
    {"name":"harness_run_semantics",
     "description":"Run operator-approved required semantic obligations: good-reference calibration and intended-defect assertion failures.",
     "inputSchema":_schema({})},
    {"name": "harness_run_probe",
     "description": "Host-execute a current reviewer packet scratch script with an operator-approved runner. Returns a bound receipt, not an engineering correctness guarantee.",
     "inputSchema": _schema({"packet_id":{"type":"string"},"check_id":{"type":"string"},
                             "script":{"type":"string"},"reviewer_session":{"type":"string"},
                             "runner":{"type":"integer"},"arguments":{"type":"array"},"inputs":{"type":"array"}},
                            ["packet_id","check_id","script","reviewer_session"])},
    {"name": "harness_status",
     "description": "Current checkpoint, gate problems, check status and the next action. Call this first.",
     "inputSchema": _schema({})},
    {"name": "harness_packet",
     "description": "The task prompt for one role at the current checkpoint. Give it to the agent playing that role "
                    "(a reviewer must be a separate session from the builder). A reviewer packet also returns its "
                    "packet_id and the answer schema.",
     "inputSchema": _schema({"role": {"type": "string", "enum": ROLES}, "task": {"type": "string"}}, ["role"])},
    {"name": "harness_run_check",
     "description": "Run one declared check command and return its status with the key MATLAB error lines.",
     "inputSchema": _schema({"name": {"type": "string"}}, ["name"])},
    {"name": "harness_mutation",
     "description": "Plant small defects in copies of the source and run the configured test check on each. "
                    "Survivors show lines the tests do not pin down.",
     "inputSchema": _schema({})},
    {"name": "harness_submit_review",
     "description": "Submit the reviewer's answer to its packet: verdict, findings, traceability, independent_checks "
                    "and open_items, as the packet prompt describes. Returns the gate, or the protocol problem to fix.",
     "inputSchema": _schema({"report": {"type": "object"}, "report_text": {"type": "string"}, "reviewer_session": {"type": "string"},
                             "model": {"type": "string"}, "packet_id": {"type": "string"}},
                            ["reviewer_session", "model"])},
    {"name": "harness_record_repair",
     "description": "Record that a repair round starts for the current findings (uses one unit of the repair budget).",
     "inputSchema": _schema({"reason": {"type": "string"}}, ["reason"])},
    {"name": "harness_accept",
     "description": "Accept the current checkpoint. Refused unless checks passed, the reviewer accepted and no serious "
                    "finding is open.",
     "inputSchema": _schema({})},
]


def _check_arguments(name, arguments):
    """Refuse wrong argument types by the tool schema, so a model gets a fixable answer."""
    tool = next((t for t in TOOLS if t["name"] == name), None)
    if tool is None:
        raise ProjectError(f"Unknown tool {name}")
    if not isinstance(arguments, dict):
        raise ProjectError("arguments must be a JSON object")
    schema = tool["inputSchema"]
    if name == "harness_submit_review" and not ({"report", "report_text"} & arguments.keys()):
        raise ProjectError("Provide report_text (raw JSON) or a decoded host-attested report")
    missing = [key for key in schema["required"] if key not in arguments]
    if missing:
        raise ProjectError("missing argument(s): " + ", ".join(missing))
    for key, spec in schema["properties"].items():
        if key not in arguments:
            continue
        value = arguments[key]
        if (isinstance(value,bool) and spec["type"]=="integer") or not isinstance(value, {"string": str, "object": dict, "integer":int, "array":list}[spec["type"]]) or value not in spec.get("enum", [value]):
            raise ProjectError(f"argument {key} must be " + (" or ".join(spec["enum"]) if "enum" in spec
                                                              else "a " + spec["type"]))


class Server:
    def __init__(self, root, owner):
        self.project = Project(Path(root))
        self.owner = owner

    def call(self, name, arguments):
        _check_arguments(name, arguments)
        project, owner = self.project, self.owner
        stage = project.load()["phase"]
        if name == "harness_status":
            state = next_step(project)
            return {"phase": state["phase"], "completed": state["completed"], "next_action": state["next_action"],
                    "gate_problems": state["gate"]["problems"], "checks": [
                        {"name": c["name"], "status": c["status"]} for c in state["checks"]],
                    "repairs_remaining": state["repairs_remaining"]}
        if name == "harness_packet":
            record = packet(project, arguments["role"], stage, arguments.get("task", ""))
            reply = {"prompt": Path(record["prompt"]).read_text(encoding="utf-8"), "scratch": record["scratch"],
                     "estimated_tokens": record["estimated_tokens"]}
            if "answer_schema" in record:
                reply.update(packet_id=Path(record["prompt"]).parent.name,
                             answer_schema=json.loads(Path(record["answer_schema"]).read_text(encoding="utf-8")))
            return reply
        if name == "harness_run_check":
            evidence = project.run_check(owner, arguments["name"])
            return {"name": evidence["name"], "status": evidence["status"], "exit_code": evidence["exit_code"],
                    "output": matlab_digest(evidence["stdout"], evidence["stderr"])}
        if name == "harness_run_probe":
            from .probes import run
            return run(project,owner,arguments["packet_id"],arguments["check_id"],arguments["script"],
                       arguments["reviewer_session"],arguments.get("runner",0),arguments.get("arguments",[]),arguments.get("inputs",[]))
        if name == "harness_run_semantics":
            from .semantics import run
            return run(project,owner)
        if name == "harness_mutation":
            limit = project.load().get("budgets", DEFAULT_BUDGETS).get("native", DEFAULT_BUDGETS["native"])
            result = run_mutation(project, owner, stage, limit)
            return mutation_summary(project.load()["mutation_results"][stage]) | {"status_code": result["status"]}
        if name == "harness_submit_review":
            reviewed = getattr(self, "_raw_ingress", None)
            if reviewed is None:
                reviewed = combine_answers(arguments.get("report"), arguments.get("report_text"))
            return submit_answer(project, owner, reviewed, arguments["reviewer_session"],
                                 arguments["model"], arguments.get("packet_id"))
        if name == "harness_record_repair":
            project.repair(owner, arguments["reason"])
            data = project.load()
            return {"repairs_remaining": data["repair_budget"] - data["repairs"]}
        if name == "harness_accept":
            return project.accept(owner, stage)
        raise ProjectError("Unknown tool " + name)

    def handle(self, message):
        method, ident = message.get("method"), message.get("id")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "initialize":
            return {"protocolVersion": params.get("protocolVersion", PROTOCOL),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "matlab-harness", "version": __version__}}
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            try:
                result = self.call(params.get("name"), params.get("arguments") or {})
                return {"content": [{"type": "text", "text": json.dumps(result, indent=1, default=str)}]}
            except (ProjectError, KeyError, OSError) as exc:
                # A refused action is a normal answer the model should read and act on.
                return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "isError": True}
            except Exception as exc:  # one bad call must not end the server for the whole session
                return {"content": [{"type": "text", "text": f"Failed: {type(exc).__name__}: {exc}"}], "isError": True}
        if method == "ping":
            return {}
        if ident is None:
            return None
        raise LookupError(method)


def _variants(value):
    if isinstance(value, dict) and set(value) == {"answer_sources"}:
        return value["answer_sources"]
    return [value]


def _requests(stdin,project):
    stream=getattr(stdin,'buffer',stdin)
    while True:
        line=stream.readline(MAX_BYTES+1)
        if not line:return
        encoded=line if isinstance(line,bytes) else line.encode('utf-8',errors='surrogatepass')
        if not encoded.strip():continue
        if len(encoded)<=MAX_BYTES:
            yield line,decode_document(encoded,"mcp-request")
            continue
        directory=project.control/'ingestion';directory.mkdir(exist_ok=True)
        path=directory/('incoming-'+uuid.uuid4().hex+'.bin')
        with path.open('xb') as handle:
            handle.write(encoded)
            while not line.endswith(b'\n' if isinstance(line,bytes) else '\n'):
                line=stream.readline(MAX_BYTES+1)
                if not line:break
                handle.write(line if isinstance(line,bytes) else line.encode('utf-8',errors='surrogatepass'))
        yield '',ReviewInput(problems=['MCP request byte limit exceeded; opaque source needs inspection'],sources=[file_source(path,'mcp-request')])


def serve(root, owner, stdin=sys.stdin, stdout=sys.stdout):
    server = Server(root, owner)
    for line,reviewed in _requests(stdin,server.project):
        if not line.strip() and not reviewed.problems:
            continue
        message = reviewed.answer
        if message is None and reviewed.problems:
            from .ingestion import record_gap
            from .project import value_digest
            data=server.project.load()
            record_gap(server.project,owner,{'checkpoint':data['phase'],'snapshot_digest':value_digest(server.project.snapshot(data))},reviewed)
        server._raw_ingress = None
        error = bool(reviewed.problems)
        # A clear submit envelope can carry an ambiguous review. Do not guess
        # which tool/session an ambiguous envelope meant or poison other calls.
        if isinstance(message, dict) and message.get("method") == "tools/call":
            params = message.get("params", {})
            if isinstance(params, dict) and params.get("name") == "harness_submit_review":
                variants = _variants(params.get("arguments", {}))
                allowed = all(isinstance(v, dict) for v in variants)
                if allowed and variants:
                    first = variants[0]
                    identities = [(v.get("reviewer_session"), v.get("model"), v.get("packet_id")) for v in variants]
                    allowed = bool(identities) and all(
                        all(isinstance(x, str) or x is None for x in identity)
                        and identity == identities[0] for identity in identities)
                    # Only duplicate review fields are routed into a blocking
                    # review intake; envelope ambiguity remains a parse error.
                    if reviewed.problems:
                        allowed = allowed and all(
                            p.startswith("Duplicate JSON member at $.params.arguments.report")
                            or p.startswith("Nonfinite JSON") or p.startswith("Invalid Unicode surrogate at $.params.arguments.report")
                            for p in reviewed.problems)
                    if allowed:
                        values, problems, sources = [], list(reviewed.problems), list(reviewed.sources)
                        for args in variants:
                            part = combine_answers(args.get("report"), args.get("report_text"))
                            values.append(part.answer)
                            problems.extend(part.problems)
                            sources.extend(part.sources)
                        server._raw_ingress = ReviewInput(values[0] if len(values) == 1 else values, problems, sources)
                        params["arguments"] = first
                        error = False
                if error and reviewed.problems:
                    # A definitely named review submission with ambiguous
                    # identity is an unread review, not an unrelated tool call.
                    from .ingestion import record_gap
                    from .project import value_digest
                    data = server.project.load()
                    record_gap(server.project, owner,
                               {"checkpoint": data["phase"], "snapshot_digest": value_digest(server.project.snapshot(data))},
                               reviewed)
        if error or message is None:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid or ambiguous JSON request"}}
        elif not isinstance(message, dict):
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        else:
            ident = message.get("id")
            try:
                result = server.handle(message)
            except LookupError as exc:
                reply = {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"Unknown method {exc}"}}
            else:
                if ident is None:
                    continue
                reply = {"jsonrpc": "2.0", "id": ident, "result": result}
        stdout.write(json.dumps(reply, ensure_ascii=True) + "\n")
        stdout.flush()
