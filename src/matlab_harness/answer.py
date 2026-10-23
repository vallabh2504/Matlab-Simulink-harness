"""Reviewer answers: the one shape any reviewer returns, translated exactly into a review record.

A reviewer answers a packet. The packet names every item still open at its checkpoint by a
handle: a prior finding by its own ID, a serious allegation from an answer that was not imported
by "A-" and a digest of the claim. The reviewer answers each handle and reports its own new
findings. Three rules govern decoded answers while tolerating small-model formats:

- Read every answer as the claim that supports acceptance least. Where a part is put (a wrapper
  object, a list, an object keyed by ID or by severity, lines of text), what it is called
  ("issues"), case, markup and common synonyms ("HIGH", "PASS") never matter. A value written
  alone is itself. Text that says more ("ACCEPT (if F-2 is fixed)", "Closed?") is read as the
  least supporting value it names, and never as ACCEPT, CLOSED, VERIFIED or PASS: those count
  only written alone. Whatever is written more than once (two answers in one reply, a part under
  two names, two status fields) is read as weakly as any copy says it, and every finding of every
  copy is kept. Severity is the strongest recognized label or explicit severity in the claim. A
  closure without proof reads as not checked, and a new finding closed without proof as open; a
  missing row reads as not assessed.
- Refuse only what the harness will not guess (a verdict, a severity) and a strong claim without
  support: ACCEPT with an item still open, a requirement not verified, or no independent probe
  where one is required.
- Every serious claim in an answer that was not imported binds as an allegation, whatever the
  reason, once the answer is known to come from an independent reviewer of the current bytes.
  A finding is whatever object or text the findings hold; one whose severity cannot be read is
  kept as MAJOR, so no claim is lost to its shape.

Identity is the handle the reviewer chose, never a guess about which earlier finding a new one
"means", and no two handles differ by case alone. The one exception is exact: a new finding
identical to an open allegation is that claim made again, and keeps it open. A new finding that
reuses an ID is renamed, never merged, so no claim is ever folded into another and lost. Handles
are a namespace of their own: no new finding is ever given an "A-" handle's shape.
Every digest, origin artifact and disposition the strict record needs follows from the handle,
so a small model copies nothing it could mistype.

The record is built from the fields the harness knows, as plain text. Nothing a reviewer writes
(a NaN, an unknown key, a nesting a thousand deep) reaches a digest or a file unread.
Oversized decoded answers produce a blocking unexamined-answer condition. Untrusted raw
reviews enter through the loss-aware decoder before this decoded-answer boundary.
"""
from __future__ import annotations

import functools
import json
import os
from pathlib import Path
import re

from .project import KINDS, PHASES, SERIOUS, SEVERITIES, TEXT_DOCUMENTS, ProjectError, ReviewProtocolError, atomic_json, cites, digest, inside, read_json, value_digest

TRACE_STATUSES = ["VERIFIED", "PARTIAL", "FAILED", "UNVERIFIED"]
EXECUTED_CHECKPOINTS = {"implementation", "verification", "handoff"}
VERDICTS = ["ACCEPT", "REJECT", "INCOMPLETE"]
ANSWERS = ["CLOSED", "STILL_OPEN", "NOT_CHECKED"]
STATUSES = ["OPEN", "CLOSED", "DISPUTED", "ACCEPTED-RISK"]
RESULTS = ["PASS", "FAIL", "ERROR"]
NOT_STATED = "not stated by reviewer"
NOT_ASSESSED = "not assessed by reviewer"
PROBES_SHOWN = 8
TRACE_RANK = ["VERIFIED", "PARTIAL", "UNVERIFIED", "FAILED"]
# Each part's values, from the one that supports acceptance most to the one that supports it least.
ORDER = {"verdict": ["ACCEPT", "REJECT", "INCOMPLETE"], "answer": ["CLOSED", "STILL_OPEN", "NOT_CHECKED"],
         "status": ["CLOSED", "ACCEPTED-RISK", "DISPUTED", "OPEN"], "trace": TRACE_RANK,
         "result": ["PASS", "FAIL", "ERROR"], "severity": ["MINOR", "MODERATE", "MAJOR", "CRITICAL"],
         "kind": ["OPTIONAL IMPROVEMENT", "POTENTIAL DEFECT", "EVIDENCE GAP", "PROVEN DEFECT"]}
SYNONYMS = {
    "verdict": {"ACCEPTED": "ACCEPT", "APPROVE": "ACCEPT", "APPROVED": "ACCEPT", "PASS": "ACCEPT",
                "REJECTED": "REJECT", "FAIL": "REJECT", "FAILED": "REJECT"},
    "severity": {"BLOCKER": "CRITICAL", "P0": "CRITICAL", "SEVERE": "MAJOR", "HIGH": "MAJOR", "P1": "MAJOR",
                 "ERROR": "MAJOR", "MEDIUM": "MODERATE", "P2": "MODERATE", "WARNING": "MODERATE",
                 "LOW": "MINOR", "P3": "MINOR", "INFO": "MINOR", "NOTE": "MINOR", "TRIVIAL": "MINOR"},
    "status": {"FIXED": "CLOSED", "RESOLVED": "CLOSED"},
    "trace": {"PASS": "VERIFIED", "PASSED": "VERIFIED", "FAIL": "FAILED", "NOT VERIFIED": "UNVERIFIED",
              "PARTIALLY VERIFIED": "PARTIAL", "PARTIALLY": "PARTIAL"},
    "result": {"PASSED": "PASS", "FAILED": "FAIL"},
    "answer": {"OPEN": "STILL_OPEN", "FIXED": "CLOSED", "RESOLVED": "CLOSED", "UNCHECKED": "NOT_CHECKED"},
}
# The names a reviewer may give each part of its answer, the harness's own first.
PARTS = {"verdict": ("verdict", "decision"), "findings": ("findings", "issues", "defects", "problems"),
         "traceability": ("traceability", "trace"), "independent_checks": ("independent_checks", "checks"),
         "open_items": ("open_items", "items")}
KNOWN_PARTS = {name for names in PARTS.values() for name in names}
KEYED_PARTS = {"traceability", "open_items"}
# The fields of a finding, each with the names a reviewer may give it.
FINDING_TEXT = {"artifact": ("artifact", "location", "file"),
                "evidence": ("evidence", "description", "detail", "title", "message"),
                "repair": ("repair", "fix", "recommendation"), "impact": ("impact",), "closure": ("closure",)}
SEVERITY_FIELDS = ("severity", "priority", "level")
USER_DECISION = ("user_decision", "needs_user_decision", "decision_required")
# The conflict a serious finding on the approved contract names to keep it open after requirements.
QUOTES = ("contract_text", "design_text")
QUOTE_CHARACTERS = 8
AFFIRMATIVE = {"TRUE", "YES", "Y", "REQUIRED", "NEEDED"}
# Words that may stand next to a severity ("high priority") without saying more.
SEVERITY_FILLER = {"SEVERITY", "PRIORITY", "LEVEL"}
# A text's leading label: "[Low] ...", "(MAJOR) ...", "**HIGH** ...", "F-1 (MAJOR): ...".
LABEL = re.compile(r"\s*(?:\[([^\]\n]{1,40})\]|\(([^)\n]{1,40})\)|\*\*([^*\n]{1,40})\*\*|([^:\n]{1,40}):)")
CHECK_TEXT = ("command", "observed", "artifact", "purpose", "requirements", "expected")
# An object with any of these is an entry; one without is a container to look inside.
FINDING_FIELDS = {"id", "kind", "status", *SEVERITY_FIELDS, *(n for names in FINDING_TEXT.values() for n in names)}
CHECK_FIELDS = {"id", "result", "receipt_id", "run", *CHECK_TEXT}
# Fields the harness records from the packet and the channel; an answer that echoes them is ignored.
CHANNEL_FIELDS = {"checkpoint", "snapshot_digest", "reviewer_session", "model", "protocol_dispositions"}
READ_ELSEWHERE = {"independence", "summary"}
# The shape of an allegation's handle. A finding never takes it; a longer digest breaks a collision.
HANDLE = re.compile(r"A-[0-9a-f]{8,}", re.IGNORECASE)
# Text that says a part is empty: "None found", "There are no findings.", "No major issues".
NOTHING = re.compile(r"(?:(?:THERE )?(?:ARE|WERE|IS) )?(?:NONE|NIL|N/?A|NOTHING|NO)"
                     r"(?: (?:NEW|OTHER|FURTHER|ADDITIONAL|REMAINING|OPEN|SERIOUS|SIGNIFICANT|BLOCKING|CRITICAL|MAJOR"
                     r"|MODERATE|MINOR))*(?: (?:FINDINGS?|ISSUES?|DEFECTS?|PROBLEMS?|BUGS?|CONCERNS?))?"
                     r"(?: (?:FOUND|IDENTIFIED|DETECTED|REMAINING|TO REPORT))?|")
# A check ID that can stand for its check: compound (CHK-ORACLES, P1), never a word of prose.
CHECK_ID = re.compile(r"(?=.*[a-z])(?=.*[\d_-])[\w-]{2,}")
# How many JSON values an answer may hold before it is too large to read whole.
BUDGET = 100000
TEXT_BUDGET = 1000000

# Canonicalize only vocabulary, not user IDs, paths or wrapper names. Aliases stay
# separate so _shape can report them and combine every value that was supplied.
_KEY_NAMES = {re.sub(r"[^a-z0-9]", "", name): name for name in
              KNOWN_PARTS | FINDING_FIELDS | CHECK_FIELDS | CHANNEL_FIELDS | READ_ELSEWHERE |
              {"requirement", "requirement_id", "req", "handle", "finding", "finding_id",
               "item", "answer", "probe", "finding_ids"}}


class _AnswerBoundaryError(ValueError):
    pass


def _canonical_answer(answer):
    """Admit a complete decoded answer once, within node and text limits.

    Iterative copying avoids depth-dependent recursion. Equivalent field names
    share a key, but contradictory copies share a list rather than overwriting
    each other. Unknown branches count too: no later reader may silently cut a
    tail which could contradict acceptance.
    """
    holder, stack, remaining, characters = [None], [], BUDGET - 1, 0
    stack.append((answer, holder, 0))
    while stack:
        value, parent, slot = stack.pop()
        if isinstance(value, (dict, list, tuple)):
            remaining -= len(value)
            if remaining < 0:
                raise _AnswerBoundaryError("decoded answer exceeds the JSON-value limit")
            if isinstance(value, dict):
                groups = {}
                for name, child in value.items():
                    if not isinstance(name, str):
                        raise _AnswerBoundaryError("decoded answer keys must be text")
                    characters += len(name)
                    if characters > TEXT_BUDGET:
                        raise _AnswerBoundaryError("decoded answer exceeds the key/text-character limit")
                    key = _KEY_NAMES.get(re.sub(r"[^a-z0-9]", "", name.strip().casefold()), name)
                    groups.setdefault(key, []).append(child)
                target = parent[slot] = {}
                for key, children in groups.items():
                    # Identical scalar copies need no extra container. Structured
                    # values are never compared recursively or thrown away.
                    if len(children) > 1 and isinstance(children[0], (str, int, float, bool, type(None))):
                        first = children[0]
                        if all(type(child) is type(first) and child == first for child in children):
                            children = [first]
                    if len(children) == 1:
                        stack.append((children[0], target, key))
                    else:
                        remaining -= 1
                        target[key] = [None] * len(children)
                        stack.extend((child, target[key], index) for index, child in enumerate(children))
            else:
                target = parent[slot] = [None] * len(value)
                stack.extend((child, target, index) for index, child in enumerate(value))
        elif value is None or isinstance(value, (str, int, float, bool)):
            if isinstance(value, str):
                characters += len(value)
            parent[slot] = value
        else:
            raise _AnswerBoundaryError("decoded answer contains a non-JSON value")
        if remaining < 0 or characters > TEXT_BUDGET:
            raise _AnswerBoundaryError("decoded answer exceeds the node or key/text-character limit")
    return holder[0]


def _unexamined_answer(stage, reason):
    """A refusal must leave a durable condition, not erase an unread serious tail.

    This is an evidence gap about the answer, not an invented engineering defect.
    Original runtime/host provenance stays with the packet; no claim is made that
    an oversized answer's individual allegations have all been extracted.
    """
    message = "the answer is too large to read whole; report each finding and check once"
    return {"checkpoint": stage, "verdict": "INCOMPLETE", "traceability": [],
            "independent_checks": [], "protocol_dispositions": [], "findings": [{
                "id": "REVIEW-ANSWER-LIMIT", "severity": "MAJOR", "kind": "EVIDENCE GAP",
                "status": "OPEN", "artifact": "reviewer answer",
                "evidence": reason + "; the complete set of reviewer claims could not be examined",
                "impact": "An unexamined answer may contain unresolved serious claims",
                "repair": "Resubmit the complete review within the answer limits; retain and disposition all claims",
                "closure": "An independent reviewer examines the complete resubmission and dispositions this gap"}],
            "harness_notes": [reason]}, [message, reason]

_TEXT, _NONEMPTY = {"type": "string"}, {"type": "string", "minLength": 1}
FINDING_SCHEMA = {"type": "object", "properties": {
    "id": _NONEMPTY, "artifact": _NONEMPTY, "evidence": _NONEMPTY, "repair": _NONEMPTY,
    "severity": {"type": "string", "enum": sorted(SEVERITIES)},
    "kind": {"type": "string", "enum": sorted(KINDS)},
    "status": {"type": "string", "enum": STATUSES},
    "impact": _TEXT, "closure": _TEXT, "user_decision": {"type": "boolean"},
    "contract_text": _TEXT, "design_text": _TEXT},
    "required": ["id", "severity", "artifact", "evidence", "repair"]}
CHECK_SCHEMA = {"type": "object", "properties": {
    "id": _NONEMPTY, "command": _NONEMPTY, "observed": _NONEMPTY, "artifact": _NONEMPTY,
    "result": {"type": "string", "enum": RESULTS},
    "purpose": _TEXT, "requirements": _TEXT, "expected": _TEXT, "finding_ids": _TEXT,
    "receipt_id": _TEXT, "run": {"type": "object", "properties": {
        "script": _NONEMPTY, "runner": {"type": "integer"},
        "arguments": {"type": "array", "items": _TEXT}, "inputs": {"type": "array", "items": _TEXT}},
        "required": ["script"]}},
    "required": ["id", "command", "observed", "result", "artifact"]}
ROW_SCHEMA = {"type": "object", "properties": {
    "status": {"type": "string", "enum": TRACE_STATUSES}, "evidence": _NONEMPTY, "finding_ids": _TEXT},
    "required": ["status", "evidence"]}
ITEM_SCHEMA = {"type": "object", "properties": {
    "status": {"type": "string", "enum": ANSWERS}, "evidence": _NONEMPTY, "probe": _TEXT,
    "contract_text": _TEXT, "design_text": _TEXT},
    "required": ["status", "evidence"]}


def _text(value):
    """Plain text of any JSON value. Containers are flattened without recursion, so no depth
    can raise; every leaf becomes a string, so no number reaches a digest."""
    parts, stack = [], [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, (list, tuple)):
            stack.extend(reversed(item))
        elif item is not None:
            try:
                part = str(item).strip()
            except ValueError:  # an integer too long to print
                part = "number"
            if part:
                parts.append(part)
    return ", ".join(parts)


def _plain(value):
    """A value as written alone: upper case, without surrounding punctuation, markup or a check
    mark, with runs of spaces, underscores and hyphens as one space. A question mark is not
    markup: "Closed?" says more than CLOSED."""
    return re.sub(r"[\s_-]+", " ", _text(value).strip(" \t\r\n*_`'\".,;:!()[]{}\u2705\u2714\u2611\ufe0f")).strip().upper()


def _words(value):
    return " " + re.sub(r"[^A-Z0-9]+", " ", _text(value).upper()) + " "


def _vocabulary(part):
    """Every way to write a value of part, as words, with the value each means."""
    return [(_plain(option), option) for option in ORDER[part]] + list(SYNONYMS.get(part, {}).items())


def _read(value, part, default=None):
    """The value of part a reviewer wrote, read as the claim that supports acceptance least.
    Written alone, in any case or punctuation or as a common synonym, a value is itself. Text
    that says more is the least supporting value it names, never the most supporting one, or
    default when it names none."""
    if isinstance(value, (list, tuple)):
        stack, votes = list(value), []
        while stack:
            item = stack.pop()
            if isinstance(item, (list, tuple)):
                stack.extend(item)
            else:
                votes.append(_read(item, part, default))
        return (max(votes, key=ORDER[part].index) if votes and all(v is not None for v in votes) else default)
    plain, words = _plain(value), _words(value)
    meaning = dict(reversed(_vocabulary(part)))
    if plain in meaning:
        return meaning[plain]
    order = ORDER[part]
    named = [meant for word, meant in _vocabulary(part) if f" {word} " in words and meant != order[0]]
    return max(named, key=order.index) if named else default


def _hedged(value, part):
    """Whether text names the value of part that supports acceptance most, but not alone."""
    strongest = ORDER[part][0]
    return _read(value, part) != strongest and any(
        meant == strongest and f" {word} " in _words(value) for word, meant in _vocabulary(part))


def _says_more(text, part):
    """Whether text says anything besides a value of part."""
    rest = _words(text)
    for word, _ in sorted(_vocabulary(part), key=lambda pair: len(pair[0]), reverse=True):
        rest = re.sub(rf"(?<!\S){re.escape(word)}(?!\S)", " ", rest)
    return bool(rest.strip())


def _grades(text):
    """The severities text names when it is made only of severities, their synonyms, filler
    ("priority") and IDs ("F-1 (MAJOR)", "Minor/Major", "Medium-High"); else none."""
    grades, scale = [], {**{s: s for s in ORDER["severity"]}, **SYNONYMS["severity"]}
    for token in re.findall(r"[\w-]+", text.upper()):
        meant = [scale.get(word) for word in ([token] if token in scale else re.split(r"[-_]+", token))]
        if all(meant):
            grades += meant
        elif not (token in SEVERITY_FILLER or re.search(r"\d", token)):
            return []
    return grades


def _severity(*values):
    """The most severe severity the values give, or None. A value made only of severity words
    is them; so is a text's leading label ("[Low] typo", "P1: crash"), which is a text finding's
    severity field. Otherwise it is the most severe of CRITICAL, MAJOR, MODERATE and MINOR the
    text names; a synonym inside prose ("a low-level bug") never grades a claim."""
    order, found = ORDER["severity"], []
    for value in values:
        text = _text(value)
        label = LABEL.match(text)
        label = next((g for g in label.groups() if g), "") if label else ""
        found += _grades(text) or _grades(label)
        # A leading/explicit label can strengthen a claim, never hide stronger
        # prose. Hyphenated terms such as major-axis are not severity labels.
        found += re.findall(r"(?<![\w-])(?:CRITICAL|MAJOR|MODERATE|MINOR)(?![\w-])", text.upper())
    return max(found, key=order.index) if found else None


def _weakest(statuses, part, default):
    """The status that supports acceptance least of those written, or default when none is."""
    return max((_read(s, part, default) for s in statuses), key=ORDER[part].index, default=default)


def _first(entry, names):
    return next((text for text in (_text(entry.get(name)) for name in names) if text), "")


def _named_id(keys):
    """The ID the keys an entry was found under give it: the nearest one with a digit."""
    return next((key for key in reversed(keys) if re.search(r"\d", key)), "")


def _packet_id(path):
    parts = Path(path).parts
    return parts[parts.index("packets") + 1] if "packets" in parts[:-1] else None


def claim_digest(finding):
    """What a finding claims, without the ID a reviewer happened to give it."""
    return value_digest({k: v for k, v in finding.items() if k != "id"})


def normalize_finding(raw, keys=()):
    """A reviewer's own finding, from its known fields only, with every missing or loose field
    read as its weakest value. raw is an object, or text that is the finding's evidence and
    names its severity; keys are the object keys it was found under, which may name its ID or
    severity. Returns the finding and a problem when no severity can be read; such a finding is
    kept as MAJOR, so it binds if the answer is not imported. Normalizing a normalized finding
    changes nothing."""
    if not isinstance(raw, dict):
        raw = {"evidence": raw, "severity": raw}
    given = [raw[name] for name in SEVERITY_FIELDS if raw.get(name) is not None]
    finding = {"id": _text(raw.get("id")) or _named_id(keys) or "F"}
    for field, names in FINDING_TEXT.items():
        finding[field] = "; ".join(text for text in (_text(raw.get(name)) for name in names) if text) or NOT_STATED
    finding["kind"] = _read(raw.get("kind"), "kind", "POTENTIAL DEFECT")
    finding["status"] = _read(raw.get("status"), "status", "OPEN")
    severity = _severity(*given, *keys, *(finding[field] for field in FINDING_TEXT))
    finding["severity"] = severity or "MAJOR"
    # Present only when written affirmatively, so a finding without it keeps its claim digest.
    if any(raw.get(name) is True or (isinstance(raw.get(name), str) and _plain(raw[name]) in AFFIRMATIVE)
           for name in USER_DECISION):
        finding["user_decision"] = True
    finding.update({name: _text(raw[name]) for name in QUOTES if _text(raw.get(name))})
    problem = None if severity else (f"finding {finding['id']} needs severity CRITICAL, MAJOR, MODERATE or MINOR, "
                                     f"not {_text(given)[:40] or 'nothing'}")
    return finding, problem


def open_items(project, data, stage):
    """Everything still open at this checkpoint, by handle. Recomputed from the record; each
    handle depends only on its own item, so it means the same thing in the packet that showed
    it and in any later answer.

    A prior finding is answered by its own ID; it must be answered when it blocks. A serious
    allegation is answered by "A-" and a digest of the claim, so the same claim left by two
    answers that were not imported is one item. It shows the probes of every attempt that made
    the claim or restated it, so a new session can re-run them.
    """
    items, taken = {}, set()
    for key, item in project._seed_defects(data).items():
        if item["checkpoint"] == stage and item["finding"]["status"] != "CLOSED":
            handle = key.split(":", 1)[1]
            if handle.casefold() in taken:  # a record from before IDs were case-blind
                handle += "-" + item["origin_digest"][:8]
            taken.add(handle.casefold())
            items[handle] = {"type": "finding", "key": key, "required": item["blocking"],
                             "finding": item["finding"], "origin_artifact": item["origin"]["artifact"],
                             "origin_digest": item["origin_digest"]}
    groups = {}
    for key, item in project.pending_review_findings(data).items():
        if item["checkpoint"] == stage:
            finding = normalize_finding(item["finding"])[0]
            claim = claim_digest(finding)
            group = groups.setdefault(claim, {"finding": finding, "keys": [], "reports": set()})
            group["keys"].append(key)
            group["reports"].add(item["source_report"])
    handles = {}
    for claim in groups:
        # Only a record from before handles were reserved can collide; a longer digest separates it.
        size = 8
        while ("a-" + claim[:size]).casefold() in taken:
            size *= 2
        handles["A-" + claim[:size]] = claim
        taken.add(("a-" + claim[:size]).casefold())
    by_handle = {handle: groups[claim] for handle, claim in handles.items()}
    for failure in data.get("review_protocol_failures", {}).values():
        path = project.root / failure["path"]
        if failure["checkpoint"] == stage and by_handle and path.is_file() and digest(path) == failure["sha256"]:
            findings = json.loads(path.read_text(encoding="utf-8")).get("findings")
            for finding in findings if isinstance(findings, list) else []:
                if isinstance(finding, dict) and finding.get("answers") in by_handle:
                    by_handle[finding["answers"]]["reports"].add(failure["path"])
    for handle, group in by_handle.items():
        probes = set()
        for report in group["reports"]:
            scratch = project.control / "scratch" / (_packet_id(report) or "")
            if _packet_id(report) and scratch.is_dir():
                # Copies from an earlier refused report are listed under that report already.
                probes |= {p.relative_to(project.root).as_posix() for p in scratch.rglob("*") if p.is_file()
                           and p.relative_to(scratch).parts[0] not in ("prior-report.json", "prior-probes")}
        items[handle] = {"type": "allegation", "keys": group["keys"], "required": True,
                         "claim": handles[handle], "finding": group["finding"],
                         "probes": sorted(probes)[:PROBES_SHOWN], "more_probes": max(0, len(probes) - PROBES_SHOWN)}
    return items


def answer_schema(data, items):
    """The answer this packet expects: a row for every requirement and, when anything is
    open, an answer for every item that blocks acceptance."""
    ids = [r["id"] for r in data["requirements"]]
    schema = {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": VERDICTS},
        "findings": {"type": "array", "items": FINDING_SCHEMA},
        "traceability": {"type": "object", "properties": {i: ROW_SCHEMA for i in ids},
                         "required": ids, "additionalProperties": False},
        "independent_checks": {"type": "array", "items": CHECK_SCHEMA}},
        "required": ["verdict", "findings", "traceability", "independent_checks"]}
    schema["properties"]["reconciliation"] = {
        "type": "array", "items": {"type": "object", "properties": {
            "gap_id": {"type": "string"}, "source_sha256": {"type": "string"},
            "complete": {"type": "boolean"}}, "required": ["gap_id", "source_sha256", "complete"]}}
    if items:
        schema["properties"]["open_items"] = {
            "type": "object", "properties": {handle: ITEM_SCHEMA for handle in items},
            "required": [h for h, item in items.items() if item["required"]], "additionalProperties": False}
        schema["required"].append("open_items")
    return schema


def _within(path, root):
    try:
        return os.path.commonpath([os.path.normcase(path), os.path.normcase(root)]) == os.path.normcase(root)
    except ValueError:  # another drive, or one path relative
        return False


def _in_scratch(project, scratch, artifact):
    """The file one path names inside the scratch directory, resolved, or None. A relative path
    names a project file first, so "src/f.m" never means a scratch copy of the builder's file;
    "scratch/p.m" is p.m in the scratch directory. Containment is decided on the text before the
    filesystem is touched, so a path a model wrote never reaches another drive or a network share."""
    text = _text(artifact).replace("\\", "/")
    if not text or "\0" in text:
        return None
    try:
        location, base = Path(text), os.path.normpath(scratch.absolute())
        if not location.parts:
            return None
        candidates = [location]
        if not location.is_absolute():
            own = os.path.normpath((project.root / location).absolute())
            if _within(own, os.path.normpath(project.root.absolute())) and not _within(own, base) and os.path.isfile(own):
                return None
            tail = location.parts[1:] if location.parts[0].casefold() == "scratch" else location.parts
            candidates = [project.root / location, scratch / location, scratch.joinpath(*tail)]
        for candidate in candidates:
            lexical = os.path.normpath(candidate.absolute())
            if _within(lexical, base) and os.path.isfile(lexical):
                resolved = Path(lexical).resolve()
                if resolved.is_relative_to(scratch.resolve()):
                    return resolved
    except (OSError, ValueError, RuntimeError):
        # Invalid/overlong names and link loops are unproved paths, not crashes
        # which discard an otherwise readable answer's serious claims.
        return None
    return None


def _artifacts(project, scratch, artifact):
    """The scratch files a check's artifact names: the whole text as one path, else each word of
    it that looks like a path ("p.m (MATLAB probe)", "p.m, p.log")."""
    whole = _in_scratch(project, scratch, artifact)
    if whole:
        return [whole]
    words = [w.rstrip(".:") for w in re.split(r"[\s,;()\[\]{}<>\"'`*]+", _text(artifact)) if re.search(r"[./\\]", w)]
    return list(dict.fromkeys(f for f in (_in_scratch(project, scratch, w) for w in words) if f))


def _own_artifacts(project, scratch, check, ran_here=None):
    """The scratch files a check may claim. A copy from a refused report is not this reviewer's
    work: the report never counts, and a copied probe counts only once this packet ran it."""
    found = _artifacts(project, scratch, check.get("artifact"))
    try:
        report, copies = (scratch / "prior-report.json").resolve(), (scratch / "prior-probes").resolve()
    except (OSError, RuntimeError):
        return []
    if ran_here is None:
        from .probes import validate
        ran_here = lambda: validate(project, scratch, check)
    return [f for f in found if f != report and (not f.is_relative_to(copies) or ran_here())]


def _proofs(project, scratch, checks, reserved):
    """Index consistent proof by the one canonical file resolver, never by basename.

    Every reported check using a file must PASS. A check ID additionally needs
    every occurrence to PASS and resolve only to consistent files. A failing
    subcheck of one shared script therefore vetoes both its filename and a
    different passing subcheck's ID as proof of closure.
    """
    files, ids = {}, {}
    from .probes import proof_mode, validate
    strict = proof_mode(project.load()) == "executed"
    for check in checks:
        ran_here = functools.cache(lambda check=check: validate(project, scratch, check))
        ran = set(_own_artifacts(project, scratch, check, ran_here))
        result = check["result"]
        if strict and result == "PASS" and not ran_here():
            result = "ERROR"
        ids.setdefault(check["id"].casefold(), []).append((result, ran))
        for where in ran:
            files.setdefault(where, []).append(result)
    passed = {path for path, results in files.items() if all(r == "PASS" for r in results)}
    check_ids = {name for name, rows in ids.items() if name not in reserved and CHECK_ID.fullmatch(name)
                 and all(result == "PASS" and paths and paths <= passed for result, paths in rows)}
    return project, scratch, passed, check_ids


def _proved(evidence, proofs):
    """Whether evidence names a consistent check ID or the same resolved scratch file.
    Markup and line numbers are tolerated; basename/suffix guesses are not proof.
    """
    project, scratch, files, ids = proofs
    for token in re.findall(r"[\w./~:-]+", _text(evidence).replace("\\", "/")):
        name = re.sub(r":\d+(?::\d+)?$", "", token.rstrip(".:"))
        if any(part.casefold() in ids for part in (name, *name.split("/"))):
            return True
        where = _in_scratch(project, scratch, name)
        if where is not None and where.suffix and where in files:
            return True
    return False


def _roots(answer):
    """Read every answer root across unknown wrappers, including below another root.

    Known part payloads are entries, not alternative answer roots; their own
    readers handle nested findings/checks. Input admission has already bounded
    the whole tree, so depth and a convenient earlier ACCEPT never cut traversal.
    """
    found, stack = [], [(answer, "")]
    while stack:
        item, where = stack.pop()
        if isinstance(item, dict):
            rooted = bool(item.keys() & KNOWN_PARTS)
            if rooted:
                found.append((item, where))
            stack.extend((child, name) for name, child in reversed(list(item.items()))
                         if not rooted or name not in KNOWN_PARTS)
        elif isinstance(item, list):
            stack.extend((child, where or "a list") for child in reversed(item))
    return found


def _shape(answer, notes):
    """The answer under the harness's own part names, each part as the list of every value
    written for it, or None when the answer is not a JSON object or array. An answer that names
    no part anywhere is read as findings."""
    roots = _roots(answer)
    if not roots:
        if not isinstance(answer, (dict, list)):
            return None
        notes.append("found no verdict or other part; read the whole answer as findings")
        roots = [({"findings": answer}, "")]
    elif len(roots) > 1:
        notes.append(f"read {len(roots)} answers together; each part is as weak as any of them says")
    elif roots[0][0] is not answer:
        notes.append(f"read the answer inside {roots[0][1][:40]!r}")
    shaped = {}
    for part, names in PARTS.items():
        present = [(root, name) for root, _ in roots for name in names if name in root]
        if present:
            shaped[part] = [root[name] for root, name in present]
            used = sorted({name for _, name in present})
            if used != [part]:
                notes.append(f"read {', '.join(used)} as {part}")
    fields = set().union(*(root.keys() for root, _ in roots))
    echoed = sorted(CHANNEL_FIELDS & fields)
    if echoed:
        notes.append("ignored fields the harness records itself: " + ", ".join(echoed))
    unknown = sorted(str(k) for k in fields - KNOWN_PARTS - CHANNEL_FIELDS - READ_ELSEWHERE)
    if unknown:
        notes.append("ignored fields the harness does not read: " + ", ".join(k[:40] for k in unknown[:10]))
    shaped["independence"] = [root.get("independence") for root, _ in roots]
    return shaped


def _leaves(value, fields):
    """The entries a part holds wherever a reviewer put them: in a list, alone, keyed by ID or by
    severity, or wrapped in another object, each with the keys it was found under. An object
    with any of fields is an entry; so is text, unless it says there is nothing. Returns the
    entries. The complete input has already passed the boundary limits; this
    reader never truncates it independently."""
    found, stack = [], [(value, ())]
    while stack:
        item, keys = stack.pop()
        if isinstance(item, dict):
            # An id-only grouping is not a claim; its children are. An actual
            # entry can also have nested claims in unknown container branches.
            entry = bool(item.keys() & (fields - {"id"})) or (
                "id" in item and not any(isinstance(v, (dict, list, tuple)) for v in item.values()))
            if entry:
                found.append((item, keys))
            stack += [(v, (*keys, _text(k))) for k, v in reversed(list(item.items()))
                      if k != "id" and (not entry or (k not in fields and isinstance(v, (dict, list, tuple))))]
        elif isinstance(item, (list, tuple)):
            stack += [(v, keys) for v in reversed(item)]
        elif isinstance(item, str) and not NOTHING.fullmatch(_plain(item)):
            found.append((item, keys))
    return found


def _ids(value):
    """The IDs a finding_ids value names: split on , ; | / whitespace and the word "and"; brackets,
    quotes and trailing . or : stripped. A qualified key keeps its ":"."""
    tokens = re.split(r"[,;|/\s]+", _text(value))
    tokens = [t.strip("[](){}\"'`").rstrip(".:").strip("[](){}\"'`") for t in tokens]
    return [t for t in tokens if t and t.casefold() != "and"]


def _norm(name):
    return re.sub(r"[-_]+", "", name.casefold())


def _key(name, known, stage=None):
    """The known key an entry's name is about: itself in any case, else the one its first word
    is ("R-1: VERIFIED, as R-2"), else the only one it names; "F1" names F-1. None otherwise.
    With stage (open_items only), "<phase>:<id>" names <id> at its own phase, and nothing at another."""
    exact = {k.casefold(): k for k in known}
    if name.strip().casefold() in exact:
        return exact[name.strip().casefold()]
    phase, _, rest = name.strip().partition(":")
    if stage and rest and phase.strip().casefold() in PHASES:
        return _key(rest, known) if phase.strip().casefold() == stage else None
    norms = {}
    for k in known:
        norms.setdefault(_norm(k), []).append(k)
    words = re.findall(r"[\w-]+", name)
    hits = [norms.get(_norm(w), []) for w in words[:200]]
    if hits and len(hits[0]) == 1:
        return hits[0][0]
    named = {k for hit in hits for k in hit}
    return named.pop() if len(named) == 1 else None


def _keyed(values, known, fields, part, notes, stage=None):
    """{key: [entries]} for a part keyed by requirement or handle, from every value written for
    it: an object keyed by it, a list of rows that name it in one of fields (or that are keyed
    objects themselves), or lines of text."""
    pairs, stack = [], list(reversed(values))
    row_fields = {"status", "answer", "result", "evidence", "probe", "finding_ids", *fields}

    def nested(entry):
        if isinstance(entry, dict):
            return [child for name, child in entry.items()
                    if name not in row_fields and isinstance(child, (dict, list, tuple))]
        if isinstance(entry, (list, tuple)):
            return [child for child in entry if isinstance(child, (dict, list, tuple))]
        return []

    while stack:
        row = stack.pop()
        if isinstance(row, (list, tuple)):
            stack.extend(reversed(row))
        elif isinstance(row, dict):
            named = _first(row, fields)
            if named:
                pairs.append((named, row))
                stack.extend(reversed(nested(row)))
            else:
                for name, entry in row.items():
                    if _key(name, known, stage) is not None:
                        pairs.append((name, entry))
                        stack.extend(reversed(nested(entry)))
                    elif name in row_fields:
                        continue
                    elif isinstance(entry, (dict, list, tuple)):
                        if isinstance(entry, dict) and entry.keys() & row_fields:
                            pairs.append((name, entry))
                        stack.append(entry)
                    else:
                        pairs.append((name, entry))
        elif isinstance(row, str):
            pairs += [(line, line) for line in row.splitlines() if line.strip()]
        elif row is not None:
            notes.append(f"{part} entry {_text(row)[:40]!r} was not an object or text; ignored")
    given = {}
    for name, entry in pairs:
        name = _text(name)
        key = _key(name, known, stage)
        if key is None:
            phase = name.partition(":")[0].strip().casefold()
            if stage and phase in PHASES and phase != stage:
                notes.append(f"ignored {part} entry {name[:40]!r}: a carried key, which needs no answer here")
            elif not known:
                notes.append(f"ignored {part} entry {name[:40]!r}: this checkpoint has no {part}; carried findings "
                             "need no answer. Cite their keys in finding_ids if relevant")
            else:
                notes.append(f"ignored {part} entry {name[:40]!r}, which names no single one of {', '.join(known)[:80]}")
            continue
        given.setdefault(key, []).append(entry)
    return given


def _line(entry, key, part, status_fields):
    """One keyed entry as (statuses, evidence, cited IDs): every status field of an object, or a
    line of text whose status is the line without its key and whose evidence is the line if it
    says more than that status."""
    if isinstance(entry, dict):
        evidence = "; ".join(t for t in (_text(entry.get("evidence")), _text(entry.get("probe"))) if t)
        return [entry[f] for f in status_fields if _text(entry.get(f))], evidence, entry.get("finding_ids")
    text, dropped = _text(entry), []
    rest = re.sub(r"[\w-]+", lambda m: m.group() if dropped or _norm(m.group()) != _norm(key)
                  else dropped.append(1) or " ", text)
    return [rest], text if _says_more(rest, part) else "", ""


def translate(project, data, stage, answer, scratch):
    """Translate an answer into the strict review record. Never raises: returns the record and
    the problems that keep it from being imported. The record is normalized either way, so its
    serious claims can bind as allegations when it is not imported."""
    notes, problems = [], []
    try:
        answer = _canonical_answer(answer)
    except _AnswerBoundaryError as exc:
        return _unexamined_answer(stage, str(exc))
    answer = _shape(answer, notes)
    if answer is None:
        record = {"checkpoint": stage, "verdict": "", "findings": [], "traceability": [],
                  "independent_checks": [], "protocol_dispositions": [], "harness_notes": notes}
        return record, ["the answer must be one JSON object"]
    written = answer.get("verdict", [])
    verdicts = [_read(v, "verdict") for v in written]
    verdict = max(verdicts, key=VERDICTS.index) if verdicts and all(verdicts) else None
    if not verdict:
        unread = next((_text(v)[:40] for v, read in zip(written, verdicts) if not read), "")
        problems.append("verdict must be ACCEPT, REJECT or INCOMPLETE" + (" written alone" if unread else "")
                        + ", not " + (repr(unread) if unread else "nothing"))
    elif len(set(verdicts)) > 1:
        notes.append(f"verdicts {', '.join(sorted(set(verdicts)))}; read as {verdict}")

    entries = _leaves(answer.get("findings"), FINDING_FIELDS)
    drafts = []
    for entry, keys in entries:
        finding, problem = normalize_finding(entry, keys)
        if problem:
            problems.append(problem)
        drafts.append(finding)

    entries = _leaves(answer.get("independent_checks"), CHECK_FIELDS)
    checks = []
    for index, (entry, keys) in enumerate(entries):
        if not isinstance(entry, dict):
            notes.append("dropped an independent check written as text: " + entry[:60])
            continue
        check = {"id": _text(entry.get("id")) or _named_id(keys) or f"C-{index + 1}",
                 **{field: _text(entry.get(field)) or NOT_STATED for field in CHECK_TEXT},
                 "result": _read(entry.get("result"), "result", "ERROR"),
                 "finding_ids": _text(entry.get("finding_ids"))}
        check["receipt_id"] = _text(entry.get("receipt_id"))
        if _hedged(entry.get("result"), "result"):
            notes.append(f"check {check['id']}: result read as {check['result']}; PASS counts only written alone")
        checks.append(check)

    ids = [r["id"] for r in data["requirements"]]
    items = open_items(project, data, stage)
    reserved = {name.casefold() for name in (*ids, *items, *(f["id"] for f in drafts))}
    proofs = _proofs(project, scratch, checks, reserved) if stage in EXECUTED_CHECKPOINTS else None
    for finding in drafts:
        # A reviewer changes nothing, so its own finding is closed only by what it observed.
        if finding["status"] == "CLOSED" and proofs is not None and not _proved(
                finding["closure"] + "; " + finding["evidence"], proofs):
            notes.append(f"finding {finding['id']}: CLOSED reads as OPEN; its closure must name a probe file that a "
                         "check with result PASS ran in the scratch directory, or that check's ID")
            finding["status"] = "OPEN"
    by_claim, alias = {}, {}
    for finding in drafts:
        first = by_claim.setdefault(claim_digest(finding), finding)
        if first is not finding:
            notes.append(f"finding {finding['id']} repeats {first['id']}; kept once")
            alias[finding["id"].casefold()] = first
    drafts = [f for f in drafts if by_claim[claim_digest(f)] is f]

    replies = _keyed(answer.get("open_items", []), list(items), ("handle", "id", "finding", "finding_id", "item"),
                     "open_items", notes, stage)
    taken = {key.split(":", 1)[1].casefold() for key, item in project._seed_defects(data).items()
             if key.startswith(stage + ":") or item.get("raised_at") == stage}
    taken |= {handle.casefold() for handle in items}
    counters = {}

    def fresh(name):
        """name, or name-rN when a handle or another finding has it in any case."""
        final, n = name, counters.get(name.casefold(), 2)
        while final.casefold() in taken or HANDLE.fullmatch(final):
            final, n = f"{name}-r{n}", n + 1
        counters[name.casefold()] = n
        taken.add(final.casefold())
        return final

    findings, dispositions, unresolved, names, used, answered = [], [], [], {}, set(), {}
    for handle, item in items.items():
        lines = [_line(entry, handle, "answer", ("status", "answer", "result")) for entry in replies.get(handle, [])]
        status = max((_weakest(s, "answer", "NOT_CHECKED") for s, _, _ in lines), key=ANSWERS.index,
                     default="NOT_CHECKED")
        evidence = "; ".join(e for _, e, _ in lines if e)
        if any(_hedged(s, "answer") for statuses, _, _ in lines for s in statuses):
            notes.append(f"{handle}: read as {status}; CLOSED counts only written alone, as in "
                         f'{{"{handle}": {{"status": "CLOSED", "evidence": "..."}}}}')
        # Making the claim again keeps it open, whatever the reply says.
        again = by_claim.get(item.get("claim"))
        if again:
            if status != "STILL_OPEN":
                notes.append(handle + ": reported again as a new finding, so it stays open")
            status, evidence = "STILL_OPEN", evidence or again["evidence"]
            used.add(id(again))
        if status != "NOT_CHECKED" and not evidence:
            notes.append(handle + ": an answer without evidence reads as NOT_CHECKED")
            status = "NOT_CHECKED"
        if status == "CLOSED" and proofs is not None and not _proved(evidence, proofs):
            notes.append(handle + ": CLOSED reads as NOT_CHECKED; its evidence must name a probe file that a check "
                         "with result PASS ran in the scratch directory, or that check's ID")
            status = "NOT_CHECKED"
        answered[handle] = status
        if item["required"] and status != "CLOSED":
            unresolved.append(f"{handle} (read as {status})")
        if status == "NOT_CHECKED":
            continue
        quotes = {name: _text(e[name]) for e in replies.get(handle, []) if isinstance(e, dict)
                  for name in QUOTES if _text(e.get(name))}
        if item["type"] == "finding":
            finding = {**item["finding"], "artifact": item["origin_artifact"], "evidence": evidence, "answers": handle,
                       **quotes}
            finding.pop("prior_finding_digest", None)
            if status == "CLOSED":
                finding.update(status="CLOSED", closure=evidence, prior_finding_digest=item["origin_digest"])
            else:
                finding["status"] = "OPEN"
            findings.append(finding)
        elif status == "CLOSED":
            dispositions += [{"finding_digest": key, "status": "CLOSED", "finding_id": "",
                              "evidence": evidence, "closure": evidence} for key in item["keys"]]
        else:
            source = again or {**item["finding"], "status": "OPEN", "evidence": evidence, **quotes}
            final = names[handle.casefold()] = fresh(item["finding"]["id"] if HANDLE.fullmatch(source["id"]) else source["id"])
            if again:
                names[again["id"].casefold()] = final
            findings.append({**source, "id": final, "answers": handle})
            dispositions += [{"finding_digest": key, "status": "TRACKED", "finding_id": final,
                              "evidence": evidence, "closure": "Tracked as open finding " + final} for key in item["keys"]]
    defects = data.get("defects", {})
    for finding in drafts:
        if id(finding) not in used:
            name = finding["id"]
            handle = next((h for h, item in items.items() if item["type"] == "finding" and h.casefold() == name.casefold()), None)
            if handle and _restates(finding, items[handle], defects.get(items[handle]["key"], {}), answered.get(handle)):
                prior = next((f for f in findings if f.get("answers") == handle), None)
                if prior is None:
                    prior = {**items[handle]["finding"], "artifact": items[handle]["origin_artifact"],
                             "evidence": finding["evidence"], "answers": handle, "status": "OPEN"}
                    prior.pop("prior_finding_digest", None)
                    findings.append(prior)
                elif finding["evidence"] not in prior["evidence"]:
                    prior["evidence"] += "; " + finding["evidence"]
                if finding.get("user_decision") is True:
                    prior["user_decision"] = True
                prior.update({name: finding[name] for name in QUOTES if name in finding})
                if answered.get(handle) == "NOT_CHECKED" and items[handle]["required"]:
                    unresolved[unresolved.index(f"{handle} (read as NOT_CHECKED)")] = f"{handle} (read as STILL_OPEN)"
                answered[handle] = "STILL_OPEN"
                names[name.casefold()] = prior["id"]
                notes.append(f"{name} restated as a finding; read as STILL_OPEN answer to {handle}")
                continue
            finding["id"] = names[name.casefold()] = fresh(name)
            if handle:
                notes.append(f"{finding['id']} reuses the ID of open {handle} with a different claim: possible restatement of {handle}")
            findings.append({**finding})
    names.update({name: names.get(first["id"].casefold(), first["id"]) for name, first in alias.items()})

    def cite(value):
        """The final IDs of the findings a row names by the reviewer's own ID or by handle."""
        return ", ".join(names.get(i.casefold(), i) for i in _ids(value))

    given = _keyed(answer.get("traceability", []), ids, ("requirement", "requirement_id", "req", "id"),
                   "traceability", notes)
    trace = []
    for requirement in ids:
        stated = []
        for statuses, evidence, cited in (_line(e, requirement, "trace", ("status", "result"))
                                          for e in given.get(requirement, [])):
            stated.append({"status": _weakest(statuses, "trace", "UNVERIFIED"), "evidence": evidence,
                           "finding_ids": cited})
            if any(_hedged(s, "trace") for s in statuses):
                notes.append(f"{requirement}: read as {stated[-1]['status']}; VERIFIED counts only written alone, as in "
                             f'{{"{requirement}": {{"status": "VERIFIED", "evidence": "..."}}}}')
        if not stated:
            trace.append({"requirement": requirement, "status": "UNVERIFIED", "evidence": NOT_ASSESSED, "finding_ids": ""})
            continue
        if len(stated) > 1:
            notes.append(f"{requirement}: {len(stated)} rows merged, keeping the weakest status")
        trace.append({"requirement": requirement, "status": max((r["status"] for r in stated), key=TRACE_RANK.index),
                      "evidence": "; ".join(r["evidence"] for r in stated if r["evidence"]) or NOT_STATED,
                      "finding_ids": ", ".join(c for c in (cite(r["finding_ids"]) for r in stated) if c)})
    for check in checks:
        check["finding_ids"] = cite(check["finding_ids"])

    shown = next((_text(v)[:40] for v in written if _text(v)), "")
    record = {"checkpoint": stage, "verdict": verdict or shown, "findings": findings,
              "traceability": trace, "independent_checks": checks, "protocol_dispositions": dispositions}
    if any(_plain(v) == "SEQUENTIAL ROLE PASS" for v in answer["independence"]):
        record["independence"] = "sequential-role-pass"
    if notes:
        record["harness_notes"] = notes
    if verdict == "ACCEPT" and unresolved:
        problems.append("ACCEPT needs every open item CLOSED on current evidence; not closed: " + ", ".join(unresolved)
                        + ". Answer each in open_items as {\"status\": \"CLOSED\", \"evidence\": ...}"
                        + (" naming your passing probe" if proofs is not None else "") + ", or REJECT")
    if verdict == "REJECT" and not unresolved and not _blocks(project, data, stage, record):
        carried = [f["id"] for f in findings if f.get("status") != "CLOSED" and _carried(project, data, stage, f)]
        still = [f"{f['id']} ({f['severity']})" for f in findings
                 if f.get("status") != "CLOSED" and f["id"] not in carried]
        problems.append("REJECT needs a blocking reason, an open CRITICAL or MAJOR finding or a FAILED requirement,"
                        " and this report has neither" + (" (open: " + ", ".join(still) + ")" if still else "") + ". "
                        + (", ".join(carried) + " question the approved contract, which this checkpoint cannot change:"
                           " each is carried to the architecture design, which must answer it, and none blocks "
                           + stage + ". Keep each OPEN as written, and name it in a PARTIAL row, not a FAILED one. "
                           if carried else "")
                        + "If the open findings do not block real use, answer ACCEPT and keep them open, with a"
                        " traceability row with evidence for every requirement, naming each open finding in the rows"
                        " it explains" + ("; if one does block, make it MAJOR and say in its impact how a user is hurt"
                                          if still else ""))
    if stage != "requirements":
        problems += [p for p in (_conflict_problem(project, data, f) for f in findings) if p]
    return record, problems + charter_problems(project, record, data, stage, scratch)


def _plain_quote(text):
    """Text as a quote is compared: case, spacing, markdown marks, list and heading markers,
    curly quotes, dashes and closing punctuation aside."""
    text = _text(text).translate({0x60: None, 0x2A: None, 0x5F: None, 0x2018: "'", 0x2019: "'", 0x201C: '"',
                                  0x201D: '"', 0x2212: "-", 0x2013: "-", 0x2014: "-"})
    text = " ".join(re.sub(r"^[\s>#|+-]+", "", line) for line in text.splitlines())
    return " ".join(text.casefold().split()).strip(" '\".,;:")


def _carried(project, data, stage, finding):
    """Whether a finding is due at a later checkpoint, so it does not block this one."""
    return project.due(stage, finding, data.get("defects", {})) != stage


def _conflict_problem(project, data, finding):
    """Why a serious open finding on the approved contract may not stay open, or None. After
    requirements it sends the design back for repair, so it must quote the requirements.md text
    and the design's own text that conflict, each exactly; a question the design answers is closed."""
    if (finding.get("severity") not in SERIOUS or finding.get("status") == "CLOSED"
            or project.reserved_location(_text(finding.get("artifact"))) != "contract"):
        return None
    documents = {"contract_text": "", "design_text": ""}
    names = [name for name, fingerprint in project.snapshot(data)["artifacts"].items() if fingerprint is not None]
    for name in ["requirements.md", *names]:
        path, kind = project.root / name, project.reserved_location(name)
        part = "contract_text" if kind == "contract" else "design_text"
        if (kind != "control" and path.suffix.lower() in TEXT_DOCUMENTS and path.is_file()
                and not (part == "contract_text" and documents[part])):
            documents[part] += _plain_quote(path.read_text(encoding="utf-8", errors="replace")) + "\n"
    failed = []
    for name, source in (("contract_text", "requirements.md"), ("design_text", "a scoped design document")):
        quote = _plain_quote(finding.get(name))
        if not quote:
            failed.append(name + " is missing")
        elif len(quote.replace(" ", "")) < QUOTE_CHARACTERS or quote not in documents[name]:
            failed.append(name + " is not an exact quote of " + source)
        elif name == "design_text" and quote in documents["contract_text"]:
            failed.append("design_text is requirements.md text, not the design's own reading")
    if not failed:
        return None
    return (finding["id"] + " keeps a serious finding on the approved contract open, which sends the design back for"
            " repair; that needs contract_text and design_text, the requirements.md sentence and the design's own"
            " sentence that conflict, each copied exactly, in the finding or in its open_items answer ("
            + "; ".join(failed) + "). If the design's reading contradicts no requirements.md sentence, answer "
            + finding["id"] + " CLOSED; that the contract could say more is no reason to keep it open")


def _blocks(project, data, stage, record):
    """Whether something blocks this checkpoint, so a REJECT has a reason: the record's own open
    CRITICAL or MAJOR finding or FAILED requirement, or what the gate refuses whatever the review
    says (a declared check or semantic adequacy not passed on the current files, an earlier
    checkpoint's blocking finding or serious allegation, a handoff obligation). Open items the
    record leaves unanswered are the caller's to count."""
    carried = {name.casefold() for f in record["findings"] if _carried(project, data, stage, f)
               for name in (f["id"], project.due(stage, f, data.get("defects", {})) + ":" + f["id"])}
    if (any(f.get("severity") in SERIOUS and f.get("status") != "CLOSED" and f["id"].casefold() not in carried
            for f in record["findings"])
            # A FAILED row that names only findings due later is no reason here either.
            or any(row.get("status") == "FAILED"
                   and not ({i.casefold() for i in _ids(row.get("finding_ids"))} or {""}) <= carried
                   for row in record["traceability"])):
        return True
    current = project.snapshot(data)
    if stage in EXECUTED_CHECKPOINTS and any(value is None for value in current["artifacts"].values()):
        return True
    for name in data.get("required_checks", {}).get(stage, []):
        # As the gate reads a check record: a missing, changed or unreadable one blocks.
        entry = data.get("evidence", {}).get(name)
        try:
            path = inside(project.root, entry["path"])
            evidence = read_json(path) if digest(path) == entry["sha256"] else {}
        except (ProjectError, OSError, KeyError, TypeError, ValueError):
            return True
        if (evidence.get("status") != "PASSED" or evidence.get("exit_code") != 0
                or evidence.get("command") != data.get("commands", {}).get(name)
                or evidence.get("snapshot") != current):
            return True
    from .semantics import problems as semantic_problems
    # The gate blocks on a defect of an earlier checkpoint, or of one it does not know.
    later = PHASES[PHASES.index(stage):]
    return bool(semantic_problems(project, data, stage)
                or any(item["blocking"] and item.get("checkpoint") not in later for item in data.get("defects", {}).values())
                or any(item["checkpoint"] not in later for item in project.pending_review_findings(data).values())
                or (stage == "handoff" and project.handoff_obligations(data)))


def _same_text(a, b):
    return " ".join(_text(a).casefold().split()) == " ".join(_text(b).casefold().split())


def _restates(finding, item, defect, status):
    """Whether a new finding under an open finding's ID is that same claim: the same evidence as
    its origin, or the same exact artifact (line included) in a report that answers it STILL_OPEN.
    Never when it is more severe, not open, or the report closes the item."""
    rank = ("CRITICAL", "MAJOR", "MODERATE", "MINOR")
    if (finding["status"] != "OPEN" or status == "CLOSED"
            or rank.index(finding["severity"]) < rank.index(item["finding"]["severity"])):
        return False
    origin = defect.get("origin", {})
    return (_same_text(finding["evidence"], origin.get("evidence")) or (
        status == "STILL_OPEN" and any(_same_text(finding["artifact"], a)
                                       for a in (item["origin_artifact"], item["finding"].get("artifact")))))


def charter_problems(project, record, data, stage, scratch):
    """Structural minimum of the reviewer charter on a translated record; it never supplies a
    verdict. ACCEPT needs a supported row for every requirement, and a row it does not verify
    needs an open finding of its own that is not serious (a serious one blocks ACCEPT anyway).
    An executed checkpoint needs a probe of the reviewer's own, whatever the verdict."""
    problems = []
    if record.get("verdict") == "ACCEPT":
        explained = {_text(f.get("id")).casefold() for f in record.get("findings", []) if isinstance(f, dict)
                     and f.get("status") != "CLOSED"
                     and (f.get("severity") not in SERIOUS or _carried(project, data, stage, f))}
        explained |= {f"{stage}:{name}".casefold() for name in explained}
        closed = {_text(f.get("answers")).casefold() for f in record.get("findings", [])
                  if isinstance(f, dict) and f.get("status") == "CLOSED"}
        carried, bare = {}, {}
        for key, item in data.get("defects", {}).items():
            phase, _, name = key.partition(":")
            bare.setdefault(name.casefold(), []).append(key)
            if item["finding"]["status"] != "OPEN" or item["finding"]["severity"] in SERIOUS:
                continue
            if phase == stage:
                # A recorded finding of this checkpoint that this report does not close.
                if name.casefold() not in closed:
                    explained |= {name.casefold(), key.casefold()}
            else:
                carried[key] = item["finding"]

        def explains(cited, requirement):
            """A carried finding explains a row only when its own text cites that requirement."""
            for i in cited:
                keys = [k for k in carried if k.casefold() == i] or [
                    k for k in bare.get(i, []) if len(bare[i]) == 1 and k in carried]
                if any(cites(" ".join(_text(carried[k].get(f)) for f in ("artifact", "evidence", "repair", "impact")),
                             requirement) for k in keys):
                    return True
            return False
        rows = {row.get("requirement"): row for row in record.get("traceability", []) if isinstance(row, dict)}
        missing = [i for i in (r["id"] for r in data["requirements"])
                   if _text(rows.get(i, {}).get("evidence")) in {"", NOT_STATED, NOT_ASSESSED}]
        if missing:
            problems.append("ACCEPT needs a traceability row with evidence for every requirement, as "
                            f'{{"{missing[0]}": {{"status": "VERIFIED", "evidence": "..."}}}}; missing: '
                            + ", ".join(missing))
        for name, row in rows.items():
            if name in missing:
                continue
            ids = {i.casefold() for i in _ids(row.get("finding_ids"))}
            if row.get("status") == "FAILED":
                problems.append("ACCEPT is inconsistent with FAILED requirement " + name)
            elif row.get("status") != "VERIFIED" and not ids & explained and not explains(ids, name):
                problems.append("requirement " + name + " is " + str(row.get("status")) + " under ACCEPT; "
                                "name the open MODERATE or MINOR finding that explains it (this report's, or a "
                                "recorded one that cites " + name + "), or REJECT if something blocks (an open"
                                " CRITICAL or MAJOR finding, or a FAILED requirement)")
    if stage in EXECUTED_CHECKPOINTS and not any(
            isinstance(c, dict) and _own_artifacts(project, scratch, c)
            for c in record.get("independent_checks", [])):
        problems.append("no independent check names an existing artifact in the scratch directory " + str(scratch)
                        + "; re-running the builder's tests is not independent review")
    return problems


def scratch_files(project, scratch):
    if not scratch.is_dir():
        return {}
    return {path.relative_to(project.root).as_posix(): digest(path)
            for path in sorted(scratch.rglob("*")) if path.is_file()}


def import_answer(project, owner, handoff, answer, report, identity, refusal=None, kind="protocol"):
    """The one way an answer becomes a review, for a runtime receipt and a host alike.

    handoff is the reviewer packet the answer belongs to; its snapshot must still be current and
    the reviewer must not have built anything (a ProjectError, and nothing binds). identity
    carries reviewer_session, model, independence and identity_source, all attested by the
    channel; an answer may lower its independence to sequential-role-pass, never raise it.
    The record is written to report, a path no other answer uses. refusal is a reason found
    outside the answer (the reviewer changed files, its run did not finish). An answer that is
    not imported, for any reason, binds its serious claims and raises ReviewProtocolError
    with every problem, how the answer was read, and the handles those claims now have.
    Returns the import result.
    """
    stage = handoff["checkpoint"]
    data = project.load()
    if handoff.get("role") != "reviewer" or stage != data["phase"]:
        raise ProjectError("Answer a reviewer packet for the current checkpoint " + data["phase"])
    if handoff["snapshot_digest"] != value_digest(project.snapshot(data)):
        raise ProjectError("Reviewer did not inspect current artifact snapshot; the files changed after the packet, "
                           "so ask for a new reviewer packet and review again")
    contributors = {data["builder_session"], *data.get("contributors", []), *(t["worker"] for t in data["tasks"].values())}
    if identity["reviewer_session"] in contributors:
        raise ProjectError("Reviewer session must differ from every contributing builder/worker session")
    from .ingestion import prepare_answer, finish_reconciliation
    reviewed, ingress_problems, reconciled = prepare_answer(project, owner, handoff, answer)
    # Reload because raw admission may have durably added an unread-source gap.
    data = project.load()
    scratch = Path(handoff["scratch"])
    record, problems = translate(project, data, stage, reviewed.answer, scratch)
    problems = ingress_problems + problems
    record["input_assurance"] = reviewed.assurance
    if refusal:
        problems.insert(0, refusal)
    lowered = record.get("independence") == "sequential-role-pass"
    record.update(checkpoint=stage, snapshot_digest=handoff["snapshot_digest"],
                  packet_id=Path(handoff["prompt"]).parent.name,
                  reviewer_session=identity["reviewer_session"], model=identity["model"],
                  independence="sequential-role-pass" if lowered else identity["independence"],
                  scratch_manifest=scratch_files(project, scratch))
    atomic_json(report, record)
    name = report.relative_to(project.root).as_posix()
    if not problems:
        try:
            project.review(owner, stage, name, identity_source=identity["identity_source"])
            finish_reconciliation(project, owner, handoff, reconciled, name)
            return {"imported": name, "notes": record.get("harness_notes", [])}
        except ReviewProtocolError as exc:
            problems = [str(exc)]
    project.record_review_protocol_failure(owner, stage, name, "; ".join(problems), kind=kind)
    data = project.load()
    pending = project.pending_review_findings(data)
    bound = [handle for handle, item in open_items(project, data, stage).items() if item["type"] == "allegation"
             and any(pending[key]["source_report"] == name for key in item["keys"])]
    message = "Review not imported: " + "; ".join(problems) + "."
    if record.get("harness_notes"):
        message += " How your answer was read: " + "; ".join(record["harness_notes"][:8]) + "."
    if bound:
        message += (" Your serious findings are now open items " + ", ".join(bound) + ": answer each in open_items "
                    "(STILL_OPEN keeps it as your finding; CLOSED needs evidence).")
    raise ReviewProtocolError(message)


def latest_packet(project, packet_id=None):
    """A reviewer packet by ID, or the newest one for the current checkpoint."""
    if packet_id:
        path = project.control / "packets" / Path(str(packet_id)).name / "packet.json"
        if not path.is_file():
            raise ProjectError("Unknown packet " + str(packet_id))
        return json.loads(path.read_text(encoding="utf-8"))
    stage = project.load()["phase"]
    found = []
    for path in (project.control / "packets").glob("*/packet.json"):
        item = json.loads(path.read_text(encoding="utf-8"))
        if item["role"] == "reviewer" and item["checkpoint"] == stage:
            found.append((item["created"], path.parent.name, item))
    if not found:
        raise ProjectError("No reviewer packet for checkpoint " + stage + "; ask for a reviewer packet first")
    return max(found, key=lambda entry: entry[:2])[2]
