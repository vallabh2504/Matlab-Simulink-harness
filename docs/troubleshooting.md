# Troubleshooting

| Symptom | Diagnosis and repair |
| --- | --- |
| preflight blocked | Supply actual MATLAB path/license; inspect captured startup diagnostics and required products. |
| built-in API reported missing | Use `which` or `exist(name,'builtin')`; `exist(name,'file')` alone misses `sim` and `new_system`. |
| Stateflow entitlement true but no chart API | Product is absent. Treat unsupported; do not report a chart test pass. |
| `Name is nonexistent or not a directory` warning at MATLAB start | A MATLAB MCP server left a temporary path in your MATLAB path. It is harmless for the harness; remove it from your own startup configuration if you like. This package does not change MATLAB startup files. |
| `Reviewer did not inspect current artifact snapshot` | The review's `snapshot_digest` is not the current one. Use the `snapshot_digest` from a fresh reviewer packet or from `snapshot`, not the requirements hash. If files changed after the review, review again. |
| model name/dirty/running collision | Save or isolate user work. Helpers reject collisions rather than discard changes. |
| `Stale check` or `Review is stale` after a configure command | Check plans, probe runners and the property plan are part of the reviewed snapshot. Set them all up before the first `run-check`, then run the checks again and create a fresh reviewer packet. |
| probe cannot find project code | MATLAB runs a reviewer probe from its scratch directory. Reach the project with `addpath(fullfile('..','..','..','src'))`. |
| stale review/evidence | Re-run meaningful checks and obtain review of the current snapshot. Do not edit hashes to force acceptance. |
| lock remains after interruption | Inspect its token and the previous process. Explicit recover-lock requires confirmation the process stopped; age/PID alone is insufficient. |
| unreadable/corrupt lock | Original operation errors are preserved and the unknown lock remains. Inspect stopped processes and authoritative project state before manually repairing an owned lock record. A successful mutation may already be committed when cleanup reports failure; do not blindly repeat it. |
| another orchestrator owns project | Read resume. Stop/coordinate the previous owner before explicit recover-owner, with recorded reason. |
| revised test command rejected | Check names preserve original argv; version the name after revise and declare all new obligations before first acceptance. |
| skills link installed but not discovered | Restart the host in the intended project; check canonical target and actual discovery. CLI presence does not prove skill support. |
| reviewer/runtime quota | Preserve interrupted work and negative outcome. Use available independent runtime or mark checkpoint blocked; never label self-review independent. |

Record the failed command, exit status, release/runtime, source snapshot and repair.
Do not suppress mandatory failures or silently narrow approved requirements.
