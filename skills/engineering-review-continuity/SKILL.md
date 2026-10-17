---
name: engineering-review-continuity
description: Independently review MATLAB and Simulink engineering checkpoints, calibrate defects, perform bounded repair, and resume portable project records across sessions or runtimes.
---

Use for meaningful checkpoint review, rejected engineering evidence, interruption recovery or runtime handoff. This is a skeptical engineering role, not a guaranteed seniority persona. Independent runtime agents/humans are required for independent acceptance; a sequential self-role pass is labeled honestly and remains diagnostic.

Read [review/repair/continuity contract](../../docs/standards/review.md). Inspect approved requirements, equations/dimensions, actual source/saved model, exact artifact snapshot and independently executed results. Challenge missing states, conditioning/stiffness, solver/initialization, workspace ownership, interface/sampletime, Stateflow logic where applicable, and plots whose plausible shapes hide wrong quantities.

Record finding ID, artifact/requirement/location, severity/kind, evidence or reproducible probe, impact, bounded repair and closure. Distinguish proven defects, evidence gaps, hypotheses and optional improvements. Failed mandatory oracles or unresolved critical/major findings block; scores cannot compensate. Reassess builder counterevidence rather than treating criticism as infallible.

Exercise calibration using [independent fixtures/tests](../../tests/matlab/graders). Known-good and unfamiliar valid solutions must be accepted; equation/sign/calibration defects must be rejected. There is no universal numeric score threshold.

Reviewer: inspect `matlab-harness snapshot` and existing evidence, then return the structured independent report. Keep requirements, design, source, stable results and control records unchanged. Run useful diagnostic checks into fresh temporary output directories; propose checks whose execution would change scoped artifacts. An obvious defect still belongs to a separate repair worker.

Orchestrator: import the independent report with `matlab-harness review`, assess `matlab-harness gate`, then explicitly `accept` only when current obligations pass. The orchestrator owns approval, check registration/execution and control-record mutations; these commands are not reviewer instructions. Only predeclared commands executed by `run-check` form accepted check records. These hashes/identities are not signatures/authentication; inspect real commands and oracles. Never approve changed requirements to get around a blocker.

On repair: assign limited owned change, rerun relevant independent/regression checks and obtain current closure. On interruption: inspect `resume`, active leases, current hashes, actual artifacts and explicit stale-lock recovery. Preserve previous baseline when revising and keep approvals separate from proposals. Native runtime spawning owns parallelism; the policy does not invent MCP subagent APIs or privileges.

Outputs: evidence-backed review, calibrated finding/closure records, honest independence/capability level, bounded repair status and portable continuation sufficient without private chat transcripts.
