function evidence = gradeHeat(solve)
%GRADEHEAT Independent conduction oracle: polynomial, convergence, invariance.
p = struct('L',1.7,'k',4.3,'n',31,'Tleft',291,'Tright',317);
source = 63; p.q = @(x) source + zeros(size(x));
[x,T] = solve(p); x=x(:); T=T(:);
assert(numel(x)==p.n && numel(T)==p.n,'engineering:heat:Shape','Wrong grid size.');
assert(all(isfinite(T)) && max(abs(x-linspace(0,p.L,p.n)'))<1e-12,...
    'engineering:heat:Grid','Grid must be finite, uniform and include endpoints.');
ref=p.Tleft+(p.Tright-p.Tleft)*x/p.L+source*x.*(p.L-x)/(2*p.k);
quadraticError=max(abs(T-ref));
assert(quadraticError<1e-9*max(abs(ref)),'engineering:heat:Equation','Conduction equation or boundary mismatch.');
% Scaling k and source together must leave temperature unchanged.
p.k=2*p.k; p.q=@(x) 2*source+zeros(size(x));
[~,scaled]=solve(p);
assert(max(abs(scaled(:)-T))<1e-9*max(abs(T)),'engineering:heat:Scaling','Conductivity/source scaling failed.');
errors=zeros(1,3);
for j=1:3
    p.n=2^(j+3)+1; p.Tleft=0; p.Tright=0;
    p.q=@(x) p.k*(pi/p.L)^2*sin(pi*x/p.L);
    [x,T]=solve(p); x=x(:); T=T(:);
    assert(numel(x)==p.n && numel(T)==p.n,'engineering:heat:Shape','Wrong refined grid size.');
    assert(max(abs(x-linspace(0,p.L,p.n)'))<1e-12,'engineering:heat:Grid','Refined grid differs from contract.');
    errors(j)=max(abs(T-sin(pi*x/p.L)));
end
assert(all(isfinite(errors)) && errors(3)<3e-4,'engineering:heat:Accuracy','Finest-grid sinusoidal error is too large.');
% Exact higher-order/analytic methods are also valid; do not reject zero errors.
if errors(1)>1e-10 && errors(2)>1e-10
    assert(errors(1)/errors(2)>3.5,'engineering:heat:Convergence','Grid refinement lacks second-order convergence.');
end
if errors(2)>1e-10 && errors(3)>1e-10
    assert(errors(2)/errors(3)>3.5,'engineering:heat:Convergence','Fine-grid refinement lacks second-order convergence.');
end
bad=p; bad.k=0; expectRejected(@() solve(bad));
bad=p; bad.n=2; expectRejected(@() solve(bad));
evidence=struct('quadraticMaxError',quadraticError,'refinementErrors',errors);
end

function expectRejected(f)
rejected=false; try, f(); catch, rejected=true; end
assert(rejected,'engineering:heat:Domain','Invalid physical domain was accepted.');
end
