"""Native MATLAB batch fallback; the official MCP remains the interactive bridge."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from .project import ProjectError


def toolkit_root(explicit=None):
    candidates = [explicit, os.environ.get("MATLAB_HARNESS_ROOT"), Path(__file__).resolve().parents[2],
                  Path(__file__).resolve().parent / "resources"]
    for value in candidates:
        if value and (Path(value) / "matlab").is_dir() and (Path(value) / "skills").is_dir():
            return Path(value).resolve()
    raise ProjectError("Engineering resources not found; set MATLAB_HARNESS_ROOT to the standalone repository")


def matlab_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def detect_executable(explicit=None):
    executable = explicit or os.environ.get("MATLAB_HARNESS_MATLAB") or shutil.which("matlab")
    if executable and not Path(executable).is_file():
        resolved = shutil.which(executable)
        if resolved:
            executable = resolved
        elif os.name == 'nt' and Path(str(executable)+'.exe').is_file():
            executable = str(executable)+'.exe'
    if not executable or not Path(executable).is_file():
        raise ProjectError("MATLAB executable unavailable. Supply --matlab or MATLAB_HARNESS_MATLAB; user license required")
    return str(Path(executable).resolve())


def preflight(matlab=None, root=None, timeout=180):
    result = {"python": sys.version.split()[0], "os": platform.system(),
              "runtimes": {name: bool(shutil.which(name)) for name in ("codex", "claude", "agy")},
              "matlab": {"status": "UNTESTED"}, "limits": ["CLI presence does not prove model access or spawning"]}
    try:
        executable = detect_executable(matlab)
        resources = toolkit_root(root)
        expression = (f"addpath({matlab_string(resources / 'matlab')}); "
                      "fprintf('MATLAB_HARNESS_CAPABILITIES=%s\\n',jsonencode(engineering.capabilities()));")
        process = subprocess.run([executable, "-batch", expression], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=timeout, shell=False)
        marker = next((line.split("MATLAB_HARNESS_CAPABILITIES=", 1)[1] for line in process.stdout.splitlines()
                       if "MATLAB_HARNESS_CAPABILITIES=" in line), None)
        if process.returncode != 0 or marker is None:
            result["matlab"] = {"status": "UNSUPPORTED", "exit_code": process.returncode,
                                "diagnostic": process.stderr or process.stdout, "remedy": "Check installation, license and startup.m"}
        else:
            result["matlab"] = {"status": "VERIFIED", "capabilities": json.loads(marker),
                                "execution": "native-batch", "release_validation": "environment detection only, not engineering acceptance"}
    except (ProjectError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        result["matlab"] = {"status": "UNSUPPORTED", "diagnostic": str(exc),
                            "remedy": "Provide a working local MATLAB executable/license and retry"}
    return result
