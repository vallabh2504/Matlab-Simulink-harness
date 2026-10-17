# Change log

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
