"""Harness-run mutation probe: plant small defects in copies, run a declared test check.

A surviving mutant is evidence for the reviewer, not a verdict: some mutants are
equivalent (they do not change behaviour) and the reviewer judges each survivor.
Copies live under .matlab-harness/mutation and never touch scoped artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import time
import uuid

from .project import ProjectError, atomic_json, digest, now, value_digest

# (label, pattern, replacement). Binary + and - only when spaced, so unary signs,
# exponents (1e-3) and ranges keep their meaning.
OPERATORS = (
    ("<= to <", r"<=", "<"),
    (">= to >", r">=", ">"),
    ("< to <=", r"(?<![<>=~])<(?!=)", "<="),
    ("> to >=", r"(?<![<>=~])>(?!=)", ">="),
    ("== to ~=", r"==", "~="),
    ("+ to -", r"(?<=[\w)\].']) \+ (?=[\w(.])", " - "),
    ("- to +", r"(?<=[\w)\].']) - (?=[\w(.])", " + "),
    (".* to ./", r"\.\*", "./"),
    ("min to max", r"\bmin\(", "max("),
    ("max to min", r"\bmax\(", "min("),
    ("exp(-x) to exp(x)", r"\bexp\(-", "exp("),
    ("abs removed", r"\babs\(", "("),
)
SKIP_LINE = re.compile(r"^\s*(function|arguments|end\b|error\(|warning\(|fprintf|disp\(|sprintf|assert|%)")
TEST_PATH = re.compile(r"(^|/)tests?/|[Tt]est[^/]*\.m$|^test")
COPY_IGNORE = shutil.ignore_patterns(".git", ".matlab-harness", "slprj", "__pycache__", "*.asv", "*.slxc")


def _code_part(line):
    """The line before a % comment, ignoring % inside quoted text."""
    quote = None
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char == '"' or (char == "'" and (index == 0 or not re.match(r"[\w)\].']", line[index - 1]))):
            quote = char
        elif char == "%":
            return line[:index]
    return line


def candidates(root, sources):
    sites = []
    for name in sources:
        lines = (Path(root) / name).read_text(encoding="utf-8", errors="replace").splitlines()
        for number, line in enumerate(lines, 1):
            if SKIP_LINE.match(line):
                continue
            code = _code_part(line)
            # Mutating text inside quotes changes messages, not behaviour.
            masked = re.sub(r"'[^']*'|\"[^\"]*\"", lambda m: "\0" * len(m.group()), code)
            for label, pattern, replacement in OPERATORS:
                for match in re.finditer(pattern, masked):
                    mutated = line[:match.start()] + replacement + line[match.end():]
                    sites.append({"file": name, "line": number, "operator": label,
                                  "original": line.strip(), "mutant": mutated.strip(),
                                  "start": match.start(), "end": match.end(), "replacement": replacement})
    return sites


def choose(sites, count, seed):
    """Spread the picks over operators and files, deterministically per snapshot."""
    generator = random.Random(seed)
    groups = {}
    for site in sites:
        groups.setdefault(site["operator"], []).append(site)
    for group in groups.values():
        generator.shuffle(group)
    picked, order = [], sorted(groups)
    generator.shuffle(order)
    while len(picked) < count and any(groups.values()):
        for label in order:
            if groups[label] and len(picked) < count:
                picked.append(groups[label].pop())
    return picked


def _apply(copy, site):
    path = copy / site["file"]
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    line = lines[site["line"] - 1]
    lines[site["line"] - 1] = line[:site["start"]] + site["replacement"] + line[site["end"]:]
    path.write_text("".join(lines), encoding="utf-8")


def _retarget(argv, project_root, copy):
    forms = {str(project_root), str(project_root).replace("\\", "/")}
    out = []
    for argument in argv:
        for form in forms:
            argument = argument.replace(form, str(copy).replace("\\", "/"))
        out.append(argument)
    return out


def _single_session(argv, project_root, copies, workdir, timeout):
    """Run every copy in one MATLAB process: a cold start can take minutes."""
    expression = argv[2]
    runner = workdir / "harness_mutation_runner.m"
    results = workdir / "results.txt"
    lines = ["function harness_mutation_runner()", "p0 = path; w0 = pwd;",
             "fid = fopen(" + _matlab_text(results) + ", 'a');"]
    for index, copy in enumerate(copies):
        lines += [f"cd({_matlab_text(copy)}); rehash;",
                  "try", f"    evalc('harness_mutation_case_{index}()'); status = 'PASSED'; message = '';",
                  "catch err", "    status = 'FAILED'; message = err.identifier;", "end",
                  "path(p0); cd(w0); clear('functions');",
                  f"fprintf(fid, '%d\\t%s\\t%s\\n', {index}, status, message);"]
    lines += ["fclose(fid);", "end"]
    for index, copy in enumerate(copies):
        lines += [f"function harness_mutation_case_{index}()", _retarget([expression], project_root, copy)[0], "end"]
    runner.write_text("\n".join(lines) + "\n", encoding="utf-8")
    command = [argv[0], "-batch", f"cd({_matlab_text(workdir)}); harness_mutation_runner"]
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=workdir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        process.wait(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        from .runtime import _stop_owned_process
        _stop_owned_process(process)
        timed_out = True
    statuses = {}
    if results.is_file():
        for row in results.read_text(encoding="utf-8", errors="replace").splitlines():
            index, status, *message = row.split("\t")
            statuses[int(index)] = (status, message[0] if message else "")
    return statuses, timed_out, time.monotonic() - started


def _matlab_text(path):
    return "'" + str(path).replace("\\", "/").replace("'", "''") + "'"


def _separate_processes(argv, project_root, copies, timeout):
    statuses, timed_out, started = {}, False, time.monotonic()
    for index, copy in enumerate(copies):
        left = timeout - (time.monotonic() - started)
        if left <= 0:
            timed_out = True
            break
        try:
            code = subprocess.run(_retarget(argv, project_root, copy), cwd=copy, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=left).returncode
            statuses[index] = ("PASSED" if code == 0 else "FAILED", f"exit {code}")
        except subprocess.TimeoutExpired:
            statuses[index] = ("TIMEOUT", "")
            timed_out = True
            break
    return statuses, timed_out, time.monotonic() - started


def run_mutation(project, owner, stage, timeout):
    """Plant mutants in copies, run the configured test check on each, record the result."""
    data = project.load()
    config = data.get("runtime", {}).get("mutation") or {}
    check = config.get("check")
    if check not in data["commands"]:
        raise ProjectError("Mutation probe needs runtime.mutation.check naming a declared check")
    count = int(config.get("count", 6))
    snapshot = project.snapshot(data)
    seed = value_digest(snapshot)
    sources = sorted(name for name, fingerprint in snapshot["artifacts"].items()
                     if fingerprint is not None and name.endswith(".m") and not TEST_PATH.search(name))
    sites = candidates(project.root, sources)
    picked = choose(sites, count, seed)
    identifier = uuid.uuid4().hex[:12]
    workdir = project.control / "mutation" / identifier
    workdir.mkdir(parents=True)
    copies = []
    try:
        for index in range(len(picked) + 1):
            copy = workdir / f"m{index:02d}"
            shutil.copytree(project.root, copy, ignore=COPY_IGNORE)
            if index:
                _apply(copy, picked[index - 1])
            copies.append(copy)
        argv = data["commands"][check]
        single = (len(argv) == 3 and argv[1] == "-batch" and "matlab" in Path(argv[0]).name.lower()
                  and not re.search(r"\b(exit|quit)\b", argv[2]))
        if single:
            statuses, timed_out, seconds = _single_session(argv, project.root, copies, workdir, timeout)
        else:
            statuses, timed_out, seconds = _separate_processes(argv, project.root, copies, timeout)
    finally:
        for copy in copies:
            shutil.rmtree(copy, ignore_errors=True)
    baseline = statuses.get(0, ("NOT_RUN", ""))[0]
    mutants = []
    for index, site in enumerate(picked, 1):
        status, detail = statuses.get(index, ("TIMEOUT" if timed_out and index == len(statuses) else "NOT_RUN", ""))
        verdict = {"FAILED": "KILLED", "TIMEOUT": "KILLED", "PASSED": "SURVIVED"}.get(status, "NOT_RUN")
        mutants.append({key: site[key] for key in ("file", "line", "operator", "original", "mutant")}
                       | {"result": verdict, "detail": detail})
    result = {"stage": stage, "check": check, "snapshot_digest": seed, "recorded": now(),
              "mode": "single-session" if single else "separate-processes", "seconds": round(seconds, 1),
              "baseline": baseline, "sites_available": len(sites),
              "mutants": mutants,
              "killed": sum(m["result"] == "KILLED" for m in mutants),
              "survived": sum(m["result"] == "SURVIVED" for m in mutants)}
    result["status"] = ("INVALID" if baseline != "PASSED" else "NO_SITES" if not mutants else "COMPLETED")
    evidence = project.control / "evidence" / f"mutation-{identifier}.json"
    atomic_json(evidence, result)
    with project.transaction(owner) as locked:
        locked.setdefault("mutation_results", {})[stage] = {
            **{k: result[k] for k in ("check", "snapshot_digest", "status", "baseline", "killed", "survived", "recorded")},
            "survivors": [m for m in mutants if m["result"] == "SURVIVED"],
            "evidence": evidence.relative_to(project.root).as_posix(), "sha256": digest(evidence)}
    return result


def mutation_summary(record, limit=6):
    """What the reviewer reads: the count and each surviving mutant at file:line."""
    if record["status"] != "COMPLETED":
        return {"status": record["status"], "note": "baseline check failed in the copy" if record["status"] == "INVALID"
                else "no mutable operators found in the source"}
    total = record["killed"] + record["survived"]
    return {"status": f"the {record['check']} check caught {record['killed']} of {total} planted defects",
            "survivors": [f"{m['file']}:{m['line']} {m['operator']}: {m['mutant'][:120]}"
                          for m in record["survivors"][:limit]]}
