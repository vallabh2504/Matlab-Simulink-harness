function tests = testModelGraderCalibration
tests=functiontests(localfunctions);
end

function setupOnce(testCase)
assumeTrue(testCase,~isempty(which('sim')) && license('test','Simulink'),...
    'Simulink unavailable: model calibration is unsupported, not passed.');
end

function testStateSpaceFixture(testCase)
fixture=modelFixtures('good');
verifyWarningFree(testCase,@() gradeOscillator(fixture.build,fixture.simulate));
end

function testIntegratorAlternative(testCase)
fixture=modelFixtures('alternative');
verifyWarningFree(testCase,@() gradeOscillator(fixture.build,fixture.simulate));
end

function testDampingSignFault(testCase)
fixture=modelFixtures('wrong');
verifyError(testCase,@() gradeOscillator(fixture.build,fixture.simulate),'engineering:model:Dynamics');
end
