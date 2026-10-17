function report = reconcileModel(baselinePath, revisedPath, intent)
%RECONCILEMODEL Reopen two saved models and bind native changes to intent.
% intent is a struct array with category, target, parameter, before, after.
% Targets are relative block paths, workspace variable names, or '<model>'.
% This is trusted-model execution (load/update/compile callbacks execute).
% The comparison is scoped, not a universal Simulink semantic equivalence test.
required = {'category','target','parameter','before','after'};
assert(isstruct(intent) && all(isfield(intent,required)), ...
    'engineering:RevisionIntent','Intent must contain category/target/parameter/before/after.');
baselinePath = savedFile(baselinePath);
revisedPath = savedFile(revisedPath);
assert(~strcmpi(baselinePath,revisedPath),'engineering:RevisionIdentity','Use separate saved baseline and revision artifacts.');
baselineHash = fileHash(baselinePath);
revisedHash = fileHash(revisedPath);
baseline = snapshot(baselinePath);
revised = snapshot(revisedPath);
assert(strcmp(baselineHash,fileHash(baselinePath)) && strcmp(revisedHash,fileHash(revisedPath)), ...
    'engineering:RevisionFileChanged','Model artifact changed during readback.');
changes = struct('category',{},'target',{},'parameter',{},'before',{},'after',{},'approved',{});
baselineKeys = keys(baseline.entries);
revisedKeys = keys(revised.entries);
baselineIndex = indexEntries(baselineKeys);
revisedIndex = indexEntries(revisedKeys);
allKeys = unique([baselineKeys; revisedKeys]);
for index = 1:numel(allKeys)
    oldIndex = []; newIndex = [];
    if isKey(baselineIndex,allKeys{index}), oldIndex = baselineIndex(allKeys{index}); end
    if isKey(revisedIndex,allKeys{index}), newIndex = revisedIndex(allKeys{index}); end
    if isempty(oldIndex)
        entry = revised.entries(newIndex); old = absent(); new = entry.value;
    elseif isempty(newIndex)
        entry = baseline.entries(oldIndex); old = entry.value; new = absent();
    else
        entry = baseline.entries(oldIndex);
        old = entry.value; new = revised.entries(newIndex).value;
    end
    if ~isempty(oldIndex) && ~isempty(newIndex) && isequaln(old,new), continue; end
    change = struct('category',entry.category,'target',entry.target, ...
        'parameter',entry.parameter,'before',old,'after',new,'approved',false);
    changes(end+1) = change; %#ok<AGROW>
end
matched = false(size(intent));
for index = 1:numel(intent)
    item = intent(index);
    assert(isText(item.category) && isText(item.target) && isText(item.parameter), ...
        'engineering:RevisionIntent','Intent identifiers must be text scalars.');
    candidates = find(strcmp({changes.category},char(item.category)) & ...
        strcmp({changes.target},char(item.target)) & strcmp({changes.parameter},char(item.parameter)));
    assert(numel(candidates) <= 1,'engineering:RevisionAmbiguous','Duplicate comparison key.');
    if ~isempty(candidates)
        position = candidates(1);
        assert(~changes(position).approved,'engineering:RevisionIntent','Duplicate intent entry.');
        if isequaln(changes(position).before,item.before) && isequaln(changes(position).after,item.after)
            changes(position).approved = true; matched(index) = true;
        end
    end
end
report.baselineFile = baselinePath;
report.revisedFile = revisedPath;
report.baselineSha256 = baselineHash;
report.revisedSha256 = revisedHash;
report.release = version('-release');
report.baseline = baseline;
report.revised = revised;
report.changes = changes;
report.intentMatched = matched;
report.unexpectedChangeCount = sum(~[changes.approved]);
report.accepted = all(matched(:)) && all([changes.approved]);
report.coverage = {'Declared solver/time/logging configuration and model callbacks', ...
    'Block types, mask types, link/reference paths and all dialog parameters', ...
    'Compiled ports/types/sample times and native line endpoints', ...
    'Model workspace values (supported explicit value classes only)', ...
    'Resolved direct dictionary, referenced-model and linked-library file hashes'};
report.limitations = {'No physical correctness claim; execute independent trajectory/invariant oracles', ...
    'No recursively exhaustive dictionary/model-reference/library inspection', ...
    'No visual-layout diff, active-variant enumeration, mask workspace or custom config-set equivalence', ...
    'Trusted callbacks execute; this is not a sandbox or a signature'};
% Closing either owned model runs CloseFcn. Recheck every captured dependency
% across both snapshots at the final boundary, without reopening any model.
verifyDependencies(baseline.dependencies,false);
verifyDependencies(revised.dependencies,false);
end

function result = snapshot(file)
[~,name] = fileparts(file);
% Keep the actual native dependency instances loaded through inspection. A
% guessed model-folder path can differ from the model MATLAB actually executes.
ownedModels = containers.Map('KeyType','char','ValueType','char');
cleanup = engineering.runtimeSession(@() releaseModels(ownedModels,name,false));
ensureRoot(file,name,ownedModels);
dependencies = nativeDependencies(name,ownedModels);
inspection = engineering.inspectModel(file); % Update/compile the same loaded instance.
verifyDependencies(dependencies);
entries = struct('category',{},'target',{},'parameter',{},'value',{});
modelParameters = {'Solver','SolverType','RelTol','AbsTol','MaxStep','StartTime','StopTime', ...
    'SaveTime','TimeSaveName','SaveOutput','OutputSaveName','SaveFormat','ReturnWorkspaceOutputs', ...
    'DataDictionary','PreLoadFcn','PostLoadFcn','InitFcn','StartFcn','StopFcn','CloseFcn','PreSaveFcn','PostSaveFcn'};
for index = 1:numel(modelParameters)
    parameter = modelParameters{index};
    entries(end+1) = makeEntry('modelParameter','<model>',parameter,get_param(name,parameter)); %#ok<AGROW>
end
workspace = get_param(name,'ModelWorkspace');
entries(end+1) = makeEntry('workspaceSource','<model>','DataSource',workspace.DataSource);
if strcmp(workspace.DataSource,'MATLAB Code')
    entries(end+1) = makeEntry('workspaceSource','<model>','MATLABCode',workspace.MATLABCode);
elseif strcmp(workspace.DataSource,'MAT-File') || strcmp(workspace.DataSource,'MATLAB File')
    entries(end+1) = makeEntry('workspaceSource','<model>','FileName',workspace.FileName);
end
variables = workspace.whos;
for index = 1:numel(variables)
    variable = variables(index);
    value = workspace.getVariable(variable.name);
    entries(end+1) = makeEntry('workspace',variable.name,'value',supportedValue(value)); %#ok<AGROW>
    entries(end+1) = makeEntry('workspace',variable.name,'class',class(value)); %#ok<AGROW>
    entries(end+1) = makeEntry('workspace',variable.name,'size',size(value)); %#ok<AGROW>
end
for index = 1:numel(inspection.blocks)
    block = inspection.blocks(index);
    target = relativePath(block.path,name);
    entries(end+1) = makeEntry('block',target,'BlockType',block.type); %#ok<AGROW>
    entries(end+1) = makeEntry('block',target,'MaskType',block.maskType); %#ok<AGROW>
    parameterNames = fieldnames(block.parameters);
    for parameterIndex = 1:numel(parameterNames)
        parameter = parameterNames{parameterIndex};
        entries(end+1) = makeEntry('blockParameter',target,parameter,supportedValue(block.parameters.(parameter))); %#ok<AGROW>
    end
    entries(end+1) = makeEntry('compiled',target,'PortWidths',block.compiledWidths); %#ok<AGROW>
    entries(end+1) = makeEntry('compiled',target,'PortDimensions',block.compiledDimensions); %#ok<AGROW>
    entries(end+1) = makeEntry('compiled',target,'PortTypes',block.compiledTypes); %#ok<AGROW>
    entries(end+1) = makeEntry('compiled',target,'PortUnits',block.compiledUnits); %#ok<AGROW>
    entries(end+1) = makeEntry('compiled',target,'SampleTime',block.compiledSampleTime); %#ok<AGROW>
    reference = get_param(block.path,'ReferenceBlock');
    entries(end+1) = makeEntry('block',target,'ReferenceBlock',reference); %#ok<AGROW>
    entries(end+1) = makeEntry('block',target,'LinkStatus',get_param(block.path,'LinkStatus')); %#ok<AGROW>
end
lines = find_system(name,'FindAll','on','FollowLinks','off','LookUnderMasks','all','Type','line');
connections = {};
for index = 1:numel(lines)
    source = get_param(lines(index),'SrcPortHandle');
    destinations = get_param(lines(index),'DstPortHandle');
    for destination = destinations(:).'
        connections{end+1,1} = [endpoint(source,name) ' -> ' endpoint(destination,name) ...
            ' | ' get_param(lines(index),'Name')]; %#ok<AGROW>
    end
    if isempty(destinations)
        connections{end+1,1} = [endpoint(source,name) ' -> <unconnected>']; %#ok<AGROW>
    end
end
entries(end+1) = makeEntry('topology','<model>','connections',sort(unique(connections)));
for index = 1:numel(dependencies)
    item = dependencies(index);
    alreadyPresent = strcmp({entries.category},'dependency') & ...
        strcmp({entries.target},item.requested) & strcmp({entries.parameter},item.kind);
    if any(alreadyPresent)
        previous = entries(find(alreadyPresent,1));
        assert(strcmp(previous.value,item.sha256),'engineering:RevisionDependency','Dependency changed within readback.');
    else
        entries(end+1) = makeEntry('dependency',item.requested,item.kind,item.sha256); %#ok<AGROW>
    end
end
entryKeys = keys(entries);
assert(numel(unique(entryKeys)) == numel(entryKeys),'engineering:RevisionAmbiguous','Repeated dependency/comparison keys require scoped handling.');
[~,order] = sort(entryKeys);
result.entries = entries(order);
result.dependencies = dependencies;
result.updatePassed = inspection.updatePassed;
result.compilationPassed = inspection.compilationPassed;
verifyDependencies(dependencies);
% onCleanup can downgrade callback errors to warnings. Normal completion must
% close explicitly and propagate a real close failure before claiming success.
releaseModels(ownedModels,name,true);
clear cleanup;
% Cleanup is execution too: check bytes and shared native state after close.
% Owned unloaded references need not be reopened to perform this check.
verifyDependencies(dependencies,false);
end

function result = endpoint(port,name)
if port == -1, result = '<unconnected>'; return; end
parent = get_param(port,'Parent');
result = sprintf('%s:%s:%d',relativePath(parent,name),get_param(port,'PortType'),get_param(port,'PortNumber'));
end

function result = relativePath(value,name)
if strcmp(value,name), result = '<model>'; else
    assert(startsWith(value,[name '/']),'engineering:RevisionPath','Block does not belong to inspected root.');
    result = value(numel(name)+2:end);
end
end

function result = nativeDependencies(name,ownedModels)
result = struct('kind',{},'requested',{},'resolvedFile',{},'sha256',{},'resolution',{});
workspace = get_param(name,'ModelWorkspace');
if strcmp(workspace.DataSource,'MAT-File') || strcmp(workspace.DataSource,'MATLAB File')
    requested = workspace.FileName;
    % Filename sources must be on MATLAB's path; explicit relative/absolute
    % paths resolve from the current folder. Never prefer the model folder.
    resolved = which(requested);
    if isempty(resolved) && isfile(requested), resolved = savedFile(requested); end
    assert(~isempty(resolved) && isfile(resolved),'engineering:RevisionDependency', ...
        'Cannot resolve external workspace source through the actual MATLAB path.');
    result(end+1) = bindDependency('workspaceSource',requested,resolved,'MATLAB path or explicit filename');
end
dictionary = get_param(name,'DataDictionary');
if ~isempty(dictionary)
    connection = Simulink.data.dictionary.open(dictionary);
    dictionaryCleanup = onCleanup(@() close(connection));
    assert(~connection.HasUnsavedChanges,'engineering:DirtyDictionary', ...
        'Saved-model reconciliation refuses unsaved dictionary state; no changes were discarded.');
    result(end+1) = bindDependency('dictionary',dictionary,filepath(connection),'Native dictionary filepath'); %#ok<AGROW>
    clear dictionaryCleanup;
end
blocks = find_system(name,'FollowLinks','off','LookUnderMasks','all','Type','Block');
for index = 1:numel(blocks)
    block = blocks{index};
    reference = get_param(block,'ReferenceBlock');
    if strcmp(get_param(block,'BlockType'),'ModelReference')
        requested = get_param(block,'ModelName');
        result(end+1) = loadedDependency('modelReference',requested,ownedModels); %#ok<AGROW>
    elseif ~isempty(reference)
        requested = char(extractBefore(string(reference),'/'));
        result(end+1) = loadedDependency('library',requested,ownedModels); %#ok<AGROW>
    end
end
end

function result = loadedDependency(kind,requested,ownedModels)
[~,name] = fileparts(requested);
if ~bdIsLoaded(name)
    load_system(requested); % Native selection, including MATLAB path precedence.
    ownedModels(name) = get_param(name,'FileName');
end
assert(strcmp(get_param(name,'Dirty'),'off'),'engineering:DirtyDependency', ...
    'Referenced model/library has unsaved changes; preserve it and isolate the task.');
assert(strcmp(get_param(name,'SimulationStatus'),'stopped'),'engineering:BusyDependency', ...
    'Referenced model/library is busy; preserve it and isolate the task.');
resolved = get_param(name,'FileName');
assert(~isempty(resolved),'engineering:RevisionDependency','Dependency has no authoritative saved file.');
result = bindDependency(kind,requested,resolved,'Loaded native block diagram FileName');
end

function result = bindDependency(kind,requested,resolved,resolution)
resolved = savedFile(resolved);
result = struct('kind',kind,'requested',requested,'resolvedFile',resolved, ...
    'sha256',fileHash(resolved),'resolution',resolution);
end

function verifyDependencies(dependencies,requireLoaded)
if nargin < 2, requireLoaded = true; end
verifyDependencyFiles(dependencies);
for index = 1:numel(dependencies)
    item = dependencies(index);
    if strcmp(item.kind,'dictionary')
        connection = Simulink.data.dictionary.open(item.resolvedFile);
        cleanup = onCleanup(@() close(connection));
        assert(~connection.HasUnsavedChanges,'engineering:DirtyDictionary', ...
            'Dictionary became dirty during inspection; its state was preserved.');
        clear cleanup;
    elseif strcmp(item.kind,'modelReference') || strcmp(item.kind,'library')
        [~,name] = fileparts(item.requested);
        if bdIsLoaded(name)
            assert(strcmpi(get_param(name,'FileName'),item.resolvedFile), ...
                'engineering:RevisionDependencyChanged','Native dependency instance changed during inspection.');
            assert(strcmp(get_param(name,'Dirty'),'off'),'engineering:DirtyDependency','Dependency became dirty during inspection.');
            assert(strcmp(get_param(name,'SimulationStatus'),'stopped'),'engineering:BusyDependency','Dependency remained busy after inspection.');
        else
            assert(~requireLoaded,'engineering:RevisionDependencyChanged','Native dependency unloaded before inspection completed.');
        end
    end
end
end

function verifyDependencyFiles(dependencies)
for index = 1:numel(dependencies)
    item = dependencies(index);
    assert(strcmp(item.sha256,fileHash(item.resolvedFile)),'engineering:RevisionDependencyChanged', ...
        'Dependency bytes changed during saved-model inspection or owned cleanup.');
end
end

function ensureRoot(file,name,ownedModels)
if bdIsLoaded(name)
    assert(strcmpi(get_param(name,'FileName'),file),'engineering:ModelCollision','Loaded root has the same name but another file.');
    assert(strcmp(get_param(name,'Dirty'),'off'),'engineering:DirtyModel','Save or isolate target edits first.');
    assert(strcmp(get_param(name,'SimulationStatus'),'stopped'),'engineering:BusyModel','Target must be stopped.');
else
    ownedModels(name) = file;
    load_system(file);
end
end

function result = supportedValue(value)
if isnumeric(value) || islogical(value) || ischar(value) || isstring(value)
    result = value;
elseif iscell(value)
    result = cellfun(@supportedValue,value,'UniformOutput',false);
elseif isstruct(value)
    result = value;
    names = fieldnames(value);
    for index = 1:numel(value)
        for fieldIndex = 1:numel(names)
            result(index).(names{fieldIndex}) = supportedValue(value(index).(names{fieldIndex}));
        end
    end
elseif isa(value,'Simulink.Parameter')
    result = struct('class',class(value),'Value',supportedValue(value.Value), ...
        'DataType',value.DataType,'Min',value.Min,'Max',value.Max,'Unit',value.Unit);
else
    error('engineering:UnsupportedWorkspaceValue','Explicit serializer required for %s; comparison must not silently omit it.',class(value));
end
end

function result = makeEntry(category,target,parameter,value)
result = struct('category',category,'target',target,'parameter',parameter,'value',[]);
result.value = value;
end

function result = keys(entries)
result = cell(numel(entries),1);
for index = 1:numel(entries)
    % Delimiter is illegal in Simulink block names? Do not rely on that: JSON
    % encoding the tuple preserves field boundaries for arbitrary names.
    result{index} = jsonencode({entries(index).category,entries(index).target,entries(index).parameter});
end
end

function result = indexEntries(entryKeys)
% Generate keys once and use constant-time lookups; avoid repeated JSON scans.
result = containers.Map('KeyType','char','ValueType','double');
for index = 1:numel(entryKeys), result(entryKeys{index}) = index; end
end

function result = absent()
result = struct('engineeringComparisonPresence','ABSENT');
end

function result = isText(value)
result = (ischar(value) && isrow(value)) || (isstring(value) && isscalar(value));
end

function result = savedFile(value)
assert(isText(value),'engineering:RevisionFile','File path must be a text scalar.');
[ok,info] = fileattrib(value);
assert(ok && ~info.directory,'engineering:RevisionFile','Saved artifact does not exist.');
result = info.Name;
end

function result = fileHash(file)
handle = fopen(file,'rb');
assert(handle ~= -1,'engineering:RevisionFile','Cannot read artifact.');
cleanup = onCleanup(@() fclose(handle));
digest = java.security.MessageDigest.getInstance('SHA-256');
while ~feof(handle), digest.update(fread(handle,1024*1024,'*uint8')); end
bytes = typecast(digest.digest(),'uint8');
result = lower(reshape(dec2hex(bytes,2).',1,[]));
clear cleanup;
end

function releaseModels(ownedModels,root,strict)
names = ownedModels.keys;
% Close the owned parent before its owned references/libraries. Already-loaded
% models were never inserted in this registry, including dirty shared models.
names = [{root};names(~strcmp(names,root))];
firstFailure = [];
for index = 1:numel(names)
    name = names{index};
    if isKey(ownedModels,name) && bdIsLoaded(name) && ...
            strcmpi(get_param(name,'FileName'),ownedModels(name))
        try
            closeTrackedModel(name,strict);
        catch exception
            if isempty(firstFailure), firstFailure = exception; end
            % Continue releasing other owned models. Exceptional fallback must
            % preserve the originating failure; normal completion is strict.
        end
    end
end
if strict && ~isempty(firstFailure), rethrow(firstFailure); end
end

function closeTrackedModel(name,strict)
[previousMessage,previousIdentifier] = lastwarn;
restoreWarning = onCleanup(@() lastwarn(previousMessage,previousIdentifier));
lastwarn('','');
close_system(name,0);
[closeMessage,closeIdentifier] = lastwarn;
clear restoreWarning;
% R2026a converts a CloseFcn error to a warning carrying the original custom
% identifier. There is no universal callback-warning ID to hard-code. Capture
% only this owned close; preceding solver/unit warnings are not classified here.
if strict && ~isempty(closeMessage)
    error('engineering:RevisionCleanupWarning','Owned model close emitted warning [%s]: %s. Explicit assessment is required.', ...
        closeIdentifier,closeMessage);
end
assert(~strict || ~bdIsLoaded(name),'engineering:RevisionCleanupIncomplete','Owned model remained loaded after normal close.');
end
