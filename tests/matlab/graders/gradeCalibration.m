function evidence = gradeCalibration(solve)
%GRADECALIBRATION Weighted sensor-fit oracle with scaling and permutation probes.
x=linspace(-2,3,41)'; A=[ones(size(x)),x,x.^2];
b=A*[0.7;-1.2;0.09]+0.013*cos(2.4*x); w=0.1+(x+2.3).^2;
B=sqrt(w).*A; d=sqrt(w).*b;
[Q,R]=qr(B,0); reference=R\(Q'*d);
[theta,info]=solve(A,b,w); theta=theta(:);
assert(numel(theta)==3 && all(isfinite(theta)),'engineering:fit:Shape','Invalid coefficients.');
residual=norm(B*theta-d);
optimal=norm(B*reference-d);
assert(residual<=optimal+1e-10*norm(d),'engineering:fit:Optimality','Weighted residual is not optimal.');
assert(norm(A*(theta-reference),inf)<1e-9*max(1,norm(b,inf)),...
    'engineering:fit:Prediction','Fit differs from independent QR predictions.');
assert(isstruct(info) && isfield(info,'weightedResidualNorm'),...
    'engineering:fit:Diagnostics','Weighted residual norm is required.');
assert(abs(info.weightedResidualNorm-residual)<1e-9*max(1,residual),...
    'engineering:fit:Diagnostics','Reported weighted residual differs from actual residual.');
perm=[2:2:40,1:2:41];
[permuted,~]=solve(A(perm,:),b(perm),w(perm));
assert(norm(A*(permuted(:)-theta),inf)<1e-8,'engineering:fit:Permutation','Row ordering changed the physical fit.');
scale=diag([1,1e5,1e-3]);
[scaled,~]=solve(A*scale,b,w);
assert(norm(A*scale*scaled(:)-A*theta,inf)<1e-7,...
    'engineering:fit:Conditioning','Column unit changes degraded predictions.');
% Nearly collinear data: accept any coefficients with near-optimal predictions.
u=linspace(0,1,30)'; near=[ones(size(u)),u,u+1e-7*sin(3*u)];
target=near*[1;2;-0.3]+1e-9*cos(u); weight=ones(size(u));
reference=pinv(near)*target;
[nearTheta,~]=solve(near,target,weight);
assert(norm(near*nearTheta(:)-target)<=norm(near*reference-target)+1e-8,...
    'engineering:fit:Conditioning','Near-collinear prediction accuracy failed.');
expectRejected(@() solve([A,A(:,1)],b,w));
expectRejected(@() solve(A,b,-w));
evidence=struct('weightedResidual',residual,'optimalResidual',optimal,...
    'nearCollinearCondition',cond(near));
end

function expectRejected(f)
rejected=false; try, f(); catch, rejected=true; end
assert(rejected,'engineering:fit:Domain','Invalid/rank-deficient problem was accepted.');
end
