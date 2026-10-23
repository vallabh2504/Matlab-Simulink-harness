## Card: parameters and provenance
Keep parameters in one function or file, with units in the name or the comment and a source for each:
```matlab
p = defaultParameters();
assert(p.R0_ohm > 0 && p.C_F > 0)

function p = defaultParameters()
p.R0_ohm  = 0.012;    % ohmic resistance, ohm; datasheet table 3 at 25 degC
p.C_F     = 2400;     % RC capacitance, F; fitted from a pulse test
p.T_ref_K = 298.15;   % reference temperature, K; definition
end
```
- Pass parameters as arguments (a struct is fine). Do not use `global`, `evalin('base', ...)` or `assignin`.
- Simulink: give values with `Simulink.SimulationInput.setVariable` or the model workspace, not the base workspace. Use `Simulink.Parameter` or a data dictionary only when the task needs shared, typed data.
- Convert units once, at the boundary (degC to K, % to fraction, mAh to C) and name the converted field.
- Validate physical domains (resistance > 0, 0 <= SOC <= 1) with the identifier the contract names.
- A value without a source is an assumption. Write it in the handoff list of assumptions.
