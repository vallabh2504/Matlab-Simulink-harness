function [x, temperature] = solveHeat1D(p)
%SOLVEHEAT1D Steady 1-D conduction, -k*T'' = q, with fixed end temperatures.
% p.L [m], p.k [W/(m K)], p.n total nodes, p.q(x) [W/m^3],
% p.Tleft and p.Tright [K]. Constant conductivity and unit cross section.
% A centered finite difference gives second order accuracy for smooth q.
validateattributes(p, {'struct'}, {'scalar'}, mfilename, 'p');
validateattributes(p.L, {'numeric'}, {'real','finite','scalar','positive'});
validateattributes(p.k, {'numeric'}, {'real','finite','scalar','positive'});
validateattributes(p.n, {'numeric'}, {'real','finite','scalar','integer','>=',3});
validateattributes(p.Tleft, {'numeric'}, {'real','finite','scalar'});
validateattributes(p.Tright, {'numeric'}, {'real','finite','scalar'});
assert(isa(p.q,'function_handle'), 'engineering:HeatSource', 'q must be a vectorized function handle.');
x = linspace(0, double(p.L), double(p.n)).';
spacing = x(2) - x(1);
source = p.q(x(2:end-1));
validateattributes(source, {'numeric'}, {'real','finite','vector','numel',p.n-2});
interiorCount = p.n - 2;
diagonal = ones(interiorCount,1);
operator = spdiags([-diagonal, 2*diagonal, -diagonal], -1:1, interiorCount, interiorCount);
rightHandSide = source(:) * (spacing^2 / p.k);
rightHandSide(1) = rightHandSide(1) + p.Tleft;
rightHandSide(end) = rightHandSide(end) + p.Tright;
temperature = [p.Tleft; operator \ rightHandSide; p.Tright];
assert(all(isfinite(temperature)), 'engineering:HeatOverflow', 'Heat solve produced nonfinite temperatures.');
end
