function report = inspectModel(modelPath)
%INSPECTMODEL Inspect the actual saved model, update and compile port metadata.
% Callbacks execute during load/update/compile: use only trusted owned models.
% Existing dirty/running/name-colliding models are rejected, never discarded.
assert((ischar(modelPath) && isrow(modelPath)) || (isstring(modelPath) && isscalar(modelPath)), ...
    'engineering:ModelFile','Model path must be a text scalar.');
[ok,info] = fileattrib(modelPath);
assert(ok && ~info.directory,'engineering:ModelFile','Saved model file not found.');
modelPath = info.Name;
[~,modelName] = fileparts(modelPath);
wasLoaded = bdIsLoaded(modelName);
if wasLoaded
    loadedPath = get_param(modelName,'FileName');
    assert(strcmpi(loadedPath,modelPath),'engineering:ModelCollision','Loaded model has same name but different file.');
    assert(strcmp(get_param(modelName,'Dirty'),'off'),'engineering:DirtyModel','Save or isolate edits before saved-model inspection.');
    assert(strcmp(get_param(modelName,'SimulationStatus'),'stopped'),'engineering:BusyModel','Model must be stopped before inspection.');
end
modelCleanup = engineering.runtimeSession(@() finishInspection(modelName,wasLoaded));
if ~wasLoaded, load_system(modelPath); end
report.file = modelPath;
report.release = version('-release');
report.solver = get_param(modelName,'Solver');
report.solverType = get_param(modelName,'SolverType');
report.relativeTolerance = get_param(modelName,'RelTol');
report.absoluteTolerance = get_param(modelName,'AbsTol');
report.dataDictionary = get_param(modelName,'DataDictionary');
report.callbacks = struct;
callbackNames = {'PreLoadFcn','PostLoadFcn','InitFcn','StartFcn','StopFcn','CloseFcn'};
for index = 1:numel(callbackNames)
    name = callbackNames{index};
    report.callbacks.(name) = get_param(modelName,name);
end
workspace = get_param(modelName,'ModelWorkspace');
report.workspaceSource = workspace.DataSource;
report.workspaceVariables = workspace.whos;
blocks = find_system(modelName,'FollowLinks','off','LookUnderMasks','all','Type','Block');
report.blocks = struct('path',{},'type',{},'maskType',{},'parameters',{}, ...
    'sampleTime',{},'connectivity',{},'compiledWidths',{},'compiledDimensions',{},'compiledTypes',{},'compiledUnits',{}, ...
    'compiledSampleTime',{},'unconnectedInputs',{},'unconnectedOutputs',{});
set_param(modelName,'SimulationCommand','update');
report.updatePassed = true;
feval(modelName,[],[],[],'compile');
for index = 1:numel(blocks)
    block = blocks{index};
    item.path = block;
    item.type = get_param(block,'BlockType');
    item.maskType = get_param(block,'MaskType');
    item.parameters = struct;
    dialog = get_param(block,'DialogParameters');
    parameterNames = {};
    if ~isempty(dialog)
        parameterNames = fieldnames(dialog);
    end
    for parameterIndex = 1:numel(parameterNames)
        parameterName = parameterNames{parameterIndex};
        item.parameters.(parameterName) = get_param(block,parameterName);
    end
    item.sampleTime = optionalParameter(block,'SampleTime');
    item.connectivity = get_param(block,'PortConnectivity');
    item.compiledWidths = optionalParameter(block,'CompiledPortWidths');
    item.compiledDimensions = optionalParameter(block,'CompiledPortDimensions');
    item.compiledTypes = optionalParameter(block,'CompiledPortDataTypes');
    item.compiledUnits = optionalParameter(block,'CompiledPortUnits');
    item.compiledSampleTime = optionalParameter(block,'CompiledSampleTime');
    ports = get_param(block,'PortHandles');
    item.unconnectedInputs = disconnected(ports.Inport);
    item.unconnectedOutputs = disconnected(ports.Outport);
    report.blocks(index) = item;
end
report.lines = struct('name',{},'source',{},'destinations',{});
lines = find_system(modelName,'FindAll','on','FollowLinks','off', ...
    'LookUnderMasks','all','Type','line');
for index = 1:numel(lines)
    report.lines(index).name = get_param(lines(index),'Name');
    report.lines(index).source = get_param(lines(index),'SrcBlockHandle');
    report.lines(index).destinations = get_param(lines(index),'DstBlockHandle');
end
report.compilationPassed = true;
report.claim = 'Topology/parameters/compiled metadata inspected; physical correctness still needs executed independent oracles.';
% Explicit normal cleanup and one error cleanup preserve termination ordering.
% Destruction order of separate onCleanup objects is not a contract.
finishInspection(modelName,wasLoaded);
clear modelCleanup;
end

function finishInspection(modelName,wasLoaded)
% Value-captured callback avoids accessing destroyed nested-workspace variables
% during exceptional unwinding. A failed compile may already have terminated.
if bdIsLoaded(modelName) && ~strcmp(get_param(modelName,'SimulationStatus'),'stopped')
    try
        feval(modelName,[],[],[],'term');
    catch
        % Preserve original failure, then close the model owned by this call.
    end
end
closeOwnedModel(modelName,wasLoaded);
end

function result = optionalParameter(block,name)
try
    result = get_param(block,name);
catch exception
    result = struct('status','UNAVAILABLE','identifier',exception.identifier);
end
end

function indices = disconnected(ports)
indices = [];
for index = 1:numel(ports)
    if get_param(ports(index),'Line') == -1
        indices(end+1) = index; %#ok<AGROW>
    end
end
end

function closeOwnedModel(modelName,wasLoaded)
if ~wasLoaded && bdIsLoaded(modelName)
    close_system(modelName,0);
end
end
