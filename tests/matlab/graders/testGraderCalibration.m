function tests = testGraderCalibration
%TESTGRADERCALIBRATION Known-good, seeded faults, and valid unfamiliar solutions.
tests=functiontests(localfunctions);
end

function testGoodNumerical(testCase)
candidate=numericalFixtures('good');
verifyWarningFree(testCase,@() gradeHeat(candidate.heat));
verifyWarningFree(testCase,@() gradeCalibration(candidate.fit));
verifyWarningFree(testCase,@() gradeCooling(candidate.cooling));
end

function testAlternativeNumerical(testCase)
candidate=numericalFixtures('alternative');
verifyWarningFree(testCase,@() gradeHeat(candidate.heat));
verifyWarningFree(testCase,@() gradeCalibration(candidate.fit));
verifyWarningFree(testCase,@() gradeCooling(candidate.cooling));
end

function testSeededEquationFault(testCase)
candidate=numericalFixtures('wrong');
verifyError(testCase,@() gradeHeat(candidate.heat),'engineering:heat:Equation');
end

function testSeededWeightingFault(testCase)
candidate=numericalFixtures('wrong');
verifyError(testCase,@() gradeCalibration(candidate.fit),'engineering:fit:Optimality');
end

function testSeededDimensionalFault(testCase)
candidate=numericalFixtures('wrong');
verifyError(testCase,@() gradeCooling(candidate.cooling),'engineering:cooling:Energy');
end

function testMatrixExponentialReference(testCase)
p=struct('mass',2,'damping',0,'stiffness',8,'force',0,...
    'initialDisplacement',0.3,'initialVelocity',-0.2);
t=linspace(0,3,51)'; reference=oscillatorReference(p,t);
omega=sqrt(p.stiffness/p.mass);
closed=[p.initialDisplacement*cos(omega*t)+p.initialVelocity/omega*sin(omega*t),...
    -omega*p.initialDisplacement*sin(omega*t)+p.initialVelocity*cos(omega*t)];
verifyEqual(testCase,reference,closed,'AbsTol',2e-14);
end
