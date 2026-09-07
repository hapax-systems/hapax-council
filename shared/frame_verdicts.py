"""The frame's accountability verdicts, read at a work-selection point.

Stated with no estate noun in it: a work-selection point admits a unit of work only after
consulting the current accountability verdicts; work whose declared effect surface lies wholly
inside surfaces the verdicts mark as out of accountability is refused with the remedy named, and a
verdict set that is absent or older than the declared accepted-evidence allowance refuses too,
naming the producer to run. That is the whole architecture. Everything below it is a binding,
declared here so it can be swapped:

- the verdict set is the accepted epoch selected by the frame procedure's atomic
  ``_runs/current`` pointer with a matching accepted ``publish.json`` receipt; a newer rejected
  attempt does not govern. The accepted-evidence reliance allowance is
  :data:`FRAME_EPOCH_MAX_AGE_S`, independent of the producer's collection schedule;
- the surfaces are the members of the procedure's ``declaration/mass.yaml`` and their declared
  filesystem locations;
- the effect surface of a unit of work is its task row's ``mutation_scope_refs``;
- "out of accountability" is a TRUE verdict under one of the producer's seven
  :data:`DECAY_RELATIONS`: superseded, discharged, scope_exited, absorbed, contradicted,
  context_lost or unconsulted.

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

#: A ``FRAME_ITERATION_CADENCE_S = 3 * 3600`` constant stood here until 2026-09-07, already
#: annotated as historical with no runtime consumer. The annotation was not enough: a name that
#: reads as the producer's cadence invites the next editor to re-derive the allowance below from
#: it, which is the coupling deliberately removed. Deleted rather than renamed — nothing in the
#: tree referenced it, and a comment is a weaker guard than an absent symbol.
#: Independent six-hour maximum accepted-evidence age: an evidence-reliance allowance, not a
#: model of the producer's sampling. A faster schedule permits more missed attempts inside the
#: same allowance; a slower one can outlast it. Ordinary changes to this producer's collection
#: schedule or material collection and failure behaviour must reconsider and record whether
#: this allowance remains appropriate. The actor making the change owes that review and record,
#: whether human, agent or other governed execution.
#: Separating the allowance from the schedule removes the coupling that used to prompt review.
#: This amendment adds no automatic enforcement; a missed review remains a risk.
#: This supersedes the timer-coupled criterion; it is not retroactive
#: compliance, semantic-health proof, universal policy or activation permission.
FRAME_EPOCH_MAX_AGE_S = 21600

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

PRODUCER_REMEDY_TEMPLATE = (
    "run the frame producer — verify it targets procedure root {procedure_root}, "
    "then `systemctl --user start hapax-frame-iteration.service` — then retry the dispatch"
)
PRODUCER_REMEDY = PRODUCER_REMEDY_TEMPLATE.format(procedure_root=FRAME_PROCEDURE_ROOT_ENV)


def _producer_remedy(procedure_root: Path) -> str:
    """Bind the generic producer action to the subject of this read, not a default checkout."""
    return PRODUCER_REMEDY_TEMPLATE.format(procedure_root=procedure_root)


MASS_DECLARATION_LOCATION = (
    "declaration/mass.yaml (relative to the procedure root, HAPAX_FRAME_PROCEDURE_ROOT)"
)

_EPOCH_NAME = re.compile(r"^(\d{8}T\d{6}Z)-[0-9a-f]+$")
_NON_FILESYSTEM_ROOT = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
#: Producer readers whose declared roots are filesystem paths, so a colon in one is part of the
#: name. Enumerated from the installed `procedure/builtin.py` reader registrations rather than
#: assumed from the `fs.` prefix, so a future reader must be added deliberately.
_LOCAL_FILESYSTEM_READERS = frozenset({"fs.glob", "fs.content_query", "fs.witness", "fs.filelist"})
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
    # Aligned with roots; producer spellings stay relative when declared relative.
    # Only skip_dirs uses these unanchored, unresolved paths.
    lexical_roots: tuple[Path, ...] = ()
    # Aligned with files; only skip_dirs judges the declared, unresolved spelling.
    lexical_files: tuple[Path, ...] = ()


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
        raise FrameVerdictsUnavailable(
            f"no frame epoch is published at {current}", remedy=_producer_remedy(procedure_root)
        )
    try:
        epoch_dir = current.resolve(strict=True)
        epochs = (runs / "epochs").resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise FrameVerdictsUnavailable(
            f"published frame pointer {current} is broken or unreadable: {exc}",
            remedy=_producer_remedy(procedure_root),
        ) from exc
    if not epoch_dir.is_dir() or epoch_dir.parent != epochs:
        raise FrameVerdictsUnavailable(
            f"published frame pointer {current} resolves outside the epoch directory {epochs}",
            remedy=_producer_remedy(procedure_root),
        )
    if epoch_produced_at(epoch_dir.name) is None:
        raise FrameVerdictsUnavailable(
            f"published frame pointer {current} names invalid epoch {epoch_dir.name!r}",
            remedy=_producer_remedy(procedure_root),
        )

    publish_path = epoch_dir / "publish.json"
    if not publish_path.is_file():
        raise FrameVerdictsUnavailable(
            f"current epoch {epoch_dir.name} publish.json is missing",
            remedy=_producer_remedy(procedure_root),
        )
    try:
        receipt = json.loads(publish_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrameVerdictsUnavailable(
            f"{publish_path} is unreadable or malformed: {exc}",
            remedy=_producer_remedy(procedure_root),
        ) from exc
    if not isinstance(receipt, dict):
        raise FrameVerdictsUnavailable(
            f"{publish_path} must contain a JSON object", remedy=_producer_remedy(procedure_root)
        )
    if receipt.get("epoch") != epoch_dir.name:
        raise FrameVerdictsUnavailable(
            f"{publish_path} names epoch {receipt.get('epoch')!r}, not current {epoch_dir.name!r}",
            remedy=_producer_remedy(procedure_root),
        )
    if receipt.get("swapped") is not True:
        raise FrameVerdictsUnavailable(
            f"current epoch {epoch_dir.name} was not accepted for publication according to "
            f"{publish_path}",
            remedy=_producer_remedy(procedure_root),
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
            # Resolving an exclusion touches the filesystem, and a filesystem that will not answer
            # is not an empty exclusion. `load_frame_verdicts` catches only FrameVerdictsUnavailable
            # around this, so a PermissionError or a symlink-loop RuntimeError escaped the refusal
            # path entirely: no diagnostic, no remedy, no receipt (review finding, codex,
            # 2026-09-07). Both branches convert, and both name the exclusion and its path.
            try:
                if prefix:
                    prefixes.append(base.parent.resolve() / base.name)
                else:
                    roots.append(base.resolve())
            except (OSError, RuntimeError) as exc:
                raise FrameVerdictsUnavailable(
                    f"mass exclusion {index} path {raw!r} cannot be resolved: {exc}; its "
                    "effective surface is undecidable",
                    remedy=(
                        f"repair filesystem access or symlinks for exclusion path {base}, or "
                        f"amend {MASS_DECLARATION_LOCATION}; " + PRODUCER_REMEDY
                    ),
                ) from exc
    return tuple(roots), tuple(prefixes)


def _producer_working_directory(epoch_dir: Path) -> Path:
    """Use recorded execution context, or the declared vault binding, never dispatch cwd.

    Current producer epochs persist iteration.environment in hypothesis.json, but only
    record python/platform/host. Honour cwd when recorded; older epochs use the working
    directory under the declared vault binding.
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


def _member_skip_dirs(member_id: str, location: object) -> tuple[str, ...]:
    """The declared skipped directory names, or an actionable refusal naming the member.

    ``tuple(location["skip_dirs"])`` accepts anything iterable and raises ``TypeError`` on
    anything else, which left ``skip_dirs: true`` and ``skip_dirs: 42`` crashing the consumer with
    an empty stderr — no diagnostic, no remedy, no refusal receipt (review finding, codex,
    2026-09-07). A string is iterable and would silently become one entry per character, which is
    worse than the crash: it decides quietly. Both refuse here, by name.
    """

    if not isinstance(location, dict):
        return ()
    raw = location.get("skip_dirs")
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(entry, str) or not entry for entry in raw):
        raise UncontainableMemberLocation(
            f"member {member_id!r} location.skip_dirs must be a list of non-empty directory "
            f"names; got {raw!r}"
        )
    return tuple(raw)


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
    tuple[Path, ...],
    tuple[Path, ...],
]:
    """Filesystem and scheme-qualified roots/files plus the member's file patterns."""
    location = member.get("location")
    if not isinstance(location, dict):
        return (), (), (), (), (), (), ()
    reader = member.get("reader")
    reader_id = reader.get("id") if isinstance(reader, dict) else None
    content_query = reader_id == "fs.content_query"
    # The declared reader carries the grammar; the string does not. Every `fs.*` reader in the
    # installed producer takes its declared root as a filesystem path and never partitions on a
    # colon — `fs.glob` (builtin.py:34) and `fs.witness` (:521) via `Path(root_raw).expanduser()`,
    # `fs.content_query` (:1056) via `Path(str(raw_root)).expanduser()` per root, `fs.filelist`
    # (:1272) over `location.roots`. Only `ssh.glob` (:769) partitions, and it *requires* the
    # form: "ssh.glob requires location.path as '<host>:<remote-path>'". `ssh.jsonl_meta` (:642)
    # does not partition either; it reads `location.host` and `location.remote_path` as separate
    # declared fields and refuses without them.
    #
    # Reading a colon as a scheme regardless of reader therefore judged a legal relative
    # directory — `notes:archive` — in a namespace its producer never used. Scoped to the local
    # family by name rather than applied as a general gate: remote and qualified-reference
    # semantics are untouched, and a reader this consumer does not know keeps its existing
    # handling rather than acquiring a new refusal it was never subject to.
    local_filesystem_reader = reader_id in _LOCAL_FILESYSTEM_READERS
    raw_roots: list[str] = []
    if not content_query and isinstance(location.get("path"), str):
        raw_roots.append(str(location["path"]))
    if isinstance(location.get("roots"), list):
        for index, item in enumerate(location["roots"]):
            if not isinstance(item, str):
                raise FrameVerdictsUnavailable(
                    f"member {member.get('id')!r} location.roots[{index}] has unsupported entry "
                    f"{type(item).__name__}: {item!r}; expected a string path or "
                    "scheme-qualified location",
                    remedy=f"repair location.roots[{index}] for member {member.get('id')!r} in "
                    f"{MASS_DECLARATION_LOCATION}: use a string such as '/path/to/root'; "
                    + PRODUCER_REMEDY,
                )
            raw_roots.append(item)
    roots: list[Path] = []
    lexical_roots: list[Path] = []
    qualified_roots: list[QualifiedLocation] = []

    def local_path(raw: str) -> Path:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = _producer_working_directory(epoch_dir) / path
        return path

    for raw in raw_roots:
        if not local_filesystem_reader and _has_qualifier(raw.strip()):
            qualified_roots.append(_qualified_location(raw.strip())[0])
            continue
        # Both filesystem readers preserve whitespace in the declared root name.
        #
        # `expanduser` is a resolution step and can fail on its own terms: with no resolvable
        # home directory it raises RuntimeError, and the message it carries ("Could not
        # determine home directory") reaches a reader as an unhandled traceback rather than as
        # a frame refusal naming the member and a remedy. The resolve below was already
        # converted; the expansion that precedes it was not, so a `~`-relative root failed
        # outside the refusal contract while an absolute one failed inside it.
        # Two distinct faults, kept distinct: `expanduser` fails when no home directory can be
        # resolved, and anchoring a *relative* root fails when the producer's working directory
        # is unavailable. Wrapping both in one message named the wrong cause for half the cases —
        # the same one-message-for-two-conditions shape this file exists to refuse.
        try:
            producer_root = Path(raw).expanduser()
        except (OSError, RuntimeError) as exc:
            raise FrameVerdictsUnavailable(
                f"member {member.get('id')!r} reader {reader_id or 'unknown'} root {raw!r} "
                f"cannot be expanded: {exc}",
                remedy=f"declare an absolute root, or repair home-directory resolution, for "
                f"member {member.get('id')!r} root {raw!r} in {MASS_DECLARATION_LOCATION}; "
                + PRODUCER_REMEDY,
            ) from exc
        try:
            absolute_root = local_path(raw)
        except (OSError, RuntimeError) as exc:
            raise FrameVerdictsUnavailable(
                f"member {member.get('id')!r} reader {reader_id or 'unknown'} root {raw!r} "
                f"cannot be anchored: {exc}",
                remedy=f"declare an absolute root for member {member.get('id')!r} in "
                f"{MASS_DECLARATION_LOCATION}, or repair the producer working directory this "
                f"relative root is resolved against; " + PRODUCER_REMEDY,
            ) from exc
        lexical_roots.append(producer_root)
        try:
            roots.append(absolute_root.resolve())
        except (OSError, RuntimeError) as exc:
            raise FrameVerdictsUnavailable(
                f"member {member.get('id')!r} root {raw!r} cannot be resolved: {exc}",
                remedy=f"repair filesystem access or symlinks for member {member.get('id')!r} "
                f"root {raw!r} in {MASS_DECLARATION_LOCATION}; " + PRODUCER_REMEDY,
            ) from exc
    patterns = location.get("patterns")
    if patterns is not None and not isinstance(patterns, list):
        raise FrameVerdictsUnavailable(
            f"member {member.get('id')!r} location.patterns has malformed container "
            f"{type(patterns).__name__}: {patterns!r}; expected a list of patterns or absence",
            remedy=f"repair location.patterns for member {member.get('id')!r} in "
            f"{MASS_DECLARATION_LOCATION}: use a list such as ['*'], or omit patterns; "
            + PRODUCER_REMEDY,
        )
    globs = tuple(str(item) for item in patterns) if isinstance(patterns, list) else ()
    files_raw = None if content_query else location.get("files")
    files: list[Path] = []
    lexical_files: list[Path] = []
    qualified_files: list[QualifiedLocation] = []
    if isinstance(files_raw, list):
        for item in files_raw:
            if not isinstance(item, str):
                continue
            item = item.strip()
            # The same reader grammar governs `location.files`, not only `location.roots` — a
            # declared file under a local reader is a filesystem path whose name may contain a
            # colon. Gating only the roots loop left this sibling with the original defect, in
            # the same function.
            if not local_filesystem_reader and _has_qualifier(item):
                qualified_files.append(_qualified_location(item)[0])
            else:
                # `location.roots` converts its expansion and resolution failures; this sibling
                # did not, so `~no-such-user/x` raised RuntimeError straight out of the loader —
                # the caller converts only NonCanonicalScopeRef here, so no diagnostic, no remedy
                # and no receipt (review finding, codex, 2026-09-07). Third time in this family
                # tonight, each in the branch next to the one repaired.
                try:
                    lexical_files.append(Path(item).expanduser())
                    files.append(local_path(item).resolve())
                except (OSError, RuntimeError) as exc:
                    raise UncontainableMemberLocation(
                        f"location.files entry {item!r} cannot be resolved: {exc}"
                    ) from exc
    return (
        tuple(roots),
        globs,
        tuple(files),
        tuple(qualified_roots),
        tuple(qualified_files),
        tuple(lexical_roots),
        tuple(lexical_files),
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
    # `frame_procedure_root()` expands `~` itself, so calling it outside this handler left the
    # same RuntimeError escaping as an unhandled traceback that the member-root repair closed —
    # the configured default is `~`-relative, so the ordinary path is the one that escaped.
    # `root` must be bound before the handler can name it: when `frame_procedure_root()` is the
    # thing that raises, referring to `root` in the message would fail with a NameError inside
    # the refusal path and lose the actual cause.
    declared_root = (
        str(procedure_root)
        if procedure_root is not None
        else (
            os.environ.get(FRAME_PROCEDURE_ROOT_ENV, "").strip()
            or str(DEFAULT_FRAME_PROCEDURE_ROOT)
        )
    )
    try:
        root = procedure_root if procedure_root is not None else frame_procedure_root()
        root = root.expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise FrameVerdictsUnavailable(
            f"configured frame procedure root {declared_root} cannot be resolved: {exc}",
            f"repair filesystem access or symlinks for configured frame procedure root "
            f"{declared_root} (check {FRAME_PROCEDURE_ROOT_ENV}), then retry the dispatch",
        ) from exc
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
            exc.remedy.replace(PRODUCER_REMEDY, _producer_remedy(root)),
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
            f"current frame epoch {epoch_dir.name} is {age.total_seconds():.6f} s old, "
            f"older than {max_age_s // 60} min ({max_age_s} s); "
            "the accepted pointer may not have been advanced, or the producer's publication "
            "may have been refused",
            remedy=f"read {root / '_runs/current'}, then the newest retained epoch's publish.json "
            f"under {root / '_runs/epochs'} (swapped and reason fields), then inspect producer "
            "state with `systemctl --user status hapax-frame-iteration.service` before any "
            "restart; distinguish an unadvanced accepted pointer from refused publication, "
            "then retry the dispatch",
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
            (
                roots,
                patterns,
                files,
                qualified_roots,
                qualified_files,
                lexical_roots,
                lexical_files,
            ) = _member_location(member, epoch_dir=epoch_dir)
            host_aliases = _member_host_aliases(member) if reader_id == "ssh.glob" else ()
            # Inside the handler on purpose: raising here without it produced an uncaught
            # exception and an empty stderr, which is the failure this validation exists to end.
            skip_dirs = _member_skip_dirs(member_id, member.get("location") or {})
        except NonCanonicalScopeRef as exc:
            raise FrameVerdictsUnavailable(
                f"member {member_id!r} has an uncontainable scheme-qualified location: {exc}",
                remedy=UncontainableMemberLocation.remedy,
            ) from exc
        location = member.get("location") or {}
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
                    lexical_roots=lexical_roots,
                    lexical_files=lexical_files,
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
            # Repeating a character does not enlarge a class's language: [ss]bin
            # names the same alias as [s]bin. Leave ranges and negation undecidable.
            end = pattern.find("]", index + 2)
            characters = pattern[index + 1 : end] if end != -1 else ""
            if not characters or characters[0] == "!" or len(set(characters)) != 1:
                return None
            literal.append(characters[0])
            index = end + 1
        else:
            literal.append(char)
            index += 1
    return "".join(literal)


def _member_path_is_excluded(path: Path, root: Path, member: DecayedMember) -> bool:
    """Filter an in-root remainder under each spelling of that declared root.

    fs.glob checks producer_root / selected_tail, with no cwd anchoring or resolution.
    The absolute selected path still governs mass exclusions and containment;
    fs.content_query never reads skip_dirs.
    """
    if member.reader == "fs.content_query" or not member.lexical_roots:
        return _path_is_excluded(path, member)
    return all(
        any(part in member.skip_dirs for part in (lexical_root / path.relative_to(root)).parts)
        for canonical_root, lexical_root in zip(member.roots, member.lexical_roots, strict=True)
        if canonical_root == root
    ) or _path_is_mass_excluded(path, member)


def _path_is_excluded(path: Path, member: DecayedMember) -> bool:
    """Filter a producer-selected lexical spelling before resolving mass exclusions."""
    if any(part in member.skip_dirs for part in path.parts):
        return True
    return _path_is_mass_excluded(path, member)


def _path_is_mass_excluded(path: Path, member: DecayedMember) -> bool:
    """Canonical byte targets have mass exclusions, but never lexical skip_dirs."""
    if not member.excluded_roots and not member.excluded_prefixes:
        return False
    path = _resolve_member_path(path)
    if any(path == root or root in path.parents for root in member.excluded_roots):
        return True
    text = str(path)
    return any(text.startswith(str(prefix)) for prefix in member.excluded_prefixes)


def _selected_member_files(member: DecayedMember) -> tuple[Path, ...]:
    """Keep canonical targets selected by at least one declared file spelling."""
    if member.files and member.skip_dirs and not member.lexical_files:
        raise UndecidableScopeContainment(
            f"member {member.member_id!r} has no declared file spellings for skip_dirs"
        )
    return tuple(
        file
        for file, lexical_file in zip(
            member.files, member.lexical_files or member.files, strict=True
        )
        if not any(part in member.skip_dirs for part in lexical_file.parts)
        and not _path_is_mass_excluded(file, member)
    )


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


def _scope_intersects_exclusions(
    path: Path, scope_pattern: str, member: DecayedMember, *, root: Path | None = None
) -> bool:
    excluded = (
        _path_is_excluded(path, member)
        if root is None
        else _member_path_is_excluded(path, root, member)
    )
    if excluded:
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


@dataclass(frozen=True)
class _CanonicalPathForm:
    # Producer-spelled prefix for member forms; original absolute prefix for scope forms.
    lexical_base: Path
    base: Path
    remainder: str | None
    prefix: tuple[str, ...]


def _canonical_path_forms(
    path: Path,
    pattern: str | None,
    *,
    recursive: bool = False,
    producer_root: Path | None = None,
) -> tuple[_CanonicalPathForm, ...]:
    """Canonical existing prefixes plus lexical future tails, for either side of a decision.

    Keep the unexpanded language as well as EVERY existing directory expansion. A missing
    leaf never removes a prefix witness. Strict component resolution precedes directory
    filtering, so broken aliases cannot disappear as empty glob results. ``recursive``
    supplies the content reader's rglob semantics; it does not change resolution.
    ``producer_root`` changes only the retained spelling, never the absolute comparisons.
    """
    lexical_root = path if producer_root is None else producer_root
    if pattern is None:
        return (_CanonicalPathForm(lexical_root, _resolve_external_scope_path(path), None, ()),)
    prefix, tail, _ = _filesystem_scope_parts(pattern)
    bases = [(path.joinpath(*prefix), tail, tuple(prefix))]
    parts = _glob_segments(pattern)
    for length in range(1 if recursive else len(prefix) + 1, len(parts)):
        directory_pattern = "/".join(parts[:length])
        try:
            entries = path.rglob(directory_pattern) if recursive else path.glob(directory_pattern)
            for entry in entries:
                canonical = _resolve_external_scope_path(entry)
                if canonical.is_dir():
                    bases.append((entry, "/".join(parts[length:]), parts[:length]))
        except (OSError, RuntimeError, ValueError) as exc:
            if isinstance(exc, UndecidableScopeContainment):
                raise
            raise UndecidableScopeContainment(
                f"cannot resolve directory prefix {path / directory_pattern}: {exc}; "
                "containment is undecidable"
            ) from exc
    return tuple(
        _CanonicalPathForm(
            lexical_root / base.relative_to(path),
            _resolve_external_scope_path(base),
            remainder,
            consumed,
        )
        for base, remainder, consumed in dict.fromkeys(bases)
    )


def _resolve_scope_directory_prefix(
    path: Path,
    pattern: str,
    *,
    missing_ok: bool = False,
    literal_targets: tuple[Path, ...] = (),
    member_roots: tuple[Path, ...] = (),
) -> tuple[Path, str | None]:
    """Resolve the longest existing globbed directory prefix, retaining future tails.

    The terminal segment may select future files, so an empty complete expansion
    cannot establish disjointness. Multiple lexical directories remain ambiguous
    even when their canonical targets coincide. With ``missing_ok``, in-root future
    directories and recursive expansions without alias crossings remain lexical;
    they supply no new canonical spelling for the containment check.
    """
    forms = _canonical_path_forms(path, pattern)
    parts = _glob_segments(pattern)
    resolved_prefix = None
    for length in range(1, len(parts)):
        directories = [form for form in forms[1:] if len(form.prefix) == length]
        if (
            missing_ok
            and "**" in parts[:length]
            and not any(form.lexical_base != form.base for form in directories)
        ):
            # Ordinary recursive expansion does not canonicalize an alias. Collapsing
            # it to today's directories would erase the future language. An actual
            # alias after ** still supplies an overlap witness for the refusing caller.
            continue
        if len(directories) > 1:
            base = forms[0].base
            if (
                member_roots
                and "**" not in parts
                and all(form.lexical_base == form.base for form in forms)
                and all(
                    root != base
                    and root not in base.parents
                    and (
                        base not in root.parents
                        or _glob_intersects_subtree(
                            forms[0].remainder or "**/*", root.relative_to(base).as_posix()
                        )
                        is False
                    )
                    for root in member_roots
                )
            ):
                # With no alias crossing, an exact lexical proof of root disjointness
                # remains valid for all future tails. Do not narrow to one expansion.
                return base, forms[0].remainder
            raise UndecidableScopeContainment(
                f"scope_containment_undecidable: directory prefix "
                f"{path / '/'.join(parts[:length])} expands to "
                f"{len(directories)} directories; containment is undecidable"
            )
        if directories:
            resolved_prefix = directories[0]
    if resolved_prefix is not None:
        # An earlier branch must not disappear merely because only another branch
        # has deeper existing directories. Check every depth before choosing a prefix.
        remainder = parts[len(resolved_prefix.prefix) :]
        if any(_WILDCARD.search(part) and part != "**" for part in remainder[:-1]):
            raise UndecidableScopeContainment(
                f"scope_containment_undecidable: directory prefix "
                f"{resolved_prefix.base / '/'.join(remainder[:-1])} "
                "expands to no resolvable directory; containment is undecidable"
            )
        tail, scope_pattern, _ = _filesystem_scope_parts("/".join(remainder))
        return _resolve_external_scope_path(resolved_prefix.base.joinpath(*tail)), scope_pattern
    # A recursive future language stays lexical. An unmatched nonrecursive directory
    # glob has no canonical alias witness and cannot establish disjointness.
    if missing_ok and not any(_WILDCARD.search(part) and part != "**" for part in parts[:-1]):
        return forms[0].base, forms[0].remainder
    if len(parts) < 2:
        return forms[0].base, forms[0].remainder
    if literal_targets and all(
        not _glob_to_regex(str(forms[0].base / (forms[0].remainder or ""))).match(str(target))
        for target in literal_targets
    ):
        # A finite set of canonical explicit files admits an exact lexical comparison,
        # including unequal path depths. No unexpanded member glob is assumed empty.
        return forms[0].base, forms[0].remainder
    raise UndecidableScopeContainment(
        f"scope_containment_undecidable: directory prefix {path / parts[0]} "
        "expands to no resolvable directory; containment is undecidable"
    )


def _refuse_in_root_alias_reaching_surface(
    path: Path,
    scope_pattern: str | None,
    member: DecayedMember,
    *,
    root: Path,
    lexical_path: Path,
) -> None:
    """Refuse an in-root candidate whose resolved spelling reaches the member's surface.

    Inside the root the lexical pattern comparison keeps the producer's glob semantics,
    but an alias (symlink, character class, wildcard over an existing directory) can name
    the same future file under a spelling the patterns never select while the leaf does
    not exist and an empty expansion supplies no witness. Ordinary recursive expansion
    supplies no alias witness. Existing witnesses retain their containment/exclusion checks;
    future literals also compare the declaration's canonical pattern prefixes.
    """
    file_patterns = _member_file_patterns(member.patterns)
    if not file_patterns:
        # Directory-only declarations have no future file surface to reach.
        return
    lexical_covered = False
    if scope_pattern is None:
        # Preserve the component-specific refusal and remedy for loops/dangling links.
        canonical_path, canonical_pattern = _canonical_path_forms(path, None)[0].base, None
        if canonical_path.is_file():
            # Existing selected targets are handled by the canonical surface below;
            # they establish containment rather than an ambiguous future overlap.
            return
    else:
        relative = "" if path == root else path.relative_to(root).as_posix()
        lexical_pattern = _scope_pattern_from_base(relative, scope_pattern)
        lexical_covered = any(
            _glob_pattern_covers(pattern, lexical_pattern) for pattern in file_patterns
        )
    try:
        canonical_patterns = _canonical_member_patterns(root, member)
        if lexical_covered:
            _canonical_path_forms(path, scope_pattern)
            # Both sides have been resolved. Keep the producer's lexical skip-dir
            # and symlink traversal checks for an already proven language inclusion.
            return
        if scope_pattern is not None:
            canonical_path, canonical_pattern = _resolve_scope_directory_prefix(
                path, scope_pattern, missing_ok=True
            )
        canonical_patterns = _canonical_member_patterns(
            root, member, scope_path=canonical_path, scope_pattern=canonical_pattern
        )
        if (
            canonical_pattern is None
            and root in canonical_path.parents
            and not _path_is_mass_excluded(canonical_path, member)
            and any(
                _local_member_file_matches(canonical_path, root, pattern)
                for pattern in canonical_patterns
            )
        ):
            # A future candidate can already use the canonical spelling while the
            # declaration traverses an alias. Compare both sides before the no-change exit.
            raise UndecidableScopeContainment(
                f"canonical declaration pattern reaches future member surface at {canonical_path}; "
                "whole-surface containment cannot be decided safely"
            )
        if canonical_path != root and root not in canonical_path.parents:
            return
        canonical_relative = (
            "" if canonical_path == root else canonical_path.relative_to(root).as_posix()
        )
        if canonical_pattern is None:
            return
        covered = _scope_glob_covered(
            _scope_pattern_from_base(canonical_relative, canonical_pattern), canonical_patterns
        )
        if (canonical_path, canonical_pattern) == (path, scope_pattern):
            # The canonical comparison is complete; the caller still checks the
            # producer's exclusions and selected entries before returning containment.
            return
        if covered:
            raise UndecidableScopeContainment(
                f"resolved directory prefix reaches canonical member patterns at {canonical_path}; "
                "whole-surface containment cannot be decided safely"
            )
        if _scope_pattern_from_base(canonical_relative, canonical_pattern) == lexical_pattern:
            return
        # A changed spelling with incomparable remaining globs cannot use a sampled
        # nonmember witness as proof of disjointness. Only distinct literal prefixes
        # establish that the canonical future languages cannot meet.
        candidate_parts = _glob_segments(
            _scope_pattern_from_base(canonical_relative, canonical_pattern)
        )
        for pattern in canonical_patterns:
            for left, right in zip(candidate_parts, _glob_segments(pattern), strict=False):
                if _WILDCARD.search(left) or _WILDCARD.search(right):
                    raise UndecidableScopeContainment(
                        f"canonical candidate remainder {canonical_pattern!r} cannot be compared "
                        f"with member pattern {pattern!r}; containment is undecidable"
                    )
                if left != right:
                    break
            else:
                raise UndecidableScopeContainment(
                    f"canonical candidate at {canonical_path} and member pattern {pattern!r} "
                    "have incomparable future depths; containment is undecidable"
                )
        if ref_within_member(
            canonical_path,
            canonical_pattern is not None or canonical_path.is_dir(),
            member,
            scope_pattern=canonical_pattern,
        ):
            raise UndecidableScopeContainment(
                f"resolved directory prefix reaches member surface at {canonical_path}; "
                "whole-surface containment cannot be decided safely"
            )
    except UndecidableScopeContainment as exc:
        spelled = lexical_path if scope_pattern is None else lexical_path / scope_pattern
        error = UndecidableScopeContainment(
            f"scope_containment_undecidable: candidate {spelled} against member root {root}: "
            f"{exc}; containment is undecidable"
        )
        error.remedy = exc.remedy
        raise error from exc


def _canonical_member_patterns(
    root: Path,
    member: DecayedMember,
    *,
    scope_path: Path | None = None,
    scope_pattern: str | None = None,
) -> tuple[str, ...]:
    """Resolve literal and existing globbed directory prefixes before comparing file languages.

    A directory alias in the declaration selects the same future paths as its target.
    Keep each remainder intact, including the original literal-prefix form: today's
    directory matches add canonical spellings without erasing the future language.
    Each form's lexical_base retains the producer-spelled root and selected prefix.
    Keep the absolute selection separately for mass exclusions and comparisons; the skip
    helper projects its tail onto every producer spelling of this canonical root.
    """
    producer_root = root
    if member.reader != "fs.content_query" and member.lexical_roots:
        producer_root = next(
            lexical_root
            for canonical_root, lexical_root in zip(member.roots, member.lexical_roots, strict=True)
            if canonical_root == root
        )
    patterns = []
    for pattern in _member_file_patterns(member.patterns or ("**/*",)):
        for form in _canonical_path_forms(
            root,
            pattern,
            recursive=member.reader == "fs.content_query",
            producer_root=producer_root,
        ):
            lexical_base, canonical_base = form.lexical_base, form.base
            selected_base = root / lexical_base.relative_to(producer_root)
            if form.remainder is None and canonical_base.is_dir():
                # A literal pattern selecting a directory supplies no file language.
                continue
            if _member_path_is_excluded(selected_base, root, member) or any(
                part in member.skip_dirs for part in _glob_segments(form.remainder or "")
            ):
                continue
            if scope_path is not None and (
                scope_path == canonical_base or canonical_base in scope_path.parents
            ):
                selected = selected_base / scope_path.relative_to(canonical_base)
                if _member_path_is_excluded(selected, root, member) or (
                    scope_pattern is not None
                    and _scope_intersects_exclusions(selected, scope_pattern, member, root=root)
                ):
                    continue
            if canonical_base != root and root not in canonical_base.parents:
                raise UndecidableScopeContainment(
                    f"member pattern component {lexical_base} resolves outside member root {root} "
                    f"to {canonical_base}; containment is undecidable"
                )
            relative = "" if canonical_base == root else canonical_base.relative_to(root).as_posix()
            patterns.append(
                relative
                if form.remainder is None
                else _scope_pattern_from_base(relative, form.remainder)
            )
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
        if (
            _path_is_mass_excluded(selected, member)
            if disjoint
            else _member_path_is_excluded(selected, root, member)
        ):
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
                if entry.is_file() and not _member_path_is_excluded(entry, root, member):
                    surface[entry] = canonical
    return surface


def _canonical_scope_entries(
    path: Path, pattern: str, member: DecayedMember, *, include_directories: bool = False
) -> dict[Path, Path]:
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
            if entry.is_dir() and not include_directories:
                continue
            for root in member.roots:
                if member.reader != "fs.content_query" and root in entry.parents:
                    _check_member_symlinks(entry, root, member, scope_pattern=None)
            target = _resolve_external_scope_path(entry)
            if entry.is_file() or (include_directories and entry.is_dir()):
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
    """A Unicode prefilter followed by builtin.fs_content_query's optional word predicate."""
    try:
        if path.stat().st_size > query.max_unit_bytes:
            raise ValueError(f"exceeds max_unit_bytes={query.max_unit_bytes}")
        with path.open("rb") as stream:
            blob = stream.read(query.max_unit_bytes + 1)
        if len(blob) > query.max_unit_bytes:
            raise ValueError(f"exceeds max_unit_bytes={query.max_unit_bytes}")
        if query.case_insensitive:
            text = blob.decode("utf-8", errors=query.encoding_error_policy)
            # Queries here are ASCII, but rg --ignore-case can select Unicode bytes
            # (long s, Kelvin sign). Python's Unicode matcher also conservatively
            # includes dotted/dotless i, as the producer's own word predicate does.
            # Keep the original text for that predicate's character boundaries.
            if not re.search(re.escape(query.query), text, re.IGNORECASE):
                return False
        elif query.query.encode("utf-8") not in blob:
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
    canonical = _canonical_path_forms(path, None)[0].base
    canonical_pattern = scope_pattern
    if not dirlike and scope_pattern is None and canonical in selected_entries.values():
        # A producer-selected entry is inside even when its alias targets another root.
        return any(
            canonical == target and _content_query_matches(entry, query)
            for entry, target in selected_entries.items()
        )
    if scope_pattern is not None:
        canonical, canonical_pattern = _resolve_scope_directory_prefix(
            path, scope_pattern, missing_ok=True
        )
        # A glob can hide an external alias in a nonliteral segment. Compare its
        # resolved expansions, including directories that can reach selected bytes.
        # Such witnesses prove overlap only, never the glob's whole future surface.
        surface = frozenset(selected_entries.values())
        for entry, target in _canonical_scope_entries(
            path, scope_pattern, member, include_directories=True
        ).items():
            if (
                target in surface
                or any(target in file.parents for file in surface)
                or any(target == root or root in target.parents for root in member.roots)
            ):
                raise UndecidableScopeContainment(
                    f"fs.content_query scope glob {scope_pattern!r} component {entry} "
                    f"resolves to member surface at {target}; whole-surface containment is "
                    "undecidable; declare explicit files so the content predicate can be evaluated"
                )
    if dirlike or scope_pattern is not None:
        for entry, target in selected_entries.items():
            if canonical in target.parents and _pattern_matches(
                target.relative_to(canonical).as_posix(), canonical_pattern or "**/*"
            ):
                raise UndecidableScopeContainment(
                    f"fs.content_query scope component {path} reaches selected target {target} "
                    f"through {entry}; whole-surface containment is undecidable; "
                    "declare explicit files so the content predicate can be evaluated"
                )
    for root in member.roots:
        canonical_patterns = _canonical_member_patterns(root, member)
        if canonical != root and root not in canonical.parents:
            if scope_pattern is not None and canonical in root.parents:
                raise UndecidableScopeContainment(
                    f"fs.content_query scope glob {scope_pattern!r} may enter {root}; "
                    "declare explicit files so the content predicate can be evaluated"
                )
            continue
        if dirlike or scope_pattern is not None:
            raise UndecidableScopeContainment(
                f"fs.content_query scope component {path} needs explicit file paths below {root} "
                "to evaluate the content predicate; whole-surface containment is undecidable"
            )
        if _path_is_mass_excluded(canonical, member) or not member.patterns:
            continue
        relative = canonical.relative_to(root).as_posix()
        for pattern in canonical_patterns:
            # rglob adds recursive selection; canonical patterns omit directory-only **.
            if _pattern_matches(relative, "**/" + pattern) and not canonical.exists():
                # Missing bytes cannot be called outside based on an alias spelling.
                _content_query_matches(canonical, query)
    return False


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


#: Distinct from ``None``: the filesystem refused to answer, rather than answering "absent".
_UNREADABLE = object()


def _file_identity(path: Path) -> tuple[int, int] | None | object:
    """``(device, inode)`` for an existing file, ``None`` when absent, ``_UNREADABLE`` when unknown.

    **A genuinely absent path and a failed stat are different evidence** and are kept apart here.
    Absence is an answer: the file is not there, nothing can be the same as it, and the lexical
    comparison stands — which is what keeps a not-yet-created leaf working. A refusal to answer is
    not an answer, and collapsing the two would let an unreadable comparison count as proof of
    disjointness (review finding, codex, 2026-09-07).
    """

    try:
        status = path.stat()
    except FileNotFoundError:
        return None
    except NotADirectoryError:
        # A component of the path is a file, so nothing exists at this name either.
        return None
    except (OSError, RuntimeError, ValueError):
        return _UNREADABLE
    return status.st_dev, status.st_ino


def _same_existing_file(candidate: Path, declared: Path) -> bool | None:
    """Whether two names are one file: ``True``/``False``, or ``None`` when it cannot be told.

    Callers must treat ``None`` as a refusal, never as ``False``. Admission in this consumer is
    affirmative — it requires disjointness to be *established* — so a comparison that could not be
    made supplies no admission evidence at all.

    ``resolve()`` collapses symlinks, so string comparison already catches those. It cannot see a
    **hard link**: two directory entries pointing at one inode are different strings naming the
    same bytes, and an in-place write through either changes the other (review finding, codex,
    2026-09-07, reproduced on the installed tree with ``gawk`` and ``gawk-5.4.0``).

    Existence is deliberately not the test for anything else. A name that does not exist yet has
    no identity to compare and keeps its lexical treatment, so a scope naming a file the work is
    about to create is unaffected. A stat that fails leaves the lexical answer standing, which is
    the behaviour that was there before this check — it is an additional way to recognise the same
    file, never a way to stop recognising one.

    **What this observation is worth, stated rather than assumed.** It is a reading of the
    filesystem at decision time, so it inherits that reading's limits: a link created after the
    check is not seen, one removed after it is still refused, and nothing here is a guarantee about
    the state at the moment work actually runs. It closes the case where the link already exists
    when the scope is declared, which is the case that was measured. It is not a proof of
    non-aliasing, and it must not be cited as one.
    """

    left = _file_identity(candidate)
    right = _file_identity(declared)
    if left is _UNREADABLE or right is _UNREADABLE:
        return None
    if left is None or right is None:
        return False
    return left == right


def _identity_reaches_surface(candidates: tuple[Path, ...], surface: frozenset[Path]) -> bool:
    """Whether any concrete candidate is the same file as any selected member target.

    Runs after every other refusal has had its say, so a symlink case keeps its own, more careful
    diagnosis — "traversal is unproven" says something different from "this file is that file".
    A comparison that cannot be made raises rather than returning False: this predicate's negative
    answer is used as admission evidence, and an unreadable filesystem is not evidence.
    """

    unreadable: tuple[Path, Path] | None = None
    for candidate in candidates:
        if candidate in surface:
            # Already accounted for by the lexical and canonical comparisons, which decide overlap
            # and partial scope on their own terms. Identity is only asked about a name those rules
            # found nothing for; asking it here would turn "this glob overlaps the surface" into
            # "this glob IS the surface" and refuse every partial scope.
            continue
        for target in surface:
            same = _same_existing_file(candidate, target)
            if same is True:
                return True
            if same is None and unreadable is None:
                unreadable = (candidate, target)
    if unreadable is not None:
        candidate, target = unreadable
        error = UndecidableScopeContainment(
            f"file identity of {candidate} against declared member target {target} cannot be "
            "read; an unreadable comparison is not evidence of disjointness"
        )
        error.remedy = (
            f"repair filesystem access for {candidate} and {target}, then retry the dispatch; "
            "or re-declare the scope as a path whose identity can be compared"
        )
        raise error
    return False


def ref_within_member(
    path: Path,
    dirlike: bool,
    member: DecayedMember,
    *,
    scope_pattern: str | None = None,
) -> bool:
    _member_file_patterns(member.patterns)  # Validate even when the candidate is outside.
    broad = dirlike or scope_pattern is not None
    selected_files = _selected_member_files(member)
    file_path = _resolve_member_path(path) if member.files else path
    if any(file_path == file or _same_existing_file(file_path, file) for file in selected_files):
        if broad:
            _refuse_directory_spelled_file(file_path)
        return True
    if scope_pattern is not None:
        for file in selected_files:
            if file_path in file.parents and _pattern_matches(
                file.relative_to(file_path).as_posix(), scope_pattern
            ):
                # The declared file is concrete; the scope supplies the glob. A matching file
                # proves overlap, but the glob may also name undeclared (even future) files.
                raise UndecidableScopeContainment(
                    f"scope glob {scope_pattern!r} matches declared member file {file}; "
                    "whole-surface containment cannot be decided safely"
                )
        if member.files:
            # Lexical glob matching misses aliases in a nonliteral parent segment.
            # Explicit-file members need canonical witnesses even without any roots.
            try:
                canonical_files = {_resolve_external_scope_path(file) for file in selected_files}
                for entry, target in _canonical_scope_entries(path, scope_pattern, member).items():
                    if target in canonical_files:
                        raise UndecidableScopeContainment(
                            f"scope glob {path / scope_pattern} component {entry} reaches canonical "
                            f"declared member file {target}; "
                            "whole-surface containment cannot be decided safely"
                        )
                canonical_path, canonical_pattern = _resolve_scope_directory_prefix(
                    path, scope_pattern, missing_ok=True, literal_targets=tuple(canonical_files)
                )
                if (canonical_path, canonical_pattern) != (
                    path,
                    scope_pattern,
                ) and ref_within_member(
                    canonical_path,
                    canonical_pattern is not None or canonical_path.is_dir(),
                    member,
                    scope_pattern=canonical_pattern,
                ):
                    raise UndecidableScopeContainment(
                        f"scope glob {path / scope_pattern} reaches canonical declared member file "
                        f"at {canonical_path}; whole-surface containment cannot be decided safely"
                    )
            except UndecidableScopeContainment as exc:
                error = UndecidableScopeContainment(
                    f"scope_containment_undecidable: candidate {path / scope_pattern} "
                    f"against explicit member files: {exc}; containment is undecidable"
                )
                error.remedy = exc.remedy
                raise error from exc
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
        if _content_query_within_member(path, dirlike, member, scope_pattern, selected_entries):
            return True
        # Falling through rather than returning: this reader has its own containment path, and
        # returning from it skipped the identity comparison entirely — so the same hard link that
        # refuses under `fs.glob` was admitted here, and a write through it changes a file the
        # query selected (review finding, codex, 2026-09-07). The query decides its own surface;
        # identity decides whether this name IS one of the files in it.
        # Only files the QUERY selects are the member's surface: an alias to a file whose bytes
        # the predicate rejects is not inside it, and comparing inodes against the unfiltered
        # entry set made one look contained. The predicate decides membership; identity decides
        # only whether this name is one of those files.
        query = member.content_query
        selected = frozenset(
            target
            for entry, target in selected_entries.items()
            if query is not None and _content_query_matches(entry, query)
        )
        if not dirlike and scope_pattern is None:
            return _identity_reaches_surface((_resolve_external_scope_path(path), path), selected)
        if scope_pattern is not None:
            # This reader's glob path compares resolved pathnames and parents, so an EXTERNAL hard
            # link supplied no overlap witness and `outside/[a-a]lias.txt` was admitted while the
            # literal `outside/alias.txt` refused — two spellings of one file, two answers again
            # (review finding, codex, 2026-09-07). An identity hit here is overlap, not whole
            # containment, so it raises the same undecidable refusal the in-root class alias
            # already gets rather than declaring the glob contained.
            aliased = tuple(
                target
                for entry, target in _canonical_scope_entries(
                    path, scope_pattern, member, include_directories=True
                ).items()
                if not entry.is_dir() and target not in selected
            )
            if aliased and _identity_reaches_surface(aliased, selected):
                raise UndecidableScopeContainment(
                    f"scope glob {scope_pattern!r} below {path} reaches a query-selected file "
                    "through a hard link; whole-surface containment cannot be decided safely"
                )
        return False
    surface = frozenset(selected_entries.values())
    expansions = (
        _canonical_scope_entries(path, scope_pattern, member, include_directories=True)
        if scope_pattern is not None
        else {}
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
            if scope_pattern is not None:
                try:
                    canonical_path, canonical_pattern = _resolve_scope_directory_prefix(
                        path, scope_pattern, member_roots=(root,)
                    )
                    if (canonical_path, canonical_pattern) != (path, scope_pattern):
                        if ref_within_member(
                            canonical_path,
                            canonical_pattern is not None or canonical_path.is_dir(),
                            member,
                            scope_pattern=canonical_pattern,
                        ):
                            # The existing prefix reaches the member's future surface.
                            # Its expansion cannot prove containment of every future alias.
                            raise UndecidableScopeContainment(
                                f"resolved directory prefix reaches member surface at "
                                f"{canonical_path}; whole-surface containment cannot be decided safely"
                            )
                except UndecidableScopeContainment as exc:
                    raise UndecidableScopeContainment(
                        f"scope_containment_undecidable: candidate {lexical_path / scope_pattern} "
                        f"against member root {root}: {exc}; containment is undecidable"
                    ) from exc
            if scope_pattern is not None and any(
                target in surface
                or any(target in file.parents for file in surface)
                or (
                    entry.is_dir()
                    and (target == root or root in target.parents or target in root.parents)
                )
                for entry, target in expansions.items()
            ):
                # Directory aliases overlap canonical roots even when no file is selected.
                # Current aliases prove overlap, never containment of future paths.
                raise UndecidableScopeContainment(
                    f"scope glob {scope_pattern!r} reaches canonical member surface in "
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
        if scope_pattern is not None and member.patterns:
            # A glob based at or below the member root can reach its future surface
            # through an alias even when there are no leaf witnesses to compare.
            _refuse_in_root_alias_reaching_surface(
                path, scope_pattern, member, root=root, lexical_path=lexical_path
            )
        relative = "" if path == root else path.relative_to(root).as_posix()
        if (
            not broad
            and member.patterns
            and path != root
            and not any(
                _local_member_file_matches(path, root, pattern) for pattern in member.patterns
            )
        ):
            # A lexical miss is not proof of being outside the patterned surface: an in-root
            # alias resolves to a spelling the patterns DO select. Resolve the existing prefix
            # (future tail kept lexical) before treating the candidate as outside.
            _refuse_in_root_alias_reaching_surface(
                path, scope_pattern, member, root=root, lexical_path=lexical_path
            )
            # The identity comparison that used to sit here is now at the end of this function,
            # where it also reaches candidates outside the root and a glob's expansion.
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
                    _canonical_member_patterns(
                        root,
                        member,
                        scope_path=canonical_base,
                        scope_pattern=scope_pattern or "**/*",
                    ),
                )
            if member.patterns and not (
                canonical_covered or _scope_glob_covered(member_scope_pattern, member.patterns)
            ):
                if any(
                    (
                        target in surface
                        or (entry.is_dir() and ref_within_member(target, True, member))
                    )
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
            if not canonical_covered and _scope_intersects_exclusions(
                path, exclusion_scope_pattern, member, root=root
            ):
                continue
            # Existing files can disprove containment, but cannot establish the proof.
            if any(
                target not in surface for entry, target in expansions.items() if not entry.is_dir()
            ):
                continue
            # Retain the conservative exclusion comparison above. An excluded link target
            # can additionally disprove containment even outside the lexical scope's root.
            if has_excluded_entry:
                continue
            return True
        if has_excluded_entry or _member_path_is_excluded(path, root, member):
            continue
        return True
    # The member's own entries may be aliases, so canonical targets must be considered
    # even when the candidate itself has no symlink components or matching lexical pattern.
    canonical = _resolve_external_scope_path(lexical_path)
    if not broad and canonical in surface:
        return True
    # Identity last, and over every concrete path the scope denotes — the literal candidate, or a
    # glob's expansion, which is how `[a-a]lias.txt` names exactly the alias. Placed here rather
    # than in the root loop: a hard link outside the declared root is still that file, and the
    # earlier placement could only see candidates inside it.
    # An explicit-files member declares no roots, so the canonical-entry surface built from roots
    # is empty for it. Its declared files are the surface, and a class-shaped scope naming a link
    # to one of them was reaching neither set.
    identity_surface = surface | {_resolve_external_scope_path(file) for file in selected_files}
    if not broad:
        return _identity_reaches_surface((canonical, lexical_path), identity_surface)
    # A BROAD scope is different: an identity hit on one expansion entry is overlap, not
    # containment of the whole scope. Returning True here made `bin/gawk*` wholly decayed because
    # one of its files is a link to the selected one, while the same glob's `gawkbug` is
    # independently admitted — a partial scope reported as a total one (review finding, codex,
    # 2026-09-07, on my own round-41 repair). So the aliases join the surface and the existing
    # partial-scope rules decide, which is what they are for.
    aliased = tuple(
        target
        for entry, target in expansions.items()
        if not entry.is_dir() and target not in identity_surface
    )
    if aliased and _identity_reaches_surface(aliased, identity_surface):
        return all(
            target in identity_surface or _identity_reaches_surface((target,), identity_surface)
            for entry, target in expansions.items()
            if not entry.is_dir()
        )
    return False


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
    """Normalize declared host identities only; remote paths and cwd remain unresolved."""
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


def _glob_disjoint(left: str, right: str) -> bool | None:
    """Establish empty intersection; a possible or unsupported intersection stays unknown.

    The product walk retains every ** transition. Segment comparisons prove only literal
    mismatches or incompatible fixed prefixes/suffixes; no sampled witness proves absence.
    """
    a, b = _glob_segments(left), _glob_segments(right)
    pending = [(0, 0)]
    seen = set()
    while pending:
        i, j = pending.pop()
        if (i, j) in seen:
            continue
        seen.add((i, j))
        if i == len(a) and j == len(b):
            return None
        if i < len(a) and a[i] == "**":
            pending.append((i + 1, j))
        if j < len(b) and b[j] == "**":
            pending.append((i, j + 1))
        if i == len(a) or j == len(b):
            continue
        x, y = a[i], b[j]
        if not _WILDCARD.search(x):
            disjoint = not fnmatch.fnmatchcase(x, y)
        elif not _WILDCARD.search(y):
            disjoint = not fnmatch.fnmatchcase(y, x)
        else:
            x_prefix, y_prefix = re.split(r"[*?\[]", x)[0], re.split(r"[*?\[]", y)[0]
            x_suffix, y_suffix = re.split(r"[*?\[\]]", x)[-1], re.split(r"[*?\[\]]", y)[-1]
            disjoint = not (
                (x_prefix.startswith(y_prefix) or y_prefix.startswith(x_prefix))
                and (x_suffix.endswith(y_suffix) or y_suffix.endswith(x_suffix))
            )
        if not disjoint:
            pending.append((i if x == "**" else i + 1, j if y == "**" else j + 1))
    return True


def _form_language(form: _CanonicalPathForm) -> str:
    return str(form.base if form.remainder is None else form.base / form.remainder)


def _local_disjoint_established(
    path: Path, dirlike: bool, scope_pattern: str | None, member: DecayedMember
) -> bool | None:
    """Compare all canonical candidate forms with every producer-spelled selection form."""
    if not member.roots and not member.files:
        return True  # Local and qualified namespaces are distinct.
    if scope_pattern is not None:
        literal = _literal_scope_glob(scope_pattern)
        if literal is not None:
            path = path / literal
            dirlike, scope_pattern = path.is_dir(), None
    candidate_forms = _canonical_path_forms(
        path, scope_pattern if scope_pattern is not None else ("**/*" if dirlike else None)
    )
    for file in _selected_member_files(member):
        target = _resolve_external_scope_path(file)
        for candidate in candidate_forms:
            if _glob_disjoint(_form_language(candidate), str(target)) is not True:
                return None
    content_query = member.reader == "fs.content_query"
    # Concrete selected aliases supplement the future languages; an empty selection
    # never establishes their disjointness. A negative content predicate does establish
    # that a literal file is outside this reader's surface at the accepted comparison.
    for entry, target in _canonical_member_entries(member).items():
        for candidate in candidate_forms:
            if _glob_disjoint(_form_language(candidate), str(target)) is True:
                continue
            if content_query and member.content_query is not None:
                if not _content_query_matches(entry, member.content_query):
                    continue
            return None
    patterns = _member_file_patterns(
        member.patterns if content_query else member.patterns or ("**/*",)
    )
    for root, producer_root in zip(member.roots, member.lexical_roots or member.roots, strict=True):
        # This spelling is wholly skipped, but every other declared spelling still runs.
        if not content_query and any(part in member.skip_dirs for part in producer_root.parts):
            continue
        for pattern in patterns:
            declaration_forms = _canonical_path_forms(
                root,
                "**/" + pattern if content_query else pattern,
                producer_root=producer_root,
            )
            for declaration in declaration_forms:
                selected_base = root / declaration.lexical_base.relative_to(producer_root)
                if declaration.remainder is None and declaration.base.is_dir():
                    continue
                if not content_query and (
                    any(part in member.skip_dirs for part in declaration.lexical_base.parts)
                    or any(
                        not _WILDCARD.search(part) and part in member.skip_dirs
                        for part in _glob_segments(declaration.remainder or "")
                    )
                ):
                    continue
                for candidate in candidate_forms:
                    if (
                        _glob_disjoint(_form_language(candidate), _form_language(declaration))
                        is True
                    ):
                        continue
                    if (
                        candidate.base == declaration.base
                        or declaration.base in candidate.base.parents
                    ):
                        tail = candidate.base.relative_to(declaration.base)
                        selected = selected_base / tail
                        producer_selected = declaration.lexical_base / tail
                        # Exclusion is evidence for THIS producer spelling only. No
                        # canonical candidate skip may discard the other declaration forms.
                        if not content_query and (
                            any(part in member.skip_dirs for part in producer_selected.parts)
                            or any(
                                not _WILDCARD.search(part) and part in member.skip_dirs
                                for part in _glob_segments(candidate.remainder or "")
                            )
                        ):
                            continue
                        if _path_is_mass_excluded(selected, member):
                            continue
                    if (
                        content_query
                        and candidate.remainder is None
                        and member.content_query is not None
                        and not _content_query_matches(candidate.base, member.content_query)
                    ):
                        continue
                    return None
    return True


def _qualified_disjoint_established(
    ref: QualifiedLocation, dirlike: bool, scope_pattern: str | None, member: DecayedMember
) -> bool | None:
    remote = member.reader == "ssh.glob"
    if remote:
        if ref.authority is not None:
            # URI-shaped refs have not established an ssh host identity.
            return None
        ref = _canonical_remote_location(ref, member)
    language = "/".join(ref.parts)
    if dirlike or scope_pattern is not None:
        language = _scope_pattern_from_base(language, scope_pattern)
    patterns = (
        _ssh_glob_patterns(member.patterns)
        if remote
        else _member_file_patterns(member.patterns or ("**/*",))
    )
    for is_root, locations in ((False, member.qualified_files), (True, member.qualified_roots)):
        for location in locations:
            if remote:
                if location.authority is not None:
                    return None
                location = _canonical_remote_location(location, member)
                if (ref.scheme, ref.authority) == (location.scheme, location.authority):
                    # Neither lexical path mismatch nor absolute/relative spelling proves
                    # disjointness without the remote filesystem and working directory.
                    # The decision path cannot consult either: same-host misses refuse.
                    return None
                continue
            if (ref.scheme, ref.authority, ref.absolute_path) != (
                location.scheme,
                location.authority,
                location.absolute_path,
            ):
                continue
            for pattern in patterns if is_root else (None,):
                selected = "/".join(location.parts)
                if pattern is not None:
                    selected = _scope_pattern_from_base(selected, pattern)
                if _glob_disjoint(language, selected) is not True:
                    return None
    return True


def _local_partial_scope_established(
    path: Path,
    dirlike: bool,
    scope_pattern: str | None,
    *members: DecayedMember,
    projections: tuple[Path, ...] = (),
) -> bool:
    """Prove noncontainment with a canonical outside path in a broad scope's language.

    One path outside every decayed member suffices for the partial-scope predicate.
    Per-member witnesses do not compose: resolve the same path against every selection.
    No witness, or an unresolved comparison, supplies no admission evidence.
    """
    if not dirlike and scope_pattern is None:
        return False
    pattern = scope_pattern or "**/*"
    for witness in _glob_witnesses(pattern):
        if not _pattern_matches(witness, pattern):
            continue
        # The same relative tail must work in every equivalent checkout. Independent
        # witnesses per checkout can each land inside another projection's decayed union.
        candidates = tuple(root / witness for root in (path, *projections))
        if any(candidate.is_dir() for candidate in candidates):
            continue
        if all(
            _local_disjoint_established(candidate, False, None, member) is True
            for candidate in candidates
            for member in members
        ):
            return True
    return False


def _scope_admission_established(
    candidates: tuple[Path | QualifiedLocation, ...],
    dirlike: bool,
    scope_pattern: str | None,
    members: tuple[DecayedMember, ...],
) -> bool:
    """Admit only after every candidate spelling is proven outside the decayed union.

    Containment has already run unchanged. Its negative answers alone are not admission
    evidence. Establish disjointness/exclusion or, for a local partial scope, a canonical
    witness outside every decayed member in every equivalent checkout projection.
    Remote paths cannot supply such a witness.
    Unknown means refusal.
    """
    for member in members:
        for candidate in candidates:
            try:
                established = (
                    _qualified_disjoint_established(candidate, dirlike, scope_pattern, member)
                    if isinstance(candidate, QualifiedLocation)
                    else _local_disjoint_established(candidate, dirlike, scope_pattern, member)
                )
                if established is not True and isinstance(candidate, Path):
                    established = _local_partial_scope_established(
                        candidate,
                        dirlike,
                        scope_pattern,
                        *members,
                        projections=tuple(path for path in candidates if isinstance(path, Path)),
                    )
                if established is not True:
                    raise UndecidableScopeContainment(
                        "neither disjointness nor a partial-scope outside witness against "
                        "every producer-selected spelling is established"
                    )
            except (OSError, RuntimeError, ValueError) as exc:
                error = UndecidableScopeContainment(
                    f"scope_containment_undecidable: candidate {candidate}"
                    f"{('/' + scope_pattern) if scope_pattern else ''} against decayed member "
                    f"{member.member_id!r}: {exc}; containment is undecidable"
                )
                if isinstance(exc, NonCanonicalScopeRef):
                    error.remedy = exc.remedy
                raise error from exc
    return True


def _candidate_within_member(
    candidate: Path | QualifiedLocation,
    dirlike: bool,
    member: DecayedMember,
    scope_pattern: str | None,
) -> bool:
    """Containment for one candidate spelling, against a member declared in the same namespace.

    The scope is what is ambiguous; the member is not. A member that declares no location in this
    candidate's namespace cannot contain it, and must not be read with this candidate's grammar
    either: normalising an ``ssh.glob`` member's ``find -name`` patterns as filesystem globs
    refuses a declaration the producer never mis-spelled. Pairing the spelling with the namespace
    the member actually declares is what keeps reading both meanings from becoming a second
    grammar error.
    """
    if isinstance(candidate, QualifiedLocation):
        if not member.qualified_roots and not member.qualified_files:
            return False
        return qualified_ref_within_member(candidate, dirlike, member, scope_pattern=scope_pattern)
    if not member.roots and not member.files:
        return False
    return ref_within_member(candidate, dirlike, member, scope_pattern=scope_pattern)


def _scope_readings(
    text: str,
    verdicts: FrameVerdicts,
    *,
    council_root: Path,
    vault_root: Path,
) -> tuple[
    list[tuple[tuple[Path | QualifiedLocation, ...], bool, str | None]],
    Exception | None,
]:
    """Every meaning a scope reference can carry, because it declares none of its own.

    A member's location is read with the grammar of the reader the member declares. A scope
    reference declares no reader, so a colon-bearing relative one denotes a scheme-qualified
    location *or* a path whose first directory happens to end in a colon, and nothing in the text
    settles which. Both readings are returned, each keeping its **own** dirlike and glob parsing
    and its own checkout projections, and the caller must find the scope outside every one of them
    before admitting it: a scope contained under a meaning the operator may have intended is not
    made disjoint by another meaning under which it is not.

    Returning only the qualified reading was the defect this replaces. Against a local member
    ``_qualified_disjoint_established`` compares against no qualified location at all and returns
    ``True`` — disjointness concluded from an empty comparison, which is the same substitution as
    the local branch's "namespaces are distinct" and lands in the opposite direction.

    There is no unambiguous colon-bearing spelling to carve out. A first revision excepted the
    ``//`` authority form, on the claim that its local reading would need an empty path segment the
    filesystem grammar refuses — it does not: :func:`_filesystem_scope_parts` drops empty segments,
    so ``notes://archive/future.py`` reads as ``notes:/archive/future.py``, a directory whose name
    ends in a colon, which is exactly the case this function exists for. The exception admitted a
    contained scope while both of its equivalent spellings refused, and it was the same defect it
    was carved out of. Both readings are built for every colon-bearing reference.

    A reading whose grammar refuses the spelling outright is returned as the second element rather
    than raised here. It still refuses — a ref that is malformed under any grammar it could be read
    with is unresolved, and unresolved refuses — but it must not pre-empt a refusal from a reading
    that *did* parse, which is the more specific answer. ``podium:**/[d]ead.yaml`` is not a
    filesystem glob, and reporting that instead of the qualified reading's whole-surface
    undecidability would name the wrong repair. This is not the "does not parse, so read it the
    other way" fallback: nothing is admitted on the strength of a failed parse.
    """

    readings: list[tuple[tuple[Path | QualifiedLocation, ...], bool, str | None]] = []
    deferred: Exception | None = None
    if _has_qualifier(text):
        try:
            qualified_ref, qualified_dirlike, qualified_pattern = _qualified_location(
                text, scope_ref=True
            )
        except (NonCanonicalScopeRef, UndecidableScopeContainment) as exc:
            deferred = exc
        else:
            readings.append(((qualified_ref,), qualified_dirlike, qualified_pattern))
    try:
        path, dirlike = resolve_scope_ref(text, council_root=council_root, vault_root=vault_root)
        _, scope_pattern, _ = _filesystem_scope_parts(text)
        candidates: tuple[Path | QualifiedLocation, ...] = (
            path,
            *_repo_relative_candidates(text, verdicts, council_root=council_root),
        )
    except (NonCanonicalScopeRef, UndecidableScopeContainment) as exc:
        deferred = deferred or exc
    else:
        readings.append((candidates, dirlike, scope_pattern))
    return readings, deferred


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
    # One ref's unresolved comparison is not the whole scope's answer. A declared scope can carry
    # several refs, and `all_inside` is false as soon as any ONE of them is provably outside — so
    # raising at the first undecidable ref discarded an outside witness that had already settled
    # the question, and two spellings of the same path disagreed because one of them happened to
    # be undecidable (review finding, codex, 2026-09-07). Deferred, and raised only if nothing
    # else settles it. **Only valid-but-undecidable containment defers**: a malformed reference, an
    # uncontainable declaration or an evidence fault is a fact about the whole request and still
    # raises where it occurs.
    deferred: UndecidableScopeContainment | None = None
    for ref in declared_refs:
        text = str(ref).strip()
        try:
            readings, unreadable = _scope_readings(
                text, verdicts, council_root=council_root, vault_root=vault_root
            )
            hit = next(
                (
                    member
                    for candidates, dirlike, scope_pattern in readings
                    for member in verdicts.decayed
                    for candidate in candidates
                    if _candidate_within_member(candidate, dirlike, member, scope_pattern)
                ),
                None,
            )
            if hit is None:
                for candidates, dirlike, scope_pattern in readings:
                    if (
                        _scope_admission_established(
                            candidates, dirlike, scope_pattern, verdicts.decayed
                        )
                        is not True
                    ):
                        raise UndecidableScopeContainment(
                            f"scope_containment_undecidable: admission not established for {ref}"
                        )
                # Nothing that parsed refuses this ref, so a spelling no grammar accepts is now
                # the whole answer and is raised on its own terms.
                if unreadable is not None:
                    raise unreadable
                outside.append(str(ref))
            else:
                matches.append(ScopeMatch(str(ref), hit.member_id, hit.relation))
        except UndecidableScopeContainment as exc:
            if deferred is None:
                deferred = exc
    if deferred is not None and not outside:
        raise deferred
    declared = bool(matches or outside)
    return ScopeVerdict(
        all_inside=declared and not outside,
        matches=tuple(matches),
        outside=tuple(outside),
    )
