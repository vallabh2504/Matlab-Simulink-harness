function varargout = withRuntime(operation)
%WITHRUNTIME Keep cache guard outside the operation's owned cleanup scope.
% This function boundary makes model cleanup finish before cache/path restore.
cleanup = engineering.runtimeSession(); %#ok<NASGU>
if nargout == 0
    operation();
else
    [varargout{1:nargout}] = operation();
end
end
