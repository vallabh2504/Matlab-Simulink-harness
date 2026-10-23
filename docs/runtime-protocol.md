# Executing native roles

See [evidence assurance](evidence-assurance.md) for executed probe receipts,
required semantic plans, explicit context capabilities, loss-aware raw review
ingestion and legacy migration. `native-schema` and `json` response modes enforce
the same domain checks. Transport failures never trigger model fallback.
With the `agy` adapter, the plain-text `toolAction` and `toolSummary` notes it adds
to a result do not count as a conflict between the raw and structured review. Both
sources are kept. Any other difference still needs reconciliation, and other hosts
are compared strictly.

## Operator entry points

Use `matlab-harness start <new-or-existing-directory> --title <title> --builder <actual-id>
--owner <orchestrator-id> --scope <owned-paths>` to initialize durable records without
overwriting existing requirements or agent instructions. `matlab-harness --project <root> next`
shows the current stage, actual findings, fresh/stale checks and active leases.
`packet --role reviewer` produces a saved native-agent handoff. The default adapter
is manual; no provider credentials or automatic authorization are assumed.

Configure an executable adapter from a project-relative JSON file using
`configure-runtime --owner <id> --config runtime.json`. For example:

```json
{"adapter":"agy","model":"available-builder-model",
 "roles":{"reviewer":{"model":"available-independent-review-model"}}}
```

`execute --owner <id> --role builder|reviewer|repair` runs the current checkpoint.
Per-role overrides choose model/adapter; the project's declared budget applies.
Reviewer output is imported only with actual observed root session/model identity,
current artifact digest and a valid review record. Every contributing builder or
leased worker identity is excluded from independent acceptance. No checkpoint is
automatically accepted: inspect `next` and use `accept <checkpoint>` after the gate.

The project mutation lock stays held during execution. Agents may inspect records
and edit their engineering scope, but must leave project-record mutation to the
orchestrator. External agent runtimes remain responsible for enforcing their tool
permissions and file ownership; this is not an operating-system sandbox.

Change execution ceilings with `configure-runtime --builder-seconds 3600
--reviewer-seconds 1800 --repair-seconds 3600 --native-seconds 1800 --repair-budget 10
--owner <id>`. Greater limits are supported. Required correctness, actual checks,
independence and file preservation remain acceptance obligations.

`matlab_harness.runtime.execute_role(project_root, role, prompt, config, evidence_dir,
response_schema=None)` launches one actual runtime process with `shell=False`.
Roles are `builder`, `reviewer` and `repair`. Default budgets are respectively
3600, 1800 and 3600 seconds; a positive finite `timeout` in the per-role configuration
overrides them. Long engineering tasks can use larger budgets. Tool access is the
native runtime's configuration; this transport imposes no short tool-call quota,
web prohibition or inventory restriction.

The return value is an execution receipt, not an engineering acceptance record.
`SUCCEEDED` means the process exited zero and emitted a completed successful
protocol response. A reviewer can successfully report `REJECT`. The project core
still checks actual independence, artifact freshness, findings and mandatory
engineering evidence. Unknown model/session identity remains `null`; the runner
does not replace it with a requested alias or generated identifier.

## AGY adapter

Example per-role configuration:

```json
{"adapter":"agy","model":"an-actually-available-model","timeout":1800}
```

The adapter uses the CLI flags `--new-project`, `--model`,
`--disable-slash-commands`, `--output-format stream-json`, `--print-timeout 0`
and `--print <prompt>`. Optional `effort` accepts the CLI's declared values.
`new_project:false` omits that flag. `skip_permissions:true` explicitly adds
`--dangerously-skip-permissions`; the default leaves the host's permission policy
in control. An unattended permission request may stall until timeout. No global
hooks or permissions are modified. Optional `executable` selects the AGY binary.

The first `init` event identifies the actual root conversation and model.
Additional observed conversation IDs are recorded separately as children.
Only a root `result` with `status:SUCCESS` completes a run; child completion
cannot substitute for it. If a completed root result omits its ID, the observed
initial root ID is retained. `structured_output` is preferred; otherwise a whole
JSON-string `response` is decoded when a schema was requested. No Markdown
scraping, finding rewriting or invented acceptance fallback is performed.

AGY structured output is requested using `--json-schema <saved-file>`.
This transport does not implement a general JSON Schema validator. The calling
workflow must validate its domain record before importing it.

Prompts are passed as a command-line argument. Very large prompts can exceed the
host's command-length limit and produce `LAUNCH_FAILED`. Keep prompts focused, reference local
role packets, or use a command adapter that reads `prompt_file`.

## Generic command adapter

Use an explicit argv list, for example a provider-specific wrapper maintained by
the operator:

```json
{"adapter":"command","model":"requested-model","timeout":1800,
 "argv":["python","provider_wrapper.py","--prompt-file","{prompt_file}",
         "--workspace","{project}","--model","{model}","--schema","{schema_file}"]}
```

Placeholders are only `prompt_file`, `project`, `model`, `schema_file` and
`scratch`. They are substituted in individual arguments without a shell. Literal
braces must be doubled; a separate script is preferable to embedded code.
`schema_file` is empty when no schema was supplied. `scratch` is the role's
own scratch directory under `.matlab-harness/scratch/`; reviewers write their
probes there. The
same path is passed to the child as the `MATLAB_HARNESS_SCRATCH` environment
variable, on top of the inherited environment. The working directory is
`project_root`. On Windows the child is assigned to a Job Object right after
launch, and the job is closed when the role ends.
The wrapper must write one JSON object to stdout:

```json
{"status":"SUCCESS","session_id":"actual-provider-root-id",
 "model":"actual-provider-model-id","response":{"verdict":"REJECT"},
 "usage":{"input_tokens":123,"output_tokens":45}}
```

Model/session/usage may be omitted when genuinely unavailable, and remain unknown
in the receipt. `response` can be text when no structured response is requested.
AGY-style NDJSON is also understood. Process failure, provider failure, missing
result and malformed structured response remain failed attempts.

## Evidence and cancellation

Every attempt gets a unique directory containing `receipt.json`, `prompt.md`,
`stdout.txt`, `stderr.txt` and the supplied schema. The initial receipt is saved
before process launch, then updated with the owned PID and terminal result.
Raw files are retained on launch errors, partial output, timeout and malformed
results. Exact argv, requested/observed models, root/child sessions, exit code,
timing and observable provider usage are preserved. These files are local project
evidence and can contain private prompts or provider output; they are not sent
as harness telemetry or automatically bundled into releases.

Some CLIs write their final root result and then do not exit. Once stdout holds a
valid root result, the runner waits `result_grace` seconds (per-role, default 30)
for the process to exit, then stops it the same way as a timeout. The attempt is
`SUCCEEDED` and its receipt has `stopped_after_result: true`; the exit code is the
one the stop produced.

On timeout/interruption, Windows uses `taskkill /PID <owned-pid> /T /F`; POSIX
uses a new process group and kills that group. Cleanup is bounded and records
whether the root stopped. This is not proof that detached children or a provider's
remote/background service stopped. External cancellation remains `UNKNOWN`;
descendant shutdown is not claimed as verified. Do not recover shared MATLAB
resources on the strength of a timeout receipt alone.

The runner does not sandbox the runtime, validate its engineering assertions,
authorize requirements, enforce its file leases, or serialize shared MATLAB.
Those remain the accountable orchestrator's duties.

Workflow reviewer schemas bind the checkpoint and snapshot digest to their exact
packet using single-value enums. The reviewer still supplies its verdict and
findings. This prevents structured transports from mistyping the packet identity;
it does not prove that an inspection happened. Review import independently checks
reviewer identity, unchanged artifacts and the current project snapshot. A runtime
that ignores the supplied schema cannot bypass those checks.

## Recovering a rejected review report

The importer retains exact finding identities. When a repair changes where the
supporting evidence lives, the reviewer keeps the original ID and artifact string
and cites the additional files in evidence/closure. It supplies its own verdict;
the harness never rewrites a report into acceptance.

A malformed finding or closure record raises `ReviewProtocolError`. The workflow
retains the raw report and returns retryable `REVIEW_NOT_IMPORTED`. The journey
allows up to three rejected protocol attempts for an unchanged checkpoint and
snapshot, including correction attempts. Counts survive resuming the project.
These are reviewer-only corrections within the original time ceiling; they do not
consume the engineering repair budget. Valid REJECT/INCOMPLETE verdicts follow
the normal engineering repair path. A REJECT without a blocking reason (see the
`verdict` rule in hosts.md) is a protocol refusal, not a valid verdict, so it costs a
correction attempt and never a repair. Identity, stale-snapshot, artifact-mutation
and transport failures do not receive this automatic protocol retry.

Serious findings (CRITICAL, MAJOR) of an answer that was not imported remain
separately labeled `UNIMPORTED_ALLEGATION`, with the immutable source report and its
digest, whatever kept the answer out: a protocol refusal, a run that did not finish,
or a reviewer that changed scoped files. They are not established engineering truth.
The next reviewer packet lists each claim as one open item with a handle (`A-` and
the first eight hex digits of the claim's digest) and the probes of every attempt
that made it. The reviewer answers it in `open_items`:

- `CLOSED`: observed closure or counterevidence on the current bytes. At an executed
  checkpoint the evidence names the scratch file a check with result `PASS` ran, or
  that check's ID. `CLOSED` counts only written alone as the status.
- `STILL_OPEN`: the harness records the claim as the reviewer's own open finding,
  which blocks acceptance like any other. Reporting the identical claim as a new
  finding means the same.

Earlier open findings are answered the same way, by their own ID. The harness
translates the answer into the strict review record (closure digests, origin
artifacts, allegation dispositions); the reviewer never copies a digest. A new
finding that reuses an earlier ID is renamed, so it cannot close the earlier one.
ACCEPT is refused until every blocking item is `CLOSED`.

A reviewer run never changes the scoped files or `requirements.md`. The harness keeps
a copy of them before the run; if the reviewer changed or added any, it moves the reviewer's versions to
`execution/reviewer-changes`, restores the reviewed bytes, records a decision and
does not import the answer.

Review-import intent is committed with the completed runtime response, before
writing a report file. A crash at either point leaves the response and a pending
import visible. Pending imports block another role dispatch and acceptance.
Inspect the actual identity, response and current snapshot, then import the valid
report or explicitly record its protocol rejection through the project API.
Do not clear the pending field or infer acceptance from a zero process exit.

## Document checkpoints and focused context

Requirements and architecture reviews judge their current contract/design
obligations. Future simulation results are not required merely to accept a
document checkpoint. A reviewer must identify consequential ambiguity from the
actual contract; it must not invent a metadata schema where equivalent forms
were explicitly allowed. Repairs describe future executable checks in the design
and leave their implementation to the implementation stage.

An approved contract binds only through its text, so a question about what it means is
answered by the design. A finding on `requirements.md` filed at requirements is carried
to architecture and does not block requirements; the architecture review closes it when
the design's reading contradicts no contract sentence. A serious finding on the contract
after requirements needs `contract_text` and `design_text`, exact quotes of the two
sentences that conflict (compared without case, spacing, markdown marks, list markers,
curly quotes or closing punctuation; a `design_text` found in `requirements.md` is not the
design's own reading), or the answer is refused as protocol. Such a conflict is a design
defect and is repaired; it pauses for the user only when the design itself writes
`USER QUESTION <id>:`. A finding on a `.matlab-harness/` record is not a contract question
and still pauses where it is raised.

Both direct `execute` and the journey detect early changes to scoped
non-document artifacts, including unfamiliar scripts, binaries and parameter
files. Markdown, reStructuredText, AsciiDoc, LaTeX and common document/figure
formats are allowed. This is a workflow boundary, not an OS sandbox. Violating
work is retained. Its original baseline and evidence digest remain durable, and
another unchanged dispatch or reviewer ACCEPT cannot adopt it. Exact restoration
is required before checkpoint acceptance records the restoration; subsequent
authorized implementation changes do not reopen that restored violation.

Each role packet contains a hashed `context.json` with current requirements,
authorization, assumptions, scope and evidence/review references. Prior repair
transcripts are indexed instead of copied repeatedly. The complete project
record and archived reports remain available for specific history questions.
Changing a generated context packet during execution is an integrity failure.
This keeps role prompts small and avoids duplicated context.
