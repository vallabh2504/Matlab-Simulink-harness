---
name: engineering-results-verification
description: Run independent engineering oracles, validate numerical results and uncertainty, and export meaningful scientific plots, figures and reproducible reports.
---

Use for experiments, sweeps, acceptance evidence, result interpretation and scientific figures. Requires MATLAB for these exercises; plotting supports native figure export. Do not use visual attractiveness or a linter score as a substitute for engineering assertions.

Read [results/figures standard](../../docs/standards/results.md) and the relevant numerical/model standard. Before candidate evaluation, declare analytic/invariant/metamorphic references, parameter perturbations, boundary cases, conditioning/convergence tests and defensible absolute/relative tolerances. Independently justified references must not simply copy the builder algorithm.

Keep grader and oracle files independently owned; builders must not edit them. Record their hashes before and after agent work. Hashes detect changes; real isolation from a malicious worker needs OS, account or read-only boundaries. Grader calibration checks grader logic only. Keep failed and unsupported checks in the record.

Worked exercise: call [runEngineeringDemo](../../examples/engineering-core/runEngineeringDemo.m) with a new empty directory. Inspect Kelvin/Joule/meter/second axes and CSV columns, compare thermal analytic values and passive mechanical energy. [verify_matlab](../../scripts/verify_matlab.m) runs real grader calibration, engineering assertions and saved-model inspection. Execute in a clean batch child to eliminate stale-workspace reuse.

Distinguish numerical approximation error, observation uncertainty, parameter identifiability and model-form uncertainty. Synthetic educational constants have no claimed measurement confidence interval. Inspect the raw arrays, not only the image. Use appropriate vector exports and legible markers/font sizes; apply requested journal/IEEE layout as a project-specific presentation contract.

Outputs: raw numerical data, actual environment/command/evidence, clean rerun, labeled figures, accepted tolerances and limitations. Do not claim improvements you have not measured; mark unobservable token, tool or cost figures as unknown.

For an entry that rejects existing output destinations, snapshot all files,
digests and empty directories before the call and compare the full tree afterward.
If the approved contract requires a returned artifact ledger, check actual final
file coverage, destination resolution, digests and duplicate aliases.
Declare manifest self-exclusion explicitly and calibrate it. Ledger requirements
are prospective; never impose them retroactively on an accepted older contract.
