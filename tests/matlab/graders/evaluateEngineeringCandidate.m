function report = evaluateEngineeringCandidate(candidateDir,includeSimulink)
%EVALUATEENGINEERINGCANDIDATE Independent runner with per-family real status.
if nargin<2, includeSimulink=true; end
candidateDir=char(candidateDir);
assert(isfolder(candidateDir),'engineering:evaluator:Directory','Candidate directory missing.');
[~,attributes]=fileattrib(candidateDir); candidateDir=attributes.Name;
originalPath=path; cleanupPath=onCleanup(@() path(originalPath)); %#ok<NASGU>
graderDir=fileparts(mfilename('fullpath'));
% Clear prior candidate resolution before changing precedence. A new MATLAB
% process is still required for release-critical clean-start reproduction.
clear solveHeat1D weightedCalibration coolingResponse buildOscillatorModel simulateOscillator
addpath(candidateDir); addpath(graderDir,'-begin');
names={'solveHeat1D','weightedCalibration','coolingResponse','buildOscillatorModel','simulateOscillator'};
for j=1:numel(names)
    location=which(names{j});
    if ~isempty(location)
        assert(startsWith(location,[candidateDir,filesep],'IgnoreCase',ispc),'engineering:evaluator:Shadow',...
            'Candidate function %s resolves outside candidate directory.',names{j});
    end
end
report=struct('matlabVersion',version,'computer',computer,'candidateDirectory',candidateDir,...
    'evaluatedAtUtc',char(datetime('now','TimeZone','UTC','Format','yyyy-MM-dd''T''HH:mm:ssXXX')),...
    'results',[],'allRequiredPassed',false);
spec={ 'T01-T02 heat',@() gradeHeat(@solveHeat1D);...
       'T03 calibration',@() gradeCalibration(@weightedCalibration);...
       'T04 legacy cooling',@() gradeCooling(@coolingResponse)};
if includeSimulink
    spec(end+1,:)={'T05-T06 saved/integrated oscillator',@() gradeOscillator(@buildOscillatorModel,@simulateOscillator)};
end
rows=repmat(struct('family','','status','','evidence',struct(),'errorIdentifier','','errorMessage',''),size(spec,1),1);
for j=1:size(spec,1)
    rows(j).family=spec{j,1};
    try
        rows(j).evidence=spec{j,2}(); rows(j).status='VERIFIED';
    catch failure
        rows(j).status='FAILED';
        if startsWith(failure.identifier,'engineering:capability:'), rows(j).status='UNSUPPORTED'; end
        rows(j).errorIdentifier=failure.identifier; rows(j).errorMessage=failure.message;
    end
end
report.results=rows;
report.allRequiredPassed=all(strcmp({rows.status},'VERIFIED'));
report.untestedFamilies={'T07 fault repair process','T08 cross-session continuation',...
    'T09 independent standalone installation','T10 Stateflow thermostat'};
report.scope='Executed engineering core only; fixture passes are calibration, not comparative agent-run evidence.';
end
