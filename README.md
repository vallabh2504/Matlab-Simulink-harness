# MATLAB Engineering Harness

Evidence-gated MATLAB and Simulink engineering workflows for AI coding agents.

The harness gives an AI agent a disciplined way to do MATLAB, numerical and Simulink
work. A project moves through five checkpoints: requirements, architecture,
implementation, verification and handoff. Each checkpoint is accepted only when an
independent reviewer agrees, and from implementation onward only when real MATLAB
checks also pass against the current files.
Everything is recorded in the project folder, so any later session can pick up exactly
where the last one stopped.

It works with the agent you already use (Codex CLI, Claude Code, Antigravity CLI or
another), on top of your own MATLAB installation.

## Contents

- [Why use it](#why-use-it)
- [Requirements](#requirements)
- [Install](#install)
- [Quick start](#quick-start)
- [How a project runs](#how-a-project-runs)
- [What is in this repository](#what-is-in-this-repository)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## Why use it

- **Requirements first.** Requirements and architecture are written, approved by you
  and reviewed before the agent builds anything consequential. Each requirement has a
  stable ID, units, a source and an acceptance check.
- **Evidence gates.** Acceptance needs executable checks that actually ran against the
  current files. A failed check, out-of-date evidence or an open critical or major
  finding blocks the checkpoint.
- **Independent, adversarial review.** The reviewer must be a different agent session
  from the builder. It writes and runs its own probes instead of only re-running the
  builder's tests, and it keeps a requirement-by-requirement trace.
- **Bounded repair.** Rejected work goes back for repair with the reviewer's findings,
  under a repair budget and time limits that you set.
- **Continuation.** The project record holds requirements, approvals, checks, reviews,
  ownership and open findings. `resume` gives a fresh session the full picture.
- **Clean MATLAB and Simulink runs.** Helpers keep Simulink cache and code generation
  in temporary folders, restore your MATLAB path and settings, and leave your unsaved
  models alone.
- **Focused skills.** Five engineering skills, loaded only when a task needs them.
- **Compact prompts.** Role prompts stay small, so smaller and lower-cost models are
  not flooded with context.
- **No lock-in.** Python standard library only. There is no server, no telemetry and
  nothing to sign up for.

## Requirements

- Python 3.10 or newer.
- Your own licensed MATLAB. It has been tested on Windows with R2026a.
- Simulink, for Simulink tasks only.
- An AI agent runtime of your choice.

## Install

```powershell
git clone https://github.com/vallabh2504/Matlab-Simulink-harness.git
cd Matlab-Simulink-harness
python matlab_harness.py preflight --matlab "C:\Program Files\MATLAB\R2026a\bin\matlab.exe"
```

Use the path to your own MATLAB executable. Preflight prints `"status": "VERIFIED"` when
it can start MATLAB.

You can also install the wheel from the
[latest release](https://github.com/vallabh2504/Matlab-Simulink-harness/releases/latest)
into a virtual environment, which gives you a `matlab-harness` command. The
[installation guide](docs/install.md) covers the wheel, setting the MATLAB path once,
connecting the skills to your agent, updating and uninstalling.

## Quick start

The examples use the source launcher, `python matlab_harness.py`. With the wheel, type
`matlab-harness` instead. Commands are shown for PowerShell on Windows; on macOS or Linux,
write paths with `/` (for example `../cooling-study`).

1. **Start a project.** This creates the project record without overwriting any
   existing files.

   ```powershell
   python matlab_harness.py start ..\cooling-study --title "Cooling study" --builder my-builder-session --owner me --scope src --brief "Predict lumped cooling of a part"
   ```

2. **Connect the skills to your agent.**

   ```powershell
   python matlab_harness.py install-skills --target ..\cooling-study --runtime claude
   ```

   Use `--runtime codex` for Codex CLI.

3. **Write and approve the requirements.** Edit `requirements.md` in the project, then
   register each requirement and record your approval:

   ```powershell
   python matlab_harness.py --project ..\cooling-study requirement --owner me --id TH-1 --text "Temperature follows the lumped energy balance" --acceptance "Matches the analytic solution within 1e-6 K" --source "project brief" --units K
   python matlab_harness.py --project ..\cooling-study approve --owner me --actor me --source "approved in review meeting"
   ```

4. **See what is next.**

   ```powershell
   python matlab_harness.py --project ..\cooling-study next
   ```

5. **Hand work to an agent.** Create a task packet for the builder role:

   ```powershell
   python matlab_harness.py --project ..\cooling-study packet --role builder
   ```

   The output names a `prompt.md` file under `.matlab-harness\packets\`. Give that file
   to your agent.

6. **Review and accept.** When the builder is done, create a packet with
   `--role reviewer` and give it to a *different* agent session. Save the reviewer's
   JSON report in the project folder as `review.json`. The reviewer fills in the
   verdict, findings and the `snapshot_digest` printed in its packet. You add three
   identity fields that the reviewer cannot vouch for itself:

   ```json
   {"reviewer_session": "id-of-the-reviewer-session",
    "model": "model-the-reviewer-ran-on",
    "independence": "independent-agent",
    "checkpoint": "requirements", "verdict": "ACCEPT",
    "snapshot_digest": "the snapshot_digest from the reviewer packet",
    "findings": []}
   ```

   The [tutorial](docs/tutorial.md) shows a full report. Then import it (the path is
   relative to the project folder) and accept the checkpoint:

   ```powershell
   python matlab_harness.py --project ..\cooling-study review requirements review.json --owner me
   python matlab_harness.py --project ..\cooling-study accept requirements --owner me
   ```

   Repeat steps 5 and 6 for each checkpoint.

To let the harness launch the agents itself, save a `runtime.json` in the project
folder and run the whole journey. The built-in launch adapters are `agy`
(Antigravity CLI), the [Codex CLI wrapper](docs/codex-cli-adapter.md) and `command`
(any program you wrap). For Claude Code and other agents, use the packets from
steps 5 and 6, or wrap the agent with `command`.

```json
{"adapter": "agy",
 "roles": {"builder": {"model": "your-builder-model"},
           "reviewer": {"model": "your-reviewer-model"},
           "repair": {"model": "your-builder-model"}}}
```

```powershell
python matlab_harness.py --project ..\cooling-study configure-runtime --owner me --config runtime.json
python matlab_harness.py --project ..\cooling-study journey --owner me --ceiling 14400
```

`--ceiling` is the total time limit in seconds. The journey stops and tells you
whenever it needs your input, such as an approval or a check plan. When the
harness launches the agents, the agent's permission prompts have nobody to answer
them; add `"skip_permissions": true` only if you accept unattended tool use. To connect a
different agent, see [runtimes](docs/runtimes.md); the
[worked tutorial](docs/tutorial.md) walks through one project from start to handoff.

## How a project runs

```text
requirements -> architecture -> implementation -> verification -> handoff
     |               |                |                 |             |
  approve       review/accept   checks + review   checks + review   gate
```

| Command | What it does |
| --- | --- |
| `start` | Creates the project record and starter files. |
| `requirement`, `approve` | Registers requirements and records your approval. |
| `configure-checks` | Declares the executable checks for a checkpoint. |
| `packet` | Writes a task for the builder, reviewer or repair agent. |
| `execute`, `journey` | Runs one role, or every checkpoint, through a configured runtime. |
| `run-check` | Runs a declared check and keeps its output as evidence. |
| `review`, `accept` | Imports a reviewer's report and accepts a checkpoint. |
| `next`, `status`, `resume` | Shows where the project stands. |
| `gate handoff` | Exits with code 0 only when the project is complete. |
| `skills` | Suggests skills for a task description. |
| `preflight` | Checks the MATLAB installation. |

Run `python matlab_harness.py <command> --help` for each command's options.

## What is in this repository

| Path | Contents |
| --- | --- |
| `matlab_harness.py` | Source launcher; runs the CLI without installing. |
| `src/matlab_harness/` | The Python package: CLI, project record, workflow, journey runner, runtime adapters and skill selection. |
| `matlab/+engineering/` | MATLAB helpers: capability detection, source and model checks, model inspection and clean Simulink sessions (`engineering.withRuntime`). |
| `skills/` | Five agent skills: MATLAB numerics, requirements modeling, results verification, review continuity and Simulink engineering. |
| `adapters/` | Short role instructions for the workflow and the reviewer. |
| `docs/` | Guides: installation, tutorial, runtimes, journey runner, recovery and troubleshooting. |
| `docs/standards/` | Engineering standards for MATLAB, Simulink, results and reviews. |
| `examples/` | Worked MATLAB and Simulink examples: 1-D heat conduction, weighted calibration, cooling, an oscillator model and model revision. |
| `scripts/` | MATLAB verification (`verify_matlab.m`), skill validation, the journey wrapper and a Codex CLI adapter. |
| `tests/python/` | Python test suite. |
| `tests/matlab/` | MATLAB tests and the independent graders for the examples. |
| `pyproject.toml` | Package metadata for building and installing the wheel. |
| `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE` | Release notes, contribution guide and the MIT license. |

## Documentation

- [Installation](docs/install.md)
- [Worked tutorial](docs/tutorial.md)
- [Runtimes and adapters](docs/runtimes.md) and the [role execution protocol](docs/runtime-protocol.md)
- [Codex CLI adapter](docs/codex-cli-adapter.md)
- [Journey runner](docs/journey-runner.md) and [journey recovery](docs/journey-recovery.md)
- [Check lifecycle](docs/run-check-lifecycle.md)
- [Revising a saved Simulink model](docs/model-revision.md)
- [Simulink runtime files](docs/runtime-files.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Change log](CHANGELOG.md)

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
test commands and the rules for skills and graders.

## License

[MIT](LICENSE) © 2026 S V V Sai Sri Vallabh Pataneni.

MATLAB and Simulink are products of The MathWorks, Inc. and are not included; they
need their own licenses. This project is not affiliated with or endorsed by MathWorks.
