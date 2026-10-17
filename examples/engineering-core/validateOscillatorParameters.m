function validateOscillatorParameters(p)
%VALIDATEOSCILLATORPARAMETERS Validate SI mass-spring-damper configuration.
validateattributes(p, {'struct'}, {'scalar'});
validateattributes(p.mass, {'numeric'}, {'real','finite','scalar','positive'});
validateattributes(p.stiffness, {'numeric'}, {'real','finite','scalar','positive'});
validateattributes(p.damping, {'numeric'}, {'real','finite','scalar','nonnegative'});
validateattributes(p.force, {'numeric'}, {'real','finite','scalar'});
validateattributes(p.initialDisplacement, {'numeric'}, {'real','finite','scalar'});
validateattributes(p.initialVelocity, {'numeric'}, {'real','finite','scalar'});
end
