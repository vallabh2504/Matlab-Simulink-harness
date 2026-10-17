function tests = testModelRevision
tests = functiontests(localfunctions);
end

function setupOnce(testCase)
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
testCase.TestData.previousPath = path;
configuration = Simulink.fileGenControl('getConfig');
testCase.TestData.previousFileGeneration = struct('CacheFolder',configuration.CacheFolder, ...
    'CodeGenFolder',configuration.CodeGenFolder,'CodeGenFolderStructure',configuration.CodeGenFolderStructure);
scratch = tempname; mkdir(scratch);
testCase.TestData.fileGenerationScratch = scratch;
Simulink.fileGenControl('set','CacheFolder',fullfile(scratch,'cache'), ...
    'CodeGenFolder',fullfile(scratch,'codegen'),'createDir',true,'keepPreviousPath',true);
addpath(fullfile(root,'matlab'),fullfile(root,'examples','engineering-core'), ...
    fullfile(root,'examples','model-revision'));
end

function teardownOnce(testCase)
configuration = testCase.TestData.previousFileGeneration;
Simulink.fileGenControl('set','CacheFolder',configuration.CacheFolder, ...
    'CodeGenFolder',configuration.CodeGenFolder,'CodeGenFolderStructure',configuration.CodeGenFolderStructure);
path(testCase.TestData.previousPath);
removeFixture(testCase.TestData.fileGenerationScratch,{});
end

function testExecutedRevisionLegacyAndPhysics(testCase)
directory = tempname;
cleanup = onCleanup(@() removeFixture(directory,{}));
% Unrelated dirty models are not discarded by readback or simulation.
[~,token] = fileparts(tempname);
sentinel = matlab.lang.makeValidName(['engineering_dirty_sentinel_' token]);
new_system(sentinel);
set_param(sentinel,'StopTime','123');
sentinelCleanup = onCleanup(@() closeIfLoaded(sentinel));
evidence = runModelRevision(directory);
verifyEqual(testCase,evidence.status,'PASS');
verifyTrue(testCase,evidence.reconciliation.accepted);
verifyEqual(testCase,numel(evidence.reconciliation.changes),2);
verifyLessThan(testCase,evidence.legacyRegressionMaxError,1e-6);
verifyTrue(testCase,bdIsLoaded(sentinel));
verifyEqual(testCase,get_param(sentinel,'Dirty'),'on');
verifyEqual(testCase,get_param(sentinel,'StopTime'),'123');
verifyTrue(testCase,isfile(fullfile(directory,'baseline-and-revision-series.mat')));
verifyTrue(testCase,isfile(fullfile(directory,'reconciliation.json')));
verifyError(testCase,@() runModelRevision(directory),'engineering:RevisionOutputExists');
clear sentinelCleanup cleanup;
end

function testUnexpectedBlockParameterIsRejected(testCase)
[baseline,revision,directory,names] = fixture;
cleanup = onCleanup(@() removeFixture(directory,names));
load_system(revision);
set_param([names{2} '/Mechanical dynamics/Damping force'],'Gain','2*damping');
save_system(names{2},revision);
close_system(names{2},0);
report = engineering.reconcileModel(baseline,revision,emptyIntent);
verifyFalse(testCase,report.accepted);
verifyTrue(testCase,any(strcmp({report.changes.parameter},'Gain')));
verifyGreaterThan(testCase,report.unexpectedChangeCount,0);
verifyFalse(testCase,bdIsLoaded(names{1}));
verifyFalse(testCase,bdIsLoaded(names{2}));
clear cleanup;
end

function testRootOutputOrderChangeIsRejected(testCase)
[baseline,revision,directory,names] = fixture;
cleanup = onCleanup(@() removeFixture(directory,names));
load_system(revision);
% Simulink reassigns the other root output port when this one becomes 2.
set_param([names{2} '/Displacement m'],'Port','2');
save_system(names{2},revision);
close_system(names{2},0);
report = engineering.reconcileModel(baseline,revision,emptyIntent);
verifyFalse(testCase,report.accepted);
verifyTrue(testCase,any(strcmp({report.changes.parameter},'Port')));
clear cleanup;
end

function testCompiledUnitAndDimensionMetadataIsBound(testCase)
[baseline,revision,directory,names] = fixture;
cleanup = onCleanup(@() removeFixture(directory,names));
load_system(revision);
set_param([names{2} '/Displacement m'],'Unit','cm');
save_system(names{2},revision);
close_system(names{2},0);
inspection = engineering.inspectModel(revision);
output = inspection.blocks(strcmp({inspection.blocks.path},[names{2} '/Displacement m']));
verifyTrue(testCase,isstruct(output.compiledUnits));
verifyFalse(testCase,isfield(output.compiledUnits,'status'),jsonencode(output.compiledUnits));
verifyTrue(testCase,contains(jsonencode(output.compiledUnits),'"cm"'),jsonencode(output.compiledUnits));
verifyTrue(testCase,isfield(output,'compiledDimensions'));
report = engineering.reconcileModel(baseline,revision,emptyIntent);
verifyFalse(testCase,report.accepted);
verifyTrue(testCase,any(strcmp({report.changes.parameter},'PortUnits')));
clear cleanup;
end

function testIncorrectDeclaredBeforeValueDoesNotApprove(testCase)
[baseline,revision,directory,names] = fixture;
cleanup = onCleanup(@() removeFixture(directory,names));
load_system(revision);
workspace = get_param(names{2},'ModelWorkspace');
workspace.assignin('damping',0.9);
save_system(names{2},revision);
close_system(names{2},0);
intent = struct('category','workspace','target','damping','parameter','value','before',0.1,'after',0.9);
report = engineering.reconcileModel(baseline,revision,intent);
verifyFalse(testCase,report.accepted);
verifyFalse(testCase,report.intentMatched);
clear cleanup;
end

function testDirtyTargetIsPreservedAndRejected(testCase)
[baseline,revision,directory,names] = fixture;
cleanup = onCleanup(@() removeFixture(directory,names));
load_system(revision);
set_param(names{2},'StopTime','13');
verifyError(testCase,@() engineering.reconcileModel(baseline,revision,emptyIntent),'engineering:DirtyModel');
verifyTrue(testCase,bdIsLoaded(names{2}));
verifyEqual(testCase,get_param(names{2},'StopTime'),'13');
verifyEqual(testCase,get_param(names{2},'Dirty'),'on');
clear cleanup;
end

function testIdenticalReadbackHasNoInventedChanges(testCase)
[baseline,revision,directory,names] = fixture;
cleanup = onCleanup(@() removeFixture(directory,names));
report = engineering.reconcileModel(baseline,revision,emptyIntent);
verifyTrue(testCase,report.accepted,jsonencode(report.changes));
verifyEmpty(testCase,report.changes);
verifyTrue(testCase,report.baseline.compilationPassed && report.revised.compilationPassed);
clear cleanup;
end

function testWorkspaceClassAndAddedSentinelAreNotOmitted(testCase)
[baseline,revision,directory,names] = fixture;
cleanup = onCleanup(@() removeFixture(directory,names));
load_system(baseline);
workspace = get_param(names{1},'ModelWorkspace');
workspace.assignin('numericProbe',double(0.43));
save_system(names{1},baseline);
close_system(names{1},0);
load_system(revision);
workspace = get_param(names{2},'ModelWorkspace');
workspace.assignin('numericProbe',single(0.43));
workspace.assignin('newMarker',struct('engineeringComparisonPresence','ABSENT'));
save_system(names{2},revision);
close_system(names{2},0);
report = engineering.reconcileModel(baseline,revision,emptyIntent);
verifyFalse(testCase,report.accepted);
verifyTrue(testCase,any(strcmp({report.changes.target},'numericProbe') & strcmp({report.changes.parameter},'class')));
verifyTrue(testCase,any(strcmp({report.changes.target},'newMarker') & strcmp({report.changes.parameter},'value')));
clear cleanup;
end

function testExternalMatWorkspaceBindsNativePathInsteadOfModelFolder(testCase)
[baseline,revision,directory,names] = fixture;
previousPath = path;
restorePath = onCleanup(@() path(previousPath));
cleanup = onCleanup(@() removeFixture(directory,names));
sourceFolder = fullfile(directory,'actual-data'); mkdir(sourceFolder);
[~,token] = fileparts(tempname);
filename = ['engineering_parameters_' token '.mat'];
actualFile = fullfile(sourceFolder,filename);
decoyFile = fullfile(directory,filename);
load_system(baseline);
workspace = get_param(names{1},'ModelWorkspace');
save(workspace,actualFile);
data = load(actualFile); data.damping = 9; save(decoyFile,'-struct','data');
close_system(names{1},0);
addpath(sourceFolder,'-begin');
for index = 1:2
    files = {baseline,revision};
    load_system(files{index});
    workspace = get_param(names{index},'ModelWorkspace');
    workspace.DataSource = 'MAT-File'; workspace.FileName = filename;
    reload(workspace);
    verifyEqual(testCase,getVariable(workspace,'damping'),0.43);
    save_system(names{index},files{index}); close_system(names{index},0);
end
beforeHash = hashFile(actualFile);
report = engineering.reconcileModel(baseline,revision,emptyIntent);
verifyTrue(testCase,report.accepted);
dependency = report.revised.dependencies(strcmp({report.revised.dependencies.kind},'workspaceSource'));
verifyEqual(testCase,numel(dependency),1);
verifyTrue(testCase,strcmpi(dependency.resolvedFile,actualFile),dependency.resolvedFile);
verifyEqual(testCase,dependency.sha256,beforeHash);
verifyNotEqual(testCase,dependency.sha256,hashFile(decoyFile));
[series,time] = nativeSimulation(revision,1);
verifySavedDynamics(testCase,series,time);
verifyEqual(testCase,hashFile(actualFile),beforeHash);
clear restorePath cleanup;
end

function testNativeDictionaryPathAndDirtySharedState(testCase)
[baseline,revision,directory,names] = fixture;
previousPath = path;
restorePath = onCleanup(@() path(previousPath));
cleanup = onCleanup(@() removeFixture(directory,names));
[~,token] = fileparts(tempname);
dictionaryName = [matlab.lang.makeValidName(['engineering_revision_data_' token]) '.sldd'];
dictionaryFile = fullfile(directory,dictionaryName);
dictionary = Simulink.data.dictionary.create(dictionaryFile);
dictionaryCleanup = onCleanup(@() discardOwnedDictionary(dictionary));
addpath(directory,'-begin');
section = getSection(dictionary,'Design Data');
entry = addEntry(section,'dictDamping',0.43); saveChanges(dictionary);
for index = 1:2
    files = {baseline,revision}; load_system(files{index});
    set_param(names{index},'DataDictionary',dictionaryName);
    set_param([names{index} '/Mechanical dynamics/Damping force'],'Gain','dictDamping');
    save_system(names{index},files{index}); close_system(names{index},0);
end
beforeHash = hashFile(dictionaryFile);
report = engineering.reconcileModel(baseline,revision,emptyIntent);
verifyTrue(testCase,report.accepted);
dependency = report.revised.dependencies(strcmp({report.revised.dependencies.kind},'dictionary'));
verifyTrue(testCase,strcmpi(dependency.resolvedFile,filepath(dictionary)),dependency.resolvedFile);
verifyEqual(testCase,dependency.sha256,beforeHash);
[series,time] = nativeSimulation(revision,1);
verifySavedDynamics(testCase,series,time);
verifyEqual(testCase,hashFile(dictionaryFile),beforeHash);
% The retained external connection represents another owner's unsaved edit.
setValue(entry,0.91);
verifyTrue(testCase,dictionary.HasUnsavedChanges);
verifyError(testCase,@() engineering.reconcileModel(baseline,revision,emptyIntent),'engineering:DirtyDictionary');
verifyTrue(testCase,dictionary.HasUnsavedChanges);
verifyEqual(testCase,getValue(entry),0.91);
verifyEqual(testCase,hashFile(dictionaryFile),beforeHash);
clear dictionaryCleanup restorePath cleanup;
end

function testModelReferenceUsesActualShadowedNativeInstance(testCase)
[baseline,revision,directory,names] = fixture;
previousPath = path;
restorePath = onCleanup(@() path(previousPath));
[~,token] = fileparts(tempname);
child = matlab.lang.makeValidName(['engineering_reference_' token]);
cleanup = onCleanup(@() removeFixture(directory,[names,{child}]));
actualFolder = fullfile(directory,'actual-model'); mkdir(actualFolder);
actualFile = createReferencedSource(actualFolder,child,3);
decoyFile = createReferencedSource(directory,child,17);
addpath(actualFolder,'-begin');
for index = 1:2
    files = {baseline,revision}; load_system(files{index});
    verifyEqual(testCase,get_param(names{index},'LoadInitialState'),'off');
    verifyEqual(testCase,get_param(names{index},'SaveFinalState'),'off');
    add_block('simulink/Ports & Subsystems/Model',[names{index} '/Referenced calibration'], ...
        'ModelName',child,'SimulationMode','Normal', ...
        'Position',[150 220 300 270]);
    add_block('simulink/Ports & Subsystems/Out1',[names{index} '/Reference result'], ...
        'Port','3','Position',[400 230 430 250]);
    add_line(names{index},'Referenced calibration/1','Reference result/1');
    save_system(names{index},files{index}); close_system(names{index},0);
end
% Native Simulink generates these state namespace values from the owning
% parent name, even after an attempted inactive dialog-value assignment.
% Declare the exact known namespace change; never erase it in the product.
intent(1) = struct('category','blockParameter','target','Referenced calibration', ...
    'parameter','InitialState','before',[names{1} '_Referenced_calibration'], ...
    'after',[names{2} '_Referenced_calibration']);
intent(2) = intent(1); intent(2).parameter = 'FinalStateName';
report = engineering.reconcileModel(baseline,revision,intent);
verifyTrue(testCase,report.accepted,jsonencode(report.changes));
verifyEqual(testCase,numel(report.changes),2);
dependency = report.revised.dependencies(strcmp({report.revised.dependencies.kind},'modelReference'));
verifyTrue(testCase,strcmpi(dependency.resolvedFile,actualFile),dependency.resolvedFile);
verifyEqual(testCase,dependency.sha256,hashFile(actualFile));
verifyNotEqual(testCase,dependency.sha256,hashFile(decoyFile));
series = nativeSimulation(revision,1);
verifyEqual(testCase,series(:,3),3*ones(size(series,1),1));
% A dirty already-loaded dependency is preserved, including its actual path.
load_system(actualFile);
set_param([child '/Source'],'Value','4');
verifyError(testCase,@() engineering.reconcileModel(baseline,revision,intent),'engineering:DirtyDependency');
verifyTrue(testCase,bdIsLoaded(child));
verifyEqual(testCase,get_param(child,'Dirty'),'on');
verifyEqual(testCase,get_param([child '/Source'],'Value'),'4');
verifyTrue(testCase,strcmpi(get_param(child,'FileName'),actualFile),get_param(child,'FileName'));
clear restorePath cleanup;
end

function testExternalDependencyMutationDuringReadbackIsRejected(testCase)
[baseline,revision,directory,names] = fixture;
cleanup = onCleanup(@() removeFixture(directory,names));
sourceFile = fullfile(directory,'bound-parameters.mat');
load_system(baseline);
workspace = get_param(names{1},'ModelWorkspace'); save(workspace,sourceFile);
workspace.DataSource = 'MAT-File'; workspace.FileName = sourceFile; reload(workspace);
% A trusted but defective initialization callback mutates an owned source.
quotedFile = strrep(sourceFile,'''','''''');
% Function arguments keep the fixture write out of the shared base workspace.
callback = sprintf('feval(@(damping) save(''%s'',''damping'',''-append''),0.91);',quotedFile);
set_param(names{1},'InitFcn',callback);
save_system(names{1},baseline); close_system(names{1},0);
verifyError(testCase,@() engineering.reconcileModel(baseline,revision,emptyIntent),'engineering:RevisionDependencyChanged');
verifyFalse(testCase,bdIsLoaded(names{1}));
data = load(sourceFile);
verifyEqual(testCase,data.damping,0.91); % Preserve failure artifacts; no hidden rollback.
clear cleanup;
end

function testRevisedCloseCallbackCannotMutateBoundDependencyAfterReadback(testCase)
[baseline,revision,directory,names] = fixture;
cleanup = onCleanup(@() removeFixture(directory,names));
sourceFile = fullfile(directory,'close_bound_parameters.mat');
load_system(baseline);
workspace = get_param(names{1},'ModelWorkspace'); save(workspace,sourceFile);
close_system(names{1},0);
quotedFile = strrep(sourceFile,'''','''''');
callback = sprintf('feval(@(damping) save(''%s'',''damping'',''-append''),0.91);',quotedFile);
files = {baseline,revision};
for index = 1:2
    load_system(files{index});
    workspace = get_param(names{index},'ModelWorkspace');
    workspace.DataSource = 'MAT-File'; workspace.FileName = sourceFile; reload(workspace);
    if index == 2, set_param(names{index},'CloseFcn',callback); end
    save_system(names{index},files{index});
    if index == 2
        % Suppress only this owned in-memory setup close. Discarding this
        % transient edit leaves the intended callback in the saved revision.
        set_param(names{index},'CloseFcn','');
    end
    close_system(names{index},0);
end
data = load(sourceFile);
verifyEqual(testCase,data.damping,0.43); % No premature fixture mutation.
beforeHash = hashFile(sourceFile);
intent = struct('category','modelParameter','target','<model>','parameter','CloseFcn', ...
    'before','','after',callback);
% The callback change itself is explicitly approved. Only post-readback
% dependency mutation may reject this otherwise reconciled owned revision.
verifyError(testCase,@() engineering.reconcileModel(baseline,revision,intent),'engineering:RevisionDependencyChanged');
verifyFalse(testCase,bdIsLoaded(names{1}));
verifyFalse(testCase,bdIsLoaded(names{2}));
verifyNotEqual(testCase,hashFile(sourceFile),beforeHash);
data = load(sourceFile); verifyEqual(testCase,data.damping,0.91);
clear cleanup;
end

function testThrowingOwnedCloseCallbackCannotBecomeSuccessfulReadback(testCase)
[baseline,revision,directory,names] = fixture;
cleanup = onCleanup(@() removeFixture(directory,names));
callback = 'error(''engineering:SeededCloseCallbackFailure'',''MATLAB_HARNESS_CLOSE_CALLBACK_SEEDED_FAILURE'')';
load_system(revision);
set_param(names{2},'CloseFcn',callback);
save_system(names{2},revision);
set_param(names{2},'CloseFcn',''); close_system(names{2},0); % Setup close only.
beforeHash = hashFile(revision);
intent = struct('category','modelParameter','target','<model>','parameter','CloseFcn', ...
    'before','','after',callback);
[previousMessage,previousIdentifier] = lastwarn;
restoreWarning = onCleanup(@() lastwarn(previousMessage,previousIdentifier));
lastwarn('MATLAB_HARNESS_CALLER_WARNING_SENTINEL','engineering:CallerWarningSentinel');
caught = false;
try
    engineering.reconcileModel(baseline,revision,intent);
catch exception
    caught = true;
    % MATLAB may wrap callback errors in a native identifier. The original
    % diagnostic must propagate, not become an onCleanup warning or ACCEPT.
    verifyTrue(testCase,contains(getReport(exception),'MATLAB_HARNESS_CLOSE_CALLBACK_SEEDED_FAILURE'),getReport(exception));
end
verifyTrue(testCase,caught,'Owned normal close failure was swallowed.');
[warningMessage,warningIdentifier] = lastwarn;
verifyEqual(testCase,warningMessage,'MATLAB_HARNESS_CALLER_WARNING_SENTINEL');
verifyEqual(testCase,warningIdentifier,'engineering:CallerWarningSentinel');
verifyEqual(testCase,hashFile(revision),beforeHash);
verifyFalse(testCase,bdIsLoaded(names{1}));
% A failed CloseFcn may leave the owned model loaded. Dispose only this test's
% model with an in-memory suppressed callback; its saved source is preserved.
if bdIsLoaded(names{2})
    set_param(names{2},'CloseFcn',''); close_system(names{2},0);
end
verifyFalse(testCase,bdIsLoaded(names{2}));
verifyEqual(testCase,hashFile(revision),beforeHash);
clear restoreWarning cleanup;
end

function testCloseCallbackDirtySharedDictionaryCannotHideBehindUnchangedBytes(testCase)
[baseline,revision,directory,names] = fixture;
previousPath = path;
restorePath = onCleanup(@() path(previousPath));
cleanup = onCleanup(@() removeFixture(directory,names));
[~,token] = fileparts(tempname);
dictionaryName = [matlab.lang.makeValidName(['engineering_close_dictionary_' token]) '.sldd'];
dictionaryFile = fullfile(directory,dictionaryName);
dictionary = Simulink.data.dictionary.create(dictionaryFile);
dictionaryCleanup = onCleanup(@() discardOwnedDictionary(dictionary));
entry = addEntry(getSection(dictionary,'Design Data'),'callbackDamping',0.43);
saveChanges(dictionary);
% This owned native fixture closes its temporary connection without saving or
% discarding the edit held by the independently retained shared connection.
functionName = matlab.lang.makeValidName(['engineering_dirty_close_' token]);
functionFile = fullfile(directory,[functionName '.m']);
handle = fopen(functionFile,'w'); assert(handle ~= -1);
fprintf(handle,['function %s(file,value)\n' ...
    'connection=Simulink.data.dictionary.open(file);\n' ...
    'cleanup=onCleanup(@() close(connection));\n' ...
    'entry=getEntry(getSection(connection,''Design Data''),''callbackDamping'');\n' ...
    'setValue(entry,value);\n' ...
    'clear cleanup;\nend\n'],functionName);
fclose(handle);
addpath(directory,'-begin');
callback = sprintf('%s(''%s'',0.91);',functionName,strrep(dictionaryFile,'''',''''''));
files = {baseline,revision};
for index = 1:2
    load_system(files{index});
    set_param(names{index},'DataDictionary',dictionaryName);
    set_param([names{index} '/Mechanical dynamics/Damping force'],'Gain','callbackDamping');
    if index == 2, set_param(names{index},'CloseFcn',callback); end
    save_system(names{index},files{index});
    if index == 2, set_param(names{index},'CloseFcn',''); end
    close_system(names{index},0);
end
verifyFalse(testCase,dictionary.HasUnsavedChanges);
beforeHash = hashFile(dictionaryFile);
intent = struct('category','modelParameter','target','<model>','parameter','CloseFcn', ...
    'before','','after',callback);
verifyError(testCase,@() engineering.reconcileModel(baseline,revision,intent),'engineering:DirtyDictionary');
verifyTrue(testCase,dictionary.HasUnsavedChanges);
verifyEqual(testCase,getValue(entry),0.91);
verifyEqual(testCase,hashFile(dictionaryFile),beforeHash);
verifyFalse(testCase,bdIsLoaded(names{1}));
verifyFalse(testCase,bdIsLoaded(names{2}));
clear dictionaryCleanup restorePath cleanup;
end

function file = createReferencedSource(directory,name,value)
new_system(name);
cleanup = onCleanup(@() closeIfLoaded(name));
set_param(name,'SolverType','Variable-step','Solver','ode45','StopTime','1');
add_block('simulink/Sources/Constant',[name '/Source'],'Value',sprintf('%.17g',value));
add_block('simulink/Ports & Subsystems/Out1',[name '/Result']);
add_line(name,'Source/1','Result/1');
file = fullfile(directory,[name '.slx']); save_system(name,file);
clear cleanup;
end

function [values,time] = nativeSimulation(file,stop)
[~,name] = fileparts(file); load_system(file);
cleanup = onCleanup(@() closeIfLoaded(name));
output = sim(name,'StopTime',sprintf('%.17g',stop),'ReturnWorkspaceOutputs','on');
data = output.get('yout');
time = data.time;
values = zeros(numel(data.time),numel(data.signals));
for index = 1:numel(data.signals), values(:,index) = data.signals(index).values; end
assert(data.time(end) >= stop-1e-9,'engineering:RevisionTestStop','Actual simulation stopped early.');
clear cleanup;
end

function verifySavedDynamics(testCase,actual,time)
% Independent mechanics truth at the actual variable-step logging times.
matrix = [0,1; -5.8/1.7,-0.43/1.7];
initial = [0.31;-0.22];
expected = zeros(numel(time),2);
for index = 1:numel(time), expected(index,:) = (expm(matrix*time(index))*initial).'; end
verifySize(testCase,actual,[numel(time),2]);
verifyTrue(testCase,all(isfinite(actual(:))));
errors = abs(actual-expected);
verifyTrue(testCase,all(errors(:) <= 2e-7+2e-6*abs(expected(:))), ...
    sprintf('Independent dependency-driven trajectory maximum error %.17g',max(errors(:))));
end

function result = hashFile(file)
handle = fopen(file,'rb'); assert(handle ~= -1);
cleanup = onCleanup(@() fclose(handle));
digest = java.security.MessageDigest.getInstance('SHA-256');
while ~feof(handle), digest.update(fread(handle,1024*1024,'*uint8')); end
result = lower(reshape(dec2hex(typecast(digest.digest(),'uint8'),2).',1,[]));
clear cleanup;
end

function discardOwnedDictionary(dictionary)
% Only a dictionary created by this test is discarded, never a shared user file.
if dictionary.HasUnsavedChanges, discardChanges(dictionary); end
close(dictionary);
end

function [baseline,revision,directory,names] = fixture
directory = tempname; mkdir(directory);
p = struct('mass',1.7,'damping',0.43,'stiffness',5.8,'force',0, ...
    'initialDisplacement',0.31,'initialVelocity',-0.22);
baseline = buildOscillatorModel(p,directory);
[~,oldName] = fileparts(baseline);
[~,token] = fileparts(tempname(directory));
newName = matlab.lang.makeValidName(['engineering_revision_test_' token]);
revision = fullfile(directory,[newName '.slx']);
names = {oldName,newName};
cleanup = onCleanup(@() closeFixtureOnFailure(names));
load_system(baseline);
save_system(oldName,revision,'ErrorIfShadowed',true);
close_system(newName,0);
clear cleanup;
end

function intent = emptyIntent
intent = struct('category',{},'target',{},'parameter',{},'before',{},'after',{});
end

function closeFixtureOnFailure(names)
for index = 1:numel(names), closeIfLoaded(names{index}); end
end

function removeFixture(directory,names)
closeFixtureOnFailure(names);
% This directory came directly from tempname and contains only test fixtures.
if isfolder(directory)
    [ok,info] = fileattrib(directory);
    assert(ok && startsWith(lower(info.Name),lower(tempdir)) && ~strcmpi(info.Name,tempdir), ...
        'engineering:RevisionCleanupScope','Fixture cleanup must remain inside the allocated temporary tree.');
    rmdir(info.Name,'s');
end
end

function closeIfLoaded(name)
if bdIsLoaded(name), close_system(name,0); end
end
