function report = checkModel(modelPath, policy)
%CHECKMODEL Enforce explicit task-specific model structure requirements.
% Default checks compilation and disconnected data ports. Generic policies
% cannot infer physical equations, variants or valid intentionally unused ports.
if nargin < 2
    policy = struct('requireSubsystem',false,'expectedRootOutports',[], ...
        'allowUnconnectedPorts',false,'allowedSolvers',{{}});
end
inspection = engineering.inspectModel(modelPath);
report.inspection = inspection;
report.violations = struct('rule',{},'artifact',{},'reason',{});
if isfield(policy,'allowedSolvers') && ~isempty(policy.allowedSolvers) && ...
        ~any(strcmp(inspection.solver,policy.allowedSolvers))
    addViolation('S03',inspection.file,'Solver is outside the task-approved set.');
end
[~,modelName] = fileparts(inspection.file);
rootOutports = 0;
hasSubsystem = false;
for index = 1:numel(inspection.blocks)
    block = inspection.blocks(index);
    hasSubsystem = hasSubsystem || strcmp(block.type,'SubSystem');
    parentPath = block.path(1:find(block.path=='/',1,'last')-1);
    rootOutports = rootOutports + (strcmp(block.type,'Outport') && strcmp(parentPath,modelName));
    if ~isfield(policy,'allowUnconnectedPorts') || ~policy.allowUnconnectedPorts
        if ~isempty(block.unconnectedInputs) || ~isempty(block.unconnectedOutputs)
            addViolation('S02',block.path,'Disconnected data port; connect, terminate, or approve a scoped exception.');
        end
    end
end
if isfield(policy,'requireSubsystem') && policy.requireSubsystem && ~hasSubsystem
    addViolation('S01',inspection.file,'Task requires a meaningful executable subsystem.');
end
if isfield(policy,'expectedRootOutports') && ~isempty(policy.expectedRootOutports) && ...
        rootOutports ~= policy.expectedRootOutports
    addViolation('S02',inspection.file,'Root Outport count differs from interface contract.');
end
report.mandatoryPassed = isempty(report.violations);
report.limits = 'Only declared machine checks; independent equation, interface ordering, unit and dynamic-result review remains required.';
    function addViolation(rule,artifact,reason)
        report.violations(end+1) = struct('rule',rule,'artifact',artifact,'reason',reason);
    end
end
