## Card: MATLAB numerics
Validate at the API boundary with the identifier the contract names, then compute vectorised.
```matlab
y = scaleSignal([1 2 3], 2);                 % returns the column [2; 4; 6]
try
    scaleSignal([1 NaN], 2);
catch err
    assert(strcmp(err.identifier, 'demo:invalidInput'))
end

function y = scaleSignal(x, gain)
if ~isnumeric(x) || ~isvector(x) || any(~isfinite(x))
    error('demo:invalidInput', 'x must be a finite numeric vector.');
end
y = gain .* x(:);
end
```
Exact zero-order-hold update of a first-order RC branch (any dt, no Euler error):
```matlab
tau = 10; R = 0.02; dt = [0.1 0.5 2]; i = [1 1 1]; v = 0;
for k = 1:numel(dt)
    a = exp(-dt(k) / tau);
    v = a * v + R * (1 - a) * i(k);
end
```
Table lookup: build the interpolant once, clamp queries per axis, never call interp1/interp2 per sample.
```matlab
soc = [0 0.5 1]; T = [263 298 318]; R0 = [3 2 1.5; 2 1.2 1; 1.8 1 0.9];   % rows: soc, columns: T
F = griddedInterpolant({soc, T}, R0, 'linear', 'nearest');
q = F(min(max([0.2 1.4], 0), 1), min(max([250 300], 263), 318));
```
Linear algebra: `x = A \ b`, never `inv(A) * b`; check `rcond(A)` and report it. Least squares: `x = A \ b` (QR) or `lsqminnorm`; avoid normal equations. ODEs: `ode45` non-stiff, `ode15s` stiff, set `RelTol`/`AbsTol` with `odeset` and justify them.

| Symptom | Usual cause | Fix |
|---|---|---|
| `MATLAB:sizeDimensionsMustMatch` | row and column mixed | `x = x(:)` at the boundary |
| `MATLAB:badsubscript` | off-by-one, empty input | check `numel` before indexing |
| NaN in output | 0/0, log(0), query outside the grid | guard, clamp, `isfinite` checks |
| 1M samples take minutes | lookup or growth inside the loop | preallocate, hoist the interpolant, vectorise |
| results differ by 1e-15 | operation order | compare with a tolerance, not `==` |
