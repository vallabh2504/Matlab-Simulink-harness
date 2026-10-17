"""Small, portable project state with explicit approvals and evidence freshness.

This is workflow integrity, not a security boundary against a malicious actor
with write access to the project. Human approval and reviewer independence are
attestations backed by records, not cryptographic authentication. The record
seal is tamper evidence for edits made outside harness transactions; an agent
that can read the operator key store can still forge it.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import uuid


PHASES = ("requirements", "architecture", "implementation", "verification", "handoff")
ASSERTIONS = {"USER-APPROVED", "PROPOSED", "ASSUMED", "VERIFIED", "UNKNOWN"}
SEVERITIES = {"CRITICAL", "MAJOR", "MODERATE", "MINOR"}
KINDS = {"PROVEN DEFECT", "EVIDENCE GAP", "POTENTIAL DEFECT", "OPTIONAL IMPROVEMENT"}
DEFAULT_BUDGETS = {"builder": 3600, "reviewer": 1800, "repair": 3600, "native": 1800}
# Out-of-scope files MATLAB or a check command could execute. A new one can
# shadow a check function, because MATLAB resolves the current folder first.
EXECUTABLE_SUFFIXES = {".m", ".p", ".mlx", ".mlapp", ".slx", ".mdl", ".sldd", ".py", ".ps1", ".bat", ".cmd", ".sh"}
# Caches and version control are not engineering truth.
UNPROTECTED_DIRECTORIES = {".git", ".matlab-harness", "__pycache__", ".pytest_cache", "slprj"}
UNPROTECTED_SUFFIXES = {".asv", ".slxc", ".pyc"}
PROTECTED_COPY_LIMIT = 16 * 1024 * 1024
TEXT_DOCUMENTS = {".md", ".txt", ".rst", ".adoc", ".tex", ".html"}


class ProjectError(ValueError):
    """An invalid project action, record or checkpoint."""


class ReviewProtocolError(ProjectError):
    """A rejected review record that its independent author can correct.

    Identity, current-snapshot and artifact-integrity failures remain hard
    ProjectErrors. This distinction never supplies a verdict or closes a defect.
    """


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def value_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def non_document_artifacts(snapshot):
    """Early-stage workflow boundary; not an operating-system sandbox."""
    documents = {".md", ".rst", ".adoc", ".tex", ".pdf", ".png", ".svg", ".jpg", ".jpeg", ".webp"}
    return {name: fingerprint for name, fingerprint in snapshot["artifacts"].items()
            if fingerprint is not None and Path(name).suffix.lower() not in documents}


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ProjectError(f"Cannot read {path.name}: {exc}") from exc


def atomic_json(path: Path, data):
    """Replace only this named record; interrupted temp files cannot become truth."""
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def inside(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ProjectError("Artifact paths must be nonempty and project-relative")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ProjectError(f"Artifact escapes project: {relative}")
    return path


def artifact_name(root: Path, relative: str) -> str:
    path = inside(root, relative)
    name = path.relative_to(root).as_posix()
    key = name.casefold() if os.name == 'nt' else name
    if key in {".", "requirements.md", ".matlab-harness"} or key.startswith(".matlab-harness/"):
        raise ProjectError("Engineering scope cannot include root, requirements or control records")
    return name


def path_key(name: str) -> str:
    """Windows future artifact names can alias before resolve sees a file."""
    return name.casefold() if os.name == 'nt' else name


def executable_name(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    return suffix in EXECUTABLE_SUFFIXES or suffix.startswith(".mex")


def key_directory() -> Path:
    """Orchestrator-held seal keys live outside every project tree."""
    configured = os.environ.get("MATLAB_HARNESS_KEY_DIR")
    if configured:
        return Path(configured)
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "matlab-harness" / "keys"


def cites(text: str, identifier: str) -> bool:
    """Exact ID citation: CELL-1 is not cited by CELL-10 or CELL-1a."""
    return re.search(r"(?<![\w-])" + re.escape(identifier) + r"(?![\w-])", text) is not None


class Project:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.control = self.root / ".matlab-harness"
        if self.control.is_symlink() or not self.control.resolve().is_relative_to(self.root):
            raise ProjectError("Project record directory must not be a symlink")
        self.record = self.control / "project.json"
        inside(self.root, ".matlab-harness/project.json")

    @classmethod
    def initialize(cls, root, title: str, builder: str, scope: list[str]):
        project = cls(root)
        project.root.mkdir(parents=True, exist_ok=True)
        if project.control.exists():
            raise ProjectError("Already initialized; initialization never overwrites records")
        if not title.strip() or not builder.strip() or not scope:
            raise ProjectError("Title, builder session and owned artifact scope are required")
        scope = [artifact_name(project.root, path) for path in scope]
        project.control.mkdir()
        (project.control / "evidence").mkdir()
        (project.control / "history").mkdir()
        requirements = project.root / "requirements.md"
        if not requirements.exists():
            requirements.write_text(
                f"# {title} requirements\n\nBaseline: PROPOSED. Obtain actual user approval before consequential construction.\n\n"
                "Record stable IDs, objective, boundaries, interfaces, units/ranges, parameter provenance, "
                "equations, acceptance methods, non-goals, toolbox needs and open questions.\n"
                "Distinguish USER-APPROVED, PROPOSED, ASSUMED, VERIFIED and UNKNOWN.\n",
                encoding="utf-8")
        data = {"schema_version": 1, "id": uuid.uuid4().hex, "title": title,
                "builder_session": builder, "created": now(), "owner": None,
                "scope": sorted(set(scope)), "phase": "requirements",
                "requirements": [], "approvals": [], "decisions": [], "tasks": {},
                "required_checks": {}, "commands": {}, "evidence": {}, "reviews": {}, "acceptances": [],
                "repair_budget": 10, "repairs": 0, "budgets": DEFAULT_BUDGETS.copy(),
                "runtime": {"adapter": "manual"}}
        project._write_record(data)
        return project

    def load(self):
        data = read_json(self.record)
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ProjectError("Unsupported schema; preserve records and migrate explicitly")
        key = self._seal_key(data.get("id"))
        if key is not None:
            seal = self.control / "project.seal"
            if not seal.is_file() or not hmac.compare_digest(
                    seal.read_text(encoding="utf-8").strip(),
                    hmac.new(key, self.record.read_bytes(), "sha256").hexdigest()):
                raise ProjectError("Project record changed outside a harness transaction; preserve it and inspect the change")
        return data

    def _seal_key(self, identifier, create=False):
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}", identifier):
            return None
        path = key_directory() / (identifier + ".key")
        if path.is_file():
            return path.read_bytes()
        if not create:
            # Unsealed legacy record, or a project moved to another machine.
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        with path.open("xb") as handle:
            handle.write(key)
        return key

    def _write_record(self, data):
        atomic_json(self.record, data)
        key = self._seal_key(data.get("id"), create=True)
        if key is not None:
            seal = self.control / "project.seal"
            temp = seal.with_name(seal.name + "." + uuid.uuid4().hex + ".tmp")
            temp.write_text(hmac.new(key, self.record.read_bytes(), "sha256").hexdigest() + "\n", encoding="utf-8")
            os.replace(temp, seal)

    def record_seal(self):
        data = read_json(self.record)
        return "VERIFIED" if self._seal_key(data.get("id")) is not None else "UNVERIFIED"

    @contextmanager
    def transaction(self, owner=None):
        """Serialize individual mutations; stale locks require explicit recovery."""
        lock = inside(self.root, ".matlab-harness/mutation.lock")
        token = uuid.uuid4().hex
        try:
            with lock.open("x", encoding="utf-8") as handle:
                json.dump({"token": token, "pid": os.getpid(), "created": now()}, handle)
        except FileExistsError as exc:
            raise ProjectError("Mutation lock exists. Inspect it; explicit recover-lock needs its token") from exc
        failed = False
        try:
            data = self.load()
            if owner is not None and data["owner"] != owner:
                raise ProjectError("Only the claimed orchestrator may mutate this project")
            yield data
            self._write_record(data)
        except BaseException:
            failed = True
            raise
        finally:
            try:
                if lock.exists():
                    lock_record = read_json(lock)
                    if not isinstance(lock_record,dict):
                        raise ProjectError('Invalid lock object; preserve and inspect it')
                    if lock_record.get("token") == token:
                        lock.unlink()
            except Exception as exc:
                # Never delete an unreadable/unknown lock or mask a primary
                # failure. Successful mutation may already be committed.
                if not failed:
                    raise ProjectError('Mutation may be committed; lock cleanup failed. Inspect records and recover explicitly') from exc

    def recover_lock(self, token: str):
        lock = self.control / "mutation.lock"
        data = read_json(lock)
        if not token or data.get("token") != token:
            raise ProjectError("Recovery token mismatch; lock remains intact")
        # No assumption that age or PID alone proves a dead worker. Operator must
        # first verify the old process has stopped. Preserve the full lock record.
        atomic_json(inside(self.root, ".matlab-harness/history/recovered-lock-" + uuid.uuid4().hex + ".json"), data)
        lock.unlink()

    def claim(self, owner: str):
        if not owner.strip():
            raise ProjectError("Owner identity cannot be empty")
        with self.transaction() as data:
            if data["owner"] not in (None, owner):
                raise ProjectError(f"Project already owned by {data['owner']}")
            data["owner"] = owner

    def release(self, owner: str):
        with self.transaction(owner) as data:
            if any(t["status"] == "ACTIVE" for t in data["tasks"].values()):
                raise ProjectError("Cannot release while artifact tasks remain active")
            data["owner"] = None

    def recover_owner(self, previous: str, owner: str, reason: str):
        if not reason.strip() or not owner.strip() or previous == owner:
            raise ProjectError("Recovery requires old/new identity and a reason")
        with self.transaction(previous) as data:
            data["decisions"].append({"assertion": "ASSUMED", "text": reason,
                                      "source": f"ownership recovery {previous} -> {owner}", "at": now()})
            data["owner"] = owner
            # Leases stay visible until individually dispositioned; do not delete work.

    def requirements_digest(self, data):
        return value_digest({"document": digest(self.root / "requirements.md"),
                             "requirements": data["requirements"]})

    def add_requirement(self, owner, identifier, text, acceptance, source, units=None):
        if not all(isinstance(v, str) and v.strip() for v in (identifier, text, acceptance, source)):
            raise ProjectError("Requirement ID/text/acceptance/source must be explicit")
        with self.transaction(owner) as data:
            if data["acceptances"]:
                raise ProjectError("Use revise before changing an accepted requirements baseline")
            if any(r["id"] == identifier for r in data["requirements"]):
                raise ProjectError("Requirement ID exists; use a documented revision instead")
            data["requirements"].append({"id": identifier, "text": text, "acceptance": acceptance,
                                         "source": source, "units": units, "assertion": "PROPOSED"})

    def approve(self, owner, actor, source):
        if not actor.strip() or not source.strip():
            raise ProjectError("Actual approving user and authorization source are required")
        with self.transaction(owner) as data:
            if not data["requirements"]:
                raise ProjectError("An empty requirements baseline cannot be approved")
            if data["acceptances"] and data["approvals"][-1]["digest"] != self.requirements_digest(data):
                raise ProjectError("Changed baseline requires revise and new checkpoint review")
            for requirement in data["requirements"]:
                requirement["assertion"] = "USER-APPROVED"
            data["approvals"].append({"actor": actor, "source": source, "at": now(),
                                      "digest": self.requirements_digest(data)})

    def decision(self, owner, text, assertion, source):
        if assertion not in ASSERTIONS or not text.strip() or not source.strip():
            raise ProjectError("Decision needs a valid assertion, text and provenance")
        with self.transaction(owner) as data:
            data["decisions"].append({"text": text, "assertion": assertion, "source": source, "at": now()})

    def snapshot(self, data=None):
        data = data or self.load()
        files = {}
        for relative in data["scope"]:
            path = inside(self.root, relative)
            candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
            found = False
            for candidate in candidates:
                if candidate.is_file():
                    if not candidate.resolve().is_relative_to(self.root):
                        raise ProjectError("Scoped symlink escapes project")
                    files[candidate.relative_to(self.root).as_posix()] = digest(candidate)
                    found = True
            # Directory/file deletion and not-yet-created artifacts must invalidate evidence.
            if not found:
                files[relative] = None
        snapshot = {"requirements": self.requirements_digest(data), "artifacts": files,
                    "checks": data["required_checks"], "commands": data["commands"], "scope": data["scope"]}
        if "support_baseline" in data:
            # Check scripts and other out-of-scope files are part of the evidence.
            # New files are handled when a role ends (enforce_support), not here.
            current = self._support_files(data)
            snapshot["support"] = {name: current.get(name) for name in data["support_baseline"]}
        return snapshot

    def _support_files(self, data):
        """Every out-of-scope file outside control records, caches and version control."""
        scope = [path_key(s).rstrip("/") for s in data["scope"]]
        found = {}
        for directory, names, files in os.walk(self.root):
            names[:] = sorted(n for n in names if n not in UNPROTECTED_DIRECTORIES
                              and not Path(directory, n).is_symlink())
            for name in sorted(files):
                path = Path(directory, name)
                relative = path.relative_to(self.root).as_posix()
                key = path_key(relative)
                if (key == path_key("requirements.md") or path.suffix.lower() in UNPROTECTED_SUFFIXES
                        or any(key == s or key.startswith(s + "/") for s in scope) or path.is_symlink()):
                    continue
                found[relative] = digest(path)
        return found

    def support_state(self, data):
        """Baseline files (None when deleted) plus any new executable file."""
        current = self._support_files(data)
        baseline = data.get("support_baseline", {})
        state = {name: current.get(name) for name in baseline}
        state.update({name: value for name, value in current.items()
                      if name not in baseline and executable_name(name)})
        return state

    def protect_support(self, data):
        """Orchestrator baseline of out-of-scope files, with restorable copies."""
        baseline = self._support_files(data)
        store = self.control / "protected"
        if store.exists():
            shutil.rmtree(store)
        for name in baseline:
            source = self.root / name
            if source.stat().st_size <= PROTECTED_COPY_LIMIT:
                target = store / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        data["support_baseline"] = baseline

    def enforce_support(self, data, before, quarantine):
        """Undo a role's out-of-scope edits: restore protected files, quarantine new executables.

        before is support_state captured when the role started, so files the
        orchestrator added between roles are never moved.
        """
        if "support_baseline" not in data:
            return {}
        after = self.support_state(data)
        baseline = data["support_baseline"]
        restored, unrestorable, quarantined = [], [], []
        for name, expected in baseline.items():
            if after.get(name) == before.get(name):
                continue
            copy = self.control / "protected" / name
            if expected is not None and copy.is_file() and digest(copy) == expected:
                target = self.root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(copy, target)
                restored.append(name)
            else:
                unrestorable.append(name)
        for name in sorted(set(after) - set(baseline) - set(before)):
            target = quarantine / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(self.root / name), str(target))
            quarantined.append(name)
        if not (restored or unrestorable or quarantined):
            return {}
        return {"restored": restored, "unrestorable": unrestorable, "quarantined": quarantined,
                "quarantine": quarantine.relative_to(self.root).as_posix()}

    def configure_checks(self, owner, checkpoint, checks):
        if checkpoint not in PHASES or not isinstance(checks, dict):
            raise ProjectError("Checks must map predeclared names to executable argument lists")
        for name, argv in checks.items():
            if not isinstance(name,str) or not name.strip() or not isinstance(argv,list) or not argv or any(not isinstance(a,str) or not a for a in argv):
                raise ProjectError("Invalid check name or executable argument list")
        with self.transaction(owner) as data:
            if checkpoint in {a["checkpoint"] for a in data["acceptances"]}:
                raise ProjectError("Accepted checkpoint obligations are frozen; revise baseline explicitly")
            for name, argv in checks.items():
                if name in data["commands"] and data["commands"][name] != argv:
                    raise ProjectError("A check name cannot bind multiple different commands")
                data["commands"][name] = argv
            data["required_checks"][checkpoint] = sorted(checks)
            # Configuring checks is the orchestrator's attestation of the files they run.
            self.protect_support(data)

    def configure_runtime(self, owner, budgets=None, repair_budget=None, runtime=None):
        budgets = budgets or {}
        if not isinstance(budgets, dict) or any(k not in DEFAULT_BUDGETS or isinstance(v, bool)
                or not isinstance(v, (int, float)) or not 0 < v <= 86400 for k, v in budgets.items()):
            raise ProjectError("Budgets must specify positive seconds up to 86400 for builder/reviewer/repair/native")
        if repair_budget is not None and (isinstance(repair_budget, bool) or not isinstance(repair_budget, int)
                                          or repair_budget < 1):
            raise ProjectError("Repair budget must be a positive integer")
        if runtime is not None and (not isinstance(runtime, dict) or runtime.get("adapter") not in
                                    {"manual", "agy", "command"}):
            raise ProjectError("Runtime adapter must be manual, agy or command")
        if runtime is not None:
            roles = runtime.get("roles", {})
            if not isinstance(roles, dict) or any(k not in {"builder", "reviewer", "repair"}
                    or not isinstance(v, dict) or v.get("adapter", runtime["adapter"]) not in
                    {"manual", "agy", "command"} for k, v in roles.items()):
                raise ProjectError("Runtime roles must map builder/reviewer/repair to adapter configuration objects")
        with self.transaction(owner) as data:
            if repair_budget is not None and repair_budget < data["repairs"]:
                raise ProjectError("Repair budget cannot erase already consumed repairs")
            data["budgets"] = {**DEFAULT_BUDGETS, **data.get("budgets", {}), **budgets}
            if repair_budget is not None:
                data["repair_budget"] = repair_budget
            if runtime is not None:
                data["runtime"] = runtime
            data["decisions"].append({"assertion": "PROPOSED", "text": "Execution configuration updated",
                                      "source": "operator configuration", "at": now(),
                                      "budgets": data["budgets"].copy(), "repair_budget": data["repair_budget"]})

    def lease(self, owner, task, worker, artifacts, requirements, kind="implementation"):
        if kind not in {"discovery", "design", "implementation", "repair"}:
            raise ProjectError("Task kind must be discovery, design, implementation or repair")
        artifacts = [artifact_name(self.root, a) for a in artifacts]
        with self.transaction(owner) as data:
            ids = {r["id"] for r in data["requirements"]}
            if not task.strip() or not worker.strip() or not artifacts or not requirements or not set(requirements) <= ids:
                raise ProjectError("Task/worker/artifacts/approved requirement IDs required")
            self._approval_current(data)
            accepted = {a["checkpoint"] for a in data["acceptances"]}
            if kind in {"implementation", "repair"} and not {"requirements", "architecture"} <= accepted:
                raise ProjectError("Implementation and repair leases require accepted requirements and architecture")
            for artifact in artifacts:
                inside(self.root, artifact)
                artifact_key = path_key(artifact)
                if not any(artifact_key == path_key(s) or artifact_key.startswith(path_key(s).rstrip("/") + "/") for s in data["scope"]):
                    raise ProjectError("Lease must remain inside declared engineering scope")
                for existing in data["tasks"].values():
                    if existing["status"] != "ACTIVE":
                        continue
                    for leased in existing["artifacts"]:
                        leased_key = path_key(leased)
                        if artifact_key == leased_key or artifact_key.startswith(leased_key.rstrip("/") + "/") or leased_key.startswith(artifact_key.rstrip("/") + "/"):
                            raise ProjectError(f"Artifact ownership collision: {artifact}")
            if task in data["tasks"]:
                raise ProjectError("Task identity already used")
            data["tasks"][task] = {"worker": worker, "artifacts": artifacts,
                                    "requirements": requirements, "kind": kind, "status": "ACTIVE", "created": now()}

    def finish_task(self, owner, task, disposition):
        if disposition not in {"DONE", "FAILED", "INTERRUPTED"}:
            raise ProjectError("Invalid task disposition")
        with self.transaction(owner) as data:
            if task not in data["tasks"] or data["tasks"][task]["status"] != "ACTIVE":
                raise ProjectError("No active task with this identity")
            data["tasks"][task].update(status=disposition, finished=now())

    def run_check(self, owner, name, command=None, timeout=None):
        if timeout is None:
            timeout = self.load().get("budgets", DEFAULT_BUDGETS).get("native", DEFAULT_BUDGETS["native"])
        if not name.strip() or isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ProjectError("Named executable command and positive timeout required")
        # Hold the mutation lock throughout execution: shared MATLAB and results
        # commands cannot race another check or change acceptance records midway.
        with self.transaction(owner) as data:
            if name not in {c for checks in data["required_checks"].values() for c in checks}:
                raise ProjectError("Check was not predeclared in checkpoint obligations")
            expected = data["commands"][name]
            if command is not None and command != expected:
                raise ProjectError("Cannot substitute a different command for the predeclared engineering check")
            command = expected
            before = self.snapshot(data)
            started = now()
            identifier=uuid.uuid4().hex
            raw={stream:'.matlab-harness/evidence/'+identifier+'-'+stream+'.txt' for stream in ('stdout','stderr')}
            process=None;interrupted=None;diagnostic=''
            cleanup={'requested':False,'external_service_cancellation':'NOT_REQUESTED'}
            # File-backed streams avoid waiting forever for pipe handles inherited
            # by descendants after the direct child has stopped.
            with inside(self.root,raw['stdout']).open('wb') as out, inside(self.root,raw['stderr']).open('wb') as err:
                try:
                    process=subprocess.Popen(command,cwd=self.root,stdout=out,stderr=err,
                                             shell=False,start_new_session=os.name!='nt')
                    atomic_json(inside(self.root,'.matlab-harness/evidence/'+identifier+'-started.json'),
                                {'name':name,'command':command,'pid':process.pid,'started':started,
                                 'raw_output':raw,'status':'STARTED'})
                    process.wait(timeout=timeout)
                    code=process.returncode;status='PASSED' if code==0 else 'FAILED'
                except (subprocess.TimeoutExpired,KeyboardInterrupt) as exc:
                    # Local import avoids the runtime module's Project import cycle.
                    from .runtime import _stop_owned_process
                    cleanup=_stop_owned_process(process) if process is not None else {
                        'requested':False,'root_stopped':False,'external_service_cancellation':'UNKNOWN',
                        'reason':'Launch interrupted before a process identity was captured'}
                    code,status=None,'BLOCKED'
                    if isinstance(exc,KeyboardInterrupt):interrupted=exc
                    diagnostic=('Command interrupted' if interrupted is not None else f'Command exceeded {timeout}s')
                    diagnostic+='; owned process-tree cleanup attempted. Inspect unverified descendants/session/backend state.'
                except OSError as exc:
                    code,status=None,'BLOCKED';diagnostic=str(exc)
                    if process is not None and process.poll() is None:
                        from .runtime import _stop_owned_process
                        cleanup=_stop_owned_process(process)
                except BaseException:
                    if process is not None and process.poll() is None:
                        from .runtime import _stop_owned_process
                        _stop_owned_process(process)
                    raise
            stdout=inside(self.root,raw['stdout']).read_text(encoding='utf-8',errors='replace')
            stderr=inside(self.root,raw['stderr']).read_text(encoding='utf-8',errors='replace')
            if diagnostic:stderr+=('\n' if stderr else '')+diagnostic
            after = self.snapshot(data)
            if before != after:
                status = "FAILED"
                stderr += "\nDeclared artifacts changed during verification; re-run against stable outputs."
            evidence = {"name": name, "status": status, "command": command,
                        "started": started, "finished": now(), "exit_code": code,
                        "stdout": stdout, "stderr": stderr, "snapshot": after,
                        "pid":process.pid if process is not None else None,"cleanup":cleanup,
                        "raw_output":{stream:{'path':relative,'sha256':digest(inside(self.root,relative))}
                                      for stream,relative in raw.items()}}
            relative = ".matlab-harness/evidence/" + identifier + ".json"
            atomic_json(inside(self.root, relative), evidence)
            data["evidence"][name] = {"path": relative, "sha256": digest(inside(self.root, relative))}
        if interrupted is not None:
            raise interrupted
        return evidence

    def review(self, owner, checkpoint, report_path, identity_source="self-attested"):
        if identity_source not in {"self-attested", "runtime-receipt"}:
            raise ProjectError("Review identity source must be self-attested or runtime-receipt")
        if checkpoint not in PHASES:
            raise ProjectError("Unknown checkpoint")
        report_file = inside(self.root, report_path)
        report = read_json(report_file)
        required = {"reviewer_session", "model", "independence", "checkpoint", "verdict", "findings", "snapshot_digest"}
        if not isinstance(report, dict) or not required <= report.keys() or report["checkpoint"] != checkpoint:
            raise ReviewProtocolError("Incomplete review record or wrong checkpoint")
        if any(not isinstance(report[k], str) or not report[k].strip() for k in required - {"findings"}):
            raise ProjectError("Review metadata must be nonempty strings")
        if report["verdict"] not in {"ACCEPT", "REJECT", "INCOMPLETE"}:
            raise ReviewProtocolError("Invalid review verdict")
        if any(not isinstance(report[k], str) or not report[k].strip() for k in ("model", "reviewer_session")) or report["independence"] not in {"independent-agent", "external-human", "sequential-role-pass"}:
            raise ProjectError("Reviewer identity and honest independence level required")
        findings = report["findings"]
        if not isinstance(findings, list):
            raise ReviewProtocolError("Findings must be a list")
        identifiers = set()
        for finding in findings:
            fields = {"id", "severity", "kind", "artifact", "evidence", "impact", "repair", "closure", "status"}
            if not isinstance(finding, dict) or not fields <= finding.keys():
                raise ReviewProtocolError("Finding lacks actionable evidence/repair/closure")
            if any(not isinstance(finding[k], str) or not finding[k].strip() for k in fields):
                raise ReviewProtocolError("Finding values must be nonempty strings")
            if not isinstance(finding["id"], str) or not finding["id"].strip() or finding["id"] in identifiers or finding["severity"] not in SEVERITIES or finding["kind"] not in KINDS:
                raise ReviewProtocolError("Duplicate finding ID or invalid severity/kind")
            identifiers.add(finding["id"])
            if finding["status"] not in {"OPEN", "CLOSED", "DISPUTED", "ACCEPTED-RISK"}:
                raise ReviewProtocolError("Invalid finding status")
            if any(not isinstance(finding[k], str) or not finding[k].strip() for k in fields - {"id"}):
                raise ReviewProtocolError("Finding values must be nonempty strings")
        with self.transaction(owner) as data:
            contributors = {data["builder_session"], *data.get("contributors", []),
                            *(t["worker"] for t in data["tasks"].values())}
            if report["reviewer_session"] in contributors:
                raise ProjectError("Reviewer session must differ from every contributing builder/worker session")
            if report["snapshot_digest"] != value_digest(self.snapshot(data)):
                raise ProjectError("Reviewer did not inspect current artifact snapshot")
            defects = self._seed_defects(data)
            current_findings = {f["id"]: f for f in findings}
            for finding in findings:
                previous_item = defects.get(checkpoint + ":" + finding["id"])
                if previous_item:
                    if finding["artifact"] != previous_item["origin"]["artifact"]:
                        raise ReviewProtocolError("Finding ID must retain its exact original artifact string; put additional repair locations in evidence/closure: " + finding["id"])
                    if previous_item["blocking"] and finding["status"] == "CLOSED" and finding.get("prior_finding_digest") != previous_item["origin_digest"]:
                        raise ReviewProtocolError("Blocking closure must explicitly reference prior finding digest: " + finding["id"])
            for item in defects.values():
                previous = item["finding"]
                if item["checkpoint"] != checkpoint or not item["blocking"]:
                    continue
                replacement = current_findings.get(previous["id"])
                if report["verdict"] == "ACCEPT" and (not replacement or replacement["status"] != "CLOSED"):
                    raise ReviewProtocolError("Review must explicitly close earlier blocking finding: " + previous["id"])
            pending = self.pending_review_findings(data)
            dispositions = report.get("protocol_dispositions", [])
            if not isinstance(dispositions, list):
                raise ReviewProtocolError("Protocol dispositions must be a list")
            resolved = {}
            for disposition in dispositions:
                fields = {"finding_digest", "status", "finding_id", "evidence", "closure"}
                if (not isinstance(disposition, dict) or not fields <= disposition.keys()
                        or any(not isinstance(disposition[k], str) for k in fields)
                        or not disposition["evidence"].strip() or not disposition["closure"].strip()):
                    raise ReviewProtocolError("Protocol allegation disposition needs identity, status, evidence and closure")
                key = disposition["finding_digest"]
                if key in resolved or key not in pending or pending[key]["checkpoint"] != checkpoint:
                    raise ReviewProtocolError("Unknown, duplicate or wrong-checkpoint protocol allegation disposition")
                if disposition["status"] == "TRACKED":
                    finding = current_findings.get(disposition["finding_id"])
                    if not finding or finding["severity"] not in {"CRITICAL", "MAJOR"} or finding["status"] == "CLOSED":
                        raise ReviewProtocolError("TRACKED allegation must reference an unresolved serious finding in this report")
                elif disposition["status"] != "CLOSED":
                    raise ReviewProtocolError("Protocol allegation disposition status must be CLOSED or TRACKED")
                resolved[key] = disposition
            if report["verdict"] == "ACCEPT" and any(
                    item["checkpoint"] == checkpoint and key not in resolved for key, item in pending.items()):
                raise ReviewProtocolError("ACCEPT must explicitly disposition serious allegations from rejected review reports")
            archived = ".matlab-harness/history/review-" + uuid.uuid4().hex + ".json"
            atomic_json(inside(self.root, archived), report)
            data["reviews"][checkpoint] = {"path": archived, "sha256": digest(inside(self.root, archived)),
                                           "source": report_path, "identity_source": identity_source,
                                           "snapshot": self.snapshot(data), "recorded": now()}
            for run in data.get("runs", []):
                if (run["role"] == "reviewer" and run["checkpoint"] == checkpoint
                        and "review_import" in run):
                    expected = Path(run["packet"]["prompt"]).parent / "execution/review.json"
                    if expected == report_file and "review_import" in run:
                        run["review_import"] = {"status": "IMPORTED", "report": report_path,
                            "sha256": digest(report_file), "archive": archived,
                            "archive_sha256": digest(inside(self.root, archived))}
            for finding in findings:
                key = checkpoint + ":" + finding["id"]
                item = defects.setdefault(key, {"checkpoint": checkpoint, "history": [], "blocking": False,
                                                "origin": finding, "origin_digest": value_digest(finding)})
                item["history"].append({"finding": finding, "review": archived,
                                         "review_sha256": digest(inside(self.root, archived)), "recorded": now()})
                item["blocking"] = (item["blocking"] or finding["severity"] in {"CRITICAL", "MAJOR"}) and finding["status"] != "CLOSED"
                item["finding"] = finding
            for key, disposition in resolved.items():
                data["pending_review_findings"][key].update(status="RESOLVED", disposition=disposition,
                    resolution_review=archived, resolution_sha256=digest(inside(self.root, archived)))

    def record_review_protocol_failure(self, owner, checkpoint, report_path, reason):
        """Retain rejected reports and serious allegations without declaring them true."""
        report_file = inside(self.root, report_path)
        report = read_json(report_file)
        fingerprint = digest(report_file)
        with self.transaction(owner) as data:
            current = value_digest(self.snapshot(data))
            contributors = {data["builder_session"], *data.get("contributors", []),
                            *(t["worker"] for t in data["tasks"].values())}
            if (checkpoint != data["phase"] or report.get("snapshot_digest") != current
                    or not report.get("reviewer_session") or report["reviewer_session"] in contributors):
                raise ProjectError("Rejected report does not have independent current-snapshot provenance")
            failures = data.setdefault("review_protocol_failures", {})
            if report_path in failures:
                if failures[report_path]["sha256"] != fingerprint:
                    raise ProjectError("Rejected review report changed")
                return
            failures[report_path] = {"checkpoint": checkpoint, "snapshot_digest": current,
                "path": report_path, "sha256": fingerprint, "reason": reason, "recorded": now()}
            for run in data.get("runs", []):
                if (run["role"] == "reviewer" and run["checkpoint"] == checkpoint
                        and "review_import" in run):
                    expected = Path(run["packet"]["prompt"]).parent / "execution/review.json"
                    if expected == report_file and "review_import" in run:
                        run["review_import"] = {"status": "REJECTED_PROTOCOL", "report": report_path,
                            "sha256": fingerprint}
            pending = data.setdefault("pending_review_findings", {})
            fields = {"id", "severity", "kind", "artifact", "evidence", "impact", "repair", "closure", "status"}
            findings = report.get("findings", [])
            for index, finding in enumerate(findings if isinstance(findings, list) else []):
                if (not isinstance(finding, dict) or not fields <= finding.keys()
                        or any(not isinstance(finding[k], str) or not finding[k].strip() for k in fields)
                        or finding["severity"] not in {"CRITICAL", "MAJOR"}
                        or finding["kind"] not in KINDS
                        or finding["status"] not in {"OPEN", "DISPUTED", "ACCEPTED-RISK"}):
                    continue
                key = value_digest({"report_sha256": fingerprint, "index": index, "finding": finding})
                pending[key] = {"checkpoint": checkpoint, "snapshot_digest": current,
                    "source_report": report_path, "source_sha256": fingerprint,
                    "finding": finding, "status": "OPEN", "classification": "UNIMPORTED_ALLEGATION"}

    def pending_review_findings(self, data=None):
        data = data if data is not None else self.load()
        pending = {}
        for key, item in data.get("pending_review_findings", {}).items():
            if digest(inside(self.root, item["source_report"])) != item["source_sha256"]:
                raise ProjectError("Rejected review allegation source changed")
            if item["status"] == "RESOLVED":
                if digest(inside(self.root, item["resolution_review"])) != item["resolution_sha256"]:
                    raise ProjectError("Protocol allegation resolution review changed")
                continue
            pending[key] = item
        return pending

    def unrestored_stage_boundaries(self, data=None):
        data = data if data is not None else self.load()
        actual = non_document_artifacts(self.snapshot(data))
        unresolved = {}
        for relative, item in data.get("stage_boundaries", {}).items():
            source = inside(self.root, relative)
            if digest(source) != item["sha256"]:
                raise ProjectError("Stage-boundary evidence changed")
            if item["status"] == "RESTORED":
                continue
            baseline = read_json(source)["baseline"]
            changed = {name: {"expected": baseline.get(name), "actual": actual.get(name)}
                       for name in sorted(set(baseline) | set(actual)) if baseline.get(name) != actual.get(name)}
            if changed:
                unresolved[relative] = changed
        return unresolved

    def unfinished_review_imports(self, data=None):
        data = data if data is not None else self.load()
        return [run["packet"]["prompt"] for run in data.get("runs", [])
                if run.get("review_import", {}).get("status") == "PENDING_REVIEW_IMPORT"]

    def _seed_defects(self, data):
        """Retain blocking findings when continuing records from before this feature."""
        if "defects" in data:
            for item in data["defects"].values():
                origin = item["history"][0]["finding"] if item["history"] else item["finding"]
                item.setdefault("origin", origin)
                item.setdefault("origin_digest", value_digest(item["origin"]))
            return data["defects"]
        defects = {}
        for checkpoint, entry in data["reviews"].items():
            path = inside(self.root, entry["path"])
            if not path.is_file() or digest(path) != entry["sha256"]:
                raise ProjectError("Cannot migrate missing/tampered archived review: " + checkpoint)
            report = read_json(path)
            for finding in report["findings"]:
                defects[checkpoint + ":" + finding["id"]] = {
                    "checkpoint": checkpoint, "finding": finding,
                    "origin": finding, "origin_digest": value_digest(finding),
                    "blocking": finding["severity"] in {"CRITICAL", "MAJOR"} and finding["status"] != "CLOSED",
                    "history": [{"finding": finding, "review": entry["path"],
                                 "review_sha256": entry["sha256"], "recorded": entry["recorded"]}]}
        data["defects"] = defects
        if data["reviews"]:
            data["decisions"].append({"assertion": "VERIFIED", "text": "Durable defect history restored from archived current reviews",
                                      "source": "compatible record migration", "at": now()})
        return defects

    def _approval_current(self, data):
        if not data["approvals"] or data["approvals"][-1]["digest"] != self.requirements_digest(data):
            raise ProjectError("Current requirements have no recorded user approval")

    def gate(self, checkpoint):
        data = self.load()
        self._seed_defects(data)  # Read-only compatibility projection, never a record write.
        if checkpoint not in PHASES:
            raise ProjectError("Unknown checkpoint")
        problems = []
        accepted = {a["checkpoint"] for a in data["acceptances"]}
        missing = [p for p in PHASES[:PHASES.index(checkpoint)] if p not in accepted]
        if missing:
            problems.append("Earlier checkpoints have not been accepted: " + ", ".join(missing))
        try:
            self._approval_current(data)
        except ProjectError as exc:
            problems.append(str(exc))
        current = self.snapshot(data)
        if checkpoint in {"implementation", "verification", "handoff"}:
            if any(value is None for value in current["artifacts"].values()):
                problems.append("A declared engineering artifact is absent, or a scoped directory has no files")
        if checkpoint not in data["required_checks"]:
            problems.append("Checkpoint obligations were not predeclared")
        checks = data["required_checks"].get(checkpoint, [])
        if checkpoint in {"implementation", "verification", "handoff"} and not checks:
            problems.append("Executed engineering checks are mandatory for this checkpoint")
        for name in checks:
            entry = data["evidence"].get(name)
            if not entry:
                problems.append(f"Missing check: {name}")
                continue
            path = inside(self.root, entry["path"])
            if not path.exists() or digest(path) != entry["sha256"]:
                problems.append(f"Missing or tampered check record: {name}")
                continue
            evidence = read_json(path)
            if evidence["status"] != "PASSED" or evidence["exit_code"] != 0:
                problems.append(f"Check not passed: {name}")
            if evidence["command"] != data["commands"].get(name):
                problems.append(f"Check command does not match the approved plan: {name}")
            if evidence["snapshot"] != current:
                problems.append(f"Stale check: {name}")
        review = data["reviews"].get(checkpoint)
        if not review:
            problems.append("Independent reviewer checkpoint missing")
        else:
            path = inside(self.root, review["path"])
            if not path.exists() or digest(path) != review["sha256"]:
                problems.append("Review record missing or tampered")
            else:
                report = read_json(path)
                if review["snapshot"] != current:
                    problems.append("Review is stale")
                if report["verdict"] != "ACCEPT":
                    problems.append("Reviewer has not accepted checkpoint")
                if report["independence"] == "sequential-role-pass":
                    problems.append("Sequential self-review does not satisfy independent acceptance")
                for finding in report["findings"]:
                    if finding["severity"] in {"CRITICAL", "MAJOR"} and finding["status"] != "CLOSED":
                        problems.append(f"Unresolved blocking finding: {finding['id']}")
                runtime = data.get("runtime", {"adapter": "manual"})
                reviewer_adapter = runtime.get("roles", {}).get("reviewer", {}).get("adapter", runtime.get("adapter", "manual"))
                if reviewer_adapter != "manual" and review.get("identity_source", "self-attested") != "runtime-receipt":
                    problems.append("Review identity is self-attested although a " + reviewer_adapter
                                    + " reviewer runtime is configured; obtain the review through the runtime receipt")
        for name in self.support_changes(data):
            problems.append("Protected out-of-scope file changed since the orchestrator check baseline: " + name)
        if checkpoint == "handoff":
            problems += ["Handoff obligation: " + item for item in self.handoff_obligations(data)]
        if checkpoint == "handoff" and any(t["status"] == "ACTIVE" for t in data["tasks"].values()):
            problems.append("Active artifact ownership remains at handoff")
        deferred = []
        unfinished_imports = self.unfinished_review_imports(data)
        if unfinished_imports:
            problems.append("Interrupted review import requires inspection")
        boundaries = self.unrestored_stage_boundaries(data)
        if boundaries:
            problems.append("Unrestored engineering changes from document/design execution")
        for key, item in self.pending_review_findings(data).items():
            if PHASES.index(item["checkpoint"]) <= PHASES.index(checkpoint):
                problems.append("Unresolved serious allegation from rejected review: " + key)
            else:
                deferred.append("protocol:" + key)
        for key, item in data.get("defects", {}).items():
            if not item["blocking"]:
                continue
            # A revision may need a new requirements/design pass before a late
            # implementation or handoff defect can be repaired. Retain its
            # immutable origin and block that stage and every later stage.
            # Deferring an obligation never closes it or permits final handoff.
            origin_stage = item.get("checkpoint")
            if origin_stage not in PHASES or PHASES.index(origin_stage) <= PHASES.index(checkpoint):
                problems.append("Unresolved durable blocking finding: " + key)
            else:
                deferred.append(key)
        return {"checkpoint": checkpoint, "accepted": not problems, "problems": problems,
                "deferred_blocking_findings": deferred,
                "stage_boundary_violations": boundaries,
                "unfinished_review_imports": unfinished_imports,
                "snapshot_digest": value_digest(current)}

    def support_changes(self, data):
        if "support_baseline" not in data:
            return []
        current = self._support_files(data)
        return sorted(name for name, expected in data["support_baseline"].items() if current.get(name) != expected)

    def handoff_obligations(self, data):
        """Content the handoff must carry, checked from the scoped documents themselves."""
        text = ""
        for name, fingerprint in self.snapshot(data)["artifacts"].items():
            if fingerprint is not None and Path(name).suffix.lower() in TEXT_DOCUMENTS:
                text += (self.root / name).read_text(encoding="utf-8", errors="replace") + "\n"
        missing = [r["id"] for r in data["requirements"] if not cites(text, r["id"])]
        problems = []
        if missing:
            problems.append("no scoped document cites requirement IDs " + ", ".join(missing)
                            + " (handoff needs one traceability row per ID)")
        for key, item in sorted(data.get("defects", {}).items()):
            # The handoff review record itself carries its own non-blocking findings.
            if item["checkpoint"] == "handoff":
                continue
            if item["finding"]["status"] == "OPEN" and not cites(text, item["finding"]["id"]):
                problems.append("open reviewer finding " + key + " is not dispositioned by ID in a scoped document")
        return problems

    def accept(self, owner, checkpoint):
        with self.transaction(owner) as data:
            if checkpoint in {a["checkpoint"] for a in data["acceptances"]}:
                raise ProjectError("Checkpoint already accepted; revise explicitly to reopen it")
            if checkpoint != data["phase"]:
                raise ProjectError("Checkpoints must be accepted in lifecycle order")
            result = self.gate(checkpoint)
            if not result["accepted"]:
                raise ProjectError("; ".join(result["problems"]))
            for item in data.get("stage_boundaries", {}).values():
                if item["status"] != "RESTORED":
                    item.update(status="RESTORED", restoration_snapshot=result["snapshot_digest"], restored_at=now())
            data["acceptances"].append({"checkpoint": checkpoint, "snapshot_digest": result["snapshot_digest"], "at": now()})
            index = PHASES.index(checkpoint)
            data["phase"] = PHASES[min(index + 1, len(PHASES) - 1)]
        return result

    def repair(self, owner, reason):
        if not reason.strip():
            raise ProjectError("Repair reason required")
        with self.transaction(owner) as data:
            if data["repairs"] >= data["repair_budget"]:
                raise ProjectError("Repair budget exhausted; retain INCOMPLETE status and escalate")
            data["repairs"] += 1
            data["decisions"].append({"assertion": "PROPOSED", "text": reason, "source": "repair", "at": now()})

    def revise(self, owner, reason):
        if not reason.strip():
            raise ProjectError("Baseline revision reason required")
        with self.transaction(owner) as data:
            if any(t["status"] == "ACTIVE" for t in data["tasks"].values()):
                raise ProjectError("Finish or interrupt active tasks before revising their requirements baseline")
            baseline_path = inside(self.root, ".matlab-harness/history/baseline-" + uuid.uuid4().hex + ".json")
            snapshot = self.snapshot(data)
            accepted_handoff = any(a["checkpoint"] == "handoff"
                and a["snapshot_digest"] == value_digest(snapshot) for a in data["acceptances"])
            declaration_path = self.control / "journey/declaration.json"
            implementation_baseline = None
            if accepted_handoff and declaration_path.is_file() and self.gate("handoff")["accepted"]:
                implementation_baseline = {"archive": baseline_path.relative_to(self.root).as_posix(), "revision_owner": owner,
                    "snapshot": snapshot, "declaration_sha256": digest(declaration_path)}
            atomic_json(baseline_path, data)
            if implementation_baseline is not None:
                implementation_baseline["archive_sha256"] = digest(baseline_path)
            self._seed_defects(data)
            data.update(phase="requirements", approvals=[], evidence={}, reviews={}, acceptances=[], repairs=0)
            decision = {"assertion": "PROPOSED", "text": reason, "source": "baseline revision", "at": now()}
            if implementation_baseline is not None:
                decision["implementation_baseline"] = implementation_baseline
            data["decisions"].append(decision)

    def resume(self):
        data = self.load()
        self._seed_defects(data)
        return {"project": data["title"], "phase": data["phase"], "owner": data["owner"],
                "requirements": data["requirements"], "approvals": data["approvals"],
                "decisions": data["decisions"], "tasks": data["tasks"], "repairs": data["repairs"],
                "repair_budget": data["repair_budget"], "budgets": {**DEFAULT_BUDGETS, **data.get("budgets", {})},
                "runtime": data.get("runtime", {"adapter": "manual"}),
                "reviews": data["reviews"], "evidence": data["evidence"],
                "runs": data.get("runs", []), "acceptances": data["acceptances"],
                "defects": data.get("defects", {}),
                "snapshot": self.snapshot(data), "current_gate": self.gate(data["phase"]),
                "next": "Read requirements.md and current artifacts; re-run stale checks; resolve reviewer findings before advancement."}
