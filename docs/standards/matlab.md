# MATLAB and numerical engineering standard, v1

This standard supports numerical, scientific and mathematical work, not one domain. Mandatory requirements are properties of the engineering deliverable; literal source scans are candidates for review, not a complete MATLAB parser. Use the installed release's native Code Analyzer defaults. Do not load a newer-release coding configuration merely because its prose is useful.

| Rule | Mandatory, machine evidence where feasible | Reviewer judgment |
|---|---|---|
| M01 | Preserve unrelated files, path, workspace and models; close only owned resources | Is ownership clear under failure and interruption? |
| M02 | Public functions receive inputs/configuration explicitly; parameter units and provenance documented | A scoped base-workspace dependency may be justified for legacy integration, but must be isolated and tested |
| M03 | Reproduction entry point resolves paths from its own source or explicit inputs | Avoid `cd` side effects and hidden startup dependencies |
| M04 | No personal absolute paths or credentials in deliverables | User-selected local paths belong in local configuration, excluded from release |
| M05 | Validate shapes, finite values, domain/range and boundary behavior; intentional exclusions throw understandable errors | Rejecting a physically valid case to hide an unstable algorithm is unacceptable |
| N01 | Equations, boundary/initial conditions and units trace to requirements | Investigate conservation, missing couplings and applicability before choosing implementation |
| N02 | Independent numerical oracle or justified invariant/metamorphic checks; explicit tolerances | A plausible plot and a builder's unit test are insufficient evidence |
| N03 | Numerical method appropriate to conditioning, stiffness, sampling and scales | `inv`, normal equations or `eval` require a specific rationale, not automatic condemnation |
| N04 | Convergence/sensitivity and parameter perturbations where discretization or uncertainty matters | Separate numerical error, parameter uncertainty and model-form error |
| N05 | Reproducible randomness uses a recorded seed/generator; generated data cannot masquerade as measurements | Expose uncertainty assumptions and failure domains |

## Architecture and parameter ownership

Keep algorithm functions separate from configuration, experiments and plotting. Prefer meaningful interfaces and cohesive functions over arbitrary line-count limits. Scripts are acceptable experiment entry points; reusable mathematics belongs in functions. Classes are justified by state/lifecycle, not to decorate a simple calculation. Parameters belong in named structs/tables, typed arguments, model workspaces or dictionaries with explicit ownership. Shared defaults must have a single authoritative definition.

Good: `r = coolingResponse(time_s,p)` where `capacity` is J/K and `conductance` W/K. Bad: a script reads an unexplained `C` from the base workspace, changes directory, loads last week's MAT file and plots cached values as a fresh simulation. A legacy adapter may intentionally read a documented workspace variable; an explicit initialization and clean-start regression must prove its behavior.

Input validation is mathematical scope, not formatting. An integer grid of at least three points includes both boundaries. Positive conductivity/capacity excludes an ill-posed or physically different problem. Weight sign, matrix rank and time ordering are part of the algorithm contract. Validate outputs for finite values and relevant invariants too.

## Worked thermal conduction exercise

Constant conductivity, unit cross section, stationary one-dimensional conduction:
`-k d²T/dx² = q(x)`, with `T(0)=TL`, `T(L)=TR`. Units: k W/(m·K), q W/m³, x m, T K. The interior discrete equation is
`2Ti - Ti-1 - Ti+1 = qi h²/k`; boundary contributions are added to the right-hand side. For constant q,
`T(x)=TL+(TR-TL)x/L+q x(L-x)/(2k)`.

Run `solveHeat1D` in `examples/engineering-core`; compare the entire field, both boundaries and flux balance. The quadratic reference is reproduced to solver roundoff by centered differences. Use a sinusoidal source and 17/33/65 nodes to demonstrate spatial convergence rather than falsely claiming a single exact quadratic demonstrates second order accuracy. A sign-flipped source produces a plausible smooth but wrong temperature; the analytic oracle rejects it.

## Worked weighted calibration exercise

Solve `min Σ wi(Aθ-b)i²` with positive inverse-variance weights and full column rank. Whiten with `sqrt(w)`, normalize weights by a common positive scale, and equilibrate columns if their units/scales differ. Solve with QR or SVD. Normal equations square the condition number and are a poor default for nearly collinear observations. Rank decisions need a numerical threshold tied to singular values and dimensions; do not promise recovery of arbitrarily ill-conditioned coefficients.

`weightedCalibration` uses normalized weights and column-equilibrated economy SVD. Verify residual optimality, row permutation, weight scaling and predictions on changed inputs. Test rank deficiency, zero/negative/nonfinite weights and differently scaled columns. Coefficient error bounds must reflect conditioning, not a universal decimal tolerance. A numerically rank-deficient problem is rejected with a diagnostic; a physically ill-conditioned problem also warrants reporting identifiability.

## Execution and source checks

From a trusted project, add only required source directories, restore the prior path with one cleanup, and run `engineering.checkSource(sourceRoot)`. It executes `checkcode(...,'-id')` and returns literal guard candidates. Review all analyzer messages; warnings are not all defects. Every mandatory exception needs a bounded artifact/rationale/closure test. Do not suppress a finding with a pragma until you understand it; remove obsolete suppressions.

Use `engineering.dependencies(entryFiles)` for native dependency analysis and current-project context. Its output is incomplete for dynamic callbacks, variants, unresolvable paths and missing products. Live code/model inspection outranks a stale dependency summary. For large projects, use MATLAB Project path/startup/shutdown configuration and dependency tools; do not activate an unrelated user project as a discovery shortcut.

Performance work follows profiling and realistic workloads. Vectorization and preallocation help when measured; giant intermediate arrays and cryptic expressions can hurt memory and maintainability. No style score can compensate for a failed governing-equation assertion.

Reference principles: [MathWorks coding guidelines](https://github.com/mathworks/MATLAB-Coding-Guidelines), [native Code Analyzer](https://www.mathworks.com/help/matlab/ref/checkcode.html). Upstream configurations are not certified by this project; actual native checks are recorded per observed release.
