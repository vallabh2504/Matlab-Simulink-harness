# Scientific results, uncertainty and figures

An acceptance plot must be reproducible from raw numerical data and parameters. Label the physical quantity and units on every axis; distinguish model output, reference, measurements and uncertainty. Use scales that expose the claimed behavior. Do not truncate axes or hide boundary/failed cases to make a result look better.

For deterministic synthetic tutorials, record that values are educational assumptions. Do not invent confidence intervals or present solver tolerance as physical uncertainty. If estimating uncertainty, state the observation/noise model, parameter covariance/identifiability assumptions and propagation method; separate model-form error. A clean reference match within tolerance is evidence about the declared mathematical problem, not validation of a real plant.

`runEngineeringDemo(emptyOutputDir)` exports original thermal/mechanical experiments, labeled PNGs, a vector heat PDF, raw CSVs, a saved editable model and metadata. The heat figure compares centered differences to an analytic quadratic; convergence is separately tested with a smooth nonquadratic source. Cooling exports Kelvin and Joules (plots may use kJ explicitly). Mechanics exports position, velocity and energy from a real Simulink run and asserts passive energy decay.

Review plotted variables against exported columns, units and operating conditions. Use readable font sizes, distinct line styles/markers and legends that identify meaning. Configurable IEEE/journal sizes are project presentation requirements, not universal rules. Export vector graphics for line plots when suitable; retain raster where necessary. Close only the figures created by the runner. Aesthetics follow numerical correctness.

Before drawing conclusions, perturb parameters and boundary values; examine convergence, error norm, conditioning and residuals. Use invariant/analytic/metamorphic checks as the evidence, not visual resemblance. A figure showing decreasing cooling temperature can still have the wrong time constant; compare `tau=C/G`, energy `C(T0-T)` and changed C/G, including equilibrium and heating-from-below cases.

Record accepted numeric tolerance and rationale before viewing the candidate. Never loosen it simply to make a failed plot pass. Report absolute/relative error, denominator, sampling and any unsupported scenarios. Preserve failed experiments as negative evidence.
