# Simulink and conditional Stateflow engineering standard, v1

Native model construction is trusted-code execution: load, initialization and simulation callbacks can change files/workspace. Inspect callbacks before loading unfamiliar models. Preserve user dirty/running models and reject name collisions instead of closing them. Serialize model mutation and the shared MATLAB session. A saved binary hash identifies the exact reviewed artifact; it is not a numerical acceptance criterion.

| Rule | Mandatory task-scoped assertion | Additional engineering review |
|---|---|---|
| S01 | Required subsystem/model boundaries exist and execute | Hierarchy expresses engineering responsibility, not cosmetic grouping |
| S02 | Root interface order, port connectivity, compiled dimension/type and declared units match contract | Intentionally unused ports need a scoped exception; names alone do not prove units |
| S03 | Actual solver, tolerances, continuous/discrete sample times and initialization match approved design | Examine stiffness, zero crossings, algebraic loops and rate transitions |
| S04 | Parameters resolve from explicit owned model workspace/dictionary/SimulationInput | No unexplained dirty base-workspace state, callbacks or cached MAT-file dependence |
| S05 | Save/reopen/update/compile/simulate and compare actual outputs independently | A diagram that opens is not evidence of correct dynamics |
| S06 | Builder script and saved-model changes remain traceable | Direct GUI edits require inspection and reconciliation, not blind script overwrite |
| S07 | Cache/codegen use owned temporary folders and saved models use explicit project outputs | Wrap the full native operation with `engineering.withRuntime`; preserve caller configuration/path and unsaved models, including on failure. See [runtime files](../runtime-files.md). |

## Mechanical worked exercise

For constant force: `m xddot + c xdot + k x = F`, states `[x;v]`,
`xdot=v`, `vdot=(F-cv-kx)/m`. Units: m kg, c N·s/m, k N/m, F N, x m, v m/s. Positive m/k and nonnegative c define the passive linear oscillator domain. For unforced motion, `E=(m v²+k x²)/2` and `Edot=-c v²<=0`. This is an independent physical invariant; an augmented matrix exponential is a separate trajectory oracle that covers critical, under- and over-damped cases without reusing the builder's integrator code.

`buildOscillatorModel(p,outDir)` creates a unique saved model: a force Constant feeds Mechanical dynamics; its Sum subtracts damping and spring forces, Gain divides by mass, and two Integrators represent velocity and displacement. Six explicit model-workspace parameters resolve without base variables. Displacement/velocity Outports specify m and m/s. Unique names protect unrelated loaded/file artifacts.

`simulateOscillator` uses `Simulink.SimulationInput`, specified output times and actual root Outport logging. Relative/absolute tolerances and maximum step are numerical choices; compare solver sensitivity and sampling if a project's frequency or stiffness changes. Verify initial conditions, forcing, changed mass/damping/stiffness, zero damping conservation and positive damping energy decay. Do not replace a failed simulation with an analytic trajectory and call it Simulink evidence.

Run `engineering.inspectModel(modelPath)` to inspect the **saved** artifact, native update/compile metadata, solver, workspace variables, callbacks, blocks/parameters, connectivity and lines. The helper terminates compilation before closing only its owned model. `engineering.checkModel(modelPath,policy)` applies declared solver/subsystem/Outport/connectivity requirements. It cannot infer complete physical correctness, signal ordering, mask semantics or optional toolbox compliance. Independent engineering graders remain mandatory.

## Existing model modifications

Record baseline source/model hashes and representative regression outputs before editing. Inspect model references, linked libraries, masks, variants and dictionaries; do not indiscriminately break links. Designate one owner per `.slx`/dictionary. A script modification must operate on a copy or explicitly named owned model. Check parameter differences and actual changed topology after reopen. Reconcile GUI changes through an inspected change record and script update when needed. Protect legacy outputs/initialization as requirements, not incidental test snapshots.

Dictionary versus workspace selection depends on sharing: one isolated tutorial may use model workspace; multiple model references sharing typed calibration data may warrant a `.sldd` and `Simulink.Parameter`. Define data types, dimensions, units, ranges and ownership; do not introduce dictionaries merely as bureaucracy. Continuous/discrete/hybrid boundaries require explicit sample-time/rate-transition analysis. Prefer model references or libraries when reuse and ownership justify them.

`engineering.reconcileModel(baselineFile,revisedFile,intent)` provides native saved-artifact reconciliation for an owned copy. Every intent entry states category, relative block/variable target, parameter, exact before value and exact after value. The report rejects extra detected changes and intent that did not occur. It compares solver/time/logging settings and callbacks, actual block dialog values, compiled interface metadata, line endpoints, explicit model-workspace values and direct external dependency hashes. Root model renaming is normalized; a changed output port order remains a real interface change. Unsupported value classes fail explicitly. This scoped comparison does not recursively prove nested library/model/dictionary equivalence, cover every variant/mask/configuration-set property or establish physics.

The [model revision workflow](../model-revision.md) contains a real saved oscillator revision: baseline trajectories are obtained before editing; damping and maximum step are changed on an owned saved copy; reopened changes must match two explicit intents; default revision, legacy damping override and changed mass/forcing are independently checked against a matrix exponential. Passive-energy monotonicity supplies an additional invariant. Transient overrides must leave the saved artifact unchanged. `tests/matlab/testModelRevision.m` exercises unapproved Gain/port-order changes, wrong before values, identical-copy readback and preservation of unrelated dirty models. Execute the tests in the actual MATLAB/Simulink runtime before claiming the workflow verified.

## Optional checks and Stateflow

Base Model Advisor presence is distinct from Simulink Check, Test or Design Verifier installation/license and task suitability. Discover actual check IDs and products before invoking a project-approved subset; report unsupported checks rather than asserting all MAB rules ran. Model Advisor findings are supplementary diagnostics and do not prove governing equations.

Stateflow requires installed functionality **and** entitlement **and** an executed chart exercise. A true `license('test','Stateflow')` alone is insufficient. The harness uses Stateflow only when `engineering.capabilities` reports it installed and executable.

When available, a worked thermostat contract is: initial OFF; ON at `temperature<=lower`; OFF at `temperature>=upper`; hold within the band; `lower<upper`, discrete sampleTime>0. Use `Stateflow.Chart`, scoped input/output Data, states with explicit entry assignments, default transition and two threshold transitions. Inspect transition priority, equality behavior, unreachable states, temporal/event interactions and output sample times. Exercise boundary equality, oscillation inside the band, repeated thresholds, startup and restart. Independently compare the exact output sequence; calibration should include reversed comparisons and a correct alternative transition arrangement. If Stateflow is unavailable, report the chart work as unsupported; a skipped test is not a pass.

References: [MAB guidelines](https://www.mathworks.com/help/simulink/mab-modeling-guidelines.html), [SimulationInput](https://www.mathworks.com/help/simulink/slref/simulink.simulationinput.html). These inform design; only explicitly reported native operations are verified.
