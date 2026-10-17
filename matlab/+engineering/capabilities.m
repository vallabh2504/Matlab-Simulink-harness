function report = capabilities()
%CAPABILITIES Observe installed products, licenses and native API presence.
% Presence/license does not prove a feature works. No license checkout occurs.
report.matlabVersion = version;
report.release = version('-release');
report.computer = computer;
report.timestampUTC = char(datetime('now','TimeZone','UTC','Format','yyyy-MM-dd''T''HH:mm:ssXXX'));
report.products = ver;
report.simulink = feature('Simulink','Simulink','new_system');
report.stateflow = feature('Stateflow','Stateflow','sfroot');
report.simulinkCheck = feature('Simulink Check','SL_Verification_Validation','ModelAdvisor.run');
report.simulinkTest = feature('Simulink Test','Simulink_Test','sltest.testmanager.TestFile');
report.designVerifier = feature('Simulink Design Verifier','Simulink_Design_Verifier','sldvrun');
report.codeAnalyzerPresent = ~isempty(which('checkcode'));
report.codeIssuesPresent = ~isempty(which('codeIssues'));
report.dependencyAnalysisPresent = ~isempty(which('matlab.codetools.requiredFilesAndProducts'));
report.projectAPIPresent = ~isempty(which('matlab.project.currentProject'));
report.matlabMCP = 'UNKNOWN: inspect the agent runtime connection, not MATLAB product licenses';
report.agenticToolkits = 'UNKNOWN: optional toolkits are not installed or certified by this probe';
report.note = 'Feature execution status is UNTESTED until an independent real exercise succeeds.';
    function observation = feature(productName, licenseName, apiName)
        observation.installed = any(strcmp({report.products.Name},productName));
        observation.apiPresent = ~isempty(which(apiName));
        observation.licenseAvailable = logical(license('test',licenseName));
        observation.executionStatus = 'UNTESTED';
        if ~observation.installed || ~observation.apiPresent || ~observation.licenseAvailable
            observation.executionStatus = 'UNSUPPORTED in observed environment';
        end
    end
end
