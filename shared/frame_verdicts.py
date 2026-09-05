"""The frame's accountability verdicts, read at a work-selection point.

Stated with no estate noun in it: a work-selection point admits a unit of work only after
consulting the current accountability verdicts; work whose declared effect surface lies wholly
inside surfaces the verdicts mark as out of accountability is refused with the remedy named, and a
verdict set that is absent or older than its producer's cadence refuses too, naming the producer to
run. That is the whole architecture. Everything below it is a binding, declared here so it can be
swapped:

- the verdict set is the accepted epoch selected by the frame procedure's atomic
  ``_runs/current`` pointer, produced by ``hapax-frame-iteration.timer`` every
  :data:`FRAME_ITERATION_CADENCE_S`;
- the surfaces are the members of the procedure's ``declaration/mass.yaml`` and their declared
  filesystem locations;
- the effect surface of a unit of work is its task row's ``mutation_scope_refs``;
- "out of accountability" is a TRUE verdict under one of :data:`DECAY_RELATIONS`, the same seven
  relations the producer uses to regionise a member as decayed.

Filesystem and scheme-qualified surfaces are separate namespaces. Scheme-qualified declarations
(``gh://``, ``podium:``) are compared structurally by scheme, authority and path segments; a
comparison that cannot be parsed refuses rather than being treated as outside the decayed member.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

FRAME_PROCEDURE_ROOT_ENV = "HAPAX_FRAME_PROCEDURE_ROOT"
DEFAULT_FRAME_PROCEDURE_ROOT = Path("~/Documents/Personal/30-areas/hapax/frame/procedure")
FRAME_VAULT_ROOT_ENV = "HAPAX_FRAME_VAULT_ROOT"
DEFAULT_FRAME_VAULT_ROOT = Path("~/Documents/Personal")

#: ``hapax-frame-iteration.timer``: ``OnUnitActiveSec=3h``. A binding, not a law — change it here
#: when the timer changes, and the tolerated age below follows.
FRAME_ITERATION_CADENCE_S = 3 * 3600
#: One missed iteration is tolerated (the timer counts from the previous activation, so a slow
#: run shifts the next one); two missed iterations mean the producer is down, and a
#: work-selection point that kept admitting work against six-hour-old verdicts would be exactly
#: the silent fall-out-of-accountability the frame exists to refuse.
FRAME_EPOCH_MAX_AGE_S = 2 * FRAME_ITERATION_CADENCE_S

#: The producer's own set, copied from `frame/procedure/iteration.py`'s DECAY_RELATIONS: the seven
#: relations a TRUE under which places a member in DECAYED. The consumer carried three of them until
#: review found the narrowing (four families, 2026-09-04): a consumer that maintains a private,
#: smaller copy of the producer's classification silently admits work on surfaces the producer has
#: already retired. Kept as a literal because the producer lives in another tree and cannot be
#: imported; :data:`MODEL_RELATIONS` below is the other half of the producer's list, and any relation
#: in neither is unknown to this reader and refuses (see `load_frame_verdicts`).
DECAY_RELATIONS = frozenset(
    {
        "superseded",
        "discharged",
        "scope_exited",
        "absorbed",
        "contradicted",
        "context_lost",
        "unconsulted",
    }
)
#: The producer's model relations: a TRUE selects which decay model applies and never decays.
MODEL_RELATIONS = frozenset({"never_relevant", "composition_only", "periodic", "deferred"})
ALL_RELATIONS = DECAY_RELATIONS | MODEL_RELATIONS
VERDICT_STATES = frozenset({"TRUE", "FALSE", "UNKNOWN", "UNEVALUABLE"})

PRODUCER_REMEDY = (
    "run the frame producer — `systemctl --user start hapax-frame-iteration.service`, or from "
    "~/Documents/Personal/30-areas/hapax: `uv run --with pyyaml python -m frame.procedure.run` — "
    "then retry the dispatch"
)

_EPOCH_NAME = re.compile(r"^(\d{8}T\d{6}Z)-[0-9a-f]+$")
_NON_FILESYSTEM_ROOT = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_WILDCARD = re.compile(r"[*?\[]")


class NonCanonicalScopeRef(ValueError):
    """A declared scope cannot be compared safely with the frame's member locations."""

    remedy = "repair mutation_scope_refs to use canonical paths, then retry the dispatch"


class UncontainableMemberLocation(NonCanonicalScopeRef):
    """A decayed member's declaration supplies no comparable location."""

    remedy = (
        "amend frame/procedure/declaration/mass.yaml with a containable member location; "
        + PRODUCER_REMEDY
    )


class UndecidableScopeContainment(NonCanonicalScopeRef):
    """A canonical scope is too broad for a sound containment proof."""

    remedy = (
        "repair mutation_scope_refs to use explicit file paths or narrower globs whose "
        "containment can be decided, then retry the dispatch"
    )


class FrameVerdictsUnavailable(RuntimeError):
    """The verdict set cannot be consulted; ``reason`` says why and ``remedy`` what to do."""

    def __init__(
        self,
        reason: str,
        remedy: str = PRODUCER_REMEDY,
        *,
        frame_epoch: str | None = None,
        frame_root_resolved: str | None = None,
    ) -> None:
        if frame_root_resolved is not None:
            reason = f"{reason}; frame_root_resolved={frame_root_resolved}"
        super().__init__(f"{reason}. Next: {remedy}")
        self.reason = reason
        self.remedy = remedy
        self.frame_epoch = frame_epoch
        self.frame_root_resolved = frame_root_resolved


@dataclass(frozen=True)
class DecayedMember:
    member_id: str
    relation: str
    roots: tuple[Path, ...]
    patterns: tuple[str, ...]
    files: tuple[Path, ...]
    qualified_roots: tuple[QualifiedLocation, ...] = ()
    qualified_files: tuple[QualifiedLocation, ...] = ()
    excluded_roots: tuple[Path, ...] = ()
    excluded_prefixes: tuple[Path, ...] = ()
    skip_dirs: tuple[str, ...] = ()


@dataclass(frozen=True)
class QualifiedLocation:
    """A scheme-qualified surface split into containment-significant components."""

    scheme: str
    authority: str | None
    absolute_path: bool
    parts: tuple[str, ...]


@dataclass(frozen=True)
class FrameVerdicts:
    epoch: str
    elements_path: Path
    produced_at: datetime
    decayed: tuple[DecayedMember, ...]
    #: decayed members with no filesystem or qualified root/file. Any declared scope is
    #: undecidable against these members and therefore refuses in :func:`scope_within_decayed`.
    unmatchable: tuple[str, ...]


@dataclass(frozen=True)
class ScopeMatch:
    ref: str
    member_id: str
    relation: str


@dataclass(frozen=True)
class ScopeVerdict:
    #: every declared ref lies inside a decayed member (and at least one ref was declared)
    all_inside: bool
    matches: tuple[ScopeMatch, ...]
    outside: tuple[str, ...]


def _member_declaration_identity(member: dict[str, object], exclusions: object) -> str:
    """The producer's per-member declaration identity, recomputed by its own rule.

    `frame/procedure/declaration.py::_member_declaration_identities`. Copied rather than imported
    because the producer lives in another tree; `test_member_declaration_identity_matches_a_real_epoch`
    pins that this reproduces a real epoch's recorded value, so a change on either side is caught.
    """
    canonical = json.dumps(
        {"member": member, "exclusions": exclusions},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return "declaration:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def frame_procedure_root() -> Path:
    raw = os.environ.get(FRAME_PROCEDURE_ROOT_ENV, "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_FRAME_PROCEDURE_ROOT.expanduser()


def frame_vault_root() -> Path:
    raw = os.environ.get(FRAME_VAULT_ROOT_ENV, "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_FRAME_VAULT_ROOT.expanduser()


def epoch_produced_at(name: str) -> datetime | None:
    match = _EPOCH_NAME.match(name)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        # A syntactically valid stamp can still name an impossible calendar date/time.
        # Let current_epoch_dir issue the same actionable refusal as any invalid name.
        return None


def latest_epoch_dir(procedure_root: Path) -> Path | None:
    """Return the newest persisted attempt, for history/diagnostics rather than consumption."""
    epochs = procedure_root / "_runs" / "epochs"
    if not epochs.is_dir():
        return None
    candidates = [
        child
        for child in epochs.iterdir()
        if child.is_dir()
        and epoch_produced_at(child.name) is not None
        and (child / "elements.json").is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda child: child.name)


def current_epoch_dir(procedure_root: Path) -> Path:
    """Resolve and validate the producer's accepted-current publication pointer.

    Every attempted epoch is durable, including attempts rejected for coverage regression. The
    producer makes an epoch govern only by atomically moving ``_runs/current`` and recording a
    matching ``publish.json`` receipt whose ``swapped`` field is true. Both facts are required: a
    missing/broken pointer or contradictory receipt is damaged guard input, never permission to
    choose another epoch.
    """
    runs = procedure_root / "_runs"
    current = runs / "current"
    if not (current.exists() or current.is_symlink()):
        raise FrameVerdictsUnavailable(f"no frame epoch is published at {current}")
    try:
        epoch_dir = current.resolve(strict=True)
        epochs = (runs / "epochs").resolve(strict=True)
    except OSError as exc:
        raise FrameVerdictsUnavailable(
            f"published frame pointer {current} is broken or unreadable: {exc}"
        ) from exc
    if not epoch_dir.is_dir() or epoch_dir.parent != epochs:
        raise FrameVerdictsUnavailable(
            f"published frame pointer {current} resolves outside the epoch directory {epochs}"
        )
    if epoch_produced_at(epoch_dir.name) is None:
        raise FrameVerdictsUnavailable(
            f"published frame pointer {current} names invalid epoch {epoch_dir.name!r}"
        )

    publish_path = epoch_dir / "publish.json"
    if not publish_path.is_file():
        raise FrameVerdictsUnavailable(f"current epoch {epoch_dir.name} publish.json is missing")
    try:
        receipt = json.loads(publish_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrameVerdictsUnavailable(f"{publish_path} is unreadable or malformed: {exc}") from exc
    if not isinstance(receipt, dict):
        raise FrameVerdictsUnavailable(f"{publish_path} must contain a JSON object")
    if receipt.get("epoch") != epoch_dir.name:
        raise FrameVerdictsUnavailable(
            f"{publish_path} names epoch {receipt.get('epoch')!r}, not current {epoch_dir.name!r}"
        )
    if receipt.get("swapped") is not True:
        raise FrameVerdictsUnavailable(
            f"current epoch {epoch_dir.name} was not accepted for publication according to "
            f"{publish_path}"
        )
    return epoch_dir


def _qualified_location(
    raw: str, *, scope_ref: bool = False
) -> tuple[QualifiedLocation, bool, str | None]:
    """Parse one scheme-qualified declaration or scope without lossy URI normalisation."""
    text = raw.strip()
    match = _NON_FILESYSTEM_ROOT.match(text)
    if match is None:
        raise NonCanonicalScopeRef(f"{raw!r} is not scheme-qualified")
    if "\\" in text or "?" in text or "#" in text or "%" in text:
        raise NonCanonicalScopeRef(
            f"scheme-qualified ref {raw!r} uses escaping, a query or a fragment; containment is "
            "undecidable"
        )
    scheme, remainder = text.split(":", 1)
    authority: str | None = None
    absolute_path = remainder.startswith("/")
    path = remainder
    if remainder.startswith("//"):
        authority_and_path = remainder[2:]
        authority, separator, path_tail = authority_and_path.partition("/")
        if not authority:
            raise NonCanonicalScopeRef(
                f"scheme-qualified ref {raw!r} has an empty authority; containment is undecidable"
            )
        authority = authority.casefold()
        path = path_tail if separator else ""
        absolute_path = True
    elif absolute_path:
        path = remainder[1:]
    if "//" in path:
        raise NonCanonicalScopeRef(
            f"scheme-qualified ref {raw!r} has an empty path segment; containment is undecidable"
        )

    dirlike = text.endswith("/")
    parts = [part for part in path.split("/") if part]
    if any(part in (".", "..") for part in parts):
        raise NonCanonicalScopeRef(
            f"scheme-qualified ref {raw!r} contains a '.' or '..' path segment"
        )
    scope_pattern: str | None = None
    if scope_ref:
        wildcard_at = next(
            (index for index, part in enumerate(parts) if _WILDCARD.search(part)), None
        )
        if wildcard_at is not None:
            scope_pattern = "/".join(parts[wildcard_at:])
            parts = parts[:wildcard_at]
            dirlike = True
    if any(_WILDCARD.search(part) for part in parts):
        raise NonCanonicalScopeRef(
            f"scheme-qualified ref {raw!r} has a wildcard before its tail; containment is "
            "undecidable"
        )
    return (
        QualifiedLocation(scheme.casefold(), authority, absolute_path, tuple(parts)),
        dirlike,
        scope_pattern,
    )


def _exclusion_locations(
    exclusions: list[object], *, declaration_dir: Path
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Resolve the producer's ordinary containment and trailing-``*`` prefix exclusions."""
    roots: list[Path] = []
    prefixes: list[Path] = []
    for index, exclusion in enumerate(exclusions):
        if not isinstance(exclusion, dict):
            raise FrameVerdictsUnavailable(
                f"mass exclusion {index} is not a mapping; its effective surface is undecidable"
            )
        paths = exclusion.get("paths")
        if not isinstance(paths, list) or not paths:
            raise FrameVerdictsUnavailable(
                f"mass exclusion {index} has no non-empty paths list; its effective surface is "
                "undecidable"
            )
        for raw in paths:
            if not isinstance(raw, str) or not raw:
                raise FrameVerdictsUnavailable(
                    f"mass exclusion {index} contains a non-string or empty path; its effective "
                    "surface is undecidable"
                )
            prefix = raw.endswith("*")
            text = raw[:-1] if prefix else raw
            path = Path(text)
            base = declaration_dir / path if not path.is_absolute() else path
            if prefix:
                prefixes.append(base.parent.resolve() / base.name)
            else:
                roots.append(base.resolve())
    return tuple(roots), tuple(prefixes)


def _member_location(
    member: dict[str, object],
) -> tuple[
    tuple[Path, ...],
    tuple[str, ...],
    tuple[Path, ...],
    tuple[QualifiedLocation, ...],
    tuple[QualifiedLocation, ...],
]:
    """Filesystem and scheme-qualified roots/files plus the member's file patterns."""
    location = member.get("location")
    if not isinstance(location, dict):
        return (), (), (), (), ()
    raw_roots: list[str] = []
    if isinstance(location.get("path"), str):
        raw_roots.append(str(location["path"]))
    if isinstance(location.get("roots"), list):
        raw_roots.extend(str(item) for item in location["roots"] if isinstance(item, str))
    roots: list[Path] = []
    qualified_roots: list[QualifiedLocation] = []
    for raw in raw_roots:
        raw = raw.strip()
        if _NON_FILESYSTEM_ROOT.match(raw):
            qualified_roots.append(_qualified_location(raw)[0])
            continue
        roots.append(Path(raw).expanduser().resolve())
    patterns = location.get("patterns")
    globs = tuple(str(item) for item in patterns) if isinstance(patterns, list) else ()
    files_raw = location.get("files")
    files: list[Path] = []
    qualified_files: list[QualifiedLocation] = []
    if isinstance(files_raw, list):
        for item in files_raw:
            if not isinstance(item, str):
                continue
            item = item.strip()
            if _NON_FILESYSTEM_ROOT.match(item):
                qualified_files.append(_qualified_location(item)[0])
            else:
                files.append(Path(item).expanduser().resolve())
    return (
        tuple(roots),
        globs,
        tuple(files),
        tuple(qualified_roots),
        tuple(qualified_files),
    )


def load_frame_verdicts(
    procedure_root: Path | None = None,
    *,
    now: datetime | None = None,
    max_age_s: int = FRAME_EPOCH_MAX_AGE_S,
) -> FrameVerdicts:
    """Read the accepted current epoch and the mass it is about; refuse when either is unusable.

    Refusal, never a default: an absent procedure root, no epoch, an epoch older than
    ``max_age_s``, malformed elements or mass, or verdict rows missing altogether each raise
    :class:`FrameVerdictsUnavailable` with the producer named — a work-selection point that
    guessed "nothing decayed" on any of these would be admitting work against no verdicts.
    """
    root = procedure_root if procedure_root is not None else frame_procedure_root()
    root = root.expanduser().resolve()
    epoch_dir: Path | None = None
    try:
        if not root.is_dir():
            raise FrameVerdictsUnavailable(
                f"frame procedure root {root} does not exist (set {FRAME_PROCEDURE_ROOT_ENV} or "
                "restore the vault)"
            )
        epoch_dir = current_epoch_dir(root)
        return _load_epoch_verdicts(root, epoch_dir, now=now, max_age_s=max_age_s)
    except FrameVerdictsUnavailable as exc:
        # Bind diagnostics to this read, including missing pointers and damaged epoch inputs.
        # The dispatcher must not re-resolve an environment override when writing its receipt.
        raise FrameVerdictsUnavailable(
            exc.reason,
            exc.remedy,
            frame_epoch=epoch_dir.name if epoch_dir is not None else None,
            frame_root_resolved=str(root),
        ) from exc


def _load_epoch_verdicts(
    root: Path, epoch_dir: Path, *, now: datetime | None, max_age_s: int
) -> FrameVerdicts:
    produced_at = epoch_produced_at(epoch_dir.name)
    assert produced_at is not None  # current_epoch_dir only returns a parseable epoch
    current = now if now is not None else datetime.now(UTC)
    age = current - produced_at
    if age > timedelta(seconds=max_age_s):
        raise FrameVerdictsUnavailable(
            f"current frame epoch {epoch_dir.name} is {int(age.total_seconds()) // 60} min old, "
            f"older than {max_age_s // 60} min (two iterations of a "
            f"{FRAME_ITERATION_CADENCE_S // 60}-min cadence); the producer has stopped"
        )
    elements_path = epoch_dir / "elements.json"
    try:
        elements = json.loads(elements_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrameVerdictsUnavailable(
            f"{elements_path} is unreadable or malformed: {exc}"
        ) from exc
    if not isinstance(elements, list):
        raise FrameVerdictsUnavailable(f"{elements_path} must contain a JSON list of elements")
    reports: list[list[object]] = []
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            raise FrameVerdictsUnavailable(
                f"{elements_path} element {index} is not a JSON object; the epoch is only "
                "partially readable"
            )
        payload = element.get("payload")
        is_relevance_report = (
            element.get("kind") == "relevance_report"
            or element.get("id") == "frame:relevance-report"
            or isinstance(payload, dict)
            and "verdicts" in payload
        )
        if not is_relevance_report:
            continue
        verdicts = payload.get("verdicts") if isinstance(payload, dict) else None
        if not isinstance(verdicts, list):
            raise FrameVerdictsUnavailable(
                f"{elements_path} relevance report element {index} has no verdicts list"
            )
        reports.append(verdicts)
    if not reports:
        raise FrameVerdictsUnavailable(
            f"{elements_path} carries no verdict rows (no element has payload.verdicts); the "
            "epoch is not a frame-reduction run"
        )
    if len(reports) != 1:
        raise FrameVerdictsUnavailable(
            f"{elements_path} carries {len(reports)} relevance reports; this reader cannot choose "
            "which verdict set governs"
        )
    rows = reports[0]
    if not rows:
        raise FrameVerdictsUnavailable(
            f"{elements_path} relevance report has an empty verdicts list"
        )

    mass_path = root / "declaration" / "mass.yaml"
    try:
        mass = yaml.safe_load(mass_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise FrameVerdictsUnavailable(f"{mass_path} is unreadable or malformed: {exc}") from exc
    members = mass.get("members") if isinstance(mass, dict) else None
    if not isinstance(members, list):
        raise FrameVerdictsUnavailable(f"{mass_path} must declare a members list")
    exclusions = mass.get("exclusions") or []
    if not isinstance(exclusions, list):
        raise FrameVerdictsUnavailable(f"{mass_path} exclusions must be a list when declared")
    mass_projection = mass.get("projection")
    if not isinstance(mass_projection, str) or not mass_projection:
        raise FrameVerdictsUnavailable(
            f"{mass_path} has no non-empty projection; relevance verdicts are projection-relative"
        )
    members_by_id: dict[str, dict[str, object]] = {}
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            raise FrameVerdictsUnavailable(
                f"{mass_path} member {index} is not a mapping; the current mass is only partially "
                "readable"
            )
        member_id = member.get("id")
        if not isinstance(member_id, str) or not member_id.strip():
            raise FrameVerdictsUnavailable(f"{mass_path} member {index} has no non-empty string id")
        if member_id in members_by_id:
            raise FrameVerdictsUnavailable(
                f"{mass_path} declares duplicate member id {member_id!r}"
            )
        members_by_id[member_id] = member

    coverage_path = epoch_dir / "coverage.json"
    if not coverage_path.is_file():
        raise FrameVerdictsUnavailable(
            f"{coverage_path} is missing; the verdicts cannot be bound to the declaration they "
            "were computed against"
        )
    epoch_identities: dict[str, str] = {}
    try:
        coverage_rows = json.loads(coverage_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrameVerdictsUnavailable(
            f"{coverage_path} is unreadable or malformed: {exc}; the verdicts cannot be bound "
            "to the declaration they were computed against"
        ) from exc
    if not isinstance(coverage_rows, list):
        raise FrameVerdictsUnavailable(
            f"{coverage_path} must contain a JSON list with one binding per declared member"
        )
    for index, row in enumerate(coverage_rows):
        if not isinstance(row, dict):
            raise FrameVerdictsUnavailable(f"{coverage_path} row {index} is not a JSON object")
        member_id = row.get("member_id")
        identity = row.get("member_declaration_identity")
        if not isinstance(member_id, str) or not member_id.strip():
            raise FrameVerdictsUnavailable(
                f"{coverage_path} row {index} has no non-empty string member_id"
            )
        if not isinstance(identity, str) or not identity:
            raise FrameVerdictsUnavailable(
                f"{coverage_path} row {index} for {member_id!r} has no declaration identity"
            )
        if member_id in epoch_identities:
            raise FrameVerdictsUnavailable(
                f"{coverage_path} carries duplicate bindings for member {member_id!r}"
            )
        epoch_identities[member_id] = identity
    declared_ids = set(members_by_id)
    covered_ids = set(epoch_identities)
    if covered_ids != declared_ids:
        missing = sorted(declared_ids - covered_ids)
        extra = sorted(covered_ids - declared_ids)
        raise FrameVerdictsUnavailable(
            f"{coverage_path} does not bind exactly the current mass; missing members={missing}, "
            f"undeclared members={extra}"
        )
    drifted = sorted(
        member_id
        for member_id, member in members_by_id.items()
        if epoch_identities[member_id] != _member_declaration_identity(member, exclusions)
    )
    if drifted:
        raise FrameVerdictsUnavailable(
            f"frame epoch {epoch_dir.name} cannot be bound to the current mass; declaration "
            f"identity changed for member(s) {drifted}"
        )
    excluded_roots, excluded_prefixes = _exclusion_locations(
        exclusions, declaration_dir=mass_path.parent
    )

    decay: dict[str, set[str]] = {}
    seen_verdicts: set[tuple[str, str]] = set()
    for index, raw_row in enumerate(rows):
        if not isinstance(raw_row, dict):
            raise FrameVerdictsUnavailable(
                f"{elements_path} verdict row {index} is not a JSON object; a partially readable "
                "report would silently shrink the decayed set"
            )
        subject = raw_row.get("subject")
        if not isinstance(subject, dict):
            raise FrameVerdictsUnavailable(
                f"{elements_path} verdict row {index} has no subject object"
            )
        member_id = subject.get("member_id")
        if not isinstance(member_id, str) or not member_id.strip():
            raise FrameVerdictsUnavailable(
                f"{elements_path} verdict row {index} has no non-empty string subject.member_id"
            )
        if member_id not in members_by_id:
            raise FrameVerdictsUnavailable(
                f"{elements_path} verdict row {index} names undeclared member {member_id!r}"
            )
        relation = raw_row.get("relation")
        if not isinstance(relation, str) or not relation:
            raise FrameVerdictsUnavailable(
                f"{elements_path} verdict row {index} has no non-empty string relation"
            )
        if relation not in ALL_RELATIONS:
            raise FrameVerdictsUnavailable(
                f"{elements_path} verdict row {index} uses relation {relation!r} that this reader "
                "does not classify as decay or model; the producer's relation set has moved"
            )
        verdict = raw_row.get("verdict")
        if isinstance(verdict, bool):
            verdict_state = "TRUE" if verdict else "FALSE"
        elif isinstance(verdict, str) and verdict.upper() in VERDICT_STATES:
            verdict_state = verdict.upper()
        else:
            raise FrameVerdictsUnavailable(
                f"{elements_path} verdict row {index} for {member_id!r}/{relation} has invalid "
                f"verdict {verdict!r}"
            )
        projection = raw_row.get("projection")
        if not isinstance(projection, str) or not projection:
            raise FrameVerdictsUnavailable(
                f"{elements_path} verdict row {index} for {member_id!r}/{relation} has no "
                "non-empty projection"
            )
        if projection != mass_projection:
            raise FrameVerdictsUnavailable(
                f"{elements_path} verdict row {index} for {member_id!r}/{relation} uses projection "
                f"{projection!r}, not the current mass projection {mass_projection!r}"
            )
        key = (member_id, relation)
        if key in seen_verdicts:
            raise FrameVerdictsUnavailable(
                f"{elements_path} carries duplicate verdicts for {member_id!r}/{relation}"
            )
        seen_verdicts.add(key)
        if relation in DECAY_RELATIONS and verdict_state == "TRUE":
            decay.setdefault(member_id, set()).add(relation)
    expected_verdicts = {
        (member_id, relation) for member_id in members_by_id for relation in ALL_RELATIONS
    }
    if seen_verdicts != expected_verdicts:
        missing = sorted(expected_verdicts - seen_verdicts)
        raise FrameVerdictsUnavailable(
            f"{elements_path} verdict matrix is incomplete; missing {len(missing)} member/relation "
            f"row(s), including {missing[:5]}"
        )

    decayed: list[DecayedMember] = []
    unmatchable: list[str] = []
    for member_id, member in members_by_id.items():
        if member_id not in decay:
            continue
        try:
            roots, patterns, files, qualified_roots, qualified_files = _member_location(member)
        except NonCanonicalScopeRef as exc:
            raise FrameVerdictsUnavailable(
                f"member {member_id!r} has an uncontainable scheme-qualified location: {exc}",
                remedy=UncontainableMemberLocation.remedy,
            ) from exc
        location = member.get("location") or {}
        skip_dirs = tuple(location.get("skip_dirs") or []) if isinstance(location, dict) else ()
        for relation in sorted(decay[member_id]):
            decayed.append(
                DecayedMember(
                    member_id,
                    relation,
                    roots,
                    patterns,
                    files,
                    qualified_roots,
                    qualified_files,
                    excluded_roots=excluded_roots,
                    excluded_prefixes=excluded_prefixes,
                    skip_dirs=skip_dirs,
                )
            )
        if not roots and not files and not qualified_roots and not qualified_files:
            unmatchable.append(member_id)
    return FrameVerdicts(
        epoch=epoch_dir.name,
        elements_path=elements_path,
        produced_at=produced_at,
        decayed=tuple(decayed),
        unmatchable=tuple(unmatchable),
    )


def _filesystem_scope_parts(ref: str) -> tuple[list[str], str | None, bool]:
    """Split a filesystem ref into its literal path prefix and unmodified glob tail."""
    text = ref.strip().replace("\\", "/")
    segments = [segment for segment in text.split("/") if segment not in ("", ".")]
    if any(segment == ".." for segment in segments):
        raise NonCanonicalScopeRef(
            f"mutation_scope_ref {ref!r} contains a '..' segment; declare the surface it actually "
            "names, without climbing out of it"
        )
    wildcard_at = next(
        (index for index, segment in enumerate(segments) if _WILDCARD.search(segment)), None
    )
    if wildcard_at is None:
        return segments, None, text.endswith("/")
    return segments[:wildcard_at], "/".join(segments[wildcard_at:]), True


def resolve_scope_ref(ref: str, *, council_root: Path, vault_root: Path) -> tuple[Path, bool]:
    """A declared ref as an absolute path plus whether it names a directory-like surface.

    A wildcard tail (``scripts/**``, ``docs/**/generated/*.md``) is preserved by
    :func:`scope_within_decayed` but stripped from the literal path resolved here. Relative refs are
    tried against the council checkout and then the vault; a ref that exists under neither resolves
    under the council root and will simply not match.
    """
    text = ref.strip().replace("\\", "/")
    segments, scope_pattern, dirlike = _filesystem_scope_parts(ref)
    absolute = text.startswith("/")
    dirlike = dirlike or scope_pattern is not None
    joined = ("/" if absolute else "") + "/".join(segments)
    path = Path(joined).expanduser() if joined else Path(".")
    if not path.is_absolute():
        # The base is the checkout whose tree already holds the ref's first segment: a ref names
        # a file that may not exist yet (the work is about to create it), so the decision is made
        # on the nearest ancestor, never on the leaf.
        first = Path(segments[0]) if segments else Path(".")
        base = next((b for b in (council_root, vault_root) if (b / first).exists()), council_root)
        path = base / path
    # Resolve symlinks on the deepest existing ancestor: a ref may name a file the work is about to
    # create, so the leaf need not exist, but every existing component must be canonical or a
    # symlinked directory would carry a ref outside the member it appears to be inside.
    path = path.absolute()
    existing = path
    tail: list[str] = []
    while not existing.exists() and existing != existing.parent:
        tail.append(existing.name)
        existing = existing.parent
    if existing.exists():
        path = existing.resolve()
        for part in reversed(tail):
            path = path / part
    if path.is_dir():
        dirlike = True
    return path, dirlike


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """A path glob where ``**`` crosses ``/`` and ``*`` does not.

    Review finding (four families, 2026-09-04): the previous implementation returned True for any
    pattern *containing* ``**``, so a member declaring `docs/**/*.md` matched every path under its
    root, including source. The distinction between the two wildcards is the whole point of the
    declaration, so it is compiled rather than approximated.
    """
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif char == "*":
            out.append("[^/]*")
            index += 1
        elif char == "?":
            out.append("[^/]")
            index += 1
        elif char == "[":
            start = index + 1
            if start < len(pattern) and pattern[start] == "!":
                start += 1
            if start < len(pattern) and pattern[start] == "]":
                start += 1
            close = pattern.find("]", start)
            if close == -1:
                out.append(re.escape(char))
                index += 1
            else:
                # pathlib uses fnmatch's class semantics: leading ! negates; ^, backslashes,
                # and non-leading ! are literals. Keep the class within one path segment.
                translated = fnmatch.translate(pattern[index : close + 1])
                out.append("(?!/)" + translated.removesuffix(r"\Z").removesuffix(r"\z"))
                index = close + 1
        else:
            out.append(re.escape(char))
            index += 1
    return re.compile("^" + "".join(out) + "$")


def _pattern_matches(relative: str, pattern: str) -> bool:
    """A member pattern against a path already known to sit under the member's root.

    The producer's fs.glob calls root.glob(pattern): every pattern is anchored at the root.
    ``*.md`` selects direct children; ``**/*.md`` also selects nested files.
    """
    return bool(_glob_to_regex(pattern).match(relative))


def _glob_segments(pattern: str) -> tuple[str, ...]:
    segments = tuple(part for part in pattern.strip("/").split("/") if part)
    if segments and segments[-1] == "**":
        return (*segments, "*")
    return segments


def _normalise_member_pattern(pattern: str) -> str:
    pattern = pattern.strip().replace("\\", "/").strip("/")
    if pattern.endswith("/**"):
        pattern += "/*"
    return pattern


def _segment_pattern_covers(member_pattern: str, scope_pattern: str) -> bool:
    """A deliberately small, sound proof that one segment glob contains another."""
    if member_pattern == "*" or member_pattern == scope_pattern:
        return True
    if not _WILDCARD.search(scope_pattern):
        return fnmatch.fnmatchcase(scope_pattern, member_pattern)
    return False


def _glob_pattern_covers(member_pattern: str, scope_pattern: str) -> bool:
    """Prove glob-language containment for the path shapes the declaration uses.

    ``**`` is handled as a whole-segment Kleene star. Segment-glob containment is intentionally
    conservative: equality, a universal member ``*``, and literal scope segments are decidable.
    More elaborate overlapping glob languages are left to the fail-closed caller.
    """
    member_segments = _glob_segments(_normalise_member_pattern(member_pattern))
    scope_segments = _glob_segments(scope_pattern)
    memo: dict[tuple[int, int], bool] = {}

    def covers(member_at: int, scope_at: int) -> bool:
        key = (member_at, scope_at)
        if key in memo:
            return memo[key]
        if member_at == len(member_segments):
            result = scope_at == len(scope_segments)
        elif member_segments[member_at] == "**":
            if member_at + 1 == len(member_segments):
                result = True
            else:
                result = covers(member_at + 1, scope_at) or (
                    scope_at < len(scope_segments) and covers(member_at, scope_at + 1)
                )
        elif scope_at == len(scope_segments) or scope_segments[scope_at] == "**":
            result = False
        else:
            result = _segment_pattern_covers(
                member_segments[member_at], scope_segments[scope_at]
            ) and covers(member_at + 1, scope_at + 1)
        memo[key] = result
        return result

    return covers(0, 0)


def _segment_witnesses(pattern: str) -> tuple[str, ...]:
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            out.append("scope")
        elif char == "?":
            out.append("x")
        elif char == "[":
            close = pattern.find("]", index + 1)
            if close != -1:
                choices = pattern[index + 1 : close].lstrip("!^")
                out.append(choices[0] if choices else "x")
                index = close
            else:
                out.append("[")
        else:
            out.append(char)
        index += 1
    primary = "".join(out) or "scope"
    candidates = [primary]
    if pattern == "*":
        candidates.extend(("scope.py", "scope.md"))
    return tuple(dict.fromkeys(c for c in candidates if fnmatch.fnmatchcase(c, pattern)))


def _glob_witnesses(pattern: str) -> tuple[str, ...]:
    paths: list[tuple[str, ...]] = [()]
    for segment in _glob_segments(pattern):
        if segment == "**":
            expansions = ((), ("scope",), ("scope", "nested"))
        else:
            expansions = tuple((witness,) for witness in _segment_witnesses(segment))
        paths = [(*prefix, *suffix) for prefix in paths for suffix in expansions][:64]
    return tuple("/".join(parts) for parts in paths if parts)


def _scope_glob_covered(scope_pattern: str, member_patterns: tuple[str, ...]) -> bool:
    if any(_glob_pattern_covers(pattern, scope_pattern) for pattern in member_patterns):
        return True
    normalised = tuple(_normalise_member_pattern(pattern) for pattern in member_patterns)
    for witness in _glob_witnesses(scope_pattern):
        if not any(_glob_to_regex(pattern).match(witness) for pattern in normalised):
            return False
    raise UndecidableScopeContainment(
        f"scope glob {scope_pattern!r} overlaps member patterns {list(member_patterns)!r}, but "
        "whole-surface containment cannot be decided safely"
    )


def _path_is_excluded(path: Path, member: DecayedMember) -> bool:
    if any(part in member.skip_dirs for part in path.parts):
        return True
    if any(path == root or root in path.parents for root in member.excluded_roots):
        return True
    text = str(path)
    return any(text.startswith(str(prefix)) for prefix in member.excluded_prefixes)


def _glob_intersects_subtree(scope_pattern: str, relative_prefix: str) -> bool | None:
    """Whether a scope glob has a path at or below one concrete subtree prefix."""
    prefix = tuple(part for part in relative_prefix.split("/") if part)
    regex = _glob_to_regex(scope_pattern)
    candidates = [relative_prefix]
    candidates.extend(
        f"{relative_prefix}/{tail}" if relative_prefix else tail
        for tail in ("scope", "scope.py", "scope.md", "nested/scope.md")
    )
    if any(candidate and regex.match(candidate) for candidate in candidates):
        return True
    if any(
        witness == relative_prefix or witness.startswith(relative_prefix + "/")
        for witness in _glob_witnesses(scope_pattern)
    ):
        return True

    segments = _glob_segments(scope_pattern)
    if "**" not in segments:
        if len(prefix) > len(segments):
            return False
        for concrete, pattern in zip(prefix, segments, strict=False):
            if not fnmatch.fnmatchcase(concrete, pattern):
                return False
        tails = [_segment_witnesses(pattern) for pattern in segments[len(prefix) :]]
        if any(not choices for choices in tails):
            # A missing sample (e.g. for [!a].py) does not prove the segment empty.
            return None
        witnesses = [*prefix, *(choices[0] for choices in tails)]
        return bool(regex.match("/".join(witnesses)))

    for concrete, pattern in zip(prefix, segments, strict=False):
        if pattern == "**" or _WILDCARD.search(pattern):
            break
        if concrete != pattern:
            return False
    return None


def _scope_intersects_exclusions(path: Path, scope_pattern: str, member: DecayedMember) -> bool:
    if _path_is_excluded(path, member):
        return True
    if member.skip_dirs and any(
        segment == "**" or any(fnmatch.fnmatchcase(skip, segment) for skip in member.skip_dirs)
        for segment in _glob_segments(scope_pattern)
    ):
        return True
    undecidable = False
    for root in member.excluded_roots:
        if path not in root.parents:
            continue
        state = _glob_intersects_subtree(scope_pattern, root.relative_to(path).as_posix())
        if state is True:
            return True
        undecidable = undecidable or state is None
    for prefix in member.excluded_prefixes:
        parent = prefix.parent
        if path != parent and path not in parent.parents:
            continue
        state = _glob_intersects_subtree(scope_pattern, prefix.relative_to(path).as_posix())
        if state is True:
            return True
        # The exclusion is a string prefix, so every possible suffix also needs checking.
        # Concrete subtree witnesses can prove overlap, but their absence cannot prove
        # disjointness (excluded-special intersects *-special even when excluded does not).
        # The current glob comparator cannot decide that language intersection.
        undecidable = True
    if undecidable:
        raise UndecidableScopeContainment(
            f"scope glob {scope_pattern!r} cannot be compared safely with the mass exclusions"
        )
    return False


def _scope_pattern_from_base(relative: str, scope_pattern: str | None) -> str:
    tail = scope_pattern or "**/*"
    return "/".join(part for part in (relative, tail) if part)


def ref_within_member(
    path: Path,
    dirlike: bool,
    member: DecayedMember,
    *,
    scope_pattern: str | None = None,
) -> bool:
    broad = dirlike or scope_pattern is not None
    if any(path == file for file in member.files):
        return not broad and not _path_is_excluded(path, member)
    if scope_pattern is not None:
        for file in member.files:
            if (
                path in file.parents
                and not _path_is_excluded(file, member)
                and _pattern_matches(file.relative_to(path).as_posix(), scope_pattern)
            ):
                # The declared file is concrete; the scope supplies the glob. A matching file
                # proves overlap, but the glob may also name undeclared (even future) files.
                raise UndecidableScopeContainment(
                    f"scope glob {scope_pattern!r} matches declared member file {file}; "
                    "whole-surface containment cannot be decided safely"
                )
    for root in member.roots:
        if path != root and root not in path.parents:
            if (
                scope_pattern is not None
                and path in root.parents
                and _glob_intersects_subtree(scope_pattern, root.relative_to(path).as_posix())
                is not False
            ):
                # The literal prefix stops before the member root, but the glob may enter it.
                # Neither overlap nor a missing witness proves whole-surface containment.
                raise UndecidableScopeContainment(
                    f"scope glob {scope_pattern!r} may enter member root {root}; "
                    "whole-surface containment cannot be decided safely"
                )
            continue
        relative = "" if path == root else path.relative_to(root).as_posix()
        if broad:
            member_scope_pattern = _scope_pattern_from_base(relative, scope_pattern)
            if member.patterns and not _scope_glob_covered(member_scope_pattern, member.patterns):
                continue
            exclusion_scope_pattern = _scope_pattern_from_base("", scope_pattern)
            if _scope_intersects_exclusions(path, exclusion_scope_pattern, member):
                continue
            return True
        if _path_is_excluded(path, member):
            continue
        if not member.patterns or path == root:
            return True
        for pattern in member.patterns:
            if _pattern_matches(relative, pattern):
                return True
    return False


def qualified_ref_within_member(
    ref: QualifiedLocation,
    dirlike: bool,
    member: DecayedMember,
    *,
    scope_pattern: str | None = None,
) -> bool:
    """Whether a parsed scheme-qualified ref is contained by one decayed member."""
    broad = dirlike or scope_pattern is not None
    if ref in member.qualified_files:
        return not broad
    if scope_pattern is not None:
        for file in member.qualified_files:
            same_namespace = (
                ref.scheme == file.scheme
                and ref.authority == file.authority
                and ref.absolute_path == file.absolute_path
            )
            if (
                same_namespace
                and file.parts[: len(ref.parts)] == ref.parts
                and _pattern_matches("/".join(file.parts[len(ref.parts) :]), scope_pattern)
            ):
                raise UndecidableScopeContainment(
                    f"scope glob {scope_pattern!r} matches declared member file {file}; "
                    "whole-surface containment cannot be decided safely"
                )
    for root in member.qualified_roots:
        same_namespace = (
            ref.scheme == root.scheme
            and ref.authority == root.authority
            and ref.absolute_path == root.absolute_path
        )
        if not same_namespace:
            continue
        if ref.parts[: len(root.parts)] != root.parts:
            if (
                scope_pattern is not None
                and root.parts[: len(ref.parts)] == ref.parts
                and _glob_intersects_subtree(scope_pattern, "/".join(root.parts[len(ref.parts) :]))
                is not False
            ):
                # As for filesystem roots, a glob before the root can enter the member even
                # though its literal prefix is outside. An absent witness is not disjointness.
                raise UndecidableScopeContainment(
                    f"scope glob {scope_pattern!r} may enter member root {root}; "
                    "whole-surface containment cannot be decided safely"
                )
            continue
        relative_parts = ref.parts[len(root.parts) :]
        relative = "/".join(relative_parts)
        if broad:
            member_scope_pattern = _scope_pattern_from_base(relative, scope_pattern)
            if member.patterns and not _scope_glob_covered(member_scope_pattern, member.patterns):
                continue
            return True
        if not member.patterns or ref.parts == root.parts:
            return True
        if any(_pattern_matches(relative, pattern) for pattern in member.patterns):
            return True
    return False


def _repository_identity(checkout: Path) -> frozenset[str] | None:
    """Verify a checkout root and identify its history without reading remote credentials."""
    try:
        top = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "--show-toplevel"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).stdout.strip()
        if not top or Path(top).resolve() != checkout.resolve():
            return None
        roots = subprocess.run(
            ["git", "-C", str(checkout), "rev-list", "--max-parents=0", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return None
    if not roots or any(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", root) is None for root in roots):
        return None
    return frozenset(roots)


def _repo_relative_candidates(
    ref: str, verdicts: FrameVerdicts, *, council_root: Path
) -> list[Path]:
    """The same repository-relative ref rooted at each decayed member's declared repository root.

    In production the dispatcher runs from the activation worktree, while the mass declares council
    members at the canonical checkout, so a ref like `scripts/x.py` resolved against the running
    tree could never match — the guard would have been inert exactly where it runs (review finding,
    codex, 2026-09-04). A repo-relative ref is therefore also tried under each declared member's
    containing git checkout, but only after verifying equivalent root commit histories.
    Repository identity cannot come from ``council_root.name``: a deployed source activation
    resolves to ``releases/<sha>`` and that basename is the release hash. An unverified checkout
    supplies no additional candidates.
    """
    text = ref.strip().replace("\\", "/")
    if text.startswith("/") or text.startswith("~"):
        return []
    segments, _, _ = _filesystem_scope_parts(ref)
    # An empty literal prefix still names the repository root; apply its glob there.
    relative = Path(*segments)
    roots: set[Path] = set()
    for member in verdicts.decayed:
        for location in (*member.roots, *member.files):
            for candidate in (location, *location.parents):
                if (candidate / ".git").exists():
                    roots.add(candidate.resolve())
                    break
    roots.discard(council_root.resolve())
    if not roots or (identity := _repository_identity(council_root)) is None:
        return []
    return [
        (root / relative).resolve()
        for root in sorted(roots)
        if _repository_identity(root) == identity
    ]


def scope_within_decayed(
    refs: list[str] | tuple[str, ...],
    verdicts: FrameVerdicts,
    *,
    council_root: Path,
    vault_root: Path | None = None,
) -> ScopeVerdict:
    vault_root = frame_vault_root() if vault_root is None else vault_root
    matches: list[ScopeMatch] = []
    outside: list[str] = []
    declared_refs = [str(ref) for ref in refs if str(ref).strip()]
    if declared_refs and verdicts.unmatchable:
        raise UncontainableMemberLocation(
            "decayed member(s) "
            f"{list(verdicts.unmatchable)} have no containable declared location; the scope "
            "cannot be compared safely"
        )
    for ref in declared_refs:
        text = str(ref).strip()
        if _NON_FILESYSTEM_ROOT.match(text):
            qualified_ref, dirlike, scope_pattern = _qualified_location(text, scope_ref=True)
            hit = next(
                (
                    member
                    for member in verdicts.decayed
                    if qualified_ref_within_member(
                        qualified_ref, dirlike, member, scope_pattern=scope_pattern
                    )
                ),
                None,
            )
            if hit is None:
                outside.append(str(ref))
            else:
                matches.append(ScopeMatch(str(ref), hit.member_id, hit.relation))
            continue
        path, dirlike = resolve_scope_ref(
            str(ref), council_root=council_root, vault_root=vault_root
        )
        _, scope_pattern, _ = _filesystem_scope_parts(str(ref))
        candidates = [
            path,
            *_repo_relative_candidates(str(ref), verdicts, council_root=council_root),
        ]
        hit = next(
            (
                member
                for member in verdicts.decayed
                for candidate in candidates
                if ref_within_member(candidate, dirlike, member, scope_pattern=scope_pattern)
            ),
            None,
        )
        if hit is None:
            outside.append(str(ref))
        else:
            matches.append(ScopeMatch(str(ref), hit.member_id, hit.relation))
    declared = bool(matches or outside)
    return ScopeVerdict(
        all_inside=declared and not outside,
        matches=tuple(matches),
        outside=tuple(outside),
    )
