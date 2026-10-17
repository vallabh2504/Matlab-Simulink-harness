# Installation

## Requirements

| Requirement | Notes |
| --- | --- |
| Python 3.10 or newer | Only the standard library is used at run time. |
| MATLAB | Your own installed and licensed copy. Tested on Windows with R2026a. |
| Simulink | Needed only for Simulink tasks and the Simulink examples. |
| An AI agent runtime | Any agent you already use (Codex CLI, Claude Code, Antigravity CLI or another). Task packets work with any of them; automatic launching is built in for Antigravity CLI and Codex CLI, and other agents can be wrapped. |
| Git | Only for installing from source. |

No MathWorks products, provider credentials or background services are bundled.

## Option 1: run from source (recommended)

```powershell
git clone https://github.com/vallabh2504/Matlab-Simulink-harness.git
cd Matlab-Simulink-harness
python matlab_harness.py --help
```

No installation step is needed. Keep the whole checkout together, because the skills
refer to the shared docs, examples and MATLAB helpers.

## Option 2: install the wheel

Download `matlab_engineering_harness-0.3.0-py3-none-any.whl` from the
[0.3.0 release](https://github.com/vallabh2504/Matlab-Simulink-harness/releases/tag/v0.3.0),
then check the download against `SHA256SUMS.txt` from the same release:

```powershell
Get-FileHash .\matlab_engineering_harness-0.3.0-py3-none-any.whl -Algorithm SHA256
```

On macOS or Linux, run `sha256sum -c SHA256SUMS.txt --ignore-missing`. Then install
the wheel into a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --no-deps .\matlab_engineering_harness-0.3.0-py3-none-any.whl
.venv\Scripts\matlab-harness --help
```

On macOS or Linux, use `.venv/bin/` instead of `.venv\Scripts\`. The wheel contains the
skills, MATLAB helpers, examples and docs, so it works without a source checkout.
After this install, use `matlab-harness` wherever this guide shows
`python matlab_harness.py`.

## Option 3: editable install for development

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
```

The `matlab-harness` command then runs from your checkout, so your edits take effect
immediately.

## Point the harness at MATLAB

The harness finds `matlab` on your `PATH`. If it is not on the `PATH`, pass the
executable each time with `--matlab`, or set it once:

```powershell
$env:MATLAB_HARNESS_MATLAB = 'C:\Program Files\MATLAB\R2026a\bin\matlab.exe'
```

Then check the installation:

```powershell
python matlab_harness.py preflight
```

Preflight starts MATLAB in batch mode and prints a JSON report. `"status": "VERIFIED"`
lists the detected MATLAB capabilities (such as Simulink and Stateflow) and which agent
runtimes are on the `PATH`. `"status": "UNSUPPORTED"` includes the MATLAB diagnostic
and a suggested fix.

## Make the skills visible to your agent

Run this once for each engineering project:

```powershell
python matlab_harness.py install-skills --target ..\my-project --runtime codex
python matlab_harness.py install-skills --target ..\my-project --runtime claude
```

`codex` links the skills into `my-project\.agents\skills`; `claude` links them into
`my-project\.claude\skills`. The links point back to this installation, so keep it in
place. With the wheel, they point inside the virtual environment: after recreating
the environment, run `install-skills` again in each project. On Windows the links
are directory junctions, which need no administrator rights.
The command refuses to replace links that already exist and never touches
your global skill folders. Restart the agent in that project, then confirm that it
lists the `engineering-*` skills.

Optional: the MATLAB MCP server lets an agent run MATLAB code interactively. The
harness does not need it, because checks run through `matlab -batch`.

## Verify the MATLAB side (optional)

From MATLAB, in the source checkout:

```matlab
addpath('scripts');
verify_matlab(fullfile(tempdir, 'engineering_verification'));
```

Or, without opening MATLAB:

```powershell
matlab -batch "addpath('scripts'); verify_matlab(fullfile(tempdir, 'engineering_verification'))"
```

This runs the bundled engineering examples against independent oracles, inspects
the saved Simulink model and exports the figures. It needs Simulink and takes several
minutes. Use a new output folder each time. The run prints some `Warning:` blocks
from deliberately faulty test models; it has succeeded when it ends with the
`MATLAB_HARNESS_VERIFIED` and `MATLAB_HARNESS_MODEL_REVISION_VERIFIED` lines.

To run the Python test suite:

```powershell
python -m unittest discover -s tests/python
```

## Update

- Source checkout: `git pull`.
- Wheel: install the newer wheel into the same virtual environment.

Keep existing projects on the version that created them unless the change log says
the project record format is compatible.

## Uninstall

1. Delete the skill links that `install-skills` created: the `engineering-*` entries
   in the project's `.agents\skills` or `.claude\skills`. Delete only the links, not
   their targets:
   - Windows: `cmd /c rmdir .claude\skills\engineering-matlab-numerics` for each link.
     Do not use `Remove-Item -Recurse` or Explorer's delete on a junction; they can
     delete the skill files it points to.
   - macOS or Linux: `rm .claude/skills/engineering-matlab-numerics` (no trailing slash).
2. Delete the virtual environment, or run `pip uninstall matlab-engineering-harness`.
3. Delete the source checkout.

Your engineering projects keep their records in their own `.matlab-harness` folders.
