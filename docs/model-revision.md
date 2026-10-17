# Existing saved-model revision and reconciliation

`engineering.reconcileModel(baselineFile, revisedFile, intent)` inspects two separate saved artifacts through native load/update/compile APIs. Each intent record identifies an exact category, relative target, parameter, before value and after value. The result accepts only when every declared change occurred and every detected change was approved. Renaming the root model for a safe owned copy does not create artificial block-path changes.

The helper reads back solver/time/logging configuration and callbacks; block types, masks, links and dialog parameters; compiled ports, dimensions, units, data types and sample times; actual line endpoints; and explicit model-workspace values. It binds direct dictionaries through native `filepath`, references and libraries through the loaded native block diagram's `FileName`, and external workspace sources through the actual MATLAB path or explicit source filename. It does not prefer a same-name file beside the root model. Dependency hashes are checked before and after update/compile and readback. Dirty dictionaries and dirty/busy referenced models reject without saving or discarding shared state. A dirty or running target and a loaded same-name different-file model are rejected by saved-model inspection. Models loaded by the helper are closed on exit; unrelated models are preserved. SHA-256 binds the saved files before and after readback.

This comparison has an explicit scope. It does not enumerate every variant, mask workspace, configuration-set property, referenced dictionary entry, nested external model or visual layout. Unsupported workspace value classes fail with `engineering:UnsupportedWorkspaceValue` instead of disappearing from the comparison. Numeric/logical/text, recursively supported structures/cells and the value/type/range/unit fields of `Simulink.Parameter` are supported; additional parameter properties such as storage class require a scoped serializer and task-specific check. Load/update/compile callbacks execute: only use trusted models and reviewed dependencies.

## Executed example contract

`examples/model-revision/runModelRevision.m` creates a saved oscillator baseline, obtains its real legacy time series, then saves an owned copy with a new model name. It doubles the saved damping from 0.43 to 0.86 N·s/m and changes maximum solver step from `auto` to 0.02 s. These are the same native parameter operations used by model-workspace and solver dialogs. The example does not claim a mouse-driven GUI session was recorded.

The revision must reconcile to exactly those two intended changes after reopening. Four native simulations then prove baseline physics, revised default physics, legacy compatibility through an explicit model-workspace override, and a changed mass/stiffness/force scenario. An independently formed augmented matrix exponential supplies trajectory truth. The unforced baseline and revision must lose mechanical energy monotonically within the stated numerical bound. Restoring old damping for one simulation must reproduce the baseline time series without changing the saved revision.

The output directory must be new. The example retains both `.slx` files, `baseline-and-revision-series.mat`, `revision-intent.json`, `reconciliation.json`, and `model-revision-evidence.json`. Evidence is written only after actual native assertions pass. Failed runs retain partial artifacts for diagnosis and throw their original error. No prewritten PASS file is included.

```matlab
addpath('matlab','examples/model-revision');
evidence = runModelRevision(fullfile(tempdir,'my-new-engineering-revision-run'));
assert(evidence.reconciliation.accepted);
results = runtests('tests/matlab/testModelRevision.m');
assertSuccess(results);
```

The native tests include real legacy/oracle execution, unexpected Gain changes,
root output-order changes, a false declared before value, dirty-target preservation,
an identical-copy comparison, workspace class/addition detection, and a saved output
unit change from metres to centimetres. The last case exercises Simulink's automatic
unit conversion and requires the change to appear in actual compiled-port readback.
`inspectModel` records compiled units and dimensions alongside widths/types/sample
times. An unavailable attribute remains explicitly `UNAVAILABLE`; it is never
manufactured. Task-specific acceptance must disposition missing required metadata.
Comparison keys are generated once and indexed by hash maps; native model loading,
compilation and external dependency inspection still have their own costs.

The additional direct-dependency fixtures cover a shadowed MAT-workspace source,
dictionary execution and dirty shared dictionary preservation, an actual path-selected
referenced model and dirty shared model preservation, and an initialization callback
that mutates an owned source file. Native simulations must execute the linked data
and reference. The referenced model's third output must equal the actual child's
value, rather than the same-name decoy beside the root. Independently computed
file hashes must agree with the readback dependency reports. The callback mutation
must reject acceptance and retain its failure artifact; no hidden rollback is performed.
MAT-file and dictionary driven oscillator trajectories are additionally compared
to an independently formed matrix exponential at the actual logging times. The
reference fixture declares the exact two observed parent-name-derived state
namespace changes as explicit intent, and verifies that parent initial-state
loading and final-state saving are disabled. Native readback regenerated these
names despite attempted inactive dialog assignments. The helper preserves these
real parameter differences instead of erasing arbitrary root-name text from
parameter expressions. A declaration of no changes must reject the differing
names; the explicit intent accepts only those two exact values.

Dependency integrity includes owned cleanup. A revised-only `CloseFcn` fixture
has its callback addition explicitly approved, and the saved callback mutates a
bound MAT-file only when reconciliation closes the revision after readback. The
helper must reject `engineering:RevisionDependencyChanged` at the post-cleanup check.
All captured dependency files are checked again immediately before return
across both snapshots. Post-close checks also inspect any still-loaded tracked
model's actual file/dirty/busy state and inspect tracked dictionaries through a
temporary native connection. Closed owned models are not required to remain
loaded or be reopened. An approved callback that leaves a retained dictionary
dirty must reject `engineering:DirtyDictionary` even when its file bytes are unchanged;
the unsaved changed value survives rejection. Trusted side effects are not rolled back.

Normal cleanup calls `close_system` explicitly and propagates a close failure;
the fallback `onCleanup` path is best effort so that an already-originating error
is preserved. A separately approved throwing `CloseFcn` fixture must propagate
its actual native error diagnostic and leave the saved source bytes unchanged.
MATLAB may leave the owned model loaded after a callback error; inspection fails
instead of reporting successful acceptance. Disposition of that loaded owned
model is an explicit recovery step, not a silent save or callback rewrite.

MATLAB can convert a `CloseFcn` error to a warning that keeps the original
user-defined identifier and still unload the model, so a universal native
callback-warning identifier cannot be assumed. Each owned normal close captures only warnings issued during that
close, restores the caller's `lastwarn` state, and rejects with
`engineering:RevisionCleanupWarning` while preserving the actual diagnostic. Preceding
unit-conversion/solver warnings are not included. Arbitrary close warnings need
explicit operator assessment; this boundary does not claim every warning means
the physical equations are wrong. No global warning-to-error mode is installed.
Tests use temporary session cache/code-generation folders and restore prior
`Simulink.fileGenControl` settings and the MATLAB path. Existing caches are preserved.

MathWorks documents [compiled port attributes](https://www.mathworks.com/help/simulink/ug/determine-port-signal-attributes-programmatically.html)
and [CompiledPortUnits](https://www.mathworks.com/help/simulink/slref/block-parameters-and-properties.html).
Unit propagation is not a proof of governing equations or universal dimensional
inference through every computational block.

## Applying the workflow to your model

1. Designate the baseline, owned revision path, dependency owners and legacy scenario grid. Keep the original saved file and its hash.
2. Inspect callbacks, references, library links, dictionaries, workspace source and the actual solver/interface before editing. For an externally sourced workspace or nested dependency, extend the task's inspection and hash binding rather than assuming a root-only comparison is sufficient.
3. Obtain baseline results through the actual saved model; define the independent equation, conservation law or experimental reference and numerical acceptance bounds.
4. Make reviewed changes on the owned copy. Translate a GUI edit into an explicit intent record and reproducible native script. Reopen the saved artifact and reconcile; investigate extra changes rather than expanding intent automatically.
5. Execute legacy and changed scenarios against independent truth. Confirm any transient `SimulationInput` override was reverted and the saved artifact still has the reviewed hash.

[MathWorks save_system](https://www.mathworks.com/help/simulink/slref/save_system.html) documents saving under a new model name. [Model-workspace getVariable](https://www.mathworks.com/help/simulink/slref/simulink.modelworkspace.getvariable.html) supplies actual workspace values. [SimulationInput setVariable](https://www.mathworks.com/help/simulink/slref/simulink.simulationinput.setvariable.html) documents the `Workspace` argument needed to override a model-workspace value for a single simulation.

[Workspace source selection](https://www.mathworks.com/help/simulink/ug/specify-source-for-data-in-model-workspace.html) requires filename-only external sources to reside on the MATLAB path. [Model reference](https://www.mathworks.com/help/simulink/slref/model.html) documents path selection of an unqualified referenced model. [Native dictionary filepath](https://www.mathworks.com/help/simulink/slref/simulink.data.dictionary.filepath.html) returns the resolved dictionary file, while [Dictionary HasUnsavedChanges](https://www.mathworks.com/help/simulink/slref/simulink.data.dictionary.html) distinguishes saved bytes from shared unsaved state. These APIs inform dependency binding; the actual fixture logs establish which branches executed.
