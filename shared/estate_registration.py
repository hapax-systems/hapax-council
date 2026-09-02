"""Stage 1 estate-store detection and canary machinery.

The sweep is intentionally report-only. It may write reports, flag receipts,
and detector state below its declared runtime store; it never mutates a scanned
candidate. Cross-host commands cause the peer to run this same source artifact.
"""

from __future__ import annotations

import glob
import json
import os
import secrets
import shlex
import stat
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.estate_store_registry import (
    Registry,
    bindings,
    matching_store,
    store_by_id,
    store_contains_path,
)

CANARY_MAX_AGE_SECONDS = 90 * 60
REMOTE_SOURCE_ROOT = "$HOME/.cache/hapax/source-activation/worktree"


class RegistrationError(RuntimeError):
    """A safety precondition or required source is unavailable."""


@dataclass(frozen=True)
class Candidate:
    path: str
    kind: str
    scan_root: str


@dataclass(frozen=True)
class ScanError:
    scan_root: str
    path: str
    error: str


@dataclass(frozen=True)
class SweepResult:
    report_path: str
    findings: tuple[dict[str, Any], ...]
    scan_errors: tuple[ScanError, ...]
    flagged_canary_ids: tuple[str, ...]
    missed_canary_ids: tuple[str, ...]
    detector_incident_path: str | None


Runner = Callable[..., subprocess.CompletedProcess[str]]


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _runtime_root(home: Path) -> Path:
    return home / ".cache" / "hapax" / "estate-registration"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Create one immutable runtime record without rename, move, or deletion."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        parent = path.parent.lstat()
    except OSError as exc:
        raise RegistrationError(f"cannot inspect output parent {path.parent}: {exc}") from exc
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid():
        raise RegistrationError(
            f"refusing unsafe output parent {path.parent}; remedy: create a caller-owned directory"
        )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise RegistrationError(
            f"cannot create immutable runtime record {path}: {exc}; "
            "remedy: preserve the existing record and use a new identity"
        ) from exc


def _expand(value: str, home: Path) -> str:
    try:
        return value.format_map(bindings(home))
    except KeyError as exc:
        raise RegistrationError(f"unknown registry path binding {exc.args[0]!r}") from exc


def _walk_bounded(
    root: Path, depth: int, scan_root: str
) -> tuple[list[Candidate], list[ScanError]]:
    candidates: list[Candidate] = []
    errors: list[ScanError] = []
    frontier = [(root, 0)]
    while frontier:
        parent, level = frontier.pop()
        if level >= depth:
            continue
        try:
            entries = sorted(os.scandir(parent), key=lambda item: os.fsencode(item.name))
        except OSError as exc:
            errors.append(ScanError(scan_root, str(parent), f"{type(exc).__name__}: {exc}"))
            continue
        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
                is_link = entry.is_symlink()
            except OSError as exc:
                errors.append(ScanError(scan_root, entry.path, f"{type(exc).__name__}: {exc}"))
                continue
            kind = (
                "directory" if is_dir else "file" if is_file else "symlink" if is_link else "other"
            )
            candidates.append(Candidate(entry.path, kind, scan_root))
            if is_dir:
                frontier.append((Path(entry.path), level + 1))
    return candidates, errors


def _unescape_mount_path(value: str) -> str:
    for encoded, decoded in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        value = value.replace(encoded, decoded)
    return value


def _mount_candidates(
    mountinfo: Path, prefixes: Sequence[str], scan_root: str
) -> tuple[list[Candidate], list[ScanError]]:
    try:
        lines = mountinfo.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [ScanError(scan_root, str(mountinfo), f"{type(exc).__name__}: {exc}")]
    candidates: list[Candidate] = []
    for line in lines:
        left, separator, _right = line.partition(" - ")
        fields = left.split()
        if not separator or len(fields) < 5:
            continue
        mount_path = _unescape_mount_path(fields[4])
        if any(
            mount_path == prefix or mount_path.startswith(prefix.rstrip("/") + "/")
            for prefix in prefixes
        ):
            candidates.append(Candidate(mount_path, "mount", scan_root))
    return candidates, []


def scan_candidates(
    registry: Registry,
    *,
    home: Path,
    mountinfo: Path = Path("/proc/self/mountinfo"),
) -> tuple[tuple[Candidate, ...], tuple[ScanError, ...]]:
    candidates: list[Candidate] = []
    errors: list[ScanError] = []
    for row in registry.scan_roots:
        root_id = str(row.get("id") or "")
        kind = str(row.get("kind") or "")
        if not root_id:
            raise RegistrationError("scan root has no id")
        if kind == "mountinfo":
            raw_prefixes = row.get("include_prefixes")
            if not isinstance(raw_prefixes, list) or not raw_prefixes:
                raise RegistrationError(f"scan root {root_id!r} has no include_prefixes")
            found, failed = _mount_candidates(
                mountinfo, [_expand(str(value), home) for value in raw_prefixes], root_id
            )
            candidates.extend(found)
            errors.extend(failed)
            continue
        raw_path = str(row.get("path") or "")
        depth = row.get("depth")
        if not isinstance(depth, int) or depth < 1 or depth > 4:
            raise RegistrationError(f"scan root {root_id!r} depth must be an integer from 1 to 4")
        expanded = _expand(raw_path, home)
        roots = (
            [Path(expanded)]
            if kind == "directory"
            else [Path(item) for item in glob.glob(expanded)]
        )
        if kind not in {"directory", "directory-glob"}:
            raise RegistrationError(f"scan root {root_id!r} has unsupported kind {kind!r}")
        if not roots:
            errors.append(ScanError(root_id, expanded, "glob matched no scan roots"))
            continue
        for root in roots:
            found, failed = _walk_bounded(root, depth, root_id)
            candidates.extend(found)
            errors.extend(failed)
    unique = {candidate.path: candidate for candidate in candidates}
    return tuple(sorted(unique.values(), key=lambda item: os.fsencode(item.path))), tuple(errors)


def originate_canaries(
    registry: Registry,
    *,
    host_id: str,
    home: Path,
    now: datetime | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    """Write registered Canary A and deliberately unregistered store-shaped Canary B."""
    runtime_store = store_by_id(registry, "estate-registration-runtime")
    if runtime_store is None or runtime_store.action != "flag-only":
        raise RegistrationError(
            "estate-registration-runtime is not safely registered; remedy: restore its registry row"
        )
    instant = (now or datetime.now(UTC)).astimezone(UTC)
    nonce = token or secrets.token_hex(4)
    canary_id = f"{host_id}-{instant:%Y%m%dT%H%M%SZ}-{nonce}"
    root = _runtime_root(home)
    a_path = root / "registered-canary" / f"{canary_id}.json"
    registration_path = root / "registrations" / f"{canary_id}.json"
    b_location = "home-dot-root" if instant.hour == 0 else "vault-hapax-area"
    b_root = (
        home / f".hapax-canary-{canary_id}"
        if b_location == "home-dot-root"
        else home / "Documents" / "Personal" / "30-areas" / "hapax" / f"canary-{canary_id}"
    )
    b_path = b_root / "store.json"
    common = {
        "schema": "hapax.estate-canary/v1",
        "canary_id": canary_id,
        "host": host_id,
        "created_at": utc_text(instant),
    }
    _write_json(a_path, {**common, "canary": "A", "registered": True})
    _write_json(
        registration_path,
        {
            **common,
            "canary": "A",
            "registered": True,
            "artifact_path": str(a_path),
            "store_id": "estate-registration-runtime",
        },
    )
    _write_json(b_path, {**common, "canary": "B", "registered": False, "location": b_location})
    b_manifest = root / "canaries" / "b" / f"{canary_id}.json"
    _write_json(
        b_manifest,
        {
            **common,
            "canary": "B",
            "registered": False,
            "artifact_path": str(b_root),
            "location": b_location,
        },
    )
    return {
        **common,
        "canary_a_path": str(a_path),
        "canary_a_registration": str(registration_path),
        "canary_b_path": str(b_root),
        "canary_b_manifest": str(b_manifest),
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RegistrationError(f"cannot read required runtime record {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RegistrationError(f"required runtime record {path} is not an object")
    return value


def export_canary_health(
    *,
    registry: Registry,
    host_id: str,
    home: Path,
    now: datetime | None = None,
    max_age_seconds: int = CANARY_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    instant = (now or datetime.now(UTC)).astimezone(UTC)
    registrations = sorted((_runtime_root(home) / "registrations").glob("*.json"))
    if not registrations:
        raise RegistrationError(
            "no Canary A registration exists; remedy: run the hourly canary originator"
        )
    registration = _load_json(registrations[-1])
    if registration.get("host") != host_id or registration.get("canary") != "A":
        raise RegistrationError("latest Canary A registration has the wrong host or type")
    try:
        created = datetime.fromisoformat(str(registration["created_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise RegistrationError("latest Canary A registration has no parseable created_at") from exc
    age = (instant - created.astimezone(UTC)).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise RegistrationError(
            f"latest Canary A registration age is {age:.0f}s; remedy: restore the hourly originator"
        )
    artifact = Path(str(registration.get("artifact_path") or ""))
    store_id = str(registration.get("store_id") or "")
    store = store_by_id(registry, store_id)
    if store is None or not store_contains_path(store, artifact, home=home):
        raise RegistrationError(
            "latest Canary A registration is not bound to its declared store; "
            "remedy: repair the registration writer or registry"
        )
    b_manifest = _runtime_root(home) / "canaries" / "b" / f"{registration['canary_id']}.json"
    if not artifact.is_file() or not b_manifest.is_file():
        raise RegistrationError(
            "latest canary pair is incomplete; remedy: repair origination before trusting peer health"
        )
    return {
        "schema": "hapax.estate-canary-health/v1",
        "host": host_id,
        "checked_at": utc_text(instant),
        "canary_id": registration["canary_id"],
        "canary_a_registered": True,
        "canary_b_manifest_present": True,
        "age_seconds": age,
    }


def _manifest_rows(home: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((_runtime_root(home) / "canaries" / "b").glob("*.json")):
        row = _load_json(path)
        row["_manifest_path"] = str(path)
        rows.append(row)
    return sorted(rows, key=lambda row: (str(row.get("created_at")), str(row.get("canary_id"))))


def _detector_state(home: Path) -> dict[str, Any]:
    snapshots = sorted((_runtime_root(home) / "detector-state").glob("*.json"))
    if not snapshots:
        return {
            "schema": "hapax.estate-detector-state/v1",
            "evaluated_ids": [],
            "miss_streak": 0,
            "incident_filed": False,
        }
    path = snapshots[-1]
    state = _load_json(path)
    if not isinstance(state.get("evaluated_ids"), list) or not isinstance(
        state.get("miss_streak"), int
    ):
        raise RegistrationError(
            f"invalid detector state {path}; remedy: preserve it and repair its schema"
        )
    return state


def sweep(
    registry: Registry,
    *,
    host_id: str,
    home: Path,
    now: datetime | None = None,
    report_root: Path | None = None,
    mountinfo: Path = Path("/proc/self/mountinfo"),
) -> SweepResult:
    """Diff reality against declarations and file findings without touching candidates."""
    instant = (now or datetime.now(UTC)).astimezone(UTC)
    candidates, scan_errors = scan_candidates(registry, home=home, mountinfo=mountinfo)
    findings: list[dict[str, Any]] = []
    for candidate in candidates:
        if matching_store(registry, Path(candidate.path), host=host_id, home=home) is None:
            findings.append(
                {
                    "kind": "unregistered-store",
                    "path": candidate.path,
                    "candidate_kind": candidate.kind,
                    "scan_root": candidate.scan_root,
                    "action": "flag-only",
                }
            )
    for error in scan_errors:
        findings.append({"kind": "scan-error", **asdict(error), "action": "flag-only"})

    reports = report_root or Path(_expand(registry.policy["reports_path"], home))
    stamp = f"{instant:%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
    report_path = reports / f"estate-drift-{host_id}-{stamp}.json"
    finding_paths = {str(row["path"]) for row in findings if row["kind"] == "unregistered-store"}
    state = _detector_state(home)
    evaluated = {str(value) for value in state["evaluated_ids"]}
    streak = int(state["miss_streak"])
    flagged: list[str] = []
    missed: list[str] = []
    incident_path: Path | None = None
    for manifest in _manifest_rows(home):
        canary_id = str(manifest.get("canary_id") or "")
        if not canary_id or canary_id in evaluated:
            continue
        b_path = str(manifest.get("artifact_path") or "")
        if b_path in finding_paths:
            streak = 0
            state["incident_filed"] = False
            flagged.append(canary_id)
            _write_json(
                _runtime_root(home) / "flags" / f"{canary_id}.json",
                {
                    "schema": "hapax.estate-canary-flag/v1",
                    "canary_id": canary_id,
                    "host": host_id,
                    "flagged_at": utc_text(instant),
                    "path": b_path,
                    "action": "flag-only",
                },
            )
        else:
            streak += 1
            missed.append(canary_id)
        evaluated.add(canary_id)
        if streak >= 2 and not state.get("incident_filed"):
            incident_path = reports / f"incident-estate-detector-dead-{host_id}-{stamp}.json"
            _write_json(
                incident_path,
                {
                    "schema": "hapax.estate-detector-incident/v1",
                    "kind": "detector-dead",
                    "detector": "hapax-estate-store-registry sweep",
                    "host": host_id,
                    "filed_at": utc_text(instant),
                    "reason": "two consecutive distinct Canary B instances passed unflagged",
                    "trigger_canary_id": canary_id,
                    "miss_streak": streak,
                    "remedy": "repair the registry drift detector and rerun the missed canaries",
                },
            )
            state["incident_filed"] = True
    state.update(
        {"evaluated_ids": sorted(evaluated), "miss_streak": streak, "updated_at": utc_text(instant)}
    )
    _write_json(_runtime_root(home) / "detector-state" / f"{stamp}.json", state)
    _write_json(
        report_path,
        {
            "schema": "hapax.estate-drift-report/v1",
            "stage": "report-only",
            "host": host_id,
            "swept_at": utc_text(instant),
            "candidate_count": len(candidates),
            "finding_count": len(findings),
            "findings": findings,
            "flagged_canary_ids": flagged,
            "missed_canary_ids": missed,
            "detector_incident_path": str(incident_path) if incident_path else None,
            "mutation_actions": [],
        },
    )
    return SweepResult(
        report_path=str(report_path),
        findings=tuple(findings),
        scan_errors=scan_errors,
        flagged_canary_ids=tuple(flagged),
        missed_canary_ids=tuple(missed),
        detector_incident_path=str(incident_path) if incident_path else None,
    )


def grandfather_fragment(
    registry: Registry,
    *,
    host_id: str,
    home: Path,
    now: datetime | None = None,
    mountinfo: Path = Path("/proc/self/mountinfo"),
) -> dict[str, Any]:
    """Produce reviewable grandfather entries; never bless or edit the registry."""
    instant = (now or datetime.now(UTC)).astimezone(UTC)
    candidates, errors = scan_candidates(registry, home=home, mountinfo=mountinfo)
    if errors:
        joined = "; ".join(f"{item.path}: {item.error}" for item in errors)
        raise RegistrationError(
            f"grandfather capture refused incomplete scan: {joined}; remedy: restore every scan root"
        )
    rows = []
    for candidate in candidates:
        if matching_store(registry, Path(candidate.path), host=host_id, home=home) is not None:
            continue
        rows.append(
            {
                "id": f"grandfather-{host_id}-{len(rows) + 1:04d}",
                "hosts": [host_id],
                "locator": candidate.path,
                "locator_kind": "filesystem",
                "class": "grandfather-candidate",
                "action": "flag-only",
                "lifecycle": "grandfathered",
                "discovery_evidence": f"bounded scan {candidate.scan_root} at {utc_text(instant)} ({candidate.kind})",
                "operator_blessing": None,
            }
        )
    return {
        "schema": "hapax.estate-grandfather-fragment/v1",
        "host": host_id,
        "captured_at": utc_text(instant),
        "complete_scan": True,
        "operator_blessing": None,
        "stores": rows,
    }


def run_peer_command(
    registry: Registry,
    *,
    host_id: str,
    command: str,
    runner: Runner = subprocess.run,
    timeout_seconds: int = 180,
) -> subprocess.CompletedProcess[str]:
    peer_id, target = registry.peer(host_id)
    remote = (
        f'exec "$HOME/.local/bin/uv" --directory "{REMOTE_SOURCE_ROOT}" run python '
        f"scripts/hapax-estate-store-registry {shlex.quote(command)} --host {shlex.quote(peer_id)} --json"
    )
    try:
        result = runner(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=12",
                target,
                remote,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RegistrationError(
            f"cross-host {command} could not reach {peer_id} via {target}: {exc}; "
            "remedy: restore the existing SSH link"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RegistrationError(
            f"cross-host {command} failed for {peer_id} via {target}: {detail or result.returncode}; "
            "remedy: repair the peer unit or source activation"
        )
    return result
