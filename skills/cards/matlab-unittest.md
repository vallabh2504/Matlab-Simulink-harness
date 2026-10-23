## Card: MATLAB tests (matlab.unittest)
A function-based test file. Its name must end in `Test` or start with `test`.
```matlab
% file: tests/scaleSignalTest.m
function tests = scaleSignalTest
tests = functiontests(localfunctions);
end

function setupOnce(testCase)
here = fileparts(mfilename('fullpath'));            % runtests changes pwd to tests/
testCase.applyFixture(matlab.unittest.fixtures.PathFixture(fullfile(here, '..', 'src')));
end

function testScales(testCase)
verifyEqual(testCase, scaleSignal([1 2], 2), [2; 4], 'AbsTol', 1e-12);
end

function testRejectsNaN(testCase)
verifyError(testCase, @() scaleSignal([1 NaN], 2), 'demo:invalidInput');
end
```
```matlab
% file: src/scaleSignal.m
function y = scaleSignal(x, gain)
if ~isnumeric(x) || ~isvector(x) || any(~isfinite(x))
    error('demo:invalidInput', 'x must be a finite numeric vector.');
end
y = gain .* x(:);
end
```
Run it so a failure gives a non-zero exit code (the harness reads the exit code):
```matlab
results = runtests('tests');
disp(table(results));
assertSuccess(results);
```
From a shell: `matlab -batch "results = runtests('tests'); assertSuccess(results)"`.

Rules:
- Assert only what the requirements state. If the contract gives no identifier for a case (for example a missing argument, where MATLAB throws `MATLAB:minrhs`), do not assert a custom one.
- Oracles come from outside the implementation: closed forms, a reference written from the equations, conservation, step refinement. Never paste the implementation's own output in as the expected value.
- Use `RelTol` for values that scale and `AbsTol` near zero. Cover every contract error identifier with `verifyError`.
- `runtests` runs each test with the test folder as the current folder: build paths from `mfilename('fullpath')`, not `pwd`. `PathFixture` restores the path afterwards; do not `cd` or `addpath` permanently in a test.
