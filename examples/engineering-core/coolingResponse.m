function r = coolingResponse(t, p)
%COOLINGRESPONSE Lumped Newton cooling with signed released energy.
% capacity [J/K], conductance [W/K], temperatures [K], time [s].
% Constant properties and ambient, spatially uniform body, no internal source.
% Negative energyReleased means ambient heats the body rather than cools it.
validateattributes(t, {'numeric'}, {'real','finite','vector','nonempty','nonnegative'});
assert(all(diff(t(:)) >= 0), 'engineering:CoolingTime', 'Times must be monotonically increasing.');
validateattributes(p, {'struct'}, {'scalar'});
validateattributes(p.capacity, {'numeric'}, {'real','finite','scalar','positive'});
validateattributes(p.conductance, {'numeric'}, {'real','finite','scalar','positive'});
validateattributes(p.initialTemperature, {'numeric'}, {'real','finite','scalar'});
validateattributes(p.ambientTemperature, {'numeric'}, {'real','finite','scalar'});
temperatureDifference = p.initialTemperature - p.ambientTemperature;
decayExponent = -(p.conductance / p.capacity) .* double(t);
r.temperature = p.ambientTemperature + temperatureDifference .* exp(decayExponent);
% expm1 preserves small-time energy instead of subtracting nearly equal K.
r.energyReleased = -p.capacity * temperatureDifference .* expm1(decayExponent);
r.time = t;
r.timeConstant = p.capacity / p.conductance;
assert(all(isfinite(r.temperature(:))) && all(isfinite(r.energyReleased(:))), ...
    'engineering:CoolingOverflow', 'Cooling results are not representable.');
end
