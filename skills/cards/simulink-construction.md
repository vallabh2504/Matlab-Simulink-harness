## Card: building Simulink models from code
Build, simulate and close a model; the parameter comes in through `SimulationInput`, not the base workspace.
```matlab
model = 'demoGain';
if bdIsLoaded(model), close_system(model, 0); end
new_system(model);
cleanup = onCleanup(@() close_system(model, 0));
add_block('simulink/Sources/Step', [model '/Step'], 'Time', '1', 'After', '2');
add_block('simulink/Math Operations/Gain', [model '/Gain'], 'Gain', 'k');
add_block('simulink/Sinks/Out1', [model '/Out1']);
add_line(model, 'Step/1', 'Gain/1');
add_line(model, 'Gain/1', 'Out1/1');
set_param(model, 'StopTime', '5', 'SolverType', 'Variable-step', 'Solver', 'ode45');
in = Simulink.SimulationInput(model);
in = in.setVariable('k', 3);
out = sim(in);
y = out.yout{1}.Values;              % timeseries
assert(abs(y.Data(end) - 6) < 1e-9)
```
Keep caches and generated code out of the project, and restore the setting afterwards. The folder must be a new one: `tempdir` itself is refused.
```matlab
cacheDir = tempname; mkdir(cacheDir);
old = Simulink.fileGenControl('getConfig');
Simulink.fileGenControl('set', 'CacheFolder', cacheDir, 'CodeGenFolder', cacheDir);
restore = onCleanup(@() Simulink.fileGenControl('setConfig', 'config', old));
```
Common library paths: `simulink/Continuous/Integrator`, `simulink/Continuous/Transfer Fcn`, `simulink/Discrete/Unit Delay`, `simulink/Discrete/Discrete-Time Integrator`, `simulink/Lookup Tables/1-D Lookup Table`, `simulink/Sources/Constant`, `simulink/Sinks/To Workspace`, `simulink/Math Operations/Sum`.
Save with `save_system(model, fullfile(folder, model))`. Read compiled port data only after `set_param(model, 'SimulationCommand', 'update')`.

| Symptom | Usual cause | Fix |
|---|---|---|
| model or block not found | wrong name, folder not on path | `load_system(fullfile(folder, model))`, check the exact library path |
| `add_line` fails | port already connected, wrong port number | use `'Block/1'` syntax; `delete_line` first |
| undefined variable in a block parameter | value only in the base workspace | `in.setVariable(...)` or the model workspace |
| algebraic loop warning or error | direct feedthrough in a loop | add `Unit Delay` or `Memory`, or reformulate |
| `slprj/` or `.slxc` files appear | cache in the project folder | `Simulink.fileGenControl` as above |
