# Explicit journey interruption recovery

An unfinished journal is evidence of interruption, not proof that a role succeeded
or that its processes stopped. recover_journey appends an observed recovery record
after explicit inspection. It never launches or kills a process, approves
requirements, imports reviews, rewrites role receipts or finishes task leases.

## Usage

    matlab-harness --project <root> recover-journey --owner <current-owner>
       --attempt .matlab-harness/journey/attempt-<id>
       --stopped-process-attestation "<actual inspection observations>"
       --source "<observed process/session check reference>"
       [--lock-token <exact recorded token>]

`--attempt` names one existing `.matlab-harness/journey/attempt-*` directory,
absolute or project-relative. The current owner must match the attempt and its
immutable declaration. The attestation and source must describe an actual
inspection of the stopped processes, not an assumed expiry. A refusal leaves the
original records unchanged.

Recovery revalidates the control path: linked or junction control directories and
journal paths that escape the project's control directory are refused before any
recovery state is read or changed.

The same operation is available from Python as
`matlab_harness.journey_recovery.recover_journey(project, owner, attempt_directory,
stopped_process_attestation, source, expected_lock_token=None)`.

Before recovery inspect the named invocation, actual raw role evidence, local
owned PID and any MATLAB/runtime service or detached children. Do not attest
resources stopped when they are unknown. Recovery records external cancellation
UNKNOWN and descendant shutdown unverified; it does not create contrary evidence.

Existing mutation.lock is always refused, including foreign or unreadable locks.
Resolve it separately through the core's explicit inspected recovery procedure.
Active leases remain ACTIVE after journal recovery; inspect resources and disposition
each one explicitly before allowing construction to resume.

## Lock binding

Each journey run records its PID and exclusive lock token in `started.json`, and
`journey.lock` names the exact attempt directory it belongs to. Recovery verifies
that binding rather than inferring it from age. A crash before those records are
complete needs manual investigation; there is no blanket lock-removal fallback.

When the journey lock is already absent, the attempt's bound tracked PID is still
queried and must be stopped. This handles interruption after owned lock cleanup
but before terminal journal creation.

## Read-only process checks

Windows uses OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION and
GetExitCodeProcess, closing its query handle. It never uses os.kill(pid,0), process
termination access, taskkill or automatic backend cancellation. A live PID is
refused. Access denial or unsupported/inaccessible query yields UNKNOWN and is
refused. POSIX uses a bounded read-only ps PID query; unrecognized results are
UNKNOWN. PID reuse can cause a conservative refusal, never automatic ownership
inference. A stopped local PID cannot certify remote service/descendant shutdown.

## Append and budget accounting

Recovery preserves started.json, every step and execution receipt, the immutable
declaration and all artifacts. It exclusively creates finished.json with status
INTERRUPTED_RECOVERED and appends an ASSUMED project decision containing the
inspection source, terminal hash and charge. The execution outcome stays UNKNOWN.
It verifies persisted decision and terminal before removing only the unchanged,
exactly bound owned journey lock. Changed/foreign/unreadable locks are retained.
A late lock change can produce a recovered terminal with lock_cleanup
INSPECTION_REQUIRED; resolve that lock before resuming.

The charge is the larger of observed start-to-recovery UTC elapsed time and summed
completed-step wall time, rounded upward. This includes human waiting after the
interruption and can exhaust the original ceiling. It does not grant a fresh
budget, cap the charge to remaining time, reset history or rewrite role timeouts.
Clock reversal, changed declaration, mismatched prior charges and unfinished
sibling invocations require inspection. Subsequent journey execution consumes this
terminal's wall_seconds through its existing cumulative accounting.

The terminal and project decision use the existing project mutation transaction;
filesystem failures during commit remain inspection-required. A partial write or
uncertain decision is never overwritten as successful recovery. Project-local
records are integrity attestations, not a security boundary against arbitrary
write-capable actors.

A crash between terminal creation and project decision commit can leave a terminal
with an uncommitted decision. Preserve both records and inspect that partial commit;
the command never manufactures completion or overwrites the existing terminal to
hide it. This recovery path establishes an interruption disposition, not a successful
engineering outcome.

## Verification

Run:

    python -m unittest discover -s tests/python -p test_journey_recovery.py -v

Tests use actual locally exited Python child PIDs and the actual current live PID
on Windows, preserved interruption fixtures, foreign locks, traversal, changed
declarations, unknown-query fault injection, clock reversal, active leases and
elapsed-budget exhaustion. A recovered fixture then runs through the normal
five-stage journey with the same declaration and prior charge.

