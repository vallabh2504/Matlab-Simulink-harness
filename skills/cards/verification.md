## Card: verification evidence
Each functional requirement needs an oracle the implementation did not produce:
- a closed form or an analytic limit (steady state, zero input, very small dt);
- a reference written separately from the equations;
- a property: conservation, linearity, splitting one run into two gives the same result, monotonicity;
- step refinement with the observed order of accuracy.

```matlab
T = 1; exact = exp(-T);
e1 = abs(eulerDecay(T, 0.01) - exact);
e2 = abs(eulerDecay(T, 0.005) - exact);
p = log2(e1 / e2);                       % about 1 for a first-order method
assert(abs(p - 1) < 0.05)

function y = eulerDecay(T, h)
y = 1;
for k = 1:round(T / h)
    y = y - h * y;
end
end
```
Edges to cover where the contract defines them: zero, a scalar, the first and last sample, exactly at a limit, table ends and beyond, saturation entry and exit, and every error condition with its exact identifier.

Planted defects (mutation): if a small change to the source (such as `<=` to `<`, or a sign flip) leaves every test passing, the tests do not pin down that line. Add a case that fails on the mutant unless the mutant is equivalent, meaning it cannot change any output. If so, say why.

Traceability table for the README or handoff, one row per requirement ID:

| ID | Implementation | Test | Observed |
|---|---|---|---|
| R-1 | `src/model.m:12-30` | `tests/modelTest.m` testStep | max error 2e-13 V |
| R-2 | `src/model.m:8` | `tests/modelTest.m` testBadInput | `demo:invalidInput` raised |

Make the suite run every case and report every failure (collect, then fail once), so one run shows all of them. `runtests` with `assertSuccess` does this; a script collects. A check that must raise a named error identifier (such as a required property assertion) runs first, outside the collection, so its identifier reaches the runner unchanged:
```matlab
assert(abs(sqrt(9) - 3) < 1e-12, 'demo:requiredProperty', 'required property failed')
cases = {@() assert(1 + 1 == 2), @() assert(abs(sqrt(4) - 2) < 1e-12)};
failed = {};
for k = 1:numel(cases)
    try
        cases{k}();
    catch err
        failed{end + 1} = sprintf('case %d: %s', k, err.message); %#ok<AGROW>
    end
end
assert(isempty(failed), 'Failures:\n%s', strjoin(failed, newline))
```

A process exit code alone is not evidence: report the observed numbers next to the expected ones.
