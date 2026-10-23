---
name: engineering-matlab-numerics
description: Implement, debug and verify MATLAB numerical algorithms with explicit architecture, stable linear algebra, conditioning, convergence and clean execution.
---

Use when numerical MATLAB code, scientific algorithms, calibration, error analysis or debugging is needed. Requires licensed MATLAB; these exercises use base MATLAB. Actual verification target is the release in the capability report. Avoid unavailable toolbox functions and untested newer-release configurations.

Read [the numerical/architecture standard](../../docs/standards/matlab.md), selecting the relevant worked derivation. Keep algorithms/configuration/experiment/plotting separate. Validate input domains, shapes and finite values; label parameter units/provenance; do not silently recover invalid physical inputs into plausible output. Preserve caller path/workspace and close only owned resources.

Choose methods from equations and conditioning: weighted QR/SVD for calibration, sparse centered differences for smooth steady conduction, suitable ODE solvers/tolerances for dynamic problems. Avoid normal equations by default for ill-conditioned least squares. Report conditioning and rank decisions. For stiff dynamics, discontinuities or singular domains, justify solver and event handling rather than increasing tolerances until tests pass.

Run `engineering.checkSource(sourceRoot)` and inspect native analyzer diagnostics plus literal guard candidates. They cannot certify equations and may match comments or justified legacy adapters. Record scoped exceptions. Use `engineering.dependencies(entryFiles)` for native dependency evidence with limitations; do not assume dynamic callbacks or all missing products are resolved.

Worked exercises: [solveHeat1D](../../examples/engineering-core/solveHeat1D.m), [weightedCalibration](../../examples/engineering-core/weightedCalibration.m), [coolingResponse](../../examples/engineering-core/coolingResponse.m). Independent graders cover analytic temperatures, nonquadratic refinement, weighted residual optimality/near collinearity, domain failures and protected legacy cooling/energy. Reproduce with `verify_matlab` from [scripts](../../scripts). Grader-owned paths must not be edited by builders.

Debugging method: isolate the failing parameter/initial state; reproduce from clean inputs; compare units/signs/residual/invariants; inspect executed code rather than cached workspace; repair the cause in the owned function; rerun relevant independent and protected regression cases. A failed result must remain visible in evidence. Never fabricate a passing MATLAB response.

Outputs: readable source, explicit interfaces/units, analyzer disposition, raw numerical results, independent checks and rationale for solver/tolerance/convergence. A style improvement without changed engineering evidence is not a numerical repair.

Short cards with runnable snippets, inlined into task packets: [matlab-numerics](../cards/matlab-numerics.md), [matlab-unittest](../cards/matlab-unittest.md), [matlab-errors](../cards/matlab-errors.md).
