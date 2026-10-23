# Using the harness from your agent host

The harness does not run a model. Your agent host does: OpenCode, Codex, Claude Code,
or anything else that can call an MCP server or run a shell command. The model can be
a hosted one or a local one that your host is set up to use. The harness keeps the
project record, runs the declared MATLAB checks, and decides whether a checkpoint can
be accepted.

There are two ways to connect:

- **MCP.** The host starts `matlab-harness mcp` and the model calls its tools.
- **Shell.** The model (or you) runs `matlab-harness` commands directly.

Both write the same project record, so you can switch between them.

## MCP server

```
matlab-harness --project <project folder> mcp --owner <your name>
```

`--project` is the engineering project folder (the one `start` created), not the
harness folder. The host runs this command itself, so `matlab-harness` must be on
the PATH the host sees; otherwise give the full path to the installed command. It
speaks MCP over stdio and needs only the Python standard library. Tools:

| Tool | What it does |
|---|---|
| `harness_status` | Current checkpoint, what is blocking it, check status, next action. Call it first. |
| `harness_packet` | The prompt for one role (`builder`, `reviewer`, `repair`) at the current checkpoint. |
| `harness_run_check` | Runs one declared check and returns its status with the key MATLAB error lines. |
| `harness_run_probe` | Executes a reviewer scratch script with an approved runner and returns a bound receipt. |
| `harness_run_semantics` | Runs approved required property calibration and intended-defect checks. |
| `harness_mutation` | Plants small defects in copies of the source and runs the configured test check on each. |
| `harness_submit_review` | Submits a reviewer's answer to its packet. Returns the gate result, or the problem to fix. |
| `harness_record_repair` | Records the start of a repair round (uses one unit of the repair budget). |
| `harness_accept` | Accepts the checkpoint. Refused until checks pass, the reviewer accepts and no serious finding is open. |

Include the host's actual tool definitions in its declared context allowance; the
tool list is not free context. A refused action comes back as text
starting with `Refused:`, so the model can read it and fix the cause.

### Claude Code

```
claude mcp add matlab-harness -- matlab-harness --project . mcp --owner me
```

or in `.mcp.json`:

```json
{"mcpServers": {"matlab-harness": {"command": "matlab-harness",
  "args": ["--project", ".", "mcp", "--owner", "me"]}}}
```

### Codex

In `~/.codex/config.toml`:

```toml
[mcp_servers.matlab-harness]
command = "matlab-harness"
args = ["--project", ".", "mcp", "--owner", "me"]
```

Codex can also use a local model through its `model_providers` setting. See the Codex
documentation for your version.

### OpenCode

In `opencode.json`:

```json
{"mcp": {"matlab-harness": {"type": "local", "enabled": true,
  "command": ["matlab-harness", "--project", ".", "mcp", "--owner", "me"]}}}
```

OpenCode can use a local model through an OpenAI-compatible provider entry.

## The review must come from a separate session

A reviewer that remembers writing the code will defend it. Give the reviewer packet to
a new session: a new chat, a subagent, or a second host. The harness cannot check
which model or session wrote a report. It records the session ID and model name you
pass, always as `host-reported`, whatever the report says. So through a host, nothing
stops one session from reviewing its own work: keeping the sessions apart is your
job. Its own `agy` and `command` adapters record what the runtime reports instead,
refuse a reviewer session that also built, and label a reviewer that uses the same
model as the builder `same-model-separate-session`.

A host answer is self-attested. If the project has a reviewer runtime configured (any
adapter other than `manual`), the gate does not accept a self-attested review in
place of one the runtime ran.

A submitted answer meets the same rules as a runtime review: a traceability row with
evidence for every requirement before ACCEPT, and at implementation, verification and
handoff at least one probe saved in the scratch directory named in the reviewer packet.

## The loop for one checkpoint

1. `harness_status` (or `matlab-harness next`).
2. Builder: `harness_packet role=builder`, give the prompt to the builder session.
3. Checks: `harness_run_check` for each declared check.
4. At implementation or verification, optionally `harness_mutation`. Its survivors go
   into the next reviewer packet.
5. Reviewer: `harness_packet role=reviewer`, give it to a separate session, then
   `harness_submit_review` with its answer (and the `packet_id` the packet returned).
6. If the gate refuses: `harness_record_repair`, `harness_packet role=repair`, then
   back to step 3.
7. `harness_accept`.

## Shell equivalents

```
matlab-harness --project . next
matlab-harness --project . packet --role reviewer
matlab-harness --project . run-check --owner me public-smoke
matlab-harness --project . mutation --owner me
matlab-harness --project . answer --owner me answer.json --reviewer-session s2 --model my-model
matlab-harness --project . accept --owner me implementation
```

`answer` reads a project-relative JSON file and binds it to the newest reviewer packet
for the current checkpoint, or to the one `--packet` names. It is refused if the files
changed since that packet was made; ask for a new packet. Each answer is kept as its
own file in the packet directory, so a later answer never overwrites an earlier one.

`review` is different: it takes a complete review record (identity, independence,
snapshot digest and all) that you, the operator, attest. Use it for a human review or
a record you produced yourself; use `answer` for anything a reviewer agent wrote. The
harness cannot tell who typed a command, so an agent with a shell could run `review`
itself and claim any independence. Keep `review` for the operator.

## What the reviewer has to write

The reviewer answers its packet. The harness records the checkpoint, the snapshot,
the reviewer identity and every earlier finding's identity.

```json
{"verdict": "REJECT",
 "findings": [{"id": "N-1", "severity": "MAJOR", "artifact": "src/f.m:42",
               "evidence": "p1.m: f(0) returned 1, requirement says 0",
               "repair": "clamp before the lookup"}],
 "traceability": {"R-1": {"status": "FAILED", "evidence": "p1.m", "finding_ids": "N-1"},
                  "R-2": {"status": "VERIFIED", "evidence": "p2.m: f(5)=5"}},
 "independent_checks": [{"id": "P1", "command": "matlab -batch p1", "observed": "f(0)=1",
                         "result": "FAIL", "artifact": "p1.m"}],
 "open_items": {"F-1": {"status": "CLOSED", "evidence": "p3.m: f(1,2) == 3 on current files"},
                "A-3f09c2d1": {"status": "STILL_OPEN", "evidence": "p4.m: f(3,1) is still 1"}}}
```

- `verdict`: `ACCEPT`, `REJECT` or `INCOMPLETE`. A `REJECT` needs a blocking reason: an
  open `CRITICAL` or `MAJOR` finding, a `FAILED` requirement, an open item it does not
  close, or something the gate refuses whatever the review says (a declared check or
  semantic adequacy that has not passed, an earlier checkpoint's blocking finding, a
  handoff obligation). Without one it is refused as protocol, so the reviewer can answer
  `ACCEPT` with its `MODERATE` and `MINOR` findings open or raise a severity with evidence.
  At requirements, a finding on `requirements.md` is carried to the design whatever its
  severity, so it is no blocking reason there, nor is a `FAILED` row that names only such
  findings: keep it `OPEN`, name it in a `PARTIAL` row and `ACCEPT`.
- `contract_text` and `design_text` (on a finding or an open-item answer): after
  requirements, a `CRITICAL` or `MAJOR` finding on `requirements.md` stays open only with
  both, the exact sentences of the contract and of the design's own text that conflict.
  The design is then repaired; the work stops for the user only once the design writes
  `USER QUESTION <id>:`.
- `findings` are the reviewer's new findings only. `severity` is `CRITICAL`, `MAJOR`,
  `MODERATE` or `MINOR`. A new finding that happens to reuse an earlier ID gets a new
  one (`F-1-r2`), so it can never close or replace the earlier finding, and no new
  finding ever gets an ID shaped like an `A-` handle.
- `traceability` has one entry per requirement ID. A list of rows with a
  `requirement` field is accepted too.
- `open_items` answers what the packet lists under "Open items", by handle: `CLOSED`,
  `STILL_OPEN` or `NOT_CHECKED`, each with evidence. An earlier finding's handle is
  its own ID. A serious claim from an answer that was not imported has a handle that
  starts with `A-`; the packet lists the probe scripts the attempts that made it left
  behind, so a new session can re-run them.
- At implementation, verification and handoff, `CLOSED` evidence (or an optional
  `probe` field next to it) names the proof: the scratch file that an independent check
  with result `PASS` ran, with its suffix (`p3.m`), or that check's ID when the ID is
  compound (`CHK-ORACLES`, `P1`) and is no handle, requirement or finding ID. A scratch
  file no passing check ran proves nothing, and neither does `src/p3.m`: a relative
  artifact path names the project's own file first. A new finding the reviewer marks
  `CLOSED` needs the same proof in its closure, or it stays `OPEN`. ACCEPT is refused until
  every item marked `blocks_acceptance` (and every `A-` item) is `CLOSED`. `STILL_OPEN`
  keeps the item open and blocking.
- Independence is set by the channel: `host-reported` for an answer from a host,
  `same-model-separate-session` or `independent-agent` for a launched reviewer. An
  answer can lower it (`"independence": "sequential-role-pass"`), never raise it.

### How a loose answer is read

The harness reads an answer as the weakest claim it could mean, and says what it
assumed in the `notes` of the result. It refuses only what it will not guess, and a
refusal ends with how the answer was read. IDs and handles that differ only in case
are the same ID.

| The answer has | Read as |
|---|---|
| a value written alone, in any case or markup, or `high`/`low`, `pass`/`fail`, `fixed`, `rejected` | that value (`MAJOR`, `MINOR`, `VERIFIED`, `FAILED`, `CLOSED`, `REJECT`) |
| a value with more text: `REJECT - see findings`, `ACCEPT (if F-2 is fixed)`, `Closed?` | the weakest value it names; `ACCEPT`, `CLOSED`, `VERIFIED` and `PASS` count only written alone |
| a value written twice: two answers in one reply, `traceability` and `trace`, `status` and `result` | as weak as any copy says; every finding of every copy is kept |
| a severity label: `[Low] typo`, `P1: crash`, `high priority`, `Minor/Major` | the most severe severity of the label |
| a severity in more text: `Major (proven)`, `MINOR (could be CRITICAL)` | the most severe one it names; none named is `MAJOR`, and refused |
| `priority` or `level` in a finding | its severity |
| `issues`, `defects` or `problems` for findings; `checks`; `trace` | that part |
| the answer inside a key or a list (`{"review": {...}}`), or inside text or a code fence | the answer inside |
| findings as a list, one object, an object keyed by ID or by severity, or lines of text (`"F-1 (MAJOR): f(3,1) overflows"`) | one finding each; `None`, `n/a`, `There are no findings.` are none |
| `location`, `description`, `fix` in a finding | `artifact`, `evidence`, `repair` |
| traceability or open items as an object, a list of rows, or lines of text (`"R-1: VERIFIED by p1.m"`) | the requirement or handle each names first, or the only one it names (`F1` is `F-1`); the rest of a line is its status |
| no `kind`, `status`, `impact`, `closure` or `repair` | `POTENTIAL DEFECT`, `OPEN`, "not stated by reviewer" |
| no row for a requirement | `UNVERIFIED`, not assessed |
| two rows for one requirement | one row with the weaker status |
| an open item it did not answer, or answered without evidence | `NOT_CHECKED` |
| `CLOSED` at an executed checkpoint without naming its proof | `NOT_CHECKED` |
| the same claim as an open `A-` item, as a new finding | that item, `STILL_OPEN` |
| `checkpoint`, `snapshot_digest`, `model` or session fields | ignored; the harness records its own |
| any other field | ignored, and named in the notes |

Refused: a verdict or severity it cannot read, ACCEPT with an open item or a
requirement not verified, no probe of the reviewer's own at an executed checkpoint, and
an answer too large to read whole (more than 100000 values in its findings or checks).
When an answer is refused, its CRITICAL and MAJOR findings (a severity it could not
read counts as MAJOR) become open `A-` items for the next reviewer. The same happens
when a reviewer run does not finish after it returned an answer (timeout, dropped
stream), when the runtime did not report the reviewer's model, and when a reviewer
changed scoped files or `requirements.md`. In that last case the harness also puts
back the files it reviewed, removes what the reviewer added, and keeps the
reviewer's versions under `execution/reviewer-changes`. A run that only failed in
transport does not count as a protocol attempt. If the harness cannot put the files
back (the reviewer also changed the kept copies, or the disk refused), it records the
run, keeps both copies and holds every dispatch until someone inspects it.

## Keeping prompts small

Set `context_budget` (tokens) in the runtime configuration. The packet is the role
text, up to three short skill cards, and the current task. If it does not fit, the
harness drops cards first, then shortens finding text, then shortens the task detail.
`packet.json` records the estimate (characters / 4) and what was trimmed. The fixed
role text comes first, so a host that caches prompt prefixes can reuse it across calls.

```json
{"adapter": "manual", "context_budget": 8000,
 "mutation": {"check": "own-tests", "count": 6, "stages": ["verification"]}}
```

`mutation.check` names a declared check that runs the project's own tests. When that
check is a single `matlab -batch` expression, all mutants run in one MATLAB session,
which avoids paying MATLAB's start-up time for each one.
