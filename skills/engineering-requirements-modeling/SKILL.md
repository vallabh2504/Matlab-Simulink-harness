---
name: engineering-requirements-modeling
description: Discover and revise MATLAB or Simulink engineering requirements, equations, units, boundaries and acceptance oracles before consequential modeling.
---

Use for a vague engineering idea, a precise new specification or a material change to an existing project's mathematical scope. Reuse an approved baseline for a small change. No MATLAB license is required for discovery; installed products are required before committing to executable APIs.

Inspect current files/models and `matlab-harness resume` first. Recommend technically sound defaults, then ask only material ambiguities: physical system boundary, operating envelope, boundary/initial conditions, meaningful inputs/outputs, units, data provenance and evidence of success. Do not turn this into a long intake form. For substantial new projects, present versioned requirements.md and obtain actual user approval before consequential construction.

Record stable IDs, equations/assumptions, quantities with units/ranges, parameter sources, interfaces, toolboxes, non-goals, acceptance methods and unresolved questions. Separate USER-APPROVED / PROPOSED / ASSUMED / VERIFIED / UNKNOWN. A chosen synthetic tutorial constant is ASSUMED, not a measured fact. Approved changes need a reason and reapproval, not reviewer fiat.

Reuse actual authorization already given for a precise specification or a local synthetic exercise. Approval of the work's scope does not transform analyst-selected synthetic constants into measured user facts. Keep those assumptions explicit. Ask for renewed approval when a consequential requirement changes; do not repeatedly request permission for already authorized reversible work. Independent review is the requirements/design checkpoint obligation; empty executable plans there are valid when no meaningful native check applies. Future engineering stages still require independently executed oracles.

Read [MATLAB/numerical standard](../../docs/standards/matlab.md) for thermal/calibration derivations and dimensional checks. Read [review/continuity](../../docs/standards/review.md) when recording approval or a baseline revision. Use native project/dependency facilities and targeted source inspection; a graph is a derived view with provenance/freshness, not authoritative physical truth.

Worked exercise: frame steady 1-D conduction as `-k T''=q`, fixed end temperatures, constant k, SI units and positive length/conductivity. Derive the constant-source analytic solution independently and predeclare a nonquadratic grid-refinement check. Explain why the quadratic case alone cannot establish convergence order. The implementation and executed independent grader are in [engineering core](../../examples/engineering-core).

Outputs: approved project requirements, governing-equation/units record, decision provenance, acceptance plan and independent requirements/architecture findings. Use the CLI's approval command only with actual recorded authorization. Discovery is not verified engineering delivery; unsupported products and uncertain assumptions remain explicit.

Short cards with runnable snippets, inlined into task packets: [requirements](../cards/requirements.md), [parameters](../cards/parameters.md).
