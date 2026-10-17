function modelPath = buildOscillatorModel(p, outputDir)
% Bootstrap canonical helpers; preserve direct callers' path and cwd.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
previousPath = path;
pathCleanup = onCleanup(@() path(previousPath)); %#ok<NASGU>
addpath(fullfile(root,'matlab'));
modelPath = engineering.withRuntime(@() executeBuild(p,outputDir));
end

function modelPath = executeBuild(p, outputDir)
%BUILDOSCILLATORMODEL Save an inspectable model of m*xddot+c*xdot+k*x=F.
% All parameters live in the saved model workspace. Root outputs are x [m]
% and v [m/s]. Names are unique; existing files/models are never overwritten.
validateOscillatorParameters(p);
assert((ischar(outputDir) && isrow(outputDir)) || (isstring(outputDir) && isscalar(outputDir)), ...
    'engineering:OutputDirectory','Output directory must be a text scalar.');
outputDir = char(outputDir);
assert(~isempty(which('new_system')) && license('test','Simulink'), ...
    'engineering:SimulinkUnavailable', 'Installed and licensed Simulink is required.');
if ~isfolder(outputDir)
    mkdir(outputDir);
end
[ok, folderInfo] = fileattrib(outputDir); %#ok<FILEATTRIB> Compatible native absolute-path resolution.
assert(ok, 'engineering:OutputDirectory', 'Cannot resolve output directory.');
outputDir = folderInfo.Name;
% tempname uses platform facilities; guard MATLAB namespace as well as disk.
while true
    [~, uniquePart] = fileparts(tempname(outputDir));
    modelName = matlab.lang.makeValidName(['engineering_oscillator_' uniquePart]);
    modelPath = fullfile(outputDir, [modelName '.slx']);
    if ~bdIsLoaded(modelName) && exist(modelName,'file') == 0 && ~isfile(modelPath)
        break
    end
end
cleanup = engineering.runtimeSession(@() closeOwned(modelName));
new_system(modelName);
set_param(modelName, 'Solver','ode45', 'SolverType','Variable-step', ...
    'RelTol','1e-8', 'AbsTol','1e-10', 'StopTime','10', ...
    'SaveTime','on', 'TimeSaveName','tout', 'SaveOutput','on', ...
    'OutputSaveName','yout', 'SaveFormat','StructureWithTime', ...
    'ReturnWorkspaceOutputs','on');
modelWorkspace = get_param(modelName,'ModelWorkspace');
parameterNames = {'mass','stiffness','damping','force','initialDisplacement','initialVelocity'};
for index = 1:numel(parameterNames)
    parameterName = parameterNames{index};
    modelWorkspace.assignin(parameterName, double(p.(parameterName)));
end
add_block('simulink/Sources/Constant', [modelName '/Applied force'], ...
    'Value','force','Position',[35 90 100 120]);
subsystem = [modelName '/Mechanical dynamics'];
add_block('built-in/Subsystem',subsystem,'Position',[150 65 335 170]);
add_block('simulink/Ports & Subsystems/In1',[subsystem '/Force N'],'Position',[25 53 55 67]);
add_block('simulink/Math Operations/Sum',[subsystem '/Net force'], ...
    'Inputs','+--','Position',[105 45 130 90]);
add_block('simulink/Math Operations/Gain',[subsystem '/Inverse mass'], ...
    'Gain','1/mass','Position',[170 48 235 82]);
add_block('simulink/Continuous/Integrator',[subsystem '/Velocity'], ...
    'InitialCondition','initialVelocity','Position',[285 48 315 82]);
add_block('simulink/Continuous/Integrator',[subsystem '/Displacement'], ...
    'InitialCondition','initialDisplacement','Position',[380 48 410 82]);
add_block('simulink/Math Operations/Gain',[subsystem '/Damping force'], ...
    'Gain','damping','Orientation','left','Position',[210 135 275 165]);
add_block('simulink/Math Operations/Gain',[subsystem '/Spring force'], ...
    'Gain','stiffness','Orientation','left','Position',[210 200 275 230]);
add_block('simulink/Ports & Subsystems/Out1',[subsystem '/Displacement m'], ...
    'Port','1','Unit','m','Position',[480 53 510 67]);
add_block('simulink/Ports & Subsystems/Out1',[subsystem '/Velocity m_per_s'], ...
    'Port','2','Unit','m/s','Position',[480 103 510 117]);
add_line(subsystem,'Force N/1','Net force/1','autorouting','on');
add_line(subsystem,'Net force/1','Inverse mass/1','autorouting','on');
add_line(subsystem,'Inverse mass/1','Velocity/1','autorouting','on');
add_line(subsystem,'Velocity/1','Displacement/1','autorouting','on');
add_line(subsystem,'Velocity/1','Damping force/1','autorouting','on');
add_line(subsystem,'Damping force/1','Net force/2','autorouting','on');
add_line(subsystem,'Displacement/1','Spring force/1','autorouting','on');
add_line(subsystem,'Spring force/1','Net force/3','autorouting','on');
displacementLine = add_line(subsystem,'Displacement/1','Displacement m/1','autorouting','on');
velocityLine = add_line(subsystem,'Velocity/1','Velocity m_per_s/1','autorouting','on');
set_param(displacementLine,'Name','displacement_m');
set_param(velocityLine,'Name','velocity_m_per_s');
add_block('simulink/Ports & Subsystems/Out1',[modelName '/Displacement m'], ...
    'Port','1','Unit','m','Position',[405 83 435 97]);
add_block('simulink/Ports & Subsystems/Out1',[modelName '/Velocity m_per_s'], ...
    'Port','2','Unit','m/s','Position',[405 133 435 147]);
add_line(modelName,'Applied force/1','Mechanical dynamics/1','autorouting','on');
add_line(modelName,'Mechanical dynamics/1','Displacement m/1','autorouting','on');
add_line(modelName,'Mechanical dynamics/2','Velocity m_per_s/1','autorouting','on');
set_param(modelName,'SimulationCommand','update');
save_system(modelName,modelPath);
clear cleanup;
end

function closeOwned(name)
if bdIsLoaded(name), close_system(name,0); end
end
