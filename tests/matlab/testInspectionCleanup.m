function tests = testInspectionCleanup
tests = functiontests(localfunctions);
end

function testFailedInitializationDoesNotLeakModel(testCase)
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
originalPath = path;
restorePath = onCleanup(@() path(originalPath));
addpath(fullfile(root,'matlab'));
folder = tempname;
mkdir(folder);
[~,token] = fileparts(folder);
name = matlab.lang.makeValidName(['engineering_failure_' token]);
cleanup = onCleanup(@() cleanupFixture(name,folder));
new_system(name);
add_block('simulink/Sources/Constant',[name '/source']);
add_block('simulink/Sinks/Out1',[name '/output']);
add_line(name,'source/1','output/1');
set_param(name,'InitFcn','error(''engineering:SeededInitializationFailure'',''Expected regression failure.'')');
file = fullfile(folder,[name '.slx']);
save_system(name,file);
close_system(name,0);
caught = false;
try
    engineering.inspectModel(file);
catch exception
    caught = true;
    verifyTrue(testCase,contains(getReport(exception),'engineering:SeededInitializationFailure') ...
        || contains(getReport(exception),'Expected regression failure.'));
end
verifyTrue(testCase,caught);
verifyFalse(testCase,bdIsLoaded(name));
clear cleanup restorePath;
end

function cleanupFixture(name,folder)
if bdIsLoaded(name), close_system(name,0); end
if isfolder(folder), rmdir(folder,'s'); end
end
