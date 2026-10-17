function artifacts = runEngineeringDemo(outputDirectory)
% Bootstrap canonical helpers; preserve direct callers' path and cwd.
root = fileparts(fileparts(fileparts(mfilename('fullpath'))));
previousPath = path;
pathCleanup = onCleanup(@() path(previousPath)); %#ok<NASGU>
addpath(fullfile(root,'matlab'));
artifacts = engineering.withRuntime(@() executeDemo(outputDirectory));
end

function artifacts = executeDemo(outputDirectory)
%RUNENGINEERINGDEMO Reproduce synthetic thermal/mechanical experiments.
% Parameters illustrate equations; they are not measurements of a real plant.
% Caller chooses a new empty output directory. No user files are overwritten.
validateattributes(outputDirectory, {'char','string'}, {'nonempty'});
if isfolder(outputDirectory)
    entries = dir(outputDirectory);
    assert(all(ismember({entries.name},{'.','..'})), 'engineering:DemoOutput', ...
        'Choose an empty output directory to preserve existing files.');
else
    mkdir(outputDirectory);
end
thermal = struct('L',0.4,'k',12,'n',65,'Tleft',300,'Tright',320, ...
    'q',@(x) 4000*ones(size(x)));
[position, temperature] = solveHeat1D(thermal);
reference = thermal.Tleft + (thermal.Tright-thermal.Tleft)*position/thermal.L ...
    + 4000*position.*(thermal.L-position)/(2*thermal.k);
heatFigure = figure('Visible','off','Color','w','Position',[100 100 850 500]);
heatCleanup = onCleanup(@() close(heatFigure));
plot(position,temperature,'-','LineWidth',1.8); hold on;
plot(position(1:8:end),reference(1:8:end),'o','MarkerSize',6);
xlabel('Position [m]'); ylabel('Temperature [K]');
title('Synthetic steady conduction: prescribed end temperatures');
legend('Centered finite difference','Analytic reference','Location','best'); grid on;
set(gca,'FontSize',11);
printAxes(heatFigure);
exportgraphics(heatFigure,fullfile(outputDirectory,'heat.png'),'Resolution',180);
exportgraphics(heatFigure,fullfile(outputDirectory,'heat.pdf'),'ContentType','vector');
writetable(table(position,temperature,reference),fullfile(outputDirectory,'heat.csv'));
clear heatCleanup;

coolingParameters = struct('capacity',1200,'conductance',8, ...
    'initialTemperature',360,'ambientTemperature',295);
coolingTime = (0:5:900).';
cooling = coolingResponse(coolingTime,coolingParameters);
coolingFigure = figure('Visible','off','Color','w','Position',[100 100 850 650]);
coolingCleanup = onCleanup(@() close(coolingFigure));
tiledlayout(2,1);
nexttile; plot(coolingTime,cooling.temperature,'LineWidth',1.8);
ylabel('Temperature [K]'); grid on; title('Synthetic lumped thermal cooling');
nexttile; plot(coolingTime,cooling.energyReleased/1000,'LineWidth',1.8);
xlabel('Time [s]'); ylabel('Energy released [kJ]'); grid on;
printAxes(coolingFigure);
exportgraphics(coolingFigure,fullfile(outputDirectory,'cooling.png'),'Resolution',180);
writetable(table(coolingTime,cooling.temperature,cooling.energyReleased, ...
    'VariableNames',{'time_s','temperature_K','energyReleased_J'}),fullfile(outputDirectory,'cooling.csv'));
clear coolingCleanup;

mechanics = struct('mass',2,'stiffness',18,'damping',1.2,'force',0, ...
    'initialDisplacement',0.1,'initialVelocity',0);
simulation = simulateOscillator(mechanics,(0:0.02:8).');
energy = 0.5*mechanics.mass*simulation.velocity.^2 ...
    + 0.5*mechanics.stiffness*simulation.displacement.^2;
assert(all(diff(energy) <= 1e-8), 'engineering:DemoEnergy', 'Unforced passive model increased energy.');
modelPath = buildOscillatorModel(mechanics,outputDirectory);
mechanicalFigure = figure('Visible','off','Color','w','Position',[100 100 850 750]);
mechanicalCleanup = onCleanup(@() close(mechanicalFigure));
tiledlayout(3,1);
nexttile; plot(simulation.time,simulation.displacement,'LineWidth',1.8);
ylabel('Displacement [m]'); grid on; title('Synthetic passive mass-spring-damper, actual Simulink');
nexttile; plot(simulation.time,simulation.velocity,'LineWidth',1.8);
ylabel('Velocity [m/s]'); grid on;
nexttile; plot(simulation.time,energy,'LineWidth',1.8);
xlabel('Time [s]'); ylabel('Stored energy [J]'); grid on;
printAxes(mechanicalFigure);
exportgraphics(mechanicalFigure,fullfile(outputDirectory,'mechanics.png'),'Resolution',180);
writetable(table(simulation.time,simulation.displacement,simulation.velocity,energy, ...
    'VariableNames',{'time_s','displacement_m','velocity_m_per_s','energy_J'}),fullfile(outputDirectory,'mechanics.csv'));
clear mechanicalCleanup;
[~,modelName,extension] = fileparts(modelPath);
artifacts = struct('parameters','Synthetic demonstration values, SI units', ...
    'modelFile',[modelName extension], 'heatMaxError_K',max(abs(temperature-reference)), ...
    'temperatureTimeConstant_s',coolingParameters.capacity/coolingParameters.conductance, ...
    'mechanicalEnergyInitial_J',energy(1),'mechanicalEnergyFinal_J',energy(end), ...
    'simulationSource',simulation.source);
artifacts.thermalParameters = rmfield(thermal,'q');
artifacts.thermalParameters.source_W_per_m3 = 4000;
artifacts.coolingParameters = coolingParameters;
artifacts.mechanicalParameters = mechanics;
file = fopen(fullfile(outputDirectory,'demo.json'),'w');
assert(file ~= -1,'engineering:DemoOutput','Cannot write demo metadata.');
fileCleanup = onCleanup(@() fclose(file));
fprintf(file,'%s\n',jsonencode(artifacts));
clear fileCleanup;
end

function printAxes(fig)
% Theme-independent scientific export: readable on a white page.
axesHandles = findall(fig,'Type','axes');
set(axesHandles,'Color','w','XColor','k','YColor','k','GridColor',[0.5 0.5 0.5]);
for index = 1:numel(axesHandles)
    set(axesHandles(index).Title,'Color','k');
    set(axesHandles(index).XLabel,'Color','k');
    set(axesHandles(index).YLabel,'Color','k');
end
legends = findall(fig,'Type','legend');
set(legends,'Color','w','TextColor','k');
end
