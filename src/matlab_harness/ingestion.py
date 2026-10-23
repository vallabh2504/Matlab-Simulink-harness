"""Durable unread-review gaps and owner-authorized, packet-bound replacement."""
from __future__ import annotations
import base64
from pathlib import Path
import uuid
import shutil
from .decoding import ReviewInput, decode_answer, file_source
from .project import PHASES, ProjectError, atomic_json, digest, now, value_digest

def open_gaps(data, checkpoint=None):
    return {k: v for k, v in data.get("ingestion_gaps", {}).items()
            if v.get("status") != "RESOLVED"
            and (checkpoint is None or PHASES.index(v["checkpoint"]) <= PHASES.index(checkpoint))}

def record_gap(project, owner, handoff, review):
    """Raw bytes first, then one transactional durable blocking record."""
    sources = []
    directory = project.control / "ingestion"
    directory.mkdir(exist_ok=True)
    for source in review.sources:
        item = {k: v for k, v in source.items() if k != "base64"}
        if "base64" in source:
            raw = base64.b64decode(source["base64"], validate=True)
            path = directory / (source["sha256"] + ".bin")
            if not path.exists():
                with path.open("xb") as handle:
                    handle.write(raw)
            if digest(path) != source["sha256"]:
                raise ProjectError("Retained raw review source was modified")
            item["path"] = path.relative_to(project.root).as_posix()
        elif "artifact" in source:
            original = Path(source["artifact"]).resolve()
            if not original.is_relative_to(project.root.resolve()):
                raise ProjectError("Retained raw source must be inside the project")
            if file_source(original)["sha256"] != source["sha256"]:
                raise ProjectError("Retained transport source changed before ingestion")
            path = directory / (source["sha256"] + ".bin")
            if not path.exists():
                with original.open("rb") as source_handle, path.open("xb") as target:
                    shutil.copyfileobj(source_handle, target, 65536)
            if file_source(path)["sha256"] != source["sha256"]:
                raise ProjectError("Retained raw transport source was modified")
            item.pop("artifact", None)
            item["path"] = path.relative_to(project.root).as_posix()
        sources.append(item)
    source_hash = value_digest(sources or {"opaque_problems": review.problems})
    with project.transaction(owner) as data:
        gaps = data.setdefault("ingestion_gaps", {})
        existing = next((k for k, v in gaps.items()
                         if v["checkpoint"] == handoff["checkpoint"]
                         and v["source_sha256"] == source_hash and v["status"] != "RESOLVED"), None)
        identifier = existing or "G-" + uuid.uuid4().hex[:16]
        if not existing:
            gaps[identifier] = {"checkpoint": handoff["checkpoint"], "status": "OPEN",
                                "source_sha256": source_hash, "sources": sources,
                                "snapshot_digest": handoff["snapshot_digest"], "created": now(),
                                "problems": list(dict.fromkeys(review.problems))}
    return identifier

def authorize_reconciliation(project, owner, gap_id, source_sha256, packet_id, reason):
    """Trusted orchestrator operation; never inferred from model JSON fields."""
    if not isinstance(reason, str) or not reason.strip():
        raise ProjectError("Reconciliation authorization requires an inspected-source reason")
    from .workflow import latest_packet
    handoff = latest_packet(project, packet_id)
    data = project.load()
    gap = open_gaps(data, handoff["checkpoint"]).get(gap_id)
    if not gap or gap["source_sha256"] != source_sha256:
        raise ProjectError("Unknown gap or changed unread source hash")
    if handoff["snapshot_digest"] != value_digest(project.snapshot(data)):
        raise ProjectError("Reconciliation packet is stale")
    pinned = handoff.get("ingestion_gaps", {}).get(gap_id)
    if not pinned or pinned["source_sha256"] != source_sha256:
        raise ProjectError("Create a new packet that explicitly pins this unread source")
    for source in gap["sources"]:
        if "path" in source:
            path = project.root / source["path"]
            if not path.is_file() or digest(path) != source["sha256"]:
                raise ProjectError("Unread source missing or changed; inspect before reconciliation")
    with project.transaction(owner) as data:
        data["ingestion_gaps"][gap_id]["authorization"] = {
            "packet_id": Path(handoff["prompt"]).parent.name,
            "snapshot_digest": handoff["snapshot_digest"], "owner": owner,
            "reason": reason.strip(), "at": now()}
    return {"gap_id": gap_id, "source_sha256": source_sha256, "packet_id": packet_id,
            "status": "CORRECTION_AUTHORIZED", "resolved": False}

def _parts(value, name):
    found, todo = [], [value]
    while todo:
        item = todo.pop()
        if isinstance(item, dict):
            if name in item:
                found.append(item[name])
            todo.extend(v for k, v in item.items() if k != name and isinstance(v, (dict, list)))
        elif isinstance(item, list):
            todo.extend(item)
    return found

def prepare_answer(project, owner, handoff, answer):
    review = answer if isinstance(answer, ReviewInput) else (
        decode_answer(answer) if isinstance(answer, (str, bytes)) else
        ReviewInput(answer, assurance="decoded-host-attested-v1"))
    if review.problems:
        gap_id = record_gap(project, owner, handoff, review)
        return review, [f"Unread review source {gap_id}: " + "; ".join(review.problems)], []
    data = project.load()
    gaps = open_gaps(data, handoff["checkpoint"])
    if not gaps:
        return review, [], []
    requests = {}
    for group in _parts(review.answer, "reconciliation"):
        if isinstance(group, list):
            for request in group:
                if isinstance(request, dict):
                    requests.setdefault(request.get("gap_id"), []).append(request)
    packet_id = Path(handoff["prompt"]).parent.name
    problems, resolved = [], []
    handles = set()
    for part in _parts(review.answer, "open_items"):
        if isinstance(part, dict):
            handles.update(part)
    missing_handles = set(handoff.get("open_handles", [])) - handles
    if missing_handles:
        problems.append("Correction must explicitly disposition every pinned open handle: " + ", ".join(sorted(missing_handles)))
    for key, gap in gaps.items():
        for source in gap["sources"]:
            if "path" in source:
                path = project.root / source["path"]
                if not path.is_file() or digest(path) != source["sha256"]:
                    problems.append("Unread source missing or changed: " + key)
        authorization = gap.get("authorization", {})
        supplied = requests.get(key, [])
        valid = (len(supplied) == 1 and supplied[0].get("source_sha256") == gap["source_sha256"]
                 and supplied[0].get("complete") is True
                 and authorization.get("packet_id") == packet_id
                 and authorization.get("snapshot_digest") == handoff["snapshot_digest"]
                 and handoff.get("ingestion_gaps", {}).get(key, {}).get("source_sha256") == gap["source_sha256"])
        if not valid:
            problems.append("Unread gap " + key + " needs owner-authorized complete correction for this packet/source hash")
        else:
            resolved.append(key)
    return review, problems, resolved

def finish_reconciliation(project, owner, handoff, identifiers, report):
    if not identifiers:
        return
    with project.transaction(owner) as data:
        for identifier in identifiers:
            gap = data["ingestion_gaps"][identifier]
            authorization = gap.get("authorization", {})
            if (authorization.get("packet_id") != Path(handoff["prompt"]).parent.name
                    or authorization.get("snapshot_digest") != handoff["snapshot_digest"]):
                raise ProjectError("Correction authorization changed before import")
            gap.update(status="RESOLVED", resolved_at=now(), replacement_report=report,
                       replacement_sha256=digest(project.root / report))
