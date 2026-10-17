function tests = testRuntimeSession
tests = functiontests(localfunctions);
end

function setupOnce(testCase)
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
testCase.TestData.path = path;
addpath(fullfile(root,'matlab'),fullfile(root,'examples','engineering-core'));
end

function teardownOnce(testCase)
path(testCase.TestData.path);
end

function testNestedStateAndGeneratedFiles(testCase)
before = snapshot();
outer = engineering.runtimeSession();
outerState = snapshot();
verifyNotEqual(testCase,outerState.cache,before.cache);
verifyTrue(testCase,startsWith(outerState.cache,tempdir));
inner = engineering.runtimeSession();
innerState = snapshot();
verifyNotEqual(testCase,innerState.cache,outerState.cache);
writelines('owned temporary cache',fullfile(innerState.cache,'probe.txt'));
clear inner;
verifyEqual(testCase,snapshot(),outerState);
verifyFalse(testCase,isfolder(fileparts(innerState.cache)));
clear outer;
verifyEqual(testCase,snapshot(),before);
verifyFalse(testCase,isfolder(fileparts(outerState.cache)));
end

function testFailureRestoresCompleteConfigAndPath(testCase)
before = snapshot();
verifyError(testCase,@failOwnedSession,'engineering:DeliberateFailure');
verifyEqual(testCase,snapshot(),before);
end

function failOwnedSession
cleanup = engineering.runtimeSession(); %#ok<NASGU>
error('engineering:DeliberateFailure','Exercise exceptional unwinding.');
end

function testDirectBuildSimulationAndDirtyCaller(testCase)
scratch = tempname; mkdir(scratch);
[~,token] = fileparts(tempname);
sentinel = matlab.lang.makeValidName(['caller_dirty_' token]);
new_system(sentinel); set_param(sentinel,'Description','unsaved caller work');
cleanup = onCleanup(@() finish(scratch,sentinel)); %#ok<NASGU>
before = snapshot();
entries = dir(pwd); namesBefore = sort({entries.name});
p = struct('mass',2,'stiffness',18,'damping',1.2,'force',0, ...
    'initialDisplacement',0.1,'initialVelocity',0);
file = buildOscillatorModel(p,scratch);
verifyTrue(testCase,isfile(file));
verifyEqual(testCase,snapshot(),before);
result = simulateOscillator(p,(0:0.02:0.2).');
verifyTrue(testCase,all(isfinite(result.displacement)));
verifyEqual(testCase,snapshot(),before);
engineering.inspectModel(file);
verifyEqual(testCase,snapshot(),before);
verifyTrue(testCase,bdIsLoaded(sentinel));
verifyEqual(testCase,get_param(sentinel,'Dirty'),'on');
verifyEqual(testCase,get_param(sentinel,'Description'),'unsaved caller work');
entries = dir(pwd); verifyEqual(testCase,sort({entries.name}),namesBefore);
verifyEmpty(testCase,dir(fullfile(scratch,'*.slxc')));
verifyFalse(testCase,isfolder(fullfile(scratch,'slprj')));
end

function testInspectionFailureRestoresCaller(testCase)
scratch = tempname; mkdir(scratch);
cleanup = onCleanup(@() finish(scratch,'')); %#ok<NASGU>
p = struct('mass',2,'stiffness',18,'damping',1.2,'force',0, ...
    'initialDisplacement',0.1,'initialVelocity',0);
file = buildOscillatorModel(p,scratch); [~,name] = fileparts(file);
load_system(file);
set_param(name,'InitFcn','error(''engineering:CallbackFailure'',''deliberate callback failure'')');
save_system(name,file); close_system(name,0);
before = snapshot();
caught = false;
try
    engineering.inspectModel(file);
catch exception
    caught = contains(exception.message,'deliberate callback failure');
end
verifyTrue(testCase,caught);
verifyEqual(testCase,snapshot(),before);
verifyFalse(testCase,bdIsLoaded(name));
end

function state = snapshot
config = Simulink.fileGenControl('getConfig');
settings = struct;
for name = properties(config).'
    settings.(name{1}) = config.(name{1});
end
state = struct('cache',config.CacheFolder,'codegen',config.CodeGenFolder, ...
    'configuration',settings,'path',path,'pwd',pwd);
end

function finish(scratch,name)
if ~isempty(name) && bdIsLoaded(name), close_system(name,0); end
if isfolder(scratch), rmdir(scratch,'s'); end
end
