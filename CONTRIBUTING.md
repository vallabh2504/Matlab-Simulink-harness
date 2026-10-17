# Contributing

Thank you for helping. Please open an issue first for large changes.

## Running the tests

```powershell
python -m unittest discover -s tests/python -v
python scripts/validate_skills.py
```

For changes to MATLAB helpers, examples or Simulink behaviour, also run the MATLAB
verification from MATLAB with a new output folder:

```matlab
addpath('scripts');
verify_matlab(fullfile(tempdir, 'engineering_verification'));
```

Add a regression test for each defect you fix.

## Skills

Each skill in `skills/` needs a narrow trigger, prerequisites, concrete operations,
good and bad examples, a verification step and explicit failure behaviour. Keep skills
short: they are loaded into an agent's context. `validate_skills.py` must pass.

## Graders

The graders in `tests/matlab/graders` are independent of the examples they grade.
Do not change a grader to make an answer pass. If a grader is wrong, show the
mathematical evidence in the pull request and re-run the grader calibration tests.

## Pull requests

- Keep one source of truth: the wheel's resources are generated from the repository
  folders at build time, so do not edit copies.
- Do not commit personal paths, keys, licensed MathWorks files or build outputs.
- Describe what you tested, including the MATLAB release and operating system.
