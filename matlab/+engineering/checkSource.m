function report = checkSource(sourceRoot)
%CHECKSOURCE Native Code Analyzer plus deliberately limited source guard scan.
% Guard matches are review candidates, not AST proof. This helper does not
% execute source or certify mathematics; inspect every candidate and analyzer
% diagnostic. See docs/standards/matlab.md for exception disposition.
assert((ischar(sourceRoot) && isrow(sourceRoot)) || (isstring(sourceRoot) && isscalar(sourceRoot)), ...
    'engineering:SourceRoot','Source root must be a text scalar.');
assert(isfolder(sourceRoot), 'engineering:SourceRoot', 'Source directory does not exist.');
files = dir(fullfile(sourceRoot,'**','*.m'));
report.release = version('-release');
report.analyzer = 'checkcode native default settings, -id';
report.files = struct('path',{},'analyzerMessages',{},'guardCandidates',{});
patterns = { ...
    'M01','(?m)^\s*(clear\s+all|bdclose\s*\(?\s*[''" ]*all)\b','Session-wide destruction'; ...
    'M02','(?m)^\s*global\s+\w','Implicit global ownership'; ...
    'M02','\b(evalin|assignin)\s*\(\s*[''"]base[''"]','Base-workspace coupling'; ...
    'M03','\bcd\s*\(','Working-directory mutation'; ...
    'M04','([A-Za-z]:[/\\]Users[/\\]|/home/|/Users/)','Personal absolute path'; ...
    'N03','\binv\s*\(','Explicit inverse: inspect numerical rationale'; ...
    'N03','\beval\s*\(','Dynamic evaluation: inspect necessity'};
for index = 1:numel(files)
    sourcePath = fullfile(files(index).folder,files(index).name);
    sourceText = fileread(sourcePath);
    candidates = struct('rule',{},'line',{},'reason',{},'matchedText',{});
    for ruleIndex = 1:size(patterns,1)
        [starts,ends] = regexp(sourceText,patterns{ruleIndex,2});
        for matchIndex = 1:numel(starts)
            candidate.rule = patterns{ruleIndex,1};
            candidate.line = 1 + count(sourceText(1:starts(matchIndex)-1),newline);
            candidate.reason = patterns{ruleIndex,3};
            candidate.matchedText = sourceText(starts(matchIndex):ends(matchIndex));
            candidates(end+1) = candidate; %#ok<AGROW>
        end
    end
    report.files(index).path = sourcePath;
    report.files(index).analyzerMessages = checkcode(sourcePath,'-id');
    report.files(index).guardCandidates = candidates;
end
report.complete = true;
report.note = 'Native findings and literal candidates require disposition; no universal style score or automatic mathematical pass.';
end
