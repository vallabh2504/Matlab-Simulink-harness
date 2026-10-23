"""Run every MATLAB snippet in skills/cards in one MATLAB session and check Simulink library paths.

    py scripts/validate_cards.py [--matlab PATH]

A block whose first line is "% file: <path>" is written to that path in the card's
folder; every other block runs there as a script, in order. Needs licensed MATLAB,
and Simulink for the Simulink card.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLOCK = re.compile(r"```matlab\n(.*?)```", re.S)
LIBRARY_PATH = re.compile(r"`(simulink/[^`]+)`")


def text(value):
    return "'" + str(value).replace("\\", "/").replace("'", "''") + "'"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--matlab", default=shutil.which("matlab") or "matlab")
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="card-check-"))
    lines = ["function run_cards()", "fid = fopen(" + text(work / "results.txt") + ", 'w');", "home = pwd;"]
    cases = []
    for card in sorted((ROOT / "skills" / "cards").glob("*.md")):
        source = card.read_text(encoding="utf-8")
        folder = work / card.stem
        folder.mkdir()
        for number, block in enumerate(BLOCK.findall(source), 1):
            first = block.splitlines()[0]
            if first.startswith("% file: "):
                target = folder / first[len("% file: "):].strip()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(block, encoding="utf-8")
                continue
            script = folder / f"snippet{number}.m"
            script.write_text(block, encoding="utf-8")
            cases.append(f"{card.stem} block {number}")
            lines += [f"cd({text(folder)});", "try",
                      f"    evalc(\"run({text(script)})\"); fprintf(fid, '%s\\tPASS\\t\\n', {text(cases[-1])});",
                      "catch err",
                      f"    fprintf(fid, '%s\\tFAIL\\t%s\\n', {text(cases[-1])}, strrep(err.message, newline, ' '));",
                      "end", "cd(home); bdclose('all');"]
        for library in LIBRARY_PATH.findall(source):
            cases.append(f"{card.stem} library {library}")
            lines += ["try", "    load_system('simulink');",
                      f"    ok = getSimulinkBlockHandle({text(library)}) > 0;",
                      "catch", "    ok = false;", "end",
                      f"fprintf(fid, '%s\\t%s\\t\\n', {text(cases[-1])}, char(string(ok)));"]
    lines += ["fclose(fid);", "end"]
    (work / "run_cards.m").write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run([args.matlab, "-batch", f"cd({text(work)}); run_cards"], cwd=work, timeout=1800)
    rows = [row.split("\t") for row in (work / "results.txt").read_text(encoding="utf-8").splitlines()]
    results = {name: {"status": "PASS" if status in {"PASS", "true"} else "FAIL", "detail": detail}
               for name, status, detail in rows}
    missing = [case for case in cases if case not in results]
    failed = {k: v for k, v in results.items() if v["status"] != "PASS"}
    print(json.dumps({"cases": len(cases), "passed": len(cases) - len(failed) - len(missing),
                      "failed": failed, "not_run": missing}, indent=2))
    shutil.rmtree(work, ignore_errors=True)
    return 1 if failed or missing else 0


if __name__ == "__main__":
    sys.exit(main())
