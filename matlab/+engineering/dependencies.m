function report = dependencies(entryFiles)
%DEPENDENCIES Use native dependency and MATLAB Project APIs without activation.
% Add relevant project paths explicitly before calling; this does not open a
% project or run startup callbacks. Dynamic dependencies can remain unknown.
validateattributes(entryFiles, {'char','string','cell'}, {'nonempty'});
report.release = version('-release');
[report.files,report.products] = matlab.codetools.requiredFilesAndProducts(entryFiles);
report.currentProject = struct('open',false,'root','','name','');
if ~isempty(which('matlab.project.currentProject'))
    project = matlab.project.currentProject;
    if ~isempty(project)
        report.currentProject.open = true;
        report.currentProject.root = char(project.RootFolder);
        report.currentProject.name = char(project.Name);
    end
end
report.limitations = ['Only resolvable paths and installed products are observable; ' ...
    'dynamic eval, callbacks, variants, external files and missing products require inspection.'];
end
