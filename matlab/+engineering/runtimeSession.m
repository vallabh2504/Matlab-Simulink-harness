function cleanup = runtimeSession(finalizer, callerPath)
%RUNTIMESESSION Isolate generated cache/codegen and restore complete caller state.
% Hold the returned onCleanup for the entire native operation. Optional owned
% model cleanup runs BEFORE restoring settings/removing the temporary folders.
% Nested calls restore their outer session. This function never changes pwd.
if nargin < 1, finalizer = []; end
assert(isempty(finalizer) || isa(finalizer,'function_handle'), ...
    'engineering:RuntimeFinalizer','Expected an owned-resource cleanup callback.');
configuration = Simulink.fileGenControl('getConfig');
previousPath = path;
if nargin >= 2, previousPath = callerPath; end
runtimeDirectory = tempname;
mkdir(runtimeDirectory);
cleanup = onCleanup(@() finishRuntime(configuration,previousPath,runtimeDirectory,finalizer));
Simulink.fileGenControl('set','CacheFolder',fullfile(runtimeDirectory,'cache'), ...
    'CodeGenFolder',fullfile(runtimeDirectory,'codegen'), ...
    'keepPreviousPath',true,'createDir',true);
end

function finishRuntime(configuration,previousPath,runtimeDirectory,finalizer)
restore = onCleanup(@() restoreCaller(configuration,previousPath,runtimeDirectory));
if ~isempty(finalizer), finalizer(); end
clear restore;
end

function restoreCaller(configuration,previousPath,runtimeDirectory)
restorePath = onCleanup(@() path(previousPath));
Simulink.fileGenControl('setConfig','config',configuration,'keepPreviousPath',true);
clear restorePath;
% runtimeDirectory came directly from tempname and is owned by this call.
if isfolder(runtimeDirectory), rmdir(runtimeDirectory,'s'); end
end
