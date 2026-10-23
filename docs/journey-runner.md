# Running an engineering project through its checkpoints

The command works in both source and wheel installations:

```powershell
matlab-harness --project C:\engineering\my-project journey --owner my-orchestrator --ceiling 14400
```

The source wrapper `python scripts/run_engineering_journey.py` invokes the same
`matlab_harness.journey` module. `--project` points to an already
initialized engineering project. A successful handoff returns `COMPLETED` and
exit 0. Pauses and failures return a precise status and exit 3, with project-local
evidence. This is an operational driver, not an engineering oracle.

## Prepare the project

Start a project without replacing existing files:

```powershell
matlab-harness start C:\engineering\my-project --title "Thermal model" --builder actual-session-id --owner my-orchestrator --scope engineering --brief "Implement the agreed thermal dynamics and preserve the legacy interface."
```

Keep engineering artifacts under explicit scope, such as `engineering` containing
design, source, parameters and deliverables. Keep independent grader definitions
outside builder-owned scope. Checks should produce diagnostics outside the scoped
source snapshot; changing a scoped file during verification invalidates that run.

Save a project-relative `runtime.json`. For an actually available AGY model:

```json
{"adapter":"agy","skip_permissions":true,
 "roles":{"builder":{"model":"available-builder-model"},
          "reviewer":{"model":"available-reviewer-model"},
          "repair":{"model":"available-builder-model"}}}
```

The model names are placeholders, not advertised access. `skip_permissions:true`
is an explicit operator choice for unattended native tools; omit it to preserve
the host permission policy; an unattended permission prompt otherwise waits until
the role times out. Generic command wrappers and manual packets follow
the [runtime protocol](runtime-protocol.md).

```powershell
matlab-harness --project C:\engineering\my-project configure-runtime --owner my-orchestrator --config runtime.json --builder-seconds 3600 --reviewer-seconds 1800 --repair-seconds 3600 --native-seconds 1800 --repair-budget 10
```

Draft `requirements.md` with the actual user and register agreed stable IDs using
`matlab-harness requirement`. If no current approval exists, the driver may run one discovery
role to draft the document, then returns `WAITING_FOR_USER_APPROVAL`. It does not
register speculative IDs, approve its own output or construct engineering code
during discovery. Record approval only after receiving real authorization:

```powershell
matlab-harness --project C:\engineering\my-project requirement --owner my-orchestrator --id TH-1 --text "The agreed physical requirement" --acceptance "The agreed independently executable oracle" --source "Actual user specification reference" --units K
matlab-harness --project C:\engineering\my-project approve --owner my-orchestrator --actor actual-user --source "Actual authorization reference"
```

Save checkpoint-specific JSON check plans mapping names to exact argv lists. An
illustrative native invocation is:

```json
{"thermal-oracle":["C:\\Program Files\\MATLAB\\R2026a\\bin\\matlab.exe",
 "-batch","run('verification/verifyThermal.m')"]}
```

Use the actual discovered executable, release and task-independent engineering
oracle, not this illustrative path. The driver does not substitute easy checks
when the plan is absent. Declare nonempty plans for implementation, verification
and handoff; requirements/architecture plans may be empty when appropriate.

```powershell
matlab-harness --project C:\engineering\my-project configure-checks implementation --owner my-orchestrator --plan implementation-checks.json
matlab-harness --project C:\engineering\my-project configure-checks verification --owner my-orchestrator --plan verification-checks.json
matlab-harness --project C:\engineering\my-project configure-checks handoff --owner my-orchestrator --plan handoff-checks.json
```

Plans can be refined before accepting their corresponding checkpoint. Previously
accepted obligations remain frozen. The driver deliberately pauses on missing
plans so the accountable orchestrator can register real engineering checks.

## Execution, repair and continuation

The driver inspects durable state before proceeding. Approved requirements receive
independent review. Architecture and implementation receive configured builders
when no current completed builder/repair receipt exists. Verification and handoff
run checks and independent review without gratuitously rebuilding source.
Construction receives a task lease for explicit scoped artifacts and registered
requirements; shared checks execute serially through the project core.

For debugging an existing implementation, add `--review-existing-implementation`:

```powershell
python scripts/run_engineering_journey.py --project C:\engineering\existing-project --owner my-orchestrator --ceiling 14400 --review-existing-implementation
```

Architecture still receives a builder to inspect and document the existing design,
with instructions to preserve existing implementation artifacts. At implementation,
the initial automatic builder is skipped: the saved source/model goes directly to
declared native checks and independent review. Any demonstrated defect then receives
targeted repair, native retesting and explicit independent closure. This preserves
the opportunity to observe an existing fault before a builder could rewrite it.
Existing scoped MATLAB/model/data files (`.m`, `.mlx`, `.slx`, `.mdl`, `.sldd`,
`.mat`, `.csv`, `.json`, `.xml`) are hash-checked across architecture execution;
a changed or deleted file pauses with `INPUT_REQUIRED` before implementation
verification. This detects an accidental overwrite but does not restore files or
provide an OS sandbox. Original hashes are frozen in the declaration, so resuming
cannot silently bless an architecture overwrite. The mode is frozen in the
journey declaration and must be repeated on
resume. Omitting or adding it to an existing declaration is refused.

Every applicable checkpoint runs its declared native checks, obtains a real
configured reviewer result and accepts only when `Project.gate` passes. Failed
checks and current findings form targeted repair input. Each repair consumes the
configured project limit, default ten; native checks and independent closure run
again. Earlier failures and findings remain recorded. Missing providers, manual
adapters, malformed reviews, unavailable checks and nonactionable review requests
produce `INPUT_REQUIRED` or the actual execution failure rather than fabricated
acceptance. A timeout does not establish that detached MATLAB processes stopped.
Blocking findings against approval documents or `.matlab-harness` records pause for the
accountable orchestrator instead of granting a construction worker control-record
repair. That orchestrator can supply authorization counterevidence, refine an
unaccepted check plan or request genuinely missing user input. File/line spellings
and project-local absolute paths identify the same reserved record.

A question about the approved `requirements.md` raised at requirements does not pause
there: it is due at architecture (key `architecture:<id>`, `raised_at: requirements`),
where the design answers it by ID with a reading the contract's text allows. A record
already stored under `requirements:<id>` stays there and is closed there. After
requirements, a serious finding on `requirements.md` stays open only when it quotes the
conflicting `requirements.md` sentence (`contract_text`) and the design's own sentence
(`design_text`) exactly. The design is then repaired; the journey pauses for the user
only once the design writes `USER QUESTION <id>:`, saying no reading fits, and the
decision record carries both quotes. A finding that names another file besides
`requirements.md` is the builder's to repair. Every question raised at requirements is
cited by ID in a scoped document at handoff.

Re-run the same command after resolving an approval or input request. The current
stage resumes; accepted stages are not accepted twice. Editing accepted handoff
artifacts requires an explicit baseline revision. Changed requirement documents
pause for renewed approval; the driver never reapproves them.

For an existing-implementation journey, call `revise` before editing a verified
handoff. When that handoff still passes its gate and matches the current snapshot,
the revision records a protected implementation baseline bound to its archived
project and the original journey declaration. The next architecture review
protects that verified implementation, including file additions and deletions.
The original faulty seed hashes, failed checks, closure history and elapsed charges
remain intact. Ordinary resume never adopts changed files. A stale handoff or a
midcycle revision cannot authorize a replacement implementation baseline; it
retains the previously protected baseline and can require explicit inspection.

To inspect a meaningful checkpoint or transfer the next phase to another session,
use `--stop-after architecture` (or another phase). A newly accepted intermediate
checkpoint returns `CHECKPOINT_REACHED` and exit 0, with leases closed and current
records retained. This is not a completed project. Resume without that option to
continue from the next phase under the same immutable declaration and remaining
budget. Already accepted checkpoints are not repeated. Stopping after handoff
still returns `COMPLETED` when its gate passes.

The 14400-second default is a generous total active-execution ceiling, separately
from role/native limits. `.matlab-harness/journey/declaration.json` freezes the chosen ceiling
before execution. Immutable invocation and step start/end records charge actual
startup, roles, native checks and cleanup wall time across resumed invocations.
Human waiting between invocations is excluded. Each role/native limit is clipped
to the remaining project ceiling before dispatch; project role budgets are never
retrospectively changed. Cleanup can exceed the remaining ceiling slightly and
its actual time is still charged. Reusing a journey with a different `--ceiling`
is refused; retain the original evidence when planning a separate amended run.

`journey.lock` prevents concurrent drivers. An abrupt process death leaves the
lock, unfinished invocation and any active task ownership for inspection. Do not
remove those records or recover shared resources merely because a timeout elapsed.
Inspect owned process/session state, retain interruption evidence, and explicitly
resolve active task leases using the core's recovery workflow. The driver refuses
an unfinished historical invocation rather than silently rerunning potentially
active work. Graceful interruption records its observed disposition.

For new PID/token-bound invocations, use the explicit
[interruption recovery command](journey-recovery.md) after inspecting stopped
resources. It appends an interrupted terminal record, preserves active leases and
charges start-to-recovery time conservatively. It never infers a successful role,
imports a review or clears an unrelated lock.

## Tests and responsibilities

Run the journey tests with
`python -m unittest discover -s tests/python -p test_journey.py -v`.

Provider tool access and ownership are contractual, not an OS sandbox. Discovery
drafting cannot acquire a construction lease before requirements approval; its
role packet expressly limits the task to requirements drafting. The runtime
remains responsible for obeying that instruction. The orchestrator must serialize
other shared MATLAB work outside this driver and protect independent evaluators.
