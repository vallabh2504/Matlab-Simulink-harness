# Native-check lifecycle and evidence

`Project.run_check` executes a predeclared argument list with `shell=False` while
holding the project mutation lock. A command must perform its verification in
the foreground and wait for its writers before exiting. A zero parent exit alone
does not establish that background or remote work finished.

Each current invocation writes file-backed stdout/stderr, a STARTED record with
its PID, and a terminal evidence record with the command, source snapshot, output,
raw-file hashes and cleanup observations. File-backed output avoids waiting on a
pipe retained by a descendant after the direct child has stopped. A missing
executable produces BLOCKED evidence and is not execution success.

Timeouts attempt to stop the owned Windows PID tree or POSIX process group through
the same helper used for command roles. They remain BLOCKED even when the root is
observed stopped. Keyboard interruption records BLOCKED evidence and then propagates
after the project record is committed. Unknown descendants or remote cancellation
are not relabelled stopped. Inspect the actual receipt before recovering ownership
or starting another command against shared MATLAB resources.

An unexpected storage exception can stop the tracked process while leaving only raw
output, without a terminal receipt; recovery must inspect that incomplete state.

A check must wait for its own writers. Background writers that outlive a PASSED
check can later change files or raw output and make the snapshot stale. Do not configure an
asynchronous launcher as a completed verification check. Use a foreground wrapper
that observes the real work, declare shared resources, and retain task-specific
source/model review. Project hashes and ownership records are integrity checks
for trusted operators, not an OS sandbox or a universal cancellation guarantee.
