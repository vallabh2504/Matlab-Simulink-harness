function candidate = numericalFixtures(kind)
%NUMERICALFIXTURES Calibration artifacts; never count these as agent successes.
candidate=struct('heat',@heat,'fit',@fit,'cooling',@cooling);
if strcmp(kind,'wrong')
    candidate.heat=@wrongHeat; candidate.fit=@wrongFit; candidate.cooling=@wrongCooling;
elseif strcmp(kind,'alternative')
    candidate.heat=@alternativeHeat; candidate.fit=@alternativeFit; candidate.cooling=@alternativeCooling;
else
    assert(strcmp(kind,'good'),'engineering:fixture:Kind','Unknown fixture.');
end
end

function [x,T]=heat(p)
validateHeat(p); x=linspace(0,p.L,p.n)'; h=x(2)-x(1);
matrix=spdiags(repmat([-1,2,-1],p.n-2,1),-1:1,p.n-2,p.n-2);
rhs=p.q(x(2:end-1))*h^2/p.k; rhs=rhs(:);
rhs(1)=rhs(1)+p.Tleft; rhs(end)=rhs(end)+p.Tright;
T=[p.Tleft;matrix\rhs;p.Tright];
end

function [x,T]=alternativeHeat(p)
% Independent Green-function integral solution, not finite differences.
validateHeat(p); x=linspace(0,p.L,p.n)'; T=zeros(size(x));
for j=1:numel(x)
    position=x(j);
    left=integral(@(s) s.*p.q(s),0,position,'AbsTol',1e-11,'RelTol',1e-11);
    right=integral(@(s) (p.L-s).*p.q(s),position,p.L,'AbsTol',1e-11,'RelTol',1e-11);
    T(j)=p.Tleft+(p.Tright-p.Tleft)*position/p.L+...
        ((p.L-position)*left+position*right)/(p.k*p.L);
end
end

function validateHeat(p)
assert(p.L>0 && p.k>0 && p.n>=3 && p.n==fix(p.n),'engineering:fixture:Domain','Invalid heat domain.');
end

function [theta,info]=fit(A,b,w)
validateFit(A,b,w); B=sqrt(w(:)).*A; d=sqrt(w(:)).*b(:);
[Q,R]=qr(B,0); theta=R\(Q'*d);
info=struct('weightedResidualNorm',norm(B*theta-d));
end

function [theta,info]=alternativeFit(A,b,w)
validateFit(A,b,w); B=sqrt(w(:)).*A; d=sqrt(w(:)).*b(:);
columnNorm=sqrt(sum(B.^2,1)); normalized=B./columnNorm;
[U,S,V]=svd(normalized,'econ'); theta=(V*(S\(U'*d)))./columnNorm';
info=struct('weightedResidualNorm',norm(B*theta-d));
end

function validateFit(A,b,w)
assert(size(A,1)==numel(b) && numel(b)==numel(w) && all(w>0) && ...
    all(isfinite(A(:))) && all(isfinite(b(:))) && all(isfinite(w(:))) && ...
    rank(A)==size(A,2),'engineering:fixture:Domain','Invalid calibration domain.');
end

function r=cooling(t,p)
validateCooling(t,p);
temperature=p.ambientTemperature+(p.initialTemperature-p.ambientTemperature)*exp(-p.conductance*t/p.capacity);
r=struct('temperature',temperature,'energyReleased',p.capacity*(p.initialTemperature-temperature));
end

function r=alternativeCooling(t,p)
validateCooling(t,p);
change=(p.initialTemperature-p.ambientTemperature)*(-expm1(-p.conductance*t/p.capacity));
r=struct('temperature',p.initialTemperature-change,'energyReleased',p.capacity*change);
end

function validateCooling(t,p)
assert(p.capacity>0 && p.conductance>0 && all(isfinite(t)) && all(t>=0) && all(diff(t)>=0),...
    'engineering:fixture:Domain','Invalid cooling domain.');
end

function [x,T]=wrongHeat(p)
[x,T]=heat(p); T=T+0.1*sin(pi*x/p.L); % plausible but wrong energy balance
end

function [theta,info]=wrongFit(A,b,w)
validateFit(A,b,w); theta=A\b; % wrong: ignores heteroscedastic weighting
info=struct('weightedResidualNorm',norm(sqrt(w(:)).*(A*theta-b(:))));
end

function r=wrongCooling(t,p)
r=cooling(t,p); r.energyReleased=r.energyReleased/p.capacity; % kelvin passed off as joules
end
