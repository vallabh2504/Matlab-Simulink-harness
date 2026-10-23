# Change log

## 0.4.0 - 2026-10-24

- Reviewers answer their task file instead of filling in a full review record. Each
  open item has a short handle (a finding ID, or `A-` and eight characters for a claim
  from an answer that was not imported), and the reviewer answers it CLOSED or
  STILL_OPEN with evidence. The harness writes the record. New `answer` command;
  `review` still imports a complete record you attest.
- Answers are read the way agents actually write them: any case, common synonyms,
  lists, objects or lines of text, inside a wrapper or a code fence. Anything unclear
  is read as the weaker claim, so a hedged ACCEPT is never read as acceptance.
- MCP server: `matlab-harness mcp --owner <id>` lets OpenCode, Codex, Claude Code or
  another host drive one project, with a hosted or local model. See
  [using the harness from your agent host](docs/hosts.md).
- Smaller prompts: short skill cards go inside the task file, `context_budget` trims a
  task file that would not fit, and MATLAB output is cut down to the lines a repair
  needs (the full output stays in the evidence files).
- New projects need independent probes that the harness itself runs, from
  implementation onward (`configure-probes`, `run-probe`). A PASS label without an
  execution receipt does not count.
- Required property checks: approve a plan of named defective variants with
  `configure-semantics` and run it with `run-semantics` before verification and
  handoff. See [evidence assurance](docs/evidence-assurance.md).
- Optional mutation probe (`runtime.mutation`, or `matlab-harness mutation`) plants
  small defects in copies and reports the ones the tests miss to the next reviewer.
- A question about what the approved `requirements.md` means, raised at requirements,
  no longer pauses the project. The design answers it by ID at architecture. A serious
  conflict must quote both sentences; the design is repaired, and the project pauses
  for you only when the design writes `USER QUESTION <id>:`.
- A review answer that could not be read is kept as an open gap until it is replaced,
  and its serious claims still block acceptance. Interrupted probe and property-check
  runs can be recovered explicitly.
- A reviewer's edits to scoped files or `requirements.md` are moved aside and the
  reviewed files are restored.

## 0.3.0 - 2026-10-17

First public release.

- Five-checkpoint workflow: requirements, architecture, implementation, verification
  and handoff, with explicit approval, evidence gates and independent review.
- Adversarial reviewer charter. Reviewers write and run their own probes in a scratch
  folder, keep a per-requirement trace and carry earlier findings forward.
- Builder and repair prompts tell agents not to assert behaviour that the requirements
  leave open.
- Journey runner that drives all five checkpoints through a configured runtime, with
  a total time ceiling, bounded repair and recovery after interruption.
- Runtime adapters: manual task packets (default), Antigravity CLI, a generic command
  adapter and a Codex CLI wrapper.
- Project record integrity: a sealed record, protected support files outside the
  agent's scope, and handoff obligations that must be met before handoff.
- On Windows, role processes run inside a Job Object that is closed when the role ends.
- Five engineering skills, selected per task instead of listed in full.
- Compact role prompts suited to smaller models.
- MATLAB helpers for clean Simulink sessions, model inspection and source checks.
- Worked MATLAB and Simulink examples with independent graders.
- MIT license.
