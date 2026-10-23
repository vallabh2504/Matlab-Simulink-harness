# Independent engineering review, repair and continuity

The reviewer challenges actual current requirements, equations, sources/models and executed results. It does not certify expertise from a persona or comment count. Review requirements, architecture, meaningful implementation, integrated evidence and handoff; combine adjacent gates only for a proportionately small task. Hard numerical/regression failures block regardless of qualitative score.

Use actionable findings: ID, requirement/artifact/line, severity, kind, evidence/counterexample, impact, scoped repair and closure check. Kinds: PROVEN DEFECT, EVIDENCE GAP, POTENTIAL DEFECT, OPTIONAL IMPROVEMENT. CRITICAL invalidates core engineering or fabricates proof; MAJOR blocks meaningful acceptance; MODERATE needs tracked disposition; MINOR is proportional polish. No unresolved CRITICAL/MAJOR may pass. Counterevidence is welcome; reassess hypotheses and escalate material unresolved disputes without changing approved requirements by fiat.

## Evidence and qualitative rubric

Applicable categories: governing equations/dimensions/invariants; numerical conditioning/solver/convergence; MATLAB architecture/ownership; model topology/interfaces/Stateflow logic; integration/clean reproduction; coverage/oracle independence; technical clarity. For each, record Unsatisfactory / Supported with limitations / Strongly supported and actual evidence. Optional scoring must declare weights and behavioral anchors before use, normalize only applicable categories, and be calibrated. There is no universal numeric score threshold. The deterministic gate and open findings determine acceptance.

Calibrate with good, incorrect and unfamiliar correct solutions. The independent graders exercise a wrong heat source/sign, numerical calibration and cooling faults plus valid alternatives; Simulink calibration compares State-Space, paired integrators and wrong damping.

## Executable lifecycle and gate

`matlab-harness init` establishes portable project records; `claim` establishes one orchestrator; `requirement` records stable IDs and source; `approve` records actual user authorization against document + requirements hashes. Do not invoke approve merely to silence a gate. `configure-checks --plan` pins name→command argument lists before advancement. `run-check` executes those exact commands without a shell; arbitrary imported text is not a passing check. `snapshot` identifies current declared engineering artifacts, requirements and obligations. The reviewer imports a JSON verdict using that exact digest. `accept` advances only the current phase after current checks/review and no unresolved blocker.

These are integrity mechanisms, **not signed evidence or authenticated human identity**. An actor with arbitrary project write access can rewrite records or configure a meaningless check. An independent evaluator must inspect actual command/acceptance quality and independently rerun oracles; use OS/account isolation and read-only grader mounts against malicious workers.

`lease` assigns exclusive paths and requirements to a worker; overlapping aliases/parents collide. Shared MATLAB/model sessions remain serialized by orchestrator convention and the CLI mutation lock during checks. `finish-task` dispositions an interrupted task without deleting its artifacts. `recover-owner` explicitly names old/new owner and reason; existing leases remain visible. `recover-lock` requires its recorded token and assertion that the old process stopped. Age alone is not permission to erase work.

After a rejection, record a repair reason and assign a bounded change, rerun relevant regression/independent checks, then obtain a new current reviewer closure. Default repair budget is ten cycles and is configurable. Exhaustion is INCOMPLETE and escalated, not silent relaxation. Approval/check-plan findings against orchestrator-owned records return to that orchestrator; a construction repair agent cannot rewrite authorization to silence them. `revise` preserves the old baseline/evidence/reviews in history and restarts requirements approval/review. Derived graph caches cannot override live artifacts.

Requirements and architecture can have empty executable plans when their independent review is the meaningful declared obligation. Implementation, verification and handoff need nonempty executed checks. Reassess actual authorization and counterevidence: an already authorized synthetic exercise does not require a new permission request for every analyst-selected tutorial constant. Those constants remain ASSUMED. Record unresolved consequential uncertainty as a gap, without turning a formatting preference or unexecuted hypothesis into a proven fabrication.

New projects additionally require packet/checkpoint/session-bound host probe receipts
for independent PASS/closure. Complete review records must explicitly name their
`packet_id`; packet answers imported through `answer` supply this bookkeeping
automatically. Verification/handoff require an approved semantic adequacy plan
or an explicit operator-approved non-applicability rationale. See
[evidence assurance](../evidence-assurance.md) for execution, calibration and legacy
attestation rules. An older example without receipts does not satisfy executed
assurance merely because its JSON parses.

## Portable continuation record

`resume` reports requirements/approvals, decisions with assertion status and sources, current artifact hashes, active ownership, pending phase, current failed/stale gate and next action. A different runtime must inspect source and this record before continuing. Keep important equations/parameters/interfaces in project files, not only chat. Do not embed private transcripts, provider secrets or sole-source hidden caches. A sequential role pass may aid diagnosis but is marked honestly and cannot satisfy an independent-agent acceptance gate.
