## Card: running and debugging MATLAB from a shell
Run non-interactively. An uncaught error exits with code 1:
`matlab -batch "addpath('src'); results = runtests('tests'); assertSuccess(results)"`.
Print the full error and stack, then fail:
```matlab
try
    error('demo:example', 'Example failure at step %d.', 3);
catch err
    report = getReport(err, 'extended', 'hyperlinks', 'off');
    assert(contains(report, 'Example failure'))
end
```
Debugging steps: reproduce with the smallest input; print sizes (`size(x)`), classes and the first non-finite index (`find(~isfinite(x), 1)`); compare with a hand calculation for one or two samples; fix the cause in the owned file; keep the failing case as a regression test.

| Message or identifier | Usual cause | Fix |
|---|---|---|
| `MATLAB:UndefinedFunction` / "Unrecognized function" | folder not on the path, typo, or the file name differs from the function name | `addpath(fullfile(pwd, 'src'))`; the file name must equal the function name |
| `MATLAB:minrhs` / "Not enough input arguments" | called with fewer arguments | check the call site; validate only what the contract requires |
| `MATLAB:TooManyInputs` | extra argument | match the signature |
| `MATLAB:badsubscript` / "Index exceeds" | off-by-one, empty array | check `numel`; MATLAB indexing starts at 1 |
| `MATLAB:sizeDimensionsMustMatch` | row and column vectors mixed | reshape with `x(:)` |
| `MATLAB:m_missing_operator` / parse error | syntax error, a missing `end` | run `checkcode('file.m')` |
| shadowed function | a file with the same name earlier on the path | `which -all name` |
| `MATLAB:license:checkout` | toolbox not licensed | use a base-MATLAB alternative |
| test passes locally but fails in batch | depends on the current folder or the base workspace | build paths from `fileparts(mfilename('fullpath'))` |

Never edit a test to match a wrong result. If the contract is unclear, report it instead of guessing.
