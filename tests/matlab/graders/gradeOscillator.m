function evidence = gradeOscillator(build,simulate)
% Bootstrap canonical helpers; preserve direct callers' path and cwd.
root = fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
previousPath = path;
pathCleanup = onCleanup(@() path(previousPath)); %#ok<NASGU>
addpath(fullfile(root,'matlab'));
evidence = engineering.withRuntime(@() executeGrade(build,simulate));
end

function evidence = executeGrade(build,simulate)
%GRADEOSCILLATOR Reopened model execution plus independent integration check.
assert(~isempty(which('sim')) && license('test','Simulink'),...
    'engineering:capability:Simulink','Simulink execution is unavailable.');
folder=tempname; mkdir(folder); cleanupFolder=onCleanup(@() rmdir(folder,'s')); %#ok<NASGU>
p=struct('mass',1.7,'damping',0.43,'stiffness',5.8,'force',0.7,...
    'initialDisplacement',0.31,'initialVelocity',-0.22);
previousModels=find_system('Type','block_diagram');
file=build(p,folder);
assert(isfile(file),'engineering:model:Save','Builder did not return a saved model.');
[~,name,extension]=fileparts(file);
assert(strcmpi(extension,'.slx'),'engineering:model:Format','Model must be saved as SLX.');
assert(~any(strcmp(previousModels,name)),'engineering:model:Collision',...
    'Builder returned an existing session model; evaluator will not close it.');
% Enforce authoritative saved artifact by discarding a builder's loaded copy.
if bdIsLoaded(name), close_system(name,0); end
load_system(file); cleanupModel=onCleanup(@() closeIfLoaded(name)); %#ok<NASGU>
ports=find_system(name,'SearchDepth',1,'BlockType','Outport');
assert(numel(ports)==2,'engineering:model:Ports','Need displacement and velocity root outputs.');
subsystems=find_system(name,'LookUnderMasks','all','BlockType','SubSystem');
meaningful=false;
for j=1:numel(subsystems)
    inner=find_system(subsystems{j},'SearchDepth',1,'Type','Block');
    if numel(inner)>=4, meaningful=true; end
end
assert(meaningful,'engineering:model:Hierarchy','No meaningful executable subsystem found.');
set_param(name,'SimulationCommand','update');
output=sim(name,'StopTime','6','SaveOutput','on','OutputSaveName','engineeringOracleOutput',...
    'SaveFormat','Dataset','ReturnWorkspaceOutputs','on');
data=output.get('engineeringOracleOutput');
assert(isa(data,'Simulink.SimulationData.Dataset') && numElements(data)==2,...
    'engineering:model:Outputs','Expected two actually simulated root output signals.');
displacement=data.getElement(1).Values; velocity=data.getElement(2).Values;
actual=[displacement.Data(:),interp1(velocity.Time,velocity.Data(:),displacement.Time,'linear')];
reference=oscillatorReference(p,displacement.Time);
directError=assertClose(actual,reference);
assert(displacement.Time(end)>=6-1e-9,'engineering:model:Stop','Simulation terminated early.');
% Integrated path must match separately derived dynamics across changed parameters.
errors=zeros(1,3); t=linspace(0,5,251)';
for scenario=1:3
    if scenario==2, p.damping=2*sqrt(p.mass*p.stiffness); p.force=-1.3; end
    if scenario==3, p.mass=0.8; p.damping=0; p.stiffness=3.1; p.force=0; end
    r=simulate(p,t);
    assert(isstruct(r) && all(isfield(r,{'time','displacement','velocity'})),...
        'engineering:integration:Interface','Integrated output fields are missing.');
    assert(numel(r.time)==numel(t) && max(abs(r.time(:)-t))<1e-10,...
        'engineering:integration:Time','Output times differ from requested vector.');
    actual=[r.displacement(:),r.velocity(:)];
    errors(scenario)=assertClose(actual,oscillatorReference(p,t));
    if scenario==3
        energy=0.5*p.mass*actual(:,2).^2+0.5*p.stiffness*actual(:,1).^2;
        assert(max(abs(energy-energy(1)))<5e-4*max(1,energy(1)),...
            'engineering:integration:Energy','Undamped system violates energy conservation.');
    end
end
evidence=struct('savedModelMaxError',directError,'integratedScenarioMaxErrors',errors);
end

function err=assertClose(actual,reference)
assert(isequal(size(actual),size(reference)) && all(isfinite(actual(:))),...
    'engineering:model:Shape','Model output dimensions or finite values failed.');
bound=2e-6+2e-4*abs(reference);
err=max(abs(actual(:)-reference(:)));
assert(all(abs(actual(:)-reference(:))<=bound(:)),...
    'engineering:model:Dynamics','Executed dynamics differ from independent mechanics oracle.');
end

function closeIfLoaded(name)
if bdIsLoaded(name), close_system(name,0); end
end
