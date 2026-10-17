# MATLAB Engineering Harness

Make your AI coding agent do MATLAB and Simulink work the way an engineering team
would: agree on the requirements first, test everything in real MATLAB, and have a
second agent check the result before anything counts as done.

## Why use it

AI agents write MATLAB quickly, and they are rarely unsure of themselves. Ask one for
a cooling model and you get a script that runs, a plot that looks reasonable and a
confident summary. Whether the physics is right, the units are consistent or the
original requirement was met is something you still have to find out yourself.

The harness does that checking for you:

- **You agree on "done" up front.** Before any code is written, each requirement is
  written down with its units, where it came from and how it will be checked. Work
  starts only after you approve it.
- **Real MATLAB runs decide what passes.** A stage is accepted only after your
  MATLAB checks have run on the latest version of the files and passed. If a file
  changes afterwards, the old result no longer counts.
- **A second agent reviews the work.** The reviewer runs in a separate session from
  the builder. From implementation onward it must write its own tests rather than
  rerun the builder's, and it reports on every requirement.
- **Problems go back for repair, within limits.** When the reviewer or the checks
  find a problem, a repair agent gets exactly that list to fix. You decide how many
  repair attempts are allowed and how long the whole job may take.

Everything is saved in the project folder: requirements, approvals, test results and
reviews. You can stop at any point, and a new session, or a different agent, carries
on from where the last one stopped. The included MATLAB helpers also keep your setup
clean when your checks use them: Simulink caches and generated code go to temporary
folders, your MATLAB path and settings are restored, and models you have open with
unsaved changes are not touched.

It works with the agent you already use (Claude Code, Codex CLI, Antigravity CLI or
another) and your own MATLAB installation. It is plain Python with no extra
packages, no server and no account.

### Is it right for you?

It is a good fit when the result has to be right and you need to show why: models,
simulations, calibrations, control code, and changes to existing Simulink models.

It adds steps on purpose. For a quick plot or a one-off script, asking your agent
directly is faster.

## How it works

A project moves through five checkpoints. Each one has to be accepted before the
next one starts.

```mermaid
flowchart TD
    req["1. Requirements"] -- "you approve,<br/>reviewer accepts" --> arch["2. Architecture"]
    arch -- "reviewer accepts<br/>the design" --> impl["3. Implementation"]
    impl -- "checks pass,<br/>reviewer accepts" --> ver["4. Verification"]
    ver -- "checks pass,<br/>reviewer accepts" --> hand["5. Handoff"]
    hand -- "final gate passes" --> done(["Project complete"])
```

Inside every checkpoint, the same loop runs. The harness is the coordinator: it gives
each agent its task, runs MATLAB, and decides whether the checkpoint passes.

```mermaid
flowchart TD
    start(["Checkpoint starts"]) --> build["Builder agent<br/>does the work for this stage"]
    build --> checks["Harness runs your MATLAB checks<br/>on the current files"]
    checks --> review["Reviewer agent, in a separate session,<br/>reads the work and runs its own tests"]
    review --> gate{"Checks passed,<br/>reviewer says ACCEPT,<br/>no serious problems open?"}
    gate -- yes --> accept(["Accepted, on to the next checkpoint"])
    gate -- no --> budget{"Repair attempts<br/>left?"}
    budget -- yes --> repair["Repair agent<br/>fixes only the reported problems"]
    repair --> checks
    budget -- no --> you(["Stops and asks you"])
```

At the requirements checkpoint, the builder only drafts `requirements.md`; nothing
moves on until you approve it. MATLAB checks are optional for requirements and
architecture and required from implementation onward. At handoff, a document in your
project, such as a README or report, must list every requirement ID with its
evidence.

The harness also stops and asks you whenever it can't carry on by itself: when a
checkpoint has no MATLAB checks yet, when MATLAB can't run a check, or when the
reviewer rejects the work without saying what to fix. Repair attempts are counted
across the whole project (ten by default).

| Who | Role |
| --- | --- |
| You | Write and approve the requirements, supply the MATLAB checks, and answer when the harness asks. |
| Harness | Keeps the project record, hands out tasks, runs the checks and applies the gate. |
| Builder agent | Writes the design, the MATLAB code or Simulink model, and the verification. |
| Reviewer agent | Looks for what is wrong. It must be a different session from the builder. |
| Repair agent | Fixes the specific problems the reviewer or the checks found. |
| MATLAB | Runs the checks. Every result is saved with the files it tested. |

The agents never talk to each other directly. The harness writes each one a task file
and reads back what it produced, so every handover is saved in the project folder.

## What you need

- Python 3.10 or newer.
- Your own licensed MATLAB. Developed on Windows with MATLAB R2026a.
- Simulink, only if your project uses Simulink.
- An AI coding agent.

## Install

```powershell
git clone https://github.com/vallabh2504/Matlab-Simulink-harness.git
cd Matlab-Simulink-harness
python matlab_harness.py preflight --matlab "C:\Program Files\MATLAB\R2026a\bin\matlab.exe"
```

Use the path to your own MATLAB. If preflight prints `"status": "VERIFIED"`, the
harness can start MATLAB and you are ready.

You can also install it as a package from the
[latest release](https://github.com/vallabh2504/Matlab-Simulink-harness/releases/latest),
which gives you a `matlab-harness` command. The [installation guide](docs/install.md)
covers that, plus setting the MATLAB path once, updating and uninstalling.

## Quick start

This walks through one project by hand, so you can see each step. The commands use
PowerShell on Windows; on macOS or Linux, write paths with `/` (for example
`../cooling-study`). If you installed the package, type `matlab-harness` instead of
`python matlab_harness.py`.

1. **Create a project.** This makes a new folder with a project record and starter
   files. Existing files are never overwritten.

   ```powershell
   python matlab_harness.py start ..\cooling-study --title "Cooling study" --builder my-builder-session --owner me --scope src --brief "Predict lumped cooling of a part"
   ```

   `--owner` is your name for yourself in the record. `--builder` is any name for the
   agent session that does the work; the reviewer's session must have a different
   name. `--scope` is the folder the agents may change.

2. **Connect the skills to your agent.** This gives your agent the five MATLAB and
   Simulink skills that come with the harness.

   ```powershell
   python matlab_harness.py install-skills --target ..\cooling-study --runtime claude
   ```

   Use `--runtime codex` for Codex CLI.

3. **Write and approve the requirements.** Edit `requirements.md` in the project
   folder, then add each requirement and record your approval:

   ```powershell
   python matlab_harness.py --project ..\cooling-study requirement --owner me --id TH-1 --text "Temperature follows the lumped energy balance" --acceptance "Matches the analytic solution within 1e-6 K" --source "project brief" --units K
   python matlab_harness.py --project ..\cooling-study approve --owner me --actor me --source "approved in review meeting"
   ```

4. **Ask what comes next.** At any point, this tells you the current checkpoint and
   what is still missing:

   ```powershell
   python matlab_harness.py --project ..\cooling-study next
   ```

5. **Give the builder its task.** For the requirements checkpoint you have already
   written the requirements, so skip to step 7.

   ```powershell
   python matlab_harness.py --project ..\cooling-study packet --role builder
   ```

   This prints the path of a `prompt.md` file under `.matlab-harness\packets\`. Open
   your agent in the project folder and give it that file.

6. **Tell the harness how to test the work.** From implementation onward, a
   checkpoint needs at least one MATLAB check. Save a `checks.json` in the project
   folder that names each check and the command that runs it:

   ```json
   {"cooling-check": ["matlab", "-batch", "addpath('src'); addpath('checks'); runCoolingCheck"]}
   ```

   Use the full path to `matlab.exe` if `matlab` is not on your PATH. Register the
   plan for the checkpoint, then run each check after the builder has finished:

   ```powershell
   python matlab_harness.py --project ..\cooling-study configure-checks implementation --owner me --plan checks.json
   python matlab_harness.py --project ..\cooling-study run-check cooling-check --owner me
   ```

7. **Have a second agent review it.** Run the step 5 command with `--role reviewer`
   and give the new `prompt.md` to a *different* agent session. Save the reviewer's
   JSON report in the project folder as `review.json`. The reviewer fills in the
   verdict, the findings and the `snapshot_digest` from its task file. You add the
   first three fields, which say who did the review. `independence` is
   `independent-agent` for another AI session, or `external-human` for a person:

   ```json
   {"reviewer_session": "id-of-the-reviewer-session",
    "model": "model-the-reviewer-ran-on",
    "independence": "independent-agent",
    "checkpoint": "requirements", "verdict": "ACCEPT",
    "snapshot_digest": "the snapshot_digest from the reviewer task file",
    "findings": []}
   ```

   Then import the report and accept the checkpoint:

   ```powershell
   python matlab_harness.py --project ..\cooling-study review requirements review.json --owner me
   python matlab_harness.py --project ..\cooling-study accept requirements --owner me
   ```

   The [tutorial](docs/tutorial.md) shows a complete review report.

8. **If the reviewer rejects the work,** run the step 5 command with `--role repair`,
   give that file to the builder, then run the checks and the review again.

Repeat steps 5 to 8 for each checkpoint until `next` reports the project complete.

## Let the harness run the agents

Once you are comfortable with the steps, the harness can launch the agents and run
the whole loop for you. It has built-in launchers for Antigravity CLI (`agy`) and
[Codex CLI](docs/codex-cli-adapter.md), and a `command` launcher for any other
program you wrap. With Claude Code, keep using the task files from the quick start, or
wrap it with `command`.

Save a `runtime.json` in the project folder:

```json
{"adapter": "agy",
 "roles": {"builder": {"model": "your-builder-model"},
           "reviewer": {"model": "your-reviewer-model"},
           "repair": {"model": "your-builder-model"}}}
```

Then start the run:

```powershell
python matlab_harness.py --project ..\cooling-study configure-runtime --owner me --config runtime.json --repair-budget 10
python matlab_harness.py --project ..\cooling-study journey --owner me --ceiling 14400
```

`--repair-budget` is the number of repair attempts for the whole project, and
`--ceiling` is the time limit for the whole job, in seconds. Whenever the harness
needs you, for example to approve requirements or to supply a check plan, it stops,
saves everything and tells you what it needs. Run the same `journey` command again to
continue.

Agents launched this way can't ask you for permission while they work. If you are
happy for them to use their tools unattended, add `"skip_permissions": true` to
`runtime.json`. To connect another agent, see [runtimes](docs/runtimes.md).

## Commands

| Command | What it does |
| --- | --- |
| `start` | Creates a project. |
| `requirement`, `approve` | Adds requirements and records your approval. |
| `next`, `status`, `resume` | Shows where the project stands and what to do next. |
| `packet` | Writes a task file for the builder, reviewer or repair agent. |
| `configure-checks`, `run-check` | Registers MATLAB checks for a checkpoint and runs them. |
| `review`, `accept` | Imports a review report and accepts a checkpoint. |
| `configure-runtime`, `journey` | Sets up the agent launcher and runs every checkpoint automatically. |
| `execute` | Runs one role through the configured launcher. |
| `gate handoff` | Exits with code 0 only when the whole project is complete. Useful in scripts. |
| `skills` | Suggests which skills fit a task. |
| `install-skills` | Connects the skills to Claude Code or Codex CLI. |
| `preflight` | Checks that MATLAB can be started. |

Run `python matlab_harness.py <command> --help` to see a command's options.

## What is in this repository

| Path | Contents |
| --- | --- |
| `matlab_harness.py` | Runs the harness straight from this folder, without installing. |
| `src/matlab_harness/` | The harness itself (Python). |
| `matlab/+engineering/` | MATLAB helpers for code and model checks and for clean Simulink sessions. |
| `skills/` | Five agent skills: MATLAB numerics, requirements, results verification, review and Simulink. |
| `adapters/` | Short role instructions for the builder and the reviewer. |
| `docs/` | Guides: installation, tutorial, launchers, troubleshooting and more. |
| `docs/standards/` | The engineering standards the reviewer checks against. |
| `examples/` | Worked examples: heat conduction, calibration, cooling, an oscillator model and a Simulink model revision. |
| `scripts/` | MATLAB setup check (`verify_matlab.m`), skill validation and launcher scripts. |
| `tests/` | Python tests, and MATLAB tests with independent graders for the examples. |
| `pyproject.toml` | Package settings for the installable version. |
| `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE` | Release notes, how to contribute, and the MIT license. |

## Documentation

- [Installation](docs/install.md)
- [Worked tutorial](docs/tutorial.md)
- [Agent launchers](docs/runtimes.md) and [how a role run works](docs/runtime-protocol.md)
- [Codex CLI launcher](docs/codex-cli-adapter.md)
- [Running all checkpoints automatically](docs/journey-runner.md) and [recovering an interrupted run](docs/journey-recovery.md)
- [How checks are run and recorded](docs/run-check-lifecycle.md)
- [Revising a saved Simulink model](docs/model-revision.md)
- [Simulink temporary files](docs/runtime-files.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Change log](CHANGELOG.md)

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for how
to run the tests and the rules for skills and graders.

## License

[MIT](LICENSE) © 2026 S V V Sai Sri Vallabh Pataneni.

MATLAB and Simulink are products of The MathWorks, Inc. and are not included; you
need your own licenses. This project is not affiliated with or endorsed by MathWorks.
