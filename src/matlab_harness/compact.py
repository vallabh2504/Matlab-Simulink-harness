"""Compress MATLAB process output to the lines a repair worker acts on.

Full stdout and stderr stay in the evidence files; prompts carry only this digest.
"""
from __future__ import annotations

import re


SIGNAL = re.compile(
    r"^(Error using|Error in|Error:|Caused by|Assertion failed|Verification failed|Assumption failed|"
    r"Failure Summary|Totals:|.*\b(Failed|FAILED|Incomplete)\b|.*\bMATLAB:\w|.*\b\w+:\w+[A-Za-z]\b.*identifier|"
    r"Warning:|.*line \d+)", re.I)
NOISE = re.compile(r"^(-{3,}|={3,}|\s*$|>>|Running |Done |\.+$)")


def matlab_digest(stdout, stderr="", limit=400):
    """Error ID, message and file:line first; the output tail when nothing matches."""
    text = (stderr or "") + "\n" + (stdout or "")
    lines = [line.strip() for line in text.splitlines()]
    picked = []
    for index, line in enumerate(lines):
        if NOISE.match(line) or not SIGNAL.match(line):
            continue
        picked.append(line)
        # "Error using f" is followed by the message, which is what matters.
        if line.lower().startswith(("error using", "error in", "caused by")) and index + 1 < len(lines):
            following = lines[index + 1]
            if following and not SIGNAL.match(following):
                picked.append(following)
    picked = list(dict.fromkeys(picked))
    digest = " | ".join(picked) if picked else " ".join(line for line in lines if line)[-limit:]
    return digest if len(digest) <= limit else digest[:limit - 3] + "..."


def check_summary(checked, limit=400):
    """A journey check result reduced to status plus the compressed output per check."""
    rows = {}
    for item in (checked or {}).get("checks", []):
        result = item.get("result", item) if isinstance(item, dict) else {}
        name = result.get("name") or item.get("name") or "check"
        # A semantic adequacy run carries its own per-case diagnosis instead of streams.
        output = ("; ".join(result["diagnosis"])[:3 * limit] if result.get("diagnosis")
                  else matlab_digest(result.get("stdout", ""), result.get("stderr", ""), limit))
        rows[name] = {"status": result.get("status", item.get("status")), "output": output}
    return {"status": (checked or {}).get("status"), "checks": rows}
