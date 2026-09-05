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

import codecs
import fnmatch
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, replace
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
MASS_DECLARATION_LOCATION = (
    "declaration/mass.yaml (relative to the procedure root, HAPAX_FRAME_PROCEDURE_ROOT)"
)

_EPOCH_NAME = re.compile(r"^(\d{8}T\d{6}Z)-[0-9a-f]+$")
_NON_FILESYSTEM_ROOT = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_AUTHORITY = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*"
)
_WILDCARD = re.compile(r"[*?\[]")


class NonCanonicalScopeRef(ValueError):
    """A declared scope cannot be compared safely with the frame's member locations."""

    remedy = "repair mutation_scope_refs to use canonical paths, then retry the dispatch"


class UncontainableMemberLocation(NonCanonicalScopeRef):
    """A decayed member's declaration supplies no comparable location."""

    remedy = (
        f"amend {MASS_DECLARATION_LOCATION} with a containable member location; " + PRODUCER_REMEDY
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
    reader: str = ""
    host_aliases: tuple[tuple[str, str], ...] = ()
    content_query: ContentQuery | None = None


@dataclass(frozen=True)
class ContentQuery:
    query: str
    case_insensitive: bool
    match_mode: str
    max_unit_bytes: int
    encoding_error_policy: str


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
    because the producer lives in another tree. The literal producer fixture pins compatibility
    even without the vault; the real-epoch test additionally checks the installed producer.
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
    except (OSError, RuntimeError) as exc:
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
    qualifier = text.partition(":")[0]
    # A malformed host qualifier must not fall through to the filesystem namespace.
    if ":" in text and not text.split(":", 1)[1].startswith("//"):
        _validate_authority(qualifier, raw)
    match = _NON_FILESYSTEM_ROOT.match(text)
    if match is None:
        raise NonCanonicalScopeRef(f"{raw!r} is not scheme-qualified")
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
        _validate_authority(authority, raw)
        authority = authority.casefold()
        path = path_tail if separator else ""
        absolute_path = True
    elif absolute_path:
        path = remainder[1:]
    if "\\" in text or "?" in text or "#" in text or "%" in text:
        raise NonCanonicalScopeRef(
            f"scheme-qualified ref {raw!r} uses escaping, a query or a fragment; containment is "
            "undecidable"
        )
    if scope_ref and path:
        path = _normalise_glob_spelling(path, allow_absolute=True)
    elif "//" in path:
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


def _validate_authority(authority: str, raw: str) -> None:
    if _AUTHORITY.fullmatch(authority) is None:
        raise NonCanonicalScopeRef(
            f"qualified ref {raw!r} has unsupported authority or host qualifier {authority!r}; "
            "accepted form is dot-separated ASCII letter/digit labels with interior hyphens "
            "(for example gh://hapax-systems/council/x or podium:council/x); "
            "wildcard-authority containment is not supported; replace the spelling with "
            "the literal authority or host qualifier"
        )


def _has_qualifier(raw: str) -> bool:
    prefix, separator, _ = raw.partition(":")
    return bool(separator) and "/" not in prefix


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


def _producer_working_directory(epoch_dir: Path) -> Path:
    """Use recorded execution context, or the declared vault binding, never dispatch cwd.

    Current producer epochs persist iteration.environment in hypothesis.json, but only
    record python/platform/host. Honour cwd when recorded; older epochs use the working
    directory from the producer command in PRODUCER_REMEDY.
    """
    remedy = (
        "record an absolute producer working directory in hypothesis.json iteration.environment.cwd "
        f"or set {FRAME_VAULT_ROOT_ENV} to the producer's vault with 30-areas/hapax; "
        + PRODUCER_REMEDY
    )
    hypothesis = epoch_dir / "hypothesis.json"
    try:
        if hypothesis.exists():
            payload = json.loads(hypothesis.read_text(encoding="utf-8"))
            environment = payload.get("iteration", {}).get("environment", {})
            if "cwd" in environment:
                raw = environment["cwd"]
                if isinstance(raw, str) and raw and Path(raw).is_absolute():
                    return Path(raw).resolve()
                raise ValueError("recorded cwd must be a non-empty absolute path")
        vault = frame_vault_root().expanduser()
        base = vault / "30-areas/hapax"
        if vault.is_absolute() and base.is_dir():
            return base.resolve()
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        raise FrameVerdictsUnavailable(
            f"producer working directory is undecidable: {exc}", remedy=remedy
        ) from exc
    raise FrameVerdictsUnavailable(
        "relative member location is undecidable: no recorded producer working directory "
        "or available declared vault base",
        remedy=remedy,
    )


def _member_host_aliases(member: dict[str, object]) -> tuple[tuple[str, str], ...]:
    location = member.get("location") or {}
    raw = (location.get("host_aliases") or {}) if isinstance(location, dict) else {}
    if not isinstance(raw, dict):
        raise UncontainableMemberLocation("location.host_aliases must be a host-to-host mapping")
    aliases: dict[str, str] = {}
    for alias, canonical in raw.items():
        if not isinstance(alias, str) or not isinstance(canonical, str):
            raise UncontainableMemberLocation("location.host_aliases must contain literal hosts")
        _validate_authority(alias, alias)
        _validate_authority(canonical, canonical)
        alias, canonical = alias.casefold(), canonical.casefold()
        if alias in aliases and aliases[alias] != canonical:
            raise UncontainableMemberLocation(
                "location.host_aliases has conflicting host spellings"
            )
        aliases[alias] = canonical
    # The producer performs ONE lookup. A chain or cycle cannot safely be flattened.
    if any(aliases.get(host, host) != host for host in aliases.values()):
        raise UncontainableMemberLocation(
            "location.host_aliases must map each alias directly to its canonical host"
        )
    return tuple(sorted(aliases.items()))


def _member_location(
    member: dict[str, object],
    *,
    epoch_dir: Path,
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
    reader = member.get("reader")
    content_query = isinstance(reader, dict) and reader.get("id") == "fs.content_query"
    raw_roots: list[str] = []
    if not content_query and isinstance(location.get("path"), str):
        raw_roots.append(str(location["path"]))
    if isinstance(location.get("roots"), list):
        raw_roots.extend(str(item) for item in location["roots"] if isinstance(item, str))
    roots: list[Path] = []
    qualified_roots: list[QualifiedLocation] = []

    def local_path(raw: str) -> Path:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = _producer_working_directory(epoch_dir) / path
        return path.resolve()

    for raw in raw_roots:
        raw = raw.strip()
        if _has_qualifier(raw):
            qualified_roots.append(_qualified_location(raw)[0])
            continue
        roots.append(local_path(raw))
    patterns = location.get("patterns")
    globs = tuple(str(item) for item in patterns) if isinstance(patterns, list) else ()
    files_raw = None if content_query else location.get("files")
    files: list[Path] = []
    qualified_files: list[QualifiedLocation] = []
    if isinstance(files_raw, list):
        for item in files_raw:
            if not isinstance(item, str):
                continue
            item = item.strip()
            if _has_qualifier(item):
                qualified_files.append(_qualified_location(item)[0])
            else:
                files.append(local_path(item))
    return (
        tuple(roots),
        globs,
        tuple(files),
        tuple(qualified_roots),
        tuple(qualified_files),
    )


def _load_content_query(
    member: dict[str, object], procedure_root: Path, epoch_dir: Path
) -> ContentQuery:
    """Use fs.content_query's declaration and parameter profile, without private defaults."""
    location = member.get("location") or {}
    try:
        query = location.get("query")
        roots = location.get("roots")
        insensitive = bool(location.get("case_insensitive"))
        mode = location.get("match")
        mode = "substring" if mode is None else str(mode)
        if not isinstance(roots, list) or not roots:
            raise ValueError("location.roots must be a nonempty list")
        if not isinstance(query, str) or not query:
            raise ValueError("location.query must be a nonempty literal")
        if mode not in {"substring", "word"}:
            raise ValueError("location.match must be substring or word")
        if "\n" in query or "\r" in query or (insensitive and not query.isascii()):
            raise ValueError("multiline or non-ASCII case-insensitive query is unsupported")
        profile = yaml.safe_load((procedure_root / "declaration/params.yaml").read_text("utf-8"))
        hypothesis = epoch_dir / "hypothesis.json"
        if hypothesis.exists():
            recorded = json.loads(hypothesis.read_text("utf-8")).get("iteration", {})
            digest = recorded.get("parameter_profile_digest")
            canonical = json.dumps(
                profile, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            if (
                digest is not None
                and digest != hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            ):
                raise ValueError(
                    "declaration/params.yaml differs from the accepted epoch's profile"
                )
        parameters = profile["parameters"]
        max_bytes = parameters["max_unit_bytes"]["value"]
        errors = parameters["encoding_error_policy"]["value"]
        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError("max_unit_bytes must be a nonnegative integer")
        codecs.lookup_error(errors)
    except (
        OSError,
        UnicodeError,
        yaml.YAMLError,
        LookupError,
        TypeError,
        AttributeError,
        ValueError,
    ) as exc:
        raise FrameVerdictsUnavailable(
            f"member {member['id']!r} fs.content_query containment is undecidable: {exc}",
            remedy="repair the fs.content_query location and declaration/params.yaml; "
            + PRODUCER_REMEDY,
        ) from exc
    return ContentQuery(query, insensitive, mode, max_bytes, errors)


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
        reader = member.get("reader")
        reader_id = reader.get("id", "") if isinstance(reader, dict) else ""
        if reader_id not in {"", "fs.glob", "ssh.glob", "fs.content_query"}:
            raise FrameVerdictsUnavailable(
                f"member {member_id!r} uses unimplemented containment reader {reader_id!r}",
                remedy=f"implement containment for reader {reader_id!r}, or re-declare the member "
                "with a supported reader; " + PRODUCER_REMEDY,
            )
        try:
            roots, patterns, files, qualified_roots, qualified_files = _member_location(
                member, epoch_dir=epoch_dir
            )
            host_aliases = _member_host_aliases(member) if reader_id == "ssh.glob" else ()
        except NonCanonicalScopeRef as exc:
            raise FrameVerdictsUnavailable(
                f"member {member_id!r} has an uncontainable scheme-qualified location: {exc}",
                remedy=UncontainableMemberLocation.remedy,
            ) from exc
        location = member.get("location") or {}
        skip_dirs = tuple(location.get("skip_dirs") or []) if isinstance(location, dict) else ()
        content_query = None
        if reader_id == "fs.content_query":
            content_query = _load_content_query(member, root, epoch_dir)
            if qualified_roots:
                raise FrameVerdictsUnavailable(
                    f"member {member_id!r} fs.content_query requires local filesystem roots",
                    remedy=UncontainableMemberLocation.remedy,
                )
            if location.get("patterns") is None:
                patterns = ("**/*",)
            # fs.content_query consults declared exclusions, but not fs.glob's skip_dirs.
            skip_dirs = ()
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
                    reader=reader_id,
                    host_aliases=host_aliases,
                    content_query=content_query,
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


def _normalise_glob_spelling(
    pattern: str, *, member_pattern: bool = False, allow_absolute: bool = False
) -> str:
    """Use pathlib's path parts without guessing about unsupported glob languages."""
    path = Path(pattern)
    normalised = path.as_posix()
    problem = None
    if not path.parts:
        problem = "an empty glob has no comparable surface"
    elif path.is_absolute() and not allow_absolute:
        problem = "Path.glob requires a relative pattern"
    elif ".." in path.parts:
        problem = "contains a '..' segment"
    elif any("**" in part and part != "**" for part in path.parts):
        problem = "'**' must be an entire path component"
    elif "\x00" in pattern:
        problem = "contains a NUL character"
    if problem:
        error_type = UncontainableMemberLocation if member_pattern else NonCanonicalScopeRef
        kind = "member pattern" if member_pattern else "mutation_scope_ref"
        raise error_type(
            f"unsupported {kind} {pattern!r}; normalized form {normalised!r}: {problem}"
        )
    return normalised


def _filesystem_scope_parts(ref: str) -> tuple[list[str], str | None, bool]:
    """Split a pathlib-normalised filesystem ref into its literal prefix and glob tail."""
    text = ref.strip().replace("\\", "/")
    normalised = _normalise_glob_spelling(text, allow_absolute=True)
    segments = [segment for segment in normalised.split("/") if segment]
    wildcard_at = next(
        (index for index, segment in enumerate(segments) if _WILDCARD.search(segment)), None
    )
    if wildcard_at is None:
        return segments, None, text.endswith("/")
    return segments[:wildcard_at], "/".join(segments[wildcard_at:]), True


def _unresolved_scope_component(
    path: Path, exc: OSError | RuntimeError
) -> UndecidableScopeContainment:
    error = UndecidableScopeContainment(
        f"cannot resolve scope component {path}: {exc}; containment is undecidable"
    )
    error.remedy = (
        f"repair or re-declare unresolved component {path} and its intended target "
        "in mutation_scope_refs, then retry the dispatch"
    )
    return error


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
        base = next(
            (
                b
                for b in (council_root, vault_root)
                if (b / first).exists() or (b / first).is_symlink()
            ),
            council_root,
        )
        path = base / path
    # Keep entries below the root lexical, as fs.glob does. A member comparison checks symlinks
    # against that member's root; resolving here would erase the very entry it enumerated.
    path = path.absolute()
    try:
        if path.is_dir():
            dirlike = True
    except (OSError, RuntimeError) as exc:
        raise _unresolved_scope_component(path, exc) from exc
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
    normalised = _normalise_member_pattern(pattern)
    # A terminal separator makes root.glob select directories; fs.glob then keeps only files.
    return not pattern.endswith("/") and bool(
        _glob_to_regex(normalised).match(Path(relative).as_posix())
    )


def _glob_segments(pattern: str) -> tuple[str, ...]:
    segments = tuple(part for part in pattern.strip("/").split("/") if part)
    if segments and segments[-1] == "**":
        return (*segments, "*")
    return segments


def _normalise_member_pattern(pattern: str) -> str:
    return _normalise_glob_spelling(pattern, member_pattern=True)


def _member_file_patterns(patterns: tuple[str, ...]) -> tuple[str, ...]:
    normalised = tuple(_normalise_member_pattern(pattern) for pattern in patterns)
    return tuple(
        value
        for pattern, value in zip(patterns, normalised, strict=True)
        if not pattern.endswith("/") and Path(value).name != "**"
    )


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
    member_patterns = _member_file_patterns(member_patterns)
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


def _literal_scope_glob(pattern: str) -> str | None:
    """Prove a singleton language, independently of the glob's current expansions."""
    literal: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char in "*?":
            return None
        if char == "[":
            # A single non-negated character is the only class we need to prove here.
            # Larger classes remain subject to the conservative language comparator.
            if index + 2 >= len(pattern) or pattern[index + 2] != "]" or pattern[index + 1] == "!":
                return None
            literal.append(pattern[index + 1])
            index += 3
        else:
            literal.append(char)
            index += 1
    return "".join(literal)


def _path_is_excluded(path: Path, member: DecayedMember) -> bool:
    if any(part in member.skip_dirs for part in path.parts):
        return True
    if not member.excluded_roots and not member.excluded_prefixes:
        return False
    # The producer checks skip_dirs lexically, but Declaration.is_excluded resolves paths.
    path = _resolve_member_path(path)
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


def _resolve_member_path(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError) as exc:
        raise UndecidableScopeContainment(
            f"cannot resolve {path}: {exc}; containment is undecidable; "
            "repair the symlink and declare its intended target explicitly"
        ) from exc


def _resolve_external_scope_path(path: Path) -> Path:
    """Resolve aliases before comparing roots, without treating broken links as future files."""
    resolved = Path(path.anchor)
    for part in path.parts[1:]:
        component = resolved / part
        try:
            try:
                component.lstat()
            except FileNotFoundError:
                # Work may create this path. An existing symlink, including a dangling one,
                # passes lstat and must instead resolve strictly below.
                resolved = component
            else:
                resolved = component.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise _unresolved_scope_component(component, exc) from exc
    return resolved


def _canonical_member_patterns(root: Path, member: DecayedMember) -> tuple[str, ...]:
    """Resolve each selected pattern's literal prefix before comparing file languages.

    A directory alias in the declaration selects the same future paths as its target.
    Keep the glob tail intact: today's file witnesses cannot prove that language.
    """
    patterns = []
    for pattern in _member_file_patterns(member.patterns or ("**/*",)):
        prefix, tail, _ = _filesystem_scope_parts(pattern)
        if tail is None:
            prefix, tail = prefix[:-1], prefix[-1]
        lexical_base = root.joinpath(*prefix)
        canonical_base = _resolve_external_scope_path(lexical_base)
        if _path_is_excluded(lexical_base, member):
            continue
        if canonical_base != root and root not in canonical_base.parents:
            raise UndecidableScopeContainment(
                f"member pattern component {lexical_base} resolves outside member root {root} "
                f"to {canonical_base}; containment is undecidable"
            )
        relative = "" if canonical_base == root else canonical_base.relative_to(root).as_posix()
        patterns.append(_scope_pattern_from_base(relative, tail))
    return tuple(patterns)


def _check_member_symlinks(
    path: Path, root: Path, member: DecayedMember, *, scope_pattern: str | None
) -> bool:
    """Check possible member entries; report excluded witnesses before testing containment."""
    paths = [path]
    if scope_pattern is not None:
        # Inspect existing witnesses only for ambiguity, never to prove that a glob's future
        # surface is contained. pathlib uses the same traversal rules as the producer here.
        try:
            paths.extend(path.glob(scope_pattern))
        except (OSError, RuntimeError, ValueError) as exc:
            raise UndecidableScopeContainment(
                f"cannot inspect scope glob {scope_pattern!r} below {path}: {exc}; "
                "containment is undecidable"
            ) from exc
    patterns = _member_file_patterns(member.patterns)
    has_excluded_entry = False
    for selected in paths:
        relative = "" if selected == root else selected.relative_to(root).as_posix()
        if selected == path and scope_pattern is not None:
            # The literal base may lead to future matches; only a disjoint subtree can be
            # discarded here. A witness outside the patterns cannot make a matching link safe.
            disjoint = member.patterns and all(
                _glob_intersects_subtree(pattern, relative) is False for pattern in patterns
            )
        else:
            disjoint = member.patterns and not any(
                _pattern_matches(relative, pattern) for pattern in patterns
            )
        if disjoint:
            # Lexical disjointness says nothing about the bytes reached by an alias.
            # Close the member selection here, then carry the canonical witness through
            # the same exclusion and parent checks as a lexically selected entry.
            canonical = _resolve_external_scope_path(selected)
            surface = frozenset(_canonical_member_entries(member).values())
            if canonical not in surface:
                if scope_pattern is None or not any(canonical in file.parents for file in surface):
                    continue
                relative = "" if canonical == root else canonical.relative_to(root).as_posix()
                try:
                    covered = _scope_glob_covered(
                        _scope_pattern_from_base(relative, scope_pattern),
                        _canonical_member_patterns(root, member),
                    )
                except UndecidableScopeContainment as exc:
                    raise UndecidableScopeContainment(
                        f"scope component {selected} resolves to selected member surface at "
                        f"{canonical}: {exc}"
                    ) from exc
                if not covered:
                    raise UndecidableScopeContainment(
                        f"scope component {selected} resolves to selected member surface at "
                        f"{canonical}, but whole-surface containment is undecidable"
                    )
            selected = canonical
        if _path_is_excluded(selected, member):
            has_excluded_entry = True
            continue
        for link in (selected, *selected.parents):
            if link == root or root not in link.parents:
                break
            try:
                if not link.is_symlink():
                    continue
                target = link.readlink()
            except (OSError, RuntimeError) as exc:
                raise _unresolved_scope_component(link, exc) from exc
            problem = None
            try:
                resolved = link.resolve(strict=True)
            except (OSError, RuntimeError):
                problem = "is dangling or cannot be resolved"
            else:
                if resolved != root and root not in resolved.parents:
                    problem = f"escapes member root {root} (resolved target {resolved})"
                elif link.is_dir() and not any(
                    (
                        "**" not in _glob_segments(pattern)
                        or link == root.joinpath(*_filesystem_scope_parts(pattern)[0])
                        or link in root.joinpath(*_filesystem_scope_parts(pattern)[0]).parents
                    )
                    and _pattern_matches(selected.relative_to(root).as_posix(), pattern)
                    for pattern in member.patterns
                ):
                    # Recursive ** does not descend into directory symlinks in root.glob.
                    # A literal prefix before ** does traverse them; a link encountered
                    # only by the recursive selector still needs a traversal proof.
                    problem = "crosses a directory symlink without a traversing member pattern"
            if problem:
                error = UndecidableScopeContainment(
                    f"symlink {link} -> {target} {problem}; containment is undecidable"
                )
                error.remedy = (
                    f"repair or re-declare symlink {link} -> {target} and its intended target "
                    "in the member location, re-run the frame producer, then retry the dispatch"
                )
                raise error
    return has_excluded_entry


def _canonical_member_entries(member: DecayedMember) -> dict[Path, Path]:
    """Close the producer's selected file entries over their canonical byte targets.

    Keep each reader's pathlib traversal and exclusions. Content-query predicates are
    evaluated on the selected entries at comparison time. Resolve before is_file(), which
    silently drops dangling links, and retain fs.glob's traversal/escape remedies.
    """
    surface: dict[Path, Path] = {}
    content_query = member.reader == "fs.content_query"
    patterns = member.patterns if content_query else member.patterns or ("**/*",)
    for root in member.roots:
        for pattern in patterns:
            try:
                entries = list(root.rglob(pattern) if content_query else root.glob(pattern))
            except (OSError, RuntimeError, ValueError) as exc:
                raise UndecidableScopeContainment(
                    f"cannot enumerate member pattern {pattern!r} below {root}: {exc}; "
                    "containment is undecidable"
                ) from exc
            for entry in entries:
                # fs.glob discards directories, including resolvable directory symlinks.
                # A file reached THROUGH one still needs the traversal checks below.
                try:
                    if entry.is_dir():
                        continue
                except (OSError, RuntimeError) as exc:
                    raise _unresolved_scope_component(entry, exc) from exc
                if not content_query and _check_member_symlinks(
                    entry, root, member, scope_pattern=None
                ):
                    continue
                canonical = _resolve_external_scope_path(entry)
                if entry.is_file() and not _path_is_excluded(entry, member):
                    surface[entry] = canonical
    return surface


def _canonical_scope_entries(path: Path, pattern: str, member: DecayedMember) -> dict[Path, Path]:
    """Expand in the producer tree before resolving every entry, including broken links."""
    try:
        entries = list(path.glob(pattern))
    except (OSError, RuntimeError, ValueError) as exc:
        raise UndecidableScopeContainment(
            f"cannot inspect scope glob {pattern!r} below {path}: {exc}; containment is undecidable"
        ) from exc
    canonical = {}
    for entry in entries:
        try:
            # The producer reads files. Terminal ** can yield only directories; those
            # entries supply no evidence about containment of the recursive file language.
            if entry.is_dir():
                continue
            for root in member.roots:
                if root in entry.parents:
                    _check_member_symlinks(entry, root, member, scope_pattern=None)
            target = _resolve_external_scope_path(entry)
            if entry.is_file():
                canonical[entry] = target
        except (UndecidableScopeContainment, OSError, RuntimeError) as exc:
            cause = (
                exc
                if isinstance(exc, UndecidableScopeContainment)
                else _unresolved_scope_component(entry, exc)
            )
            error = UndecidableScopeContainment(f"scope glob expansion {entry}: {cause}")
            error.remedy = f"repair scope glob expansion {entry}; {cause.remedy}"
            raise error from exc
    return canonical


def _refuse_directory_spelled_file(file: Path | QualifiedLocation) -> None:
    if isinstance(file, QualifiedLocation):
        prefix = (
            f"//{file.authority}/"
            if file.authority is not None
            else ("/" if file.absolute_path else "")
        )
        spelling = f"{file.scheme}:{prefix}{'/'.join(file.parts)}"
    else:
        spelling = str(file)
    error = NonCanonicalScopeRef(
        f"directory-spelled scope resolves to declared member file {spelling!r}; "
        "containment is undecidable for this inconsistent spelling"
    )
    error.remedy = (
        f"repair mutation_scope_refs to use the file form {spelling!r}, then retry the dispatch"
    )
    raise error


def _content_query_matches(path: Path, query: ContentQuery) -> bool:
    """builtin.fs_content_query's byte prefilter followed by its optional word predicate."""
    try:
        if path.stat().st_size > query.max_unit_bytes:
            raise ValueError(f"exceeds max_unit_bytes={query.max_unit_bytes}")
        with path.open("rb") as stream:
            blob = stream.read(query.max_unit_bytes + 1)
        if len(blob) > query.max_unit_bytes:
            raise ValueError(f"exceeds max_unit_bytes={query.max_unit_bytes}")
        needle = query.query.encode("utf-8")
        if query.case_insensitive:
            needle, blob = needle.lower(), blob.lower()
        if needle not in blob:
            return False
        if query.match_mode == "word":
            text = blob.decode("utf-8", errors=query.encoding_error_policy)
            return bool(
                re.search(
                    rf"(?<![A-Za-z0-9]){re.escape(query.query)}(?![A-Za-z0-9])",
                    text,
                    re.IGNORECASE if query.case_insensitive else 0,
                )
            )
        return True
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        error = UndecidableScopeContainment(
            f"fs.content_query cannot read/evaluate {path}: {exc}; containment is undecidable"
        )
        error.remedy = (
            f"restore readable bytes for {path} within the declared max_unit_bytes and "
            "encoding_error_policy, or amend declaration/params.yaml and re-run the frame "
            "producer, then retry the dispatch"
        )
        raise error from exc


def _content_query_within_member(
    path: Path,
    dirlike: bool,
    member: DecayedMember,
    scope_pattern: str | None,
    selected_entries: dict[Path, Path],
) -> bool:
    query = member.content_query
    if query is None:
        raise UncontainableMemberLocation("fs.content_query has no declared content predicate")
    canonical = _resolve_external_scope_path(path)
    if dirlike or scope_pattern is not None:
        for entry, target in selected_entries.items():
            if canonical in target.parents and _pattern_matches(
                target.relative_to(canonical).as_posix(), scope_pattern or "**/*"
            ):
                raise UndecidableScopeContainment(
                    f"fs.content_query scope component {path} reaches selected target {target} "
                    f"through {entry}; whole-surface containment is undecidable; "
                    "declare explicit files so the content predicate can be evaluated"
                )
    for root in member.roots:
        for candidate in dict.fromkeys((path, canonical)):
            if candidate != root and root not in candidate.parents:
                if scope_pattern is not None and candidate in root.parents:
                    raise UndecidableScopeContainment(
                        f"fs.content_query scope glob {scope_pattern!r} may enter {root}; "
                        "declare explicit files so the content predicate can be evaluated"
                    )
                continue
            if _path_is_excluded(candidate, member) or not member.patterns:
                continue
            if dirlike or scope_pattern is not None:
                raise UndecidableScopeContainment(
                    f"fs.content_query needs explicit file paths below {root} to evaluate "
                    "the content predicate; whole-surface containment is undecidable"
                )
            relative = candidate.relative_to(root).as_posix()
            for pattern in member.patterns:
                normalised = _normalise_member_pattern(pattern)
                # rglob adds recursive selection; terminal ** still uses pathlib itself.
                if Path(normalised).name != "**" and not _pattern_matches(
                    relative, "**/" + pattern
                ):
                    continue
                if Path(normalised).name != "**" and not candidate.exists():
                    # A future file in the path language has no readable predicate yet.
                    # Preserve the missing-bytes remedy instead of calling it outside.
                    _content_query_matches(candidate, query)
    if dirlike or scope_pattern is not None:
        return False
    # The pattern selects entries, while the content is read at their canonical targets.
    # Compare targets before evaluating bytes so both spellings receive the same verdict.
    return any(
        canonical == target and _content_query_matches(entry, query)
        for entry, target in selected_entries.items()
    )


def _local_member_file_matches(path: Path, root: Path, pattern: str) -> bool:
    normalised = _normalise_member_pattern(pattern)
    if Path(normalised).name != "**":
        return _pattern_matches(path.relative_to(root).as_posix(), pattern)
    # In Python 3.12 terminal ** selects only directories. Use the producer's exact
    # selection and is_file filter rather than expanding its surface with an added /*.
    try:
        return any(p == path and p.is_file() for p in root.glob(pattern))
    except (OSError, RuntimeError, ValueError) as exc:
        raise UndecidableScopeContainment(
            f"cannot enumerate member pattern {pattern!r} below {root}: {exc}"
        ) from exc


def ref_within_member(
    path: Path,
    dirlike: bool,
    member: DecayedMember,
    *,
    scope_pattern: str | None = None,
) -> bool:
    _member_file_patterns(member.patterns)  # Validate even when the candidate is outside.
    broad = dirlike or scope_pattern is not None
    file_path = _resolve_member_path(path) if member.files else path
    if any(file_path == file for file in member.files):
        if broad:
            _refuse_directory_spelled_file(file_path)
        return not _path_is_excluded(path, member)
    if scope_pattern is not None:
        for file in member.files:
            if (
                file_path in file.parents
                and not _path_is_excluded(file, member)
                and _pattern_matches(file.relative_to(file_path).as_posix(), scope_pattern)
            ):
                # The declared file is concrete; the scope supplies the glob. A matching file
                # proves overlap, but the glob may also name undeclared (even future) files.
                raise UndecidableScopeContainment(
                    f"scope glob {scope_pattern!r} matches declared member file {file}; "
                    "whole-surface containment cannot be decided safely"
                )
        literal = _literal_scope_glob(scope_pattern)
        if literal is not None:
            candidate = path / literal
            try:
                candidate_is_dir = candidate.is_dir()
            except (OSError, RuntimeError) as exc:
                raise _unresolved_scope_component(candidate, exc) from exc
            return ref_within_member(candidate, candidate_is_dir, member)
    if broad:
        # A literal directory base denotes the same future file language through an alias.
        # Resolve each component even inside the root; terminal ** supplies no file witnesses
        # to repair a lexical-only comparison. Keep the lexical proof as well for member
        # patterns that explicitly select entries through an alias.
        canonical_base = _resolve_external_scope_path(path)
        if canonical_base != path and ref_within_member(
            canonical_base, dirlike, member, scope_pattern=scope_pattern
        ):
            return True
    selected_entries = _canonical_member_entries(member)
    if member.reader == "fs.content_query":
        return _content_query_within_member(path, dirlike, member, scope_pattern, selected_entries)
    surface = frozenset(selected_entries.values())
    expansions = (
        _canonical_scope_entries(path, scope_pattern, member) if scope_pattern is not None else {}
    )
    lexical_path = path
    for root in member.roots:
        path = lexical_path
        if path != root and root not in path.parents:
            # An external alias can enter any descendant of the canonical member root.
            # Entries already under the root retain the producer's lexical glob semantics
            # and the member-specific symlink checks below.
            path = _resolve_external_scope_path(path)
        if path != root and root not in path.parents:
            if scope_pattern is not None and any(
                target in surface for target in expansions.values()
            ):
                # Current aliases prove overlap, never containment of future paths.
                raise UndecidableScopeContainment(
                    f"scope glob {scope_pattern!r} reaches selected canonical targets in "
                    f"member root {root}; whole-surface containment cannot be decided safely"
                )
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
        if (
            not broad
            and member.patterns
            and path != root
            and not any(
                _local_member_file_matches(path, root, pattern) for pattern in member.patterns
            )
        ):
            continue
        has_excluded_entry = _check_member_symlinks(
            path, root, member, scope_pattern=(scope_pattern or "**/*") if broad else None
        )
        if broad:
            # Resolve every file expansion before comparing the candidate's language.
            expansion_base = lexical_path
            if scope_pattern is None:
                expansion_base = path
                expansions = _canonical_scope_entries(path, "**/*", member)
            member_scope_pattern = _scope_pattern_from_base(relative, scope_pattern)
            canonical_base = _resolve_external_scope_path(path)
            canonical_covered = False
            if canonical_base == root or root in canonical_base.parents:
                canonical_relative = (
                    "" if canonical_base == root else canonical_base.relative_to(root).as_posix()
                )
                canonical_covered = _scope_glob_covered(
                    _scope_pattern_from_base(canonical_relative, scope_pattern),
                    _canonical_member_patterns(root, member),
                )
            if member.patterns and not (
                canonical_covered or _scope_glob_covered(member_scope_pattern, member.patterns)
            ):
                if any(
                    target in surface
                    and (
                        path / entry.relative_to(expansion_base) != target
                        or any(
                            selected != target and selected_target == target
                            for selected, selected_target in selected_entries.items()
                        )
                    )
                    for entry, target in expansions.items()
                ):
                    raise UndecidableScopeContainment(
                        f"scope glob {scope_pattern!r} reaches selected canonical targets; "
                        "whole-surface containment cannot be decided safely"
                    )
                continue
            exclusion_scope_pattern = _scope_pattern_from_base("", scope_pattern)
            if _scope_intersects_exclusions(path, exclusion_scope_pattern, member):
                continue
            # Existing files can disprove containment, but cannot establish the proof.
            if any(target not in surface for target in expansions.values()):
                continue
            # Retain the conservative exclusion comparison above. An excluded link target
            # can additionally disprove containment even outside the lexical scope's root.
            if has_excluded_entry:
                continue
            return True
        if has_excluded_entry or _path_is_excluded(path, member):
            continue
        return True
    # The member's own entries may be aliases, so canonical targets must be considered
    # even when the candidate itself has no symlink components or matching lexical pattern.
    canonical = _resolve_external_scope_path(lexical_path)
    return not broad and canonical in surface


def _ssh_glob_patterns(patterns: tuple[str, ...]) -> tuple[str, ...]:
    """Translate find -name's filename selection to recursive containment patterns.

    ssh.glob neither consults mass exclusions nor reads skip_dirs. It selects files
    at every depth. Slashes outside character classes never match; repeated stars are
    filename stars, not pathlib recursion. Unsupported find/fnmatch dialect features
    are undecidable.
    """
    result = []
    for pattern in patterns or ("*",):
        if ("/" in pattern and "[" in pattern) or any(
            token in pattern for token in ("\\", "\x00", "[^", "[:", "[.", "[=")
        ):
            raise UncontainableMemberLocation(
                f"ssh.glob filename pattern {pattern!r} is undecidable; declare a plain "
                "find -name pattern without escapes or locale-dependent character classes"
            )
        if "/" not in pattern and pattern not in ("", ".", ".."):
            result.append("**/" + re.sub(r"\*+", "*", pattern))
    return tuple(result)


def _canonical_remote_location(
    location: QualifiedLocation, member: DecayedMember
) -> QualifiedLocation:
    if location.authority is not None:
        return location
    aliases = dict(member.host_aliases)
    declared = {p.scheme for p in (*member.qualified_roots, *member.qualified_files)}
    known = declared | aliases.keys() | set(aliases.values())
    if location.scheme not in known:
        raise UndecidableScopeContainment(
            f"remote host {location.scheme!r} is undeclared; alias containment is undecidable "
            f"for member {member.member_id!r}. Next: use a declared host from {sorted(known)!r} "
            f"or amend location.host_aliases {aliases!r}; {PRODUCER_REMEDY}"
        )
    return replace(location, scheme=aliases.get(location.scheme, location.scheme))


def qualified_ref_within_member(
    ref: QualifiedLocation,
    dirlike: bool,
    member: DecayedMember,
    *,
    scope_pattern: str | None = None,
) -> bool:
    """Whether a parsed scheme-qualified ref is contained by one decayed member."""
    remote = member.reader == "ssh.glob"
    patterns = (
        _ssh_glob_patterns(member.patterns) if remote else _member_file_patterns(member.patterns)
    )
    qualified_roots = member.qualified_roots
    qualified_files = member.qualified_files
    if remote:
        ref = _canonical_remote_location(ref, member)
        qualified_roots = tuple(
            _canonical_remote_location(root, member) for root in qualified_roots
        )
        qualified_files = tuple(
            _canonical_remote_location(file, member) for file in qualified_files
        )
    broad = dirlike or scope_pattern is not None
    if ref in qualified_files:
        if broad:
            _refuse_directory_spelled_file(ref)
        return True
    if scope_pattern is not None:
        for file in qualified_files:
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
    for root in qualified_roots:
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
            if (member.patterns or remote) and not _scope_glob_covered(
                member_scope_pattern, patterns if remote else member.patterns
            ):
                continue
            return True
        if (not member.patterns and not remote) or ref.parts == root.parts:
            return True
        if any(_pattern_matches(relative, pattern) for pattern in patterns):
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
    return [root / relative for root in sorted(roots) if _repository_identity(root) == identity]


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
        if _has_qualifier(text):
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
