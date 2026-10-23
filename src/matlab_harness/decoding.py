"""Bounded, loss-aware decoding at untrusted review boundaries.

Persisted project/evidence JSON deliberately uses its existing versioned loader.
Duplicates never become a last-value-wins dict. Recoverable alternatives are
retained for allegation binding; every ambiguity also requires reconciliation.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import base64
import hashlib
import json
import math
import re
from pathlib import Path

MAX_BYTES = 1_048_576
MAX_DEPTH = 64
MAX_VALUES = 50_000
MAX_CANDIDATES = 200

class Pairs(list):
    pass

@dataclass
class ReviewInput:
    answer: object = None
    problems: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    assurance: str = "raw-validated-v1"

    def metadata(self):
        return {"version": 1, "problems": list(dict.fromkeys(self.problems)),
                "sources": self.sources, "assurance": self.assurance}

def source_record(raw, kind="review"):
    if isinstance(raw, str):
        raw = raw.encode("utf-8", errors="surrogatepass")
    return {"kind": kind, "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw), "base64": base64.b64encode(raw).decode("ascii")}


def file_source(path, kind="review"):
    """Reference complete retained output without loading an unbounded stream."""
    path = Path(path).resolve()
    hasher, size = hashlib.sha256(), 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
            size += len(chunk)
    return {"kind": kind, "sha256": hasher.hexdigest(), "bytes": size, "artifact": str(path)}


def decode_file(path, kind="review", document=False):
    """Bound file reads before decoding; preserve oversized sources by reference."""
    with Path(path).open("rb") as handle:
        raw=handle.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:
        return ReviewInput(problems=["Raw JSON byte limit exceeded; source not completely examined"],
                           sources=[file_source(path,kind)])
    return decode_document(raw,kind) if document else decode_answer(raw,kind)

def _key(value):
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())

def _normalise(value, problems, counter, path="$", depth=0):
    counter[0] += 1
    if counter[0] > MAX_VALUES or depth > MAX_DEPTH:
        raise ValueError("JSON value/depth limit exceeded; source not completely examined")
    if isinstance(value, Pairs):
        baseline, variants, seen = {}, [], set()
        for key, child in value:
            if any(0xD800 <= ord(c) <= 0xDFFF for c in key):
                problems.append("Invalid Unicode surrogate in object key at " + path)
                key = key.encode("unicode_escape").decode("ascii")
            normal = _normalise(child, problems, counter, path + "." + key, depth + 1)
            if key in seen:
                problems.append("Duplicate JSON member at " + path + "." + key)
                variants.append((key, normal))
            else:
                seen.add(key)
                baseline[key] = normal
        if variants:
            # Linear alternatives, not a Cartesian product of duplicate branches.
            counter[0] += (len(variants) + 1) * max(1, len(baseline))
            if counter[0] > MAX_VALUES:
                raise ValueError("JSON alternative/value limit exceeded; source not completely examined")
            # Preserve field-local alternatives together too: severity and status
            # may both conflict. One-key substitutions alone could lose the
            # strongest severity paired with the least closed status. Domain
            # readers already combine lists conservatively; this is linear in
            # the input rather than a Cartesian product.
            grouped = {}
            for key, child in variants:
                grouped.setdefault(key, [baseline[key]]).append(child)
            projection = {**baseline, **grouped}
            return {"answer_sources": [baseline, *[{**baseline, k: v} for k, v in variants], projection]}
        return baseline
    if isinstance(value, list):
        return [_normalise(v, problems, counter, path + f"[{i}]", depth + 1)
                for i, v in enumerate(value)]
    if isinstance(value, str) and any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        problems.append("Invalid Unicode surrogate at " + path)
        return value.encode("unicode_escape").decode("ascii")
    return value

def _parse(text, problems):
    def constant(value):
        problems.append("Nonfinite JSON number: " + value)
        return None
    def floating(value):
        number = float(value)
        if not math.isfinite(number):
            problems.append("Nonfinite JSON exponent: " + value)
            return None
        return number
    parsed = json.loads(text, object_pairs_hook=Pairs, parse_constant=constant, parse_float=floating)
    return _normalise(parsed, problems, [0])

def decode_document(raw, kind="review"):
    """One JSON document; callers never silently fall back after an ambiguity."""
    result = ReviewInput(sources=[source_record(raw, kind)])
    try:
        encoded = raw.encode("utf-8", errors="strict") if isinstance(raw, str) else bytes(raw)
        if len(encoded) > MAX_BYTES:
            raise ValueError("Raw JSON byte limit exceeded; source not completely examined")
        text = encoded.decode("utf-8-sig", errors="strict")
        result.answer = _parse(text, result.problems)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        result.problems.append(type(exc).__name__ + ": " + str(exc))
    return result

def decode_answer(raw, kind="review", _layer=0):
    """Whole or embedded/fenced JSON answers, preserving every candidate."""
    result = decode_document(raw, kind)
    if isinstance(result.answer, str):
        if _layer >= 8:
            result.problems.append("Encoded review layer limit exceeded; source not completely examined")
            result.answer = None
        else:
            nested = decode_answer(result.answer, kind, _layer + 1)
            result.answer = nested.answer
            result.problems.extend(nested.problems)
        return result
    if result.answer is not None or not result.problems:
        if not isinstance(result.answer, (dict, list)):
            result.problems.append("Review must contain an object or array, not a scalar")
        return result
    # Size/encoding/depth failures are not invitations to scan just a safe prefix.
    try:
        encoded = raw.encode("utf-8", errors="strict") if isinstance(raw, str) else bytes(raw)
        text = encoded.decode("utf-8-sig", errors="strict")
    except (ValueError, TypeError, UnicodeError):
        return result
    if len(encoded) > MAX_BYTES:
        return result
    values, issues = [], []
    i, candidates = 0, 0
    while i < len(text):
        if text[i] not in "[{":
            i += 1
            continue
        candidates += 1
        if candidates > MAX_CANDIDATES:
            issues.append("JSON candidate limit exceeded; source not completely examined")
            break
        start, stack, quoted, escaped = i, [], False, False
        while i < len(text):
            c = text[i]
            if quoted:
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == '"':
                    quoted = False
            elif c == '"':
                quoted = True
            elif c in "[{":
                stack.append(c)
                if len(stack) > MAX_DEPTH:
                    issues.append("JSON depth limit exceeded; source not completely examined")
                    i = len(text)
                    break
            elif c in "]}":
                if not stack or (stack[-1], c) not in {("[", "]"), ("{", "}")}:
                    issues.append("Mismatched JSON candidate")
                    i += 1
                    break
                stack.pop()
                if not stack:
                    i += 1
                    try:
                        values.append(_parse(text[start:i], issues))
                    except (ValueError, TypeError, RecursionError) as exc:
                        issues.append(type(exc).__name__ + ": " + str(exc))
                    break
            i += 1
        if stack or quoted:
            issues.append("Unterminated JSON candidate; source not completely examined")
    if values:
        result.answer = values[0] if len(values) == 1 else values
        result.problems = issues
    elif issues:
        result.problems = issues
    return result

_REVIEW_KEYS = {"verdict", "findings", "issues", "defects", "traceability",
                "requirements", "openitems", "independentchecks", "checks"}

def _has_review(value):
    if isinstance(value, dict):
        return bool({_key(k) for k in value} & _REVIEW_KEYS) or any(
            _has_review(v) for v in value.values() if isinstance(v, (dict, list)))
    if isinstance(value, list):
        return any(_has_review(v) for v in value)
    return False

def combine_answers(structured, raw=None, ignore_scalar_fields=()):
    """Keep both documented review channels and refuse conflicting content."""
    result = ReviewInput(assurance="decoded-host-attested-v1")
    values = []
    def same(left, right):
        # Documented AGY result annotations are outside the reviewer contract.
        # Only the adapter opts in, only these exact root text fields qualify,
        # and object/array payloads remain material so nested claims survive.
        allowed = set(ignore_scalar_fields) & {"toolAction", "toolSummary"}
        def view(value):
            return {k:v for k,v in value.items() if k not in allowed or not isinstance(v,str)} if isinstance(value,dict) else value
        return view(left) == view(right)
    if structured is not None:
        if isinstance(structured, (str, bytes)):
            decoded = decode_answer(structured, "structured-output")
            result.sources += decoded.sources
            result.problems += decoded.problems
            values.append(decoded.answer)
        else:
            values.append(structured)
    if raw is not None:
        decoded = decode_answer(raw, "raw-response") if isinstance(raw, (str, bytes)) else ReviewInput(raw)
        result.sources += decoded.sources
        if _has_review(decoded.answer):
            if values and not same(decoded.answer, values[0]):
                result.problems.append("Conflicting raw and structured review channels; reconcile both")
            if not values or not same(decoded.answer, values[0]):
                values.append(decoded.answer)
            result.problems += decoded.problems
        elif not values:
            if not values or decoded.answer != values[0]:
                values.append(decoded.answer)
            result.problems += decoded.problems
        # Plain progress prose beside structured output is not a review source.
        elif decoded.problems and any(word in str(raw).casefold() for word in ('"findings"', '"verdict"', '"issues"')):
            result.problems += decoded.problems
    result.answer = values[0] if len(values) == 1 else values or None
    if result.sources:
        result.assurance = "raw-validated-v1"
    return result

def from_metadata(answer, metadata):
    return ReviewInput(answer, list(metadata.get("problems", [])), list(metadata.get("sources", [])),
                       metadata.get("assurance", "decoded-host-attested-v1"))
