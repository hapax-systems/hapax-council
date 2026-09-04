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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

FRAME_PROCEDURE_ROOT_ENV = "HAPAX_FRAME_PROCEDURE_ROOT"
DEFAULT_FRAME_PROCEDURE_ROOT = Path("~/Documents/Personal/30-areas/hapax/frame/procedure")

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


class FrameVerdictsUnavailable(RuntimeError):
    """The verdict set cannot be consulted; ``reason`` says why and ``remedy`` what to do."""

    def __init__(self, reason: str, remedy: str = PRODUCER_REMEDY) -> None:
        super().__init__(f"{reason}. Next: {remedy}")
        self.reason = reason
        self.remedy = remedy


@dataclass(frozen=True)
class DecayedMember:
    member_id: str
    relation: str
    roots: tuple[Path, ...]
    patterns: tuple[str, ...]
    files: tuple[Path, ...]
    qualified_roots: tuple[QualifiedLocation, ...] = ()
    qualified_files: tuple[QualifiedLocation, ...] = ()


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


def epoch_produced_at(name: str) -> datetime | None:
    match = _EPOCH_NAME.match(name)
    if match is None:
        return None
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


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
    except (OSError, json.JSONDecodeError) as exc:
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


def _qualified_location(raw: str, *, scope_ref: bool = False) -> tuple[QualifiedLocation, bool]:
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
    if scope_ref:
        while parts and _WILDCARD.search(parts[-1]):
            parts.pop()
            dirlike = True
    if any(_WILDCARD.search(part) for part in parts):
        raise NonCanonicalScopeRef(
            f"scheme-qualified ref {raw!r} has a wildcard before its tail; containment is "
            "undecidable"
        )
    return QualifiedLocation(scheme.casefold(), authority, absolute_path, tuple(parts)), dirlike


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
    if not root.is_dir():
        raise FrameVerdictsUnavailable(
            f"frame procedure root {root} does not exist (set {FRAME_PROCEDURE_ROOT_ENV} or "
            "restore the vault)"
        )
    epoch_dir = current_epoch_dir(root)
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
    except (OSError, json.JSONDecodeError) as exc:
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
    except (OSError, yaml.YAMLError) as exc:
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
    except (OSError, json.JSONDecodeError) as exc:
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
                f"member {member_id!r} has an uncontainable scheme-qualified location: {exc}"
            ) from exc
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


def resolve_scope_ref(ref: str, *, council_root: Path, vault_root: Path) -> tuple[Path, bool]:
    """A declared ref as an absolute path plus whether it names a directory-like surface.

    A trailing wildcard segment (``scripts/**``, ``docs/*.md``) is stripped and marks the ref as
    directory-like. Relative refs are tried against the council checkout and then the vault; a
    ref that exists under neither resolves under the council root and will simply not match.
    """
    text = ref.strip().replace("\\", "/")
    dirlike = text.endswith("/")
    segments = [segment for segment in text.split("/") if segment not in ("", ".")]
    absolute = text.startswith("/")
    if any(segment == ".." for segment in segments):
        # A ref that climbs out of its own tree cannot be contained by a member, and normalising it
        # silently would let `scripts/../../elsewhere/x.py` read as inside `scripts/` (review
        # finding, four families, 2026-09-04). Refuse the ref rather than guess what it meant.
        raise NonCanonicalScopeRef(
            f"mutation_scope_ref {ref!r} contains a '..' segment; declare the surface it actually "
            "names, without climbing out of it"
        )
    while segments and _WILDCARD.search(segments[-1]):
        segments.pop()
        dirlike = True
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
            close = pattern.find("]", index + 1)
            if close == -1:
                out.append(re.escape(char))
                index += 1
            else:
                out.append(pattern[index : close + 1])
                index = close + 1
        else:
            out.append(re.escape(char))
            index += 1
    return re.compile("^" + "".join(out) + "$")


def _pattern_matches(relative: str, name: str, pattern: str) -> bool:
    """A member pattern against a path already known to sit under the member's root.

    A pattern with no separator matches by NAME at any depth — the reader's own semantics, and what
    the mass means when it declares ``patterns: ["*.md"]`` over a whole tree. A pattern containing a
    separator is anchored at the root, and there ``*`` does not cross one while ``**`` does.
    """
    if "/" in pattern or "**" in pattern:
        return bool(_glob_to_regex(pattern).match(relative))
    return fnmatch.fnmatchcase(name, pattern)


def ref_within_member(path: Path, dirlike: bool, member: DecayedMember) -> bool:
    if any(path == file for file in member.files):
        return True
    for root in member.roots:
        if path != root and root not in path.parents:
            continue
        if not member.patterns or path == root:
            return True
        relative = "" if path == root else path.relative_to(root).as_posix()
        if dirlike:
            # A directory-like ref names a surface, not a file: it is inside the member when any
            # declared pattern could match something beneath it. `docs/` under a member declaring
            # `*.md` is inside; it is not a licence to match a differently-rooted directory.
            return True
        for pattern in member.patterns:
            if _pattern_matches(relative, path.name, pattern):
                return True
    return False


def qualified_ref_within_member(
    ref: QualifiedLocation, dirlike: bool, member: DecayedMember
) -> bool:
    """Whether a parsed scheme-qualified ref is contained by one decayed member."""
    if ref in member.qualified_files:
        return True
    for root in member.qualified_roots:
        same_namespace = (
            ref.scheme == root.scheme
            and ref.authority == root.authority
            and ref.absolute_path == root.absolute_path
        )
        if not same_namespace or ref.parts[: len(root.parts)] != root.parts:
            continue
        if not member.patterns or ref.parts == root.parts:
            return True
        relative_parts = ref.parts[len(root.parts) :]
        relative = "/".join(relative_parts)
        if dirlike:
            return True
        name = relative_parts[-1] if relative_parts else ""
        if any(_pattern_matches(relative, name, pattern) for pattern in member.patterns):
            return True
    return False


def _repo_relative_candidates(
    ref: str, verdicts: FrameVerdicts, *, council_root: Path
) -> list[Path]:
    """The same repository-relative ref rooted at each decayed member's declared repository root.

    In production the dispatcher runs from the activation worktree, while the mass declares council
    members at the canonical checkout, so a ref like `scripts/x.py` resolved against the running
    tree could never match — the guard would have been inert exactly where it runs (review finding,
    codex, 2026-09-04). A repo-relative ref is therefore also tried under each declared member's
    containing git checkout. Repository identity cannot come from ``council_root.name``: a deployed
    source activation resolves to ``releases/<sha>`` and that basename is the release hash.
    """
    text = ref.strip().replace("\\", "/")
    if text.startswith("/") or text.startswith("~"):
        return []
    segments = [segment for segment in text.split("/") if segment not in ("", ".")]
    while segments and _WILDCARD.search(segments[-1]):
        segments.pop()
    if not segments:
        return []
    relative = Path(*segments)
    roots: set[Path] = set()
    for member in verdicts.decayed:
        for location in (*member.roots, *member.files):
            for candidate in (location, *location.parents):
                if (candidate / ".git").exists():
                    roots.add(candidate.resolve())
                    break
    roots.discard(council_root.resolve())
    return [(root / relative).resolve() for root in sorted(roots)]


def scope_within_decayed(
    refs: list[str] | tuple[str, ...],
    verdicts: FrameVerdicts,
    *,
    council_root: Path,
    vault_root: Path,
) -> ScopeVerdict:
    matches: list[ScopeMatch] = []
    outside: list[str] = []
    declared_refs = [str(ref) for ref in refs if str(ref).strip()]
    if declared_refs and verdicts.unmatchable:
        raise NonCanonicalScopeRef(
            "decayed member(s) "
            f"{list(verdicts.unmatchable)} have no containable declared location; the scope "
            "cannot be compared safely"
        )
    for ref in declared_refs:
        text = str(ref).strip()
        if _NON_FILESYSTEM_ROOT.match(text):
            qualified_ref, dirlike = _qualified_location(text, scope_ref=True)
            hit = next(
                (
                    member
                    for member in verdicts.decayed
                    if qualified_ref_within_member(qualified_ref, dirlike, member)
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
        candidates = [
            path,
            *_repo_relative_candidates(str(ref), verdicts, council_root=council_root),
        ]
        hit = next(
            (
                member
                for member in verdicts.decayed
                for candidate in candidates
                if ref_within_member(candidate, dirlike, member)
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
