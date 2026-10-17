function evidence = gradeCooling(solve)
%GRADECOOLING Closed form, energy balance and protected legacy behavior.
t=[0;0.17;2.8;18;45;120];
p=struct('capacity',240,'conductance',7,'initialTemperature',352,'ambientTemperature',293);
r=solve(t,p); [temperature,energy]=fields(r,t);
reference=p.ambientTemperature+(p.initialTemperature-p.ambientTemperature)*exp(-p.conductance*t/p.capacity);
err=max(abs(temperature-reference));
assert(err<1e-9*max(abs(reference)),'engineering:cooling:Legacy','Legacy thermal response changed.');
assert(max(abs(energy-p.capacity*(p.initialTemperature-temperature)))<1e-8*max(1,max(abs(energy))),...
    'engineering:cooling:Energy','Heat release has incorrect magnitude or units.');
assert(all(diff(temperature)<=1e-10) && all(energy>=-1e-10),...
    'engineering:cooling:Physical','Cooling monotonicity/energy sign failed.');
p.initialTemperature=281;
r=solve(t,p); [temperature,energy]=fields(r,t);
assert(all(diff(temperature)>=-1e-10) && all(energy<=1e-10),...
    'engineering:cooling:Physical','Heating from a cold initial state has wrong signs.');
p.initialTemperature=p.ambientTemperature;
r=solve(t,p); [temperature,energy]=fields(r,t);
assert(max(abs(temperature-p.ambientTemperature))<1e-10 && max(abs(energy))<1e-10,...
    'engineering:cooling:Equilibrium','Equilibrium must remain unchanged.');
bad=p; bad.capacity=-1; expectRejected(@() solve(t,bad));
expectRejected(@() solve([0;-1],p));
evidence=struct('legacyMaxTemperatureError',err,'energyUnit','J');
end

function [temperature,energy]=fields(r,t)
assert(isstruct(r) && all(isfield(r,{'temperature','energyReleased'})),...
    'engineering:cooling:Interface','Required fields missing.');
temperature=r.temperature(:); energy=r.energyReleased(:);
assert(numel(temperature)==numel(t) && numel(energy)==numel(t) && ...
    all(isfinite(temperature)) && all(isfinite(energy)),...
    'engineering:cooling:Shape','Output shape or finite values failed.');
end

function expectRejected(f)
rejected=false; try, f(); catch, rejected=true; end
assert(rejected,'engineering:cooling:Domain','Invalid domain was accepted.');
end
