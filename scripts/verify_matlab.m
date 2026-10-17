function report = verify_matlab(outputDirectory)
%VERIFY_MATLAB Execute independent engineering/calibration and helper checks.
% Invoke from a clean MATLAB -batch child. Outputs use relative portable paths.
root = fileparts(fileparts(mfilename('fullpath')));
if nargin < 1
    outputDirectory = fullfile(root,'results',['verification_' char(datetime('now','Format','yyyyMMdd_HHmmss_SSS'))]);
end
assert(~isfolder(outputDirectory) || isempty(dir(fullfile(outputDirectory,'*.json'))), ...
    'engineering:VerificationOutput','Use a fresh output directory; evidence is not overwritten.');
if ~isfolder(outputDirectory), mkdir(outputDirectory); end
oldPath = path;
restorePath = onCleanup(@() path(oldPath));
addpath(fullfile(root,'matlab'),fullfile(root,'examples','engineering-core'), ...
    fullfile(root,'tests','matlab','graders'));
runtimeCleanup = engineering.runtimeSession([],oldPath);
clear restorePath;
addpath(fullfile(root,'matlab'),fullfile(root,'examples','engineering-core'), ...
    fullfile(root,'tests','matlab','graders'));
report.environment = engineering.capabilities();
runtimeRegression = runtests(fullfile(root,'tests','matlab','testRuntimeSession.m'));
assertSuccess(runtimeRegression);
assert(~any([runtimeRegression.Incomplete]),'engineering:SkippedRuntime','Runtime isolation regression skipped.');
report.runtimeIsolation = struct('name',{runtimeRegression.Name}, ...
    'passed',num2cell([runtimeRegression.Passed]),'failed',num2cell([runtimeRegression.Failed]), ...
    'incomplete',num2cell([runtimeRegression.Incomplete]));
calibration = runtests(fullfile(root,'tests','matlab','graders'));
assertSuccess(calibration);
assert(~any([calibration.Incomplete]),'engineering:SkippedCalibration','Calibration was skipped, not verified.');
cleanupRegression = runtests(fullfile(root,'tests','matlab','testInspectionCleanup.m'));
assertSuccess(cleanupRegression);
assert(~any([cleanupRegression.Incomplete]),'engineering:SkippedCleanup','Cleanup regression skipped.');
report.cleanupRegressionPassed = all([cleanupRegression.Passed]);
revisionRegression = runtests(fullfile(root,'tests','matlab','testModelRevision.m'));
assertSuccess(revisionRegression);
assert(~any([revisionRegression.Incomplete]),'engineering:SkippedRevision','Model revision regression skipped.');
report.modelRevisionRegression = struct('name',{revisionRegression.Name}, ...
    'passed',num2cell([revisionRegression.Passed]),'failed',num2cell([revisionRegression.Failed]), ...
    'incomplete',num2cell([revisionRegression.Incomplete]));
report.calibration = struct('name',{calibration.Name},'passed',num2cell([calibration.Passed]), ...
    'failed',num2cell([calibration.Failed]),'incomplete',num2cell([calibration.Incomplete]));
report.engineering = evaluateEngineeringCandidate(fullfile(root,'examples','engineering-core'));
assert(report.engineering.allRequiredPassed,'engineering:EngineeringFailed','Independent engineering assertion failed.');
report.engineering.candidateDirectory = 'examples/engineering-core';
report.source = engineering.checkSource(fullfile(root,'examples','engineering-core'));
for index = 1:numel(report.source.files)
    report.source.files(index).path = strrep(report.source.files(index).path,[root filesep],'');
end
report.sourceDisposition = 'Inspect analyzer recommendations and literal candidates; neither is mathematical acceptance.';
demoDirectory = fullfile(outputDirectory,'demo');
report.demo = runEngineeringDemo(demoDirectory);
modelPath = fullfile(demoDirectory,report.demo.modelFile);
inspection = engineering.checkModel(modelPath,struct('requireSubsystem',true,'expectedRootOutports',2, ...
    'allowUnconnectedPorts',false,'allowedSolvers',{{'ode45'}}));
assert(inspection.mandatoryPassed,'engineering:ModelChecks','Declared model checks failed.');
[~,modelName] = fileparts(modelPath);
assert(~bdIsLoaded(modelName),'engineering:ModelCleanup','Inspection left its owned model loaded.');
inspection.inspection.file = fullfile('demo',report.demo.modelFile);
report.model = inspection;
dependencies = engineering.dependencies(fullfile(root,'examples','engineering-core','simulateOscillator.m'));
for index = 1:numel(dependencies.files)
    dependencies.files{index} = strrep(dependencies.files{index},[root filesep],'');
    dependencies.files{index} = strrep(dependencies.files{index},matlabroot,'<MATLABROOT>');
end
report.dependencies = dependencies;
report.status = 'VERIFIED engineering core and grader calibration';
file = fopen(fullfile(outputDirectory,'matlab-verification.json'),'w');
assert(file ~= -1,'engineering:ReportOutput','Could not write verification report.');
closeFile = onCleanup(@() fclose(file));
fprintf(file,'%s\n',jsonencode(report));
clear closeFile runtimeCleanup restorePath;
fprintf('MATLAB_HARNESS_VERIFIED: %d calibration cases and 4 engineering groups\n',numel(calibration));
fprintf('MATLAB_HARNESS_MODEL_REVISION_VERIFIED: %d native saved-model regression cases\n',numel(revisionRegression));
end
