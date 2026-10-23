"""Discover canonical skills cheaply and register project-local native links."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

from .bridge import toolkit_root
from .project import ProjectError, digest


def catalog(root=None):
    base = toolkit_root(root) / "skills"
    entries = []
    for path in sorted(base.glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        description = ""
        # Skill authors use plain one-line descriptions; no YAML dependency.
        for line in text.splitlines()[1:]:
            if line == "---":
                break
            if line.startswith("description:"):
                description = line.partition(":")[2].strip().strip('"')
        entries.append({"name": path.parent.name, "description": description,
                        "path": str(path), "sha256": digest(path)})
    return entries


def select(task, root=None):
    words = set(task.lower().replace("/", " ").replace("-", " ").split())
    entries = catalog(root)
    scored = []
    for entry in entries:
        tokens = set((entry["name"] + " " + entry["description"]).lower().replace("-", " ").split())
        score = len(tokens & words)
        if score:
            scored.append((score, entry))
    return [entry for _, entry in sorted(scored, key=lambda item: (-item[0], item[1]["name"]))[:3]]


def install(target, runtime, root=None):
    if runtime not in {"codex", "claude"}:
        raise ProjectError("Native skill registration supported for codex or claude")
    project = Path(target).resolve()
    destination = project / (".agents" if runtime == "codex" else ".claude") / "skills"
    destination.mkdir(parents=True, exist_ok=True)
    outputs = []
    for entry in catalog(root):
        source = Path(entry["path"]).parent
        link = destination / source.name
        if link.exists() or link.is_symlink():
            if link.resolve() != source.resolve():
                raise ProjectError(f"Skill conflict; existing {link} is not this canonical skill")
        elif os.name == "nt":
            quote = lambda p: "'" + str(p).replace("'", "''") + "'"
            script = f"New-Item -ItemType Junction -Path {quote(link)} -Target {quote(source)} -ErrorAction Stop | Out-Null"
            subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, capture_output=True)
        else:
            link.symlink_to(source, target_is_directory=True)
        outputs.append({"name": source.name, "link": str(link), "canonical": str(source),
                        "discovery": "link-installed; restart runtime then confirm actual skill discovery"})
    return outputs


STAGE_SKILLS = {"requirements": ["engineering-requirements-modeling"],
                "architecture": ["engineering-matlab-numerics"],
                "implementation": ["engineering-matlab-numerics"],
                "verification": ["engineering-results-verification"],
                "handoff": ["engineering-results-verification"]}
SIMULINK_SIGNALS = ("simulink", ".slx", ".mdl", "stateflow", "model-based")


def select_for(stage, role, text, root=None):
    """Stage and role defaults, plus Simulink only when the task actually names it.

    Keyword matching on stage guidance picked the Simulink skill for MATLAB-only
    work, because the guidance itself says "MATLAB or Simulink".
    """
    entries = {entry["name"]: entry for entry in catalog(root)}
    names = list(STAGE_SKILLS.get(stage, []))
    if role == "reviewer":
        names.append("engineering-review-continuity")
    if any(signal in text.lower() for signal in SIMULINK_SIGNALS):
        names.append("engineering-simulink-engineering")
    return [entries[name] for name in dict.fromkeys(names) if name in entries][:3]


# Short cards with runnable snippets are inlined into packets so a small model
# does not have to open long skill files. Order is priority: the budget trims from the end.
STAGE_CARDS = {
    ("requirements", "builder"): ["requirements"], ("requirements", "reviewer"): ["requirements"],
    ("requirements", "repair"): ["requirements"],
    ("architecture", "builder"): ["{core}"], ("architecture", "reviewer"): ["{core}"],
    ("architecture", "repair"): ["{core}"],
    ("implementation", "builder"): ["{core}", "matlab-unittest", "matlab-errors"],
    ("implementation", "reviewer"): ["verification", "{core}"],
    ("implementation", "repair"): ["matlab-errors", "{core}", "matlab-unittest"],
    ("verification", "builder"): ["verification", "matlab-unittest"],
    ("verification", "reviewer"): ["verification"],
    ("verification", "repair"): ["matlab-errors", "matlab-unittest"],
    ("handoff", "builder"): ["verification"], ("handoff", "reviewer"): ["verification"],
    ("handoff", "repair"): ["matlab-errors"],
}
TOPIC_SIGNALS = {"plotting": ("plot", "figure", "chart", "graph"),
                 "parameters": ("parameter", "calibrat", "provenance", "datasheet")}


def cards_for(stage, role, text, root=None, limit=3):
    base = toolkit_root(root) / "skills" / "cards"
    lowered = text.lower()
    core = "simulink-construction" if any(s in lowered for s in SIMULINK_SIGNALS) else "matlab-numerics"
    names = [name.format(core=core) for name in STAGE_CARDS.get((stage, role), [])]
    if stage in {"architecture", "implementation"}:
        # A card the task names outranks the generic stage cards after the first.
        topics = [topic for topic, words in TOPIC_SIGNALS.items() if any(w in lowered for w in words)]
        names = names[:1] + topics + names[1:]
    cards = []
    for name in dict.fromkeys(names):
        path = base / (name + ".md")
        if path.is_file() and len(cards) < limit:
            cards.append({"name": name, "path": str(path), "text": path.read_text(encoding="utf-8")})
    return cards
