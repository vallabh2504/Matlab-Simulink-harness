function r = simulateOscillator(p, t)
% Bootstrap canonical helpers; preserve direct callers' path and cwd.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
previousPath = path;
pathCleanup = onCleanup(@() path(previousPath)); %#ok<NASGU>
addpath(fullfile(root,'matlab'));
r = engineering.withRuntime(@() executeSimulation(p,t));
end

function r = executeSimulation(p, t)
%SIMULATEOSCILLATOR Run real Simulink dynamics on requested time samples.
% Temporary model/data files are owned by this call. No base workspace use.
validateOscillatorParameters(p);
validateattributes(t, {'numeric'}, {'real','finite','vector','nonempty','nonnegative'});
t = double(t(:));
assert(t(1) == 0 && all(diff(t) > 0), 'engineering:OscillatorTime', ...
    'Time must start at zero and be strictly increasing.');
runDirectory = tempname;
mkdir(runDirectory);
cleanup = engineering.runtimeSession(@() finishSimulation(runDirectory));
modelPath = buildOscillatorModel(p,runDirectory);
[~,modelName] = fileparts(modelPath);
load_system(modelPath);
simulationTimes = t;
if isscalar(t)
    simulationTimes = [0; 1e-6];
end
naturalTime = sqrt(p.mass / p.stiffness);
maximumStep = min(max(diff(simulationTimes)), naturalTime/50);
simInput = Simulink.SimulationInput(modelName);
simInput = simInput.setModelParameter('StartTime','0', ...
    'StopTime',sprintf('%.17g',simulationTimes(end)), ...
    'OutputOption','SpecifiedOutputTimes', 'OutputTimes',mat2str(simulationTimes.',17), ...
    'MaxStep',sprintf('%.17g',maximumStep));
simOutput = sim(simInput);
loggedOutput = simOutput.get('yout');
loggedTime = loggedOutput.time;
assert(numel(loggedOutput.signals) == 2, 'engineering:OscillatorOutputs', 'Expected displacement and velocity root outputs.');
% SpecifiedOutputTimes uses solver interpolation; interp1 accommodates roundoff
% in logging time and keeps the interface tied to the caller's exact grid.
r.time = t;
r.displacement = interp1(loggedTime,loggedOutput.signals(1).values,t,'pchip');
r.velocity = interp1(loggedTime,loggedOutput.signals(2).values,t,'pchip');
r.solver = 'ode45';
r.parameters = p;
r.source = 'Simulink root Outports, StructureWithTime';
assert(all(isfinite(r.displacement)) && all(isfinite(r.velocity)), ...
    'engineering:OscillatorNonfinite', 'Simulation produced nonfinite or missing samples.');
finishSimulation(runDirectory);
clear cleanup;
end

function finishSimulation(runDirectory)
if ~isfolder(runDirectory), return; end
assert(startsWith(runDirectory,tempdir), 'engineering:CleanupScope', ...
    'Refuse cleanup outside the allocated temporary directory.');
files = dir(fullfile(runDirectory,'*.slx'));
for index = 1:numel(files)
    [~,name] = fileparts(files(index).name);
    if bdIsLoaded(name) && strcmpi(get_param(name,'FileName'),fullfile(runDirectory,files(index).name))
        close_system(name,0);
    end
end
rmdir(runDirectory,'s');
end
