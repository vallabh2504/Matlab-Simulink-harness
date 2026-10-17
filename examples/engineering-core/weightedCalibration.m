function [theta, info] = weightedCalibration(A, b, w)
%WEIGHTEDCALIBRATION Weighted least squares using equilibrated SVD.
% w is inverse observation variance (relative scale is allowed). Coefficient
% units depend on columns of A; no normal equations or matrix inversion.
validateattributes(A, {'numeric'}, {'real','finite','2d','nonempty','nonsparse'});
validateattributes(b, {'numeric'}, {'real','finite','vector','numel',size(A,1)});
validateattributes(w, {'numeric'}, {'real','finite','vector','positive','numel',size(A,1)});
assert(size(A,1) >= size(A,2), 'engineering:CalibrationRank', 'Need at least as many observations as coefficients.');
A = double(A); b = double(b(:)); w = double(w(:));
% Weight normalization preserves the optimizer while avoiding large weights.
relativeRootWeight = sqrt(w / max(w));
weightedDesign = A .* relativeRootWeight;
weightedTarget = b .* relativeRootWeight;
columnScale = zeros(1,size(A,2));
for column = 1:size(A,2)
    columnScale(column) = norm(weightedDesign(:,column));
end
assert(all(columnScale > 0 & isfinite(columnScale)), 'engineering:CalibrationRank', ...
    'A has a zero or unrepresentable weighted column.');
equilibratedDesign = weightedDesign ./ columnScale;
[leftVectors, singularMatrix, rightVectors] = svd(equilibratedDesign, 'econ');
singularValues = diag(singularMatrix);
rankTolerance = max(size(equilibratedDesign)) * eps(singularValues(1));
assert(all(singularValues > rankTolerance), 'engineering:CalibrationRank', ...
    'Design is numerically rank deficient after column equilibration.');
scaledTheta = rightVectors * ((leftVectors' * weightedTarget) ./ singularValues);
theta = scaledTheta ./ columnScale.';
residual = A * theta - b;
info.weightedResidualNorm = norm(sqrt(w) .* residual);
info.equilibratedCondition = singularValues(1) / singularValues(end);
info.columnScale = columnScale;
info.rankTolerance = rankTolerance;
info.method = 'weight-normalized, column-equilibrated economy SVD';
assert(all(isfinite(theta)), 'engineering:CalibrationOverflow', 'Coefficients are not representable.');
end
