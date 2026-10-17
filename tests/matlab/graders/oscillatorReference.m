function state = oscillatorReference(p,t)
%OSCILLATORREFERENCE Exact constant-input state solution, including critical damping.
generator=[0,1,0;-p.stiffness/p.mass,-p.damping/p.mass,p.force/p.mass;0,0,0];
initial=[p.initialDisplacement;p.initialVelocity;1];
state=zeros(numel(t),2);
for j=1:numel(t)
    value=expm(generator*t(j))*initial;
    state(j,:)=value(1:2)';
end
end
