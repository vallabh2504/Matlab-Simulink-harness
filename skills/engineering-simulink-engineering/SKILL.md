---
name: engineering-simulink-engineering
description: Build, edit, inspect and simulate parameterized Simulink models with native compiled interfaces, solver evidence and optional capability-gated Stateflow.
---

Use for a Simulink/model-based task; MATLAB-only work should not manufacture models. Requires installed and licensed Simulink plus a working MATLAB execution path. Stateflow, Test/Check/Design Verifier and Model Advisor rules are optional capabilities, never inferred from an entitlement alone.

Read [model standard and mechanical derivation](../../docs/standards/simulink.md). Inspect current saved model, dirty/running state, references/libraries, callbacks, dictionaries/workspaces and protected legacy behavior. Establish one writer per `.slx`/dictionary and serialize shared MATLAB operations. Never `bdclose all`, discard user edits, or overwrite an unrelated named model.

Construct from explicit engineering states/ports and meaningful subsystem boundaries. Record data types/dimensions/units, continuous/discrete/hybrid sample times, rate transitions, solver and initialization rationale. Choose model workspace for isolated parameters, dictionary/typed parameters for justified shared ownership. Use SimulationInput for scenario overrides; unexplained base-workspace coupling is a defect.

Worked exercise: [buildOscillatorModel](../../examples/engineering-core/buildOscillatorModel.m) creates/saves a hierarchy for `m xddot+c xdot+k x=F`. [simulateOscillator](../../examples/engineering-core/simulateOscillator.m) runs actual Simulink outputs. Independently inspect/reopen/update/compile with `engineering.inspectModel`; apply task policy with `engineering.checkModel`; compare trajectories to an independent matrix exponential and energy decay for changed parameters.

Record saved-model/script hashes and inspect actual compiled properties after direct GUI edits. A source script's intention is not proof of the saved artifact. Numerical output agreement alone cannot prove a simulator really called Simulink; inspect execution provenance. The separate graders calibrate State-Space and integrator alternatives plus wrong damping without requiring one aesthetic hierarchy.

For saved-model parameter ownership and hierarchy claims, independently
audit the physical-field mapping; reopen saved defaults with no overrides, then
excite each owned parameter and probe actual internal trajectory influence.
Unfamiliar routing, model references or unsupported probes require individual
engineering review and calibration. These mechanics-specific helpers illustrate
methods to adapt to the project's equations, interfaces and tolerance contract.

For Stateflow, follow the thermostat procedure in the model standard only after actual API/installation detection. Do not create a stub returning analytic heating signals and advertise chart execution. No optional skipped test is a pass.

Outputs: editable saved model/build script, parameter/interface/solver records, compiled inspection, independent scenario results, visual architecture review and regression closure. Visual model-editor QA and optional toolbox checks need their own evidence.

For every native update, compile or simulation, use engineering.withRuntime around the full owned operation, including model cleanup. Load the canonical helper path first. Never leave .slxc, slprj or code generation in the caller workspace; saved models belong in explicit project outputs. See [runtime file policy](../../docs/runtime-files.md).
