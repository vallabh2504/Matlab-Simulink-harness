function candidate = modelFixtures(kind)
%MODELFixtures Native Simulink calibration with two genuinely distinct topologies.
assert(any(strcmp(kind,{'good','alternative','wrong'})),'engineering:fixture:Kind','Unknown fixture.');
candidate=struct('build',@(p,d) build(p,d,kind),'simulate',@(p,t) simulate(p,t,kind));
end

function file=build(p,directory,kind)
root=fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
previousPath=path;pathCleanup=onCleanup(@()path(previousPath)); %#ok<NASGU>
addpath(fullfile(root,'matlab'));
file=engineering.withRuntime(@()nativeBuild(p,directory,kind));
end

function file=nativeBuild(p,directory,kind)
[~,name]=fileparts(tempname); new_system(name);
cleanup=onCleanup(@() close_system(name,0)); %#ok<NASGU>
set_param(name,'Solver','ode45','RelTol','1e-8','AbsTol','1e-10','MaxStep','0.002');
system=[name,'/Mechanics'];
add_block('simulink/Ports & Subsystems/Subsystem',system);
delete_block([system,'/In1']); delete_block([system,'/Out1']);
add_block('simulink/Ports & Subsystems/In1',[system,'/Force']);
add_block('simulink/Ports & Subsystems/Out1',[system,'/Displacement'],'Port','1');
add_block('simulink/Ports & Subsystems/Out1',[system,'/Velocity'],'Port','2');
if strcmp(kind,'alternative')
    add_block('simulink/Math Operations/Sum',[system,'/Balance'],'Inputs','+--');
    add_block('simulink/Math Operations/Gain',[system,'/InverseMass'],'Gain',num2str(1/p.mass,17));
    add_block('simulink/Continuous/Integrator',[system,'/Speed'],'InitialCondition',num2str(p.initialVelocity,17));
    add_block('simulink/Continuous/Integrator',[system,'/Position'],'InitialCondition',num2str(p.initialDisplacement,17));
    add_block('simulink/Math Operations/Gain',[system,'/DampingForce'],'Gain',num2str(p.damping,17));
    add_block('simulink/Math Operations/Gain',[system,'/SpringForce'],'Gain',num2str(p.stiffness,17));
    lines={'Force/1','Balance/1';'Balance/1','InverseMass/1';'InverseMass/1','Speed/1';...
        'Speed/1','Position/1';'Speed/1','DampingForce/1';'Position/1','SpringForce/1';...
        'DampingForce/1','Balance/2';'SpringForce/1','Balance/3';...
        'Position/1','Displacement/1';'Speed/1','Velocity/1'};
else
    damping=p.damping;
    if strcmp(kind,'wrong'), damping=-p.damping; end % seeded destabilizing sign
    A=[0,1;-p.stiffness/p.mass,-damping/p.mass];
    add_block('simulink/Continuous/State-Space',[system,'/Dynamics'],...
        'A',mat2str(A,17),'B',mat2str([0;1/p.mass],17),'C','eye(2)','D','[0;0]',...
        'InitialCondition',mat2str([p.initialDisplacement;p.initialVelocity],17));
    add_block('simulink/Signal Routing/Demux',[system,'/States'],'Outputs','2');
    lines={'Force/1','Dynamics/1';'Dynamics/1','States/1';...
        'States/1','Displacement/1';'States/2','Velocity/1'};
end
for j=1:size(lines,1), add_line(system,lines{j,1},lines{j,2},'autorouting','on'); end
add_block('simulink/Sources/Constant',[name,'/AppliedForce'],'Value',num2str(p.force,17));
add_block('simulink/Ports & Subsystems/Out1',[name,'/Displacement'],'Port','1');
add_block('simulink/Ports & Subsystems/Out1',[name,'/Velocity'],'Port','2');
add_line(name,'AppliedForce/1','Mechanics/1','autorouting','on');
add_line(name,'Mechanics/1','Displacement/1','autorouting','on');
add_line(name,'Mechanics/2','Velocity/1','autorouting','on');
file=fullfile(directory,[name,'.slx']); save_system(name,file);
end

function r=simulate(p,t,kind)
root=fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))));
previousPath=path;pathCleanup=onCleanup(@()path(previousPath)); %#ok<NASGU>
addpath(fullfile(root,'matlab'));
r=engineering.withRuntime(@()nativeSimulate(p,t,kind));
end

function r=nativeSimulate(p,t,kind)
directory=tempname; mkdir(directory); folderCleanup=onCleanup(@() rmdir(directory,'s')); %#ok<NASGU>
file=build(p,directory,kind); [~,name]=fileparts(file); load_system(file);
modelCleanup=onCleanup(@() close_system(name,0)); %#ok<NASGU>
out=sim(name,'StopTime',num2str(t(end),17),'SaveOutput','on','SaveFormat','Dataset',...
    'OutputSaveName','fixtureOutputs','ReturnWorkspaceOutputs','on');
data=out.get('fixtureOutputs'); first=data.getElement(1).Values; second=data.getElement(2).Values;
r=struct('time',t,'displacement',interp1(first.Time,first.Data(:),t,'pchip'),...
    'velocity',interp1(second.Time,second.Data(:),t,'pchip'));
end
