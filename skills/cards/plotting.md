## Card: figures in batch runs
Draw off screen, label with units, export, and close the figure even after an error:
```matlab
t = linspace(0, 1, 101);
y = sin(2 * pi * t);
f = figure('Visible', 'off');
closer = onCleanup(@() close(f));
plot(t, y, 'LineWidth', 1.5); grid on
xlabel('Time (s)'); ylabel('Voltage (V)'); title('Response to a 1 Hz input');
legend('measured', 'Location', 'best');
out = fullfile(tempdir, 'response.png');
exportgraphics(f, out, 'Resolution', 150);
assert(isfile(out))
```
- Save the numbers behind every figure, for example with `writematrix([t(:) y(:)], 'response.csv')` or `save('response.mat', 't', 'y')`. A picture alone is not evidence.
- Put units in every axis label. State the conditions (parameters, input) in the title or caption.
- Write outputs to the folder the task names, or to the scratch folder, never next to the source.
- Use `tiledlayout` for several axes. Do not depend on screen size or on `figure` focus.
