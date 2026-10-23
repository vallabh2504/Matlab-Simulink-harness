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

The evidence record embeds each stream whole up to 256 KiB. Past that it embeds the
first 64 KiB, cut back to the last full line. Then it embeds up to 30 error lines and
10 warning lines from the omitted middle, with the errors first, and then the last
192 KiB. A marker names the raw file that holds the full stream. `output_bytes`
gives each stream's full size and `truncated` says whether anything was cut.

The 256 KiB limit applies to the raw bytes. The JSON can be larger, because escaping
expands non-ASCII text. A middle line longer than 4 KiB is scanned in pieces.
Acceptance never reads the embedded text: it uses the status, the exit code, the
command and the snapshot.

A hard-killed harness leaves its mutation lock behind, but the check process it
started can keep running. Its pid is stored only in that check's
`evidence/<id>-started.json`. The lock refusal and `recover-lock` both list every check
that has a STARTED record and no terminal record. Confirm those processes have
stopped before you start another check against shared MATLAB resources.

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
