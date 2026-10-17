function evidence = runModelRevision(outputDirectory)
%RUNMODELREVISION Saved-model edit, readback reconciliation and real regression.
% A new directory is required: source SLX/MAT/JSON artifacts are never overwritten.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
previousPath = path;
restorePath = onCleanup(@() path(previousPath)); %#ok<NASGU>
addpath(fullfile(root,'matlab'),fullfile(root,'examples','engineering-core'));
% Separate function scope guarantees model/cache cleanup before caller path.
evidence = executeRevision(outputDirectory);
end

function evidence = executeRevision(outputDirectory)
assert((ischar(outputDirectory) && isrow(outputDirectory)) || ...
    (isstring(outputDirectory) && isscalar(outputDirectory)), 'engineering:RevisionOutput','Expected output directory.');
outputDirectory = char(outputDirectory);
assert(~isfolder(outputDirectory) && ~isfile(outputDirectory), ...
    'engineering:RevisionOutputExists','Choose a new output directory; artifacts are retained.');
mkdir(outputDirectory);
[resolved,folderInfo] = fileattrib(outputDirectory);
assert(resolved,'engineering:RevisionOutput','Cannot resolve output directory.');
outputDirectory = folderInfo.Name;
p = struct('mass',1.7,'damping',0.43,'stiffness',5.8,'force',0, ...
    'initialDisplacement',0.31,'initialVelocity',-0.22);
t = linspace(0,6,301).';
baselineFile = buildOscillatorModel(p,outputDirectory);
[~,baselineName] = fileparts(baselineFile);
[~,token] = fileparts(tempname(outputDirectory));
revisedName = matlab.lang.makeValidName(['engineering_revision_' token]);
revisedFile = fullfile(outputDirectory,[revisedName '.slx']);
assert(~bdIsLoaded(revisedName) && exist(revisedName,'file') == 0 && ~isfile(revisedFile), ...
    'engineering:RevisionCollision','Revision model name is already owned.');
cleanup = engineering.runtimeSession(@() closeOwned({baselineName,revisedName}));
% The legacy output is obtained BEFORE any edit from the actual saved artifact.
baselineSeries = simulateSaved(baselineFile,t,struct);
changed = p; changed.damping = 0.86;
load_system(baselineFile);
save_system(baselineName,revisedFile,'ErrorIfShadowed',true);
% These are equivalent to changing the model workspace and solver dialog in GUI.
workspace = get_param(revisedName,'ModelWorkspace');
workspace.assignin('damping',changed.damping);
set_param(revisedName,'MaxStep','0.02');
set_param(revisedName,'SimulationCommand','update');
save_system(revisedName,revisedFile);
close_system(revisedName,0);
intent(1) = struct('category','workspace','target','damping','parameter','value', ...
    'before',p.damping,'after',changed.damping);
intent(2) = struct('category','modelParameter','target','<model>','parameter','MaxStep', ...
    'before','auto','after','0.02');
reconciliation = engineering.reconcileModel(baselineFile,revisedFile,intent);
assert(reconciliation.accepted,'engineering:RevisionUnreconciled','Saved changes do not match declared intent.');
revisedSeries = simulateSaved(revisedFile,t,struct);
% Explicit model-workspace override reinstates legacy damping for compatibility.
legacyOverride = simulateSaved(revisedFile,t,struct('damping',p.damping));
stress = changed; stress.mass = 0.8; stress.stiffness = 3.1; stress.force = -0.6;
stressSeries = simulateSaved(revisedFile,t,stress);
baselineError = assertTrajectory(baselineSeries,reference(p,t));
revisionError = assertTrajectory(revisedSeries,reference(changed,t));
legacyError = assertTrajectory(legacyOverride,baselineSeries);
stressError = assertTrajectory(stressSeries,reference(stress,t));
assert(max(abs(revisedSeries(:)-baselineSeries(:))) > 0.01, ...
    'engineering:RevisionNoBehaviorChange','Default damping revision did not change the actual trajectory.');
baselineEnergy = energy(p,baselineSeries);
revisionEnergy = energy(changed,revisedSeries);
energyBound = 1e-7 * max(1,baselineEnergy(1));
assert(all(diff(baselineEnergy) <= energyBound) && all(diff(revisionEnergy) <= energyBound), ...
    'engineering:RevisionEnergy','Unforced passive oscillator gained mechanical energy.');
% SimulationInput overrides must not become persistent saved workspace edits.
afterExecution = engineering.reconcileModel(baselineFile,revisedFile,intent);
assert(afterExecution.accepted && strcmp(afterExecution.revisedSha256,reconciliation.revisedSha256), ...
    'engineering:RevisionPersistentOverride','Scenario execution altered the saved revision.');
evidence = struct('status','PASS','baselineFile',baselineFile,'revisedFile',revisedFile, ...
    'reconciliation',reconciliation,'baselineOracleMaxError',baselineError, ...
    'revisedOracleMaxError',revisionError,'legacyRegressionMaxError',legacyError, ...
    'changedMassForceOracleMaxError',stressError,'timeSamples',numel(t), ...
    'baselineFinalEnergy',baselineEnergy(end),'revisionFinalEnergy',revisionEnergy(end), ...
    'source','Saved/reopened Simulink root outputs, independent augmented matrix exponential and passive energy');
save(fullfile(outputDirectory,'baseline-and-revision-series.mat'),'t','p','changed','stress', ...
    'baselineSeries','revisedSeries','legacyOverride','stressSeries','baselineEnergy','revisionEnergy');
writeJson(fullfile(outputDirectory,'revision-intent.json'),intent);
writeJson(fullfile(outputDirectory,'reconciliation.json'),reconciliation);
writeJson(fullfile(outputDirectory,'model-revision-evidence.json'),evidence);
clear cleanup;
end

function series = simulateSaved(file,t,overrides)
[~,name] = fileparts(file);
assert(~bdIsLoaded(name),'engineering:RevisionLoaded','Fixture execution owns only an unloaded saved model.');
load_system(file);
cleanup = onCleanup(@() closeOwned({name}));
input = Simulink.SimulationInput(name);
input = input.setModelParameter('StartTime','0','StopTime',sprintf('%.17g',t(end)), ...
    'OutputOption','SpecifiedOutputTimes','OutputTimes',mat2str(t.',17));
names = fieldnames(overrides);
for index = 1:numel(names)
    input = input.setVariable(names{index},overrides.(names{index}),'Workspace',name);
end
output = sim(input);
logged = output.get('yout');
assert(numel(logged.signals) == 2 && logged.time(end) >= t(end)-1e-9, ...
    'engineering:RevisionOutputs','Actual root outputs or end time are missing.');
series = [interp1(logged.time,logged.signals(1).values,t,'pchip'), ...
    interp1(logged.time,logged.signals(2).values,t,'pchip')];
assert(isequal(size(series),[numel(t),2]) && all(isfinite(series(:))), ...
    'engineering:RevisionSeries','Invalid real Simulink output shape or values.');
clear cleanup;
end

function series = reference(p,t)
% Independent governing equation with forcing as an augmented constant state.
matrix = [0,1,0; -p.stiffness/p.mass,-p.damping/p.mass,p.force/p.mass; 0,0,0];
initial = [p.initialDisplacement;p.initialVelocity;1];
series = zeros(numel(t),2);
for index = 1:numel(t)
    state = expm(matrix*t(index))*initial;
    series(index,:) = state(1:2).';
end
end

function maximumError = assertTrajectory(actual,expected)
error = abs(actual-expected);
assert(isequal(size(actual),size(expected)) && all(error(:) <= 2e-7+2e-6*abs(expected(:))), ...
    'engineering:RevisionPhysics','Native trajectory violates independent mechanics/regression oracle.');
maximumError = max(error(:));
end

function result = energy(p,series)
result = 0.5*p.mass*series(:,2).^2 + 0.5*p.stiffness*series(:,1).^2;
end

function writeJson(file,value)
handle = fopen(file,'w');
assert(handle ~= -1,'engineering:RevisionEvidence','Cannot write evidence.');
cleanup = onCleanup(@() fclose(handle));
fprintf(handle,'%s\n',jsonencode(value,'PrettyPrint',true));
clear cleanup;
end

function closeOwned(names)
for index = 1:numel(names)
    if bdIsLoaded(names{index}), close_system(names{index},0); end
end
end
