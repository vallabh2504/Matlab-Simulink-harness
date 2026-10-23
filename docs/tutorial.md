# Worked engineering workflow

Suppose an approved task predicts lumped cooling with C=1200 J/K, G=8 W/K,
T0=360 K and Ta=295 K. These are synthetic tutorial assumptions, not measurements.
The governing equation is C*dT/dt=-G*(T-Ta); its time constant is 150 s. Requirements
must address physical validity (uniform temperature, positive C/G, constant ambient),
time range, numerical tolerances, uncertainty and interfaces. Read the requirements
and MATLAB numerics skills selectively; add Simulink only if the task requires it.

```powershell
python matlab_harness.py start ../cooling-project --title 'Cooling study' --builder <actual-session-id> --owner <orchestrator-id> --scope src --brief 'Predict cooling and protect the existing parameter interface'
python matlab_harness.py --project ../cooling-project next
python matlab_harness.py --project ../cooling-project requirement --owner <orchestrator-id> --id TH-1 --text 'Temperature and energy obey the lumped balance' --acceptance 'Independent analytic temperature and C*(T0-T) energy checks over approved times' --source 'actual user brief' --units 'K, J, s'
```

Edit the project's requirements.md with operating bounds, provenance, equations,
exclusions and remaining questions. Only after actual authorization, record it:

```powershell
python matlab_harness.py --project ../cooling-project approve --owner <orchestrator-id> --actor <actual-user> --source <actual-approval-reference>
```

Declare each phase's check plan before its acceptance. The start command declares
empty requirements/architecture plans; add relevant executable checks if useful.
Later checks can be developed as the design becomes concrete. Accepted checkpoint
obligations remain frozen; changing them requires a recorded baseline revision.
Requirements/architecture
may have no machine command if independent review is the acceptance method.
Implementation/verification/handoff require nonempty meaningful executable checks.
Plan JSON maps stable names to argv lists, for example:

```json
{"thermal-oracle": ["matlab", "-batch", "addpath('src'); addpath('checks'); runThermalAcceptance"]}
```

Use absolute executable paths when needed. Write the independently designed oracle
under checks and include it in scoped artifacts if freshness must cover it. Keep
generated outputs outside scoped source so a check cannot invalidate itself by
writing reports. Do not substitute `print('pass')` for an engineering assertion.
Use `configure-checks <phase> --plan checks.json --owner ...` for each phase.

Request actual independent requirements/architecture reviews. Obtain a fresh
`snapshot`, then import the reviewer's project-relative JSON. Record observed
session/model identity; independence is an attestation, not authenticated by the CLI.

```json
{
  "reviewer_session": "actual-independent-session-id",
  "model": "actual-observed-model-id",
  "independence": "independent-agent",
  "checkpoint": "requirements",
  "verdict": "ACCEPT",
  "snapshot_digest": "actual digest from matlab-harness snapshot",
  "findings": []
}
```

Findings use the schema in [review standards](standards/review.md). Empty findings
are allowed only when the reviewer actually inspected the relevant content.
Save raw replies inside the current packet's scratch directory, using its returned
path, and pass a project-relative path when importing. Use a fresh answer file for
each packet. Rewriting a protected project support file invalidates its snapshot.
Import with `review requirements <scratch-relative-review.json> --owner ...`, then `accept requirements`.
Repeat architecture, lease src to an actual worker, implement and finish the task.
The complete-record example above is for the document checkpoints. For an executed
checkpoint in a new project, also supply the matching `packet_id`, independent
checks and host execution receipts. Prefer the simpler packet answer interface:
`answer <scratch-relative-review-answer.json> --owner <owner> --reviewer-session <observed-session>
--model <observed-model> --packet <packet-id>`; it pins bookkeeping to the packet.

Set up the tests once, after architecture is accepted and before the first
`run-check`. The check plans, probe runners and semantic plan are all part of the
reviewed snapshot, so changing any of them after a check has run makes that check
and its review stale, and the semantic plan cannot change once implementation is
accepted. In this order:

1. Write the check scripts and a known-good reference copy of each file under test
   outside the agents' scope (for example `checks/` and `reference/`).
2. `configure-checks implementation|verification|handoff --plan checks.json --owner <owner>`.
3. `configure-probes --owner <owner> --plan runners.json --reason <approval-reference>`,
   where a MATLAB runner is `[{"kind":"matlab","executable":"matlab"}]`.
4. `configure-semantics --owner <owner> --plan semantic-plan.json --reason <source>`.
   It names the good reference and defective variants of the promised properties;
   see the [assurance guide](evidence-assurance.md) for plan fields and MATLAB
   property assertion identifiers.

After each builder or repair task, run the checks, and at verification and handoff
also `run-semantics --owner <owner>`, before creating the reviewer packet. The
reviewer writes its own script inside the packet's scratch directory. MATLAB runs it
from that directory, so it reaches project code with
`addpath(fullfile('..','..','..','src'))`. In a manual host, run `run-probe --owner
<owner> --packet <packet-id> --check-id <check-id> --script <scratch-script>
--reviewer-session <observed-session>` and copy the returned receipt `id` to that
independent check's `receipt_id`; its check ID and artifact must match the executed
script. Automated runtime reviewers can supply a `run` proposal instead, which the
orchestrator executes after review.

Implementation/repair leases require accepted requirements and architecture.
Use `lease ... --kind discovery` or `--kind design` for explicitly scoped earlier
investigation/design after requirements approval.
Run `run-check thermal-oracle --owner ...`, review current evidence and source,
repair if necessary, and accept remaining phases in order. `gate handoff` returning
exit 2 means incomplete; a successful command by itself does not excuse missing reviews.

Use `resume` in a fresh session to obtain project truth, ownership, current checks,
reviews and open work. Recover interrupted ownership explicitly only after inspecting
the stopped previous process. A revision archives the baseline and resets approval,
reviews and acceptance. Check names retain their historical argv: use a new versioned
name if a revised baseline needs another command. This intentional immutability
prevents a familiar test name silently acquiring a different meaning.

The `next` command exposes actual check status, full reviewer findings, active leases
and remaining repairs. `packet --role builder`, `packet --role reviewer` and
`packet --role repair` create project-local prompts for the native agent you use.
The default runtime is manual, so `execute` returns a handoff until you explicitly
configure an executable adapter. See [runtime execution](runtime-protocol.md).

New projects use generous initial limits: builder 3600 s, reviewer 1800 s, repair 3600 s,
native checks 1800 s, ten repair attempts. Change these explicitly as the work needs:

```powershell
python matlab_harness.py --project ../cooling-project configure-runtime --owner <orchestrator-id> --builder-seconds 3600 --reviewer-seconds 1800 --native-seconds 1800 --repair-budget 8
```

These are execution ceilings, not engineering quality thresholds. Old attempts keep
their original deadlines and verdicts. A new baseline revision archives its consumed
repair history and starts a fresh count. Finish or interrupt active leases before
revising so workers cannot continue under a superseded contract.

Blocking findings also survive baseline revision. A later accepting review must
explicitly close their IDs with current evidence; omitting an old finding or merely
lowering its severity cannot erase it. `next` and `resume` include the durable defect
history and links to the archived review records.

The provided examples cover steady conduction/refinement, weighted least-squares
conditioning and actual Simulink mechanics. Run `verify_matlab` to reproduce their
independent oracles and raw figures. Those examples illustrate reusable patterns;
they are not answers to an arbitrary user's engineering problem.
