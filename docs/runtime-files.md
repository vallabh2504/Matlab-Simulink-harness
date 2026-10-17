# Native runtime files

All shipped simulation/model-inspection entry points use
`engineering.runtimeSession`. It assigns cache and code-generation folders inside
a fresh owned operating-system temporary directory. It never changes the caller's
working directory. Owned models close before cache cleanup; then the complete
prior Simulink configuration and MATLAB path are restored, including on errors.
Nested calls restore the outer operation's settings. Unrelated loaded/dirty models
are preserved. The temporary cache is removed when the operation exits.

`engineering.withRuntime(@() ownedOperation())` holds the guard outside the
operation's function scope. This guarantees that its model cleanup finishes before
the cache guard restores the caller. Standalone examples, graders and saved-model
semantic calibration bootstrap the canonical helper path themselves. When writing
new Simulink code, add the package's `matlab` folder and wrap the entire operation,
including model callbacks, update/compile, simulation and owned-model cleanup.

Saved `.slx` deliverables, CSV, figures and evidence belong in the explicit output
directory. Use a new project/results directory for these artifacts. Existing
project models are source deliverables; do not sweep them as caches.

MathWorks defaults can otherwise put `.slxc` and `slprj` in the current working
folder. The harness guard applies to its own entry points, not arbitrary Simulink
commands outside the harness. For an interactive session you can configure an
absolute user-local cache/codegen location with `Simulink.fileGenControl`. These
settings last for that MATLAB session. Global MATLAB startup/preferences are not
modified by the package. See the [MathWorks API documentation](https://www.mathworks.com/help/simulink/slref/simulink.filegencontrol.html).
