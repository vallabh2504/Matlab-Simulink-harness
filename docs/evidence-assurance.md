# Evidence assurance

The harness checks evidence and workflow state. The operator
approves the requirements, executable check plans and independent probe runners.
Keep those approvals with the project.

## Review ingestion

Raw reviews enter through a bounded decoder. Duplicate keys, conflicting raw and
structured answers, malformed JSON, invalid Unicode and incomplete responses cannot
silently become a clean acceptance. Recoverable serious findings remain open.
Unread sources are retained with hashes and a blocking gap, including after restart.

A clean answer or a new packet cannot erase a gap. Inspect the retained source,
create a reviewer packet that pins it, and use the trusted operator command:

```text
matlab-harness --project <root> authorize-correction --owner <owner> --gap <gap-id> --source-sha256 <hash> --packet <packet-id> --reason <inspection-reason>
```

The replacement must include `reconciliation: [{gap_id, source_sha256,
complete: true}]` and disposition every pinned open handle. Authorization alone
does not resolve the gap. The accepted replacement and its hash are retained.
For CLI submission, use `answer` with a raw JSON file; MCP callers can supply
`report_text`. A decoded object supplied directly by a host is labelled as such.

## Independent probe receipts

New projects use `executed` proof assurance. From implementation onward, an
independent PASS or closure needs a host execution receipt. A PASS label and an
existing scratch script are insufficient. Approve local executables explicitly:

```json
[{"kind": "python", "executable": "python"},
 {"kind": "matlab", "executable": "matlab"}]
```

```text
matlab-harness --project <root> configure-probes --owner <owner> --plan runners.json --reason <approval-reference>
```

Each reviewer check can propose `run: {script, runner, arguments, inputs}`. The
script must be inside that packet's scratch directory; `runner` is its approved
list index. The orchestrator executes it after the reviewer process exits and
releases the project lock, then adds `receipt_id`. Shell/MCP hosts can instead use
`run-probe` or `harness_run_probe` and submit the returned receipt ID.

Receipts bind checkpoint, packet, reviewer, current scoped/support snapshot, script,
declared input hashes, executable, actual arguments, exit status and output hashes.
The gate revalidates them. An altered script/output, another packet/session,
failed execution or stale input cannot close a finding. Every reported failing
check of a shared file still vetoes that file as closure proof.

Legacy records without a proof policy remain `legacy-attested`; they are not
silently upgraded or advertised as execution-verified. `configure-probes` opts a
project into executed assurance and changes its snapshot. Accepted engineering
checkpoints require explicit revision before that policy changes. Re-run checks
and obtain current reviews after an upgrade. Operator-approved runners execute
with the operator's privileges; these receipts are provenance, not a sandbox.

## Required semantic adequacy

For a new executed-assurance project, verification and handoff require an approved
semantic plan. Declare the properties promised by the contract, the existing
check suite, an operator-approved good reference and named defective variants:

```json
{"stages": ["verification", "handoff"], "obligations": [
  {"id": "CLAMP", "requirement": "R-1", "check": "suite",
   "target": "src/model.py", "reference": "reference/good.py",
   "failure_kind": "python-assertion", "mutants": [
     {"id": "missing-clamp", "find": "max(0, x)", "replace": "x",
      "failure_marker": "CLAMP_NEGATIVE"}]}]}
```

Approve it with `configure-semantics --owner <owner> --plan <file> --reason <source>`.
`run-semantics` runs the delivered suite in separate project copies; the journey
runner also executes approved obligations. The good reference must pass, and each
named defect must produce the intended assertion. A finite-output smoke test that
misses a required numerical clamp therefore fails adequacy. Syntax errors, missing
dependencies, timeouts and unrelated crashes give no detection credit. A trusted
child wrapper records the actual exception separately from diagnostic text.

`python-assertion` supports Python script commands with optional `-B`, `-u`, `-I`
flags and an uncaught `AssertionError` whose message equals the declared marker.
`matlab-assertion` supports `matlab -batch <expression>` and requires an explicit
`assertion_id` in the obligation. The approved suite uses, for example,
`assert(condition, 'engineering:SemanticAssertion', 'CLAMP_NEGATIVE')` with that
identifier and marker. MATLAB exposes assertion identifiers through its
[documented assert interface](https://www.mathworks.com/help/matlab/ref/assert.html);
an empty identifier or an unrelated exception cannot receive detection credit.
General test-framework failures must be
adapted into a property-specific assertion; an aggregate failed-test count alone
does not establish the intended property.

The plan's reference and commands are snapshot-bound. Generic sampled mutation
checks remain advisory and do not replace these required obligations. A project
without executable behavioral obligations can declare an empty plan only with an
explicit `not_applicable` rationale approved by the operator. Plan completeness
and the correctness of the reference remain engineering review responsibilities.

## Context capabilities

The same checks apply whichever model does the work, hosted or local.
Use manual/MCP packets or an executable `command` adapter for a local runtime.

```json
{"adapter": "manual", "capabilities": {
  "context_window": 8192, "reserved_output": 1024,
  "host_overhead": 1024, "tool_tokens": 1500,
  "response_mode": "json", "max_response_bytes": 1048576}}
```

Capabilities can be overridden per role. `response_mode` is explicitly `json`
or `native-schema`; both use the same review validation. Unsupported modes are
refused. Packet preflight counts the complete prompt, required reads, schema,
declared host/tool overhead and output reserve. If the task file is too large, it
drops skill cards from the end first, then shortens finding views and the task
text, keeping the head of the task with its reason and brief. If the required
content still cannot fit, dispatch is refused before launching a process.
The packet records each estimate and the declared capacity.

Estimates count four characters as one token. The default host overhead is 256
tokens and the default extra tool overhead is zero. Set both to match your host's
tools and schemas, and keep a reserve for the answer.

## Time, failure and recovery

Native commands retain complete raw output on disk with bounded in-memory reads.
Configured response byte limits and time ceilings stop oversized or incomplete
responses. Runtime receipts classify configuration, authentication, unavailable
model, timeout, unread-source and transient transport failures. There is one
automatic transport attempt and no model fallback. Ordinary protocol correction
is bounded separately; unread-source gaps require inspected correction rather
than automatic repeated reviews. The original journey ceiling persists on resume.

An interrupted execution intent blocks acceptance. Inspect its process record,
stop the owned process, then use `recover-execution --kind probe|semantic --id <id>
--owner <owner> --stopped-process-attestation <reference> --reason <inspection>`.
Recovery preserves the original record and records INTERRUPTED; it never creates
a passed result. An operator attestation is recorded as an attestation.

