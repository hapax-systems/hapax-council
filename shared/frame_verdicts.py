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
import errno
import fnmatch
import hashlib
import json
import os
import pathlib as pathlib_module
import re
import stat as stat_module
import subprocess
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

import yaml

FRAME_PROCEDURE_ROOT_ENV = "HAPAX_FRAME_PROCEDURE_ROOT"
DEFAULT_FRAME_PROCEDURE_ROOT = Path("~/Documents/Personal/30-areas/hapax/frame/procedure")
FRAME_VAULT_ROOT_ENV = "HAPAX_FRAME_VAULT_ROOT"
DEFAULT_FRAME_VAULT_ROOT = Path("~/Documents/Personal")

# TOMBSTONE, not documentation of anything below. A ``FRAME_ITERATION_CADENCE_S = 3 * 3600``
# constant stood here until 2026-09-07, already annotated as historical with no runtime consumer.
# The annotation was not enough: a name that reads as the producer's cadence invites the next
# editor to re-derive the allowance below from it, which is the coupling deliberately removed.
# Deleted rather than renamed — nothing in the tree referenced it, and a comment is a weaker
# guard than an absent symbol.
#
# Written with `#:` until 2026-09-08, which made it the first five lines of the LIVE constant's
# doc-comment: a reader of `FRAME_EPOCH_MAX_AGE_S` was told first about a different, deleted
# symbol (review finding, claude, at `069e726dc`). A tombstone for a removed name and the
# documentation of a present one are not the same text and no longer share a block.

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
#: For the refusals that have no resolved procedure root in hand. It must not pretend to have one:
#: formatting the template with the env-var NAME rendered "verify it targets procedure root
#: HAPAX_FRAME_PROCEDURE_ROOT", which reads as a path and is a variable name, so the next action
#: named an undefined subject (review finding, glm). `_producer_remedy` below is the call-time
#: twin and takes a real Path; this one says which variable to consult and what it defaults to,
#: which is the most a message written before the read can honestly say.
PRODUCER_REMEDY = PRODUCER_REMEDY_TEMPLATE.format(
    procedure_root=f"${FRAME_PROCEDURE_ROOT_ENV} (default {DEFAULT_FRAME_PROCEDURE_ROOT})"
)


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


class DuplicateGoverningKey(ValueError):
    """A governing document repeated a key, so its own text does not say what it means."""


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: set[str] = set()
    for key, _value in pairs:
        if key in seen:
            raise DuplicateGoverningKey(f"duplicate key {key!r}")
        seen.add(key)
    return dict(pairs)


def _strict_json(text: str) -> object:
    """`json.loads` that REFUSES a repeated key instead of keeping the last one.

    **Last-wins is silent, and the last value is not the safe one.** A decay row carrying
    `"verdict": "TRUE", "verdict": "FALSE"` parses to FALSE, so a scope that was refused at exit
    10 becomes eligible at exit 0 — and nothing downstream can catch it, because the ambiguity is
    gone before the matrix ever sees the document (review finding, codex, at `614dc6581`,
    reproduced through `main()` with in-memory inputs).

    `object_pairs_hook` is the only place the duplicate is still visible: it receives the pairs in
    document order, at every nesting depth, before any dict is built.
    """

    return json.loads(text, object_pairs_hook=_reject_duplicate_pairs)


class _StrictYAMLLoader(yaml.SafeLoader):
    """`yaml.safe_load` with the same refusal. The PRODUCER already rejects duplicates here."""


def _strict_yaml_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False):  # noqa: ANN201, FBT002
    seen: set[object] = set()
    for key_node, _value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in seen
        except TypeError:
            # A YAML complex key — `? [a, b]` or `? {a: b}` — is UNHASHABLE, and set membership
            # raises `TypeError` on it. That pre-empted `SafeLoader.construct_mapping`, which
            # refuses the same document with `ConstructorError` ("found unhashable key"): the
            # refusal boundary catches `yaml.YAMLError`, so a bare TypeError escaped it with no
            # refusal, remedy or receipt (review finding, codex, at `41be64bde`).
            #
            # **Duplicate detection is not this key's question.** SafeLoader already answers it,
            # correctly and actionably, so the guard steps aside rather than answering first and
            # wrongly. Stepping aside is also why this cannot mask a duplicate: an unhashable key
            # never reaches a mapping at all.
            continue
        if duplicate:
            raise DuplicateGoverningKey(f"duplicate key {key!r}")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_StrictYAMLLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    lambda loader, node: _strict_yaml_mapping(loader, node),
)


def _strict_yaml(text: str) -> object:
    """`yaml.load` here is NOT `yaml.unsafe_load` and does not widen the constructor table.

    `_StrictYAMLLoader` subclasses `yaml.SafeLoader` and overrides exactly one constructor — the
    default mapping — to refuse a duplicate key before delegating to `SafeLoader`'s own. Every
    other tag, including `!!python/object`, is resolved by `SafeLoader` and refused by it. So the
    reachable value domain is identical to `yaml.safe_load`'s.

    **What would make that false**: rebasing this loader on `yaml.Loader` or `yaml.UnsafeLoader`,
    or adding a constructor for a non-standard tag. Neither is done here, and the assertion below
    fails loudly rather than silently if the first ever happens.
    """

    assert issubclass(_StrictYAMLLoader, yaml.SafeLoader), (
        "the strict loader must stay a SafeLoader subclass; anything else widens the value domain"
    )
    return yaml.load(text, Loader=_StrictYAMLLoader)  # noqa: S506


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


_JSON_LEAF_TYPES = (str, int, float, bool, type(None))


def _emittable(key: object) -> str:
    """A path segment safe to put in a refusal that must itself be written out.

    **The diagnostic for an unencodable value has to be encodable.** A surrogate used as a mapping
    KEY was interpolated raw into the path label, so the refusal naming it could not be written to
    stderr or into a receipt — reproducing, at the moment of reporting, the exact failure it was
    reporting. `repr` escapes it to ASCII; ordinary keys keep their plain spelling so normal paths
    stay readable.
    """
    text = str(key)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return repr(text)
    return text


def _unencodable_declaration_paths(value: object, prefix: str, seen: set[int]) -> list[str]:
    """Dotted paths to values `json.dumps` cannot encode, so a refusal can name what to quote.

    Recursive because the offending scalar is usually not a top-level member field: a date under
    `location`, inside a window list, or in `exclusions` all reported "<not in a top-level member
    field>" and named nothing the operator could act on (review finding, root).

    **Guarded against cycles by identity**, because the inputs this describes include
    `metadata: &loop [*loop]` — a walker that recursed forever on the very document it exists to
    diagnose would replace one unhelpful failure with a worse one.
    """
    if id(value) in seen:
        return [f"{prefix or '<member>'} (cycle)"]
    if isinstance(value, str):
        # A `str` is a JSON leaf and still need not survive `encode("utf-8")`: a lone surrogate
        # passes `json.dumps(ensure_ascii=False)` and fails at the encode. Checked here so the
        # refusal can name WHICH field, which is the whole reason this walker exists.
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return [f"{prefix or '<member>'}={value!r} (not encodable as UTF-8)"]
        return []
    if isinstance(value, _JSON_LEAF_TYPES):
        return []
    seen = seen | {id(value)}
    if isinstance(value, dict):
        found: list[str] = []
        for key, item in value.items():
            label = f"{prefix}.{_emittable(key)}" if prefix else _emittable(key)
            if not isinstance(key, (str, int, float, bool, type(None))):
                found.append(f"{label} (key of type {type(key).__name__})")
            found.extend(_unencodable_declaration_paths(key, f"{label} (key)", seen))
            found.extend(_unencodable_declaration_paths(item, label, seen))
        return found
    if isinstance(value, (list, tuple)):
        return [
            path
            for index, item in enumerate(value)
            for path in _unencodable_declaration_paths(item, f"{prefix}[{index}]", seen)
        ]
    return [f"{prefix or '<member>'}={value!r} ({type(value).__name__})"]


def _member_declaration_identity(member: dict[str, object], exclusions: object) -> str:
    """The producer's per-member declaration identity, recomputed by its own rule.

    `frame/procedure/declaration.py::_member_declaration_identities`. Copied rather than imported
    because the producer lives in another tree. The literal producer fixture pins compatibility
    even without the vault; the real-epoch test additionally checks the installed producer.
    """
    try:
        # **The encode belongs INSIDE this handler and was left outside it.** A lone surrogate
        # passes `json.dumps(ensure_ascii=False)` and raises `UnicodeEncodeError` at the encode —
        # which is a `ValueError`, so the arm below would have caught it had the call been in
        # scope. Guarding the dumps and leaving the very next operation unguarded is the same
        # neighbourhood mistake as the comprehension guard earlier: the fix was correct and its
        # boundary was drawn one line too high (review finding, codex, at `8241e4dcf`).
        canonical = json.dumps(
            {"member": member, "exclusions": exclusions},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        # **A YAML scalar the producer never quoted is a declaration defect, not a crash.**
        # `declared: 2026-09-08` unquoted is a `datetime.date` through SafeLoader, and this
        # canonicalisation then raised `TypeError: Object of type date is not JSON serializable`
        # — outside the parsing handler, and the dispatcher catches only FrameVerdictsUnavailable,
        # so it escaped with no refusal, no remedy and no receipt (review finding, codex, at
        # `d1d7a8204`). Same class as the unhashable-key escape repaired at `cf45a21d3`: a value
        # the loader accepts and a later stage cannot govern.
        #
        # **Coercing it is not available.** This identity is copied from the producer's own rule
        # and the fixture pins byte compatibility, so serialising the date with `default=str`
        # would compute a hash the producer does not, and the two trees would silently disagree
        # about which declaration this is. Refusing is the only answer that keeps them equal.
        offending = sorted(
            _unencodable_declaration_paths(member, "", set())
            + _unencodable_declaration_paths(exclusions, "exclusions", set())
        )
        cyclic = any(path.endswith("(cycle)") for path in offending)
        # **A cycle and an unquoted scalar are different repairs and must not share a remedy.**
        # `metadata: &loop [*loop]` is accepted by SafeLoader and raises ValueError at
        # canonicalisation; telling its author to quote something would send them looking for a
        # scalar that is not the problem. The anchor has to go (root, at `9c60d1cde`, who also
        # established this class is pre-existing rather than introduced by the date refusal).
        unencodable = any(path.endswith("(not encodable as UTF-8)") for path in offending)
        # **Three causes reach this handler and each wants a different sentence.** Telling the
        # author of a lone surrogate to quote a value sends them to add quotes around a string
        # that is already one; telling the author of a cycle to quote something is worse still.
        if cyclic:
            repair = "remove the self-referencing anchor/alias so the declaration is a finite tree"
        elif unencodable:
            repair = (
                "replace the character that is not encodable as UTF-8 — a lone surrogate such as "
                "`\\udcff` survives YAML and JSON and fails only at the digest"
            )
        else:
            repair = (
                "quote the affected value so it stays a string (for example "
                "`declared: '2026-09-08'`)"
            )
        raise FrameVerdictsUnavailable(
            f"member {member.get('id')!r} declaration cannot be canonicalised: {exc}; "
            f"at: {', '.join(offending) or '<no unencodable value located>'}",
            remedy=f"{repair} in {MASS_DECLARATION_LOCATION} for member "
            f"{member.get('id')!r}, then retry the dispatch; " + PRODUCER_REMEDY,
        ) from exc
    return "declaration:" + hashlib.sha256(canonical).hexdigest()


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
    # `exists()` answers "no" for a path it cannot read as well as for one that is not there, and
    # raises for the failures it cannot answer at all — so the three states this guard must keep
    # apart, **missing / unreadable / malformed**, were collapsing into the first or escaping as a
    # bare PermissionError (root's fault check, 2026-09-07: five sites, all reaching `Path.stat`).
    try:
        published = current.exists() or current.is_symlink()
    except (OSError, RuntimeError) as exc:
        raise FrameVerdictsUnavailable(
            f"published frame pointer {current} cannot be inspected: {exc}",
            remedy=_producer_remedy(procedure_root),
        ) from exc
    if not published:
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
    try:
        resolves_to_epoch = epoch_dir.is_dir() and epoch_dir.parent == epochs
    except (OSError, RuntimeError) as exc:
        raise FrameVerdictsUnavailable(
            f"published frame epoch {epoch_dir} cannot be inspected: {exc}",
            remedy=_producer_remedy(procedure_root),
        ) from exc
    if not resolves_to_epoch:
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
    try:
        publish_present = publish_path.is_file()
    except (OSError, RuntimeError) as exc:
        raise FrameVerdictsUnavailable(
            f"{publish_path} cannot be inspected: {exc}",
            remedy=_producer_remedy(procedure_root),
        ) from exc
    if not publish_present:
        raise FrameVerdictsUnavailable(
            f"current epoch {epoch_dir.name} publish.json is missing",
            remedy=_producer_remedy(procedure_root),
        )
    try:
        # Decides whether the epoch was accepted for publication at all: `swapped is not True`
        # refuses below. A repeated `"swapped": false, "swapped": true` would admit an epoch the
        # producer rejected, which is the most direct of the seven.
        receipt = _strict_json(publish_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateGoverningKey) as exc:
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
            _refuse_unrepresentable_path(
                raw,
                subject=f"mass exclusion {index} path",
                repair=f"repair the path of mass exclusion {index}",
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
        # **UNREADABLE IS NOT ABSENT, and here the difference redirects a root.** `Path.exists`
        # swallows the ignorable errnos and answers False, so a hypothesis file that is present
        # but cannot be read — a symlink loop, a bad descriptor — took the same branch as one
        # that was never written, and this function silently substituted the declared vault base
        # for the producer's own recorded working directory. Every member location below is then
        # resolved against a root the producer never used, with no refusal and no evidence
        # binding (review findings, gemini, glm and codex, at `f9836f8ec`, three families on one
        # site).
        #
        # `_classified_exists` keeps the decided negatives — ENOENT and ENOTDIR still fall
        # through to the vault base, because "nothing is there" really is an answer — and lets
        # everything else raise into the handler below, which already carries the remedy. A
        # DANGLING symlink stays on the absent side: `stat` reports ENOENT for it, and treating
        # a decided-absent target as unknown would be widening past what was reported.
        if _classified_exists(hypothesis):
            # Decides the producer working directory every member location resolves against — the
            # same value whose unreadability redirected a root two commits ago.
            payload = _strict_json(hypothesis.read_text(encoding="utf-8"))
            environment = payload.get("iteration", {}).get("environment", {})
            if "cwd" in environment:
                raw = environment["cwd"]
                if isinstance(raw, str) and raw and Path(raw).is_absolute():
                    return Path(raw).resolve()
                raise ValueError("recorded cwd must be a non-empty absolute path")
        vault = frame_vault_root().expanduser()
        base = vault / "30-areas/hapax"
        # Same reading of the same method at the fallback: an unreadable vault base answered
        # False and became the generic "no available declared vault base" refusal at the bottom,
        # which names neither the base nor the fault. Unsuppressed, it raises into the handler
        # and the refusal says which component could not be read. A base that genuinely is not
        # there still answers False and still reaches the generic refusal, which is correct —
        # that one really is an absence.
        if vault.is_absolute() and _classified_is_dir(base):
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


def _refuse_unrepresentable_declaration(raw: str, member: Mapping[str, Any], field: str) -> None:
    """Refuse a declared path the filesystem cannot represent, BEFORE resolving it.

    A NUL cannot appear in a POSIX path, and `Path.resolve()` answers that with a `ValueError`
    ("embedded null character") — a third exception type, which every handler in this module
    catches `OSError` and `RuntimeError` for and none catches. So a declared root or file
    containing a NUL exited the dispatcher as a traceback rather than as the documented refusal,
    remedy and receipt (review finding, at `b420f26c9`, reproduced through the epoch parser for
    both `location.roots` and `location.files`).

    Validated up front rather than caught downstream, because the refusal can then name the
    field and the member instead of a resolution failure three layers away — and because a
    spelling the filesystem cannot represent is a fact about the DECLARATION, not about this
    host's access to it.

    It is also the third exception type in a family this module keeps meeting one type at a
    time: `OSError` for access, `RuntimeError` for expansion and loops, `ValueError` for
    unrepresentable spellings.
    """
    _refuse_unrepresentable_path(
        raw,
        subject=f"member {member.get('id')!r} {field} entry",
        repair=f"repair {field} for member {member.get('id')!r}",
    )


def _refuse_unrepresentable_path(raw: str, *, subject: str, repair: str) -> None:
    """The NUL check itself, phrased by whichever declaration site is asking.

    Split out because the reasoning above is about the declaration, not about members: a mass
    EXCLUSION path is not a member field and had no such guard, so its `base.resolve()` raised
    the same `ValueError` past a handler catching only `OSError` and `RuntimeError` and left the
    dispatcher without its refusal, remedy or receipt (review finding, codex, at `f74f36cf6`).

    That the docstring above already names ValueError as the third type in this family, while a
    second site in the same file still met it uncaught, is the point worth keeping: naming a
    family is not the same as having swept it.
    """
    if "\x00" in raw:
        raise FrameVerdictsUnavailable(
            f"{subject} {raw!r} contains a NUL, which no filesystem path can represent",
            remedy=(f"{repair} in {MASS_DECLARATION_LOCATION}; " + PRODUCER_REMEDY),
        )


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
        _refuse_unrepresentable_declaration(raw, member, "location.roots")
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
    if isinstance(patterns, list):
        # The container was checked and its ENTRIES were not, so `str(item)` spelled a selector
        # out of `None`, an integer or a mapping while the installed producer raises on the
        # original entry — the consumer then establishes a DIFFERENT surface, not a comparable
        # one (review finding, codex, at `842ca5937`). Twenty lines below, `location.files`
        # already type-checks its entries: the same question, asked at one of the two sites.
        #
        # The INDEX is named because a five-pattern list with one bad entry is not repairable
        # from a message that identifies only the member.
        for index, item in enumerate(patterns):
            if not isinstance(item, str):
                raise FrameVerdictsUnavailable(
                    f"member {member.get('id')!r} location.patterns has malformed entry at "
                    f"index {index}: {type(item).__name__} {item!r}; expected a pattern string",
                    remedy=f"repair location.patterns index {index} for member "
                    f"{member.get('id')!r} in {MASS_DECLARATION_LOCATION}: use a string such as "
                    "'*', or remove the entry; " + PRODUCER_REMEDY,
                )
    globs = tuple(patterns) if isinstance(patterns, list) else ()
    files_raw = None if content_query else location.get("files")
    files: list[Path] = []
    lexical_files: list[Path] = []
    qualified_files: list[QualifiedLocation] = []
    if isinstance(files_raw, list):
        for item in files_raw:
            if not isinstance(item, str):
                continue
            # No-trim rule, stated at _filesystem_scope_parts. Only a genuinely empty
            # declaration is skipped: "" cannot name a file, while " " can.
            if not item:
                continue
            _refuse_unrepresentable_declaration(item, member, "location.files")
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
        # The declaration profile whose digest is compared against the epoch's. The PRODUCER
        # already rejects duplicates here, so accepting them on the consumer side let the two
        # sides disagree about what the same bytes say. The handler below already catches
        # `ValueError`, which `DuplicateGoverningKey` is, so no clause needs widening.
        profile = _strict_yaml((procedure_root / "declaration/params.yaml").read_text("utf-8"))
        hypothesis = epoch_dir / "hypothesis.json"
        # **The SECOND site of the same suppression, and the one codex's wording pointed at.**
        # gemini and glm wrote "bypasses evidence binding" and codex wrote "bypasses PROFILE
        # binding" — different halves, and I read the report as naming one line. Here a
        # suppressed `exists()` skips the `parameter_profile_digest` comparison entirely, so an
        # unreadable hypothesis does not merely lose a recorded value: it silently drops the
        # check that the epoch was produced under the profile being read.
        #
        # Found by a two-match replacement failing, not by reading the report carefully enough.
        # The rule is the one this file keeps relearning: repair the site a finding cites and the
        # neighbours keep the defect.
        if _classified_exists(hypothesis):
            # Supplies the `parameter_profile_digest` compared against the declaration's. A
            # duplicate here chooses which digest the comparison sees.
            recorded = _strict_json(hypothesis.read_text("utf-8")).get("iteration", {})
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
        # This `try` catches `FrameVerdictsUnavailable` only, so an OSError from the very first
        # observation went straight past the refusal contract — a converting raise elsewhere in a
        # handler proves nothing about an exception that handler does not catch, which is also the
        # unsoundness that made my static enumeration claim this path was covered.
        try:
            root_present = root.is_dir()
        except (OSError, RuntimeError) as exc:
            raise FrameVerdictsUnavailable(
                f"frame procedure root {root} cannot be inspected: {exc}",
                remedy=f"repair filesystem access for {root} (check {FRAME_PROCEDURE_ROOT_ENV}), "
                "then retry the dispatch",
            ) from exc
        if not root_present:
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
    if age < timedelta(0):
        # **The age limit was one-sided, so being impossibly fresh passed it.** A negative age is
        # not greater than any positive bound, so an epoch stamped after `now` was accepted
        # however far ahead it was dated — measured here at a year (review finding, codex,
        # 2026-09-07). The bound exists to say the accepted pointer is keeping up with the
        # producer; an epoch from the future says the two clocks disagree, which establishes
        # nothing about that and is not a weaker version of freshness.
        #
        # No skew tolerance is invented here: any constant would be a number nothing measured.
        # This estate has produced future-dated stamps by hand more than once, so the refusal is
        # also the only thing that would make the next one visible.
        raise FrameVerdictsUnavailable(
            f"current frame epoch {epoch_dir.name} is dated "
            f"{-age.total_seconds():.6f} s in the future of the reading clock "
            f"({current.isoformat()}); an epoch cannot be newer than the moment it is read, so "
            "its age against the evidence allowance cannot be evaluated",
            remedy=(
                f"compare the producer's clock with this reader's, then read {root / '_runs/current'} "
                f"and the epoch's publish.json under {root / '_runs/epochs'} to see which run "
                "stamped it; re-run the frame producer once the two clocks agree, and do not "
                "hand-edit the epoch name"
            ),
        )
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
        # The verdicts themselves. A repeated `verdict` key here is the whole finding: last-wins
        # turns a TRUE decay into FALSE, and a refused scope into an eligible one.
        elements = _strict_json(elements_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateGoverningKey) as exc:
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
        # The members the verdicts are ABOUT. A duplicate here re-points a verdict at a different
        # declared surface, which is the same admission flip by another route.
        mass = _strict_yaml(mass_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, DuplicateGoverningKey) as exc:
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
    try:
        coverage_present = coverage_path.is_file()
    except (OSError, RuntimeError) as exc:
        raise FrameVerdictsUnavailable(
            f"{coverage_path} cannot be inspected: {exc}; the verdicts cannot be bound to the "
            "declaration they were computed against"
        ) from exc
    if not coverage_present:
        raise FrameVerdictsUnavailable(
            f"{coverage_path} is missing; the verdicts cannot be bound to the declaration they "
            "were computed against"
        )
    epoch_identities: dict[str, str] = {}
    try:
        # What binds the verdicts to the declaration they were computed against. A duplicate here
        # rebinds that association silently.
        coverage_rows = _strict_json(coverage_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateGoverningKey) as exc:
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
        # **Validate the TYPE before the membership test.** `reader_id` comes straight from YAML,
        # and set membership raises on an unhashable value: `id: [fs.glob]` and `id: {id: fs.glob}`
        # raised `TypeError` before any refusal could be built, escaping both the loader's handler
        # and `frame_verdict_refusal` — dispatch terminated with no next action and no refusal
        # receipt (review finding, codex, at `f08b2f955`).
        #
        # The type check also catches a case that did NOT crash and was worse for it: `id: 7` is
        # hashable, so it reached the membership test and was reported as an *unimplemented
        # reader* — sending the operator to implement containment for `7` rather than to fix a
        # malformed declaration. A non-string reader id is a declaration defect either way.
        #
        # Third instance of this class in this file. The sibling test at `location.match` is safe
        # only because it coerces with `str(mode)` first; coercing HERE would turn `[fs.glob]`
        # into the string `"['fs.glob']"` and report it as unimplemented, which is the same wrong
        # diagnostic by another route.
        if not isinstance(reader_id, str):
            raise FrameVerdictsUnavailable(
                f"member {member_id!r} declares a non-string reader id: "
                f"{reader_id!r} ({type(reader_id).__name__})",
                remedy=f"declare reader.id as a string for member {member_id!r} in "
                f"{MASS_DECLARATION_LOCATION} — one of 'fs.glob', 'ssh.glob' or "
                "'fs.content_query' — then retry the dispatch; " + PRODUCER_REMEDY,
            )
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
    """Split a pathlib-normalised filesystem ref into its literal prefix and glob tail.

    THE NO-TRIM RULE, stated here once and referenced from the other four sites that take a
    declared subject (`:1243`, `:2870`, `:3369`, and `location.files` in `_member_location`):

    **A declared path is never trimmed.** Leading and trailing whitespace are part of a POSIX
    filename, so trimming changes the subject the operator declared — which is the obligation
    `FRAME-SCOPE-SPELLING-DISPOSITION-20260907.md` names: the same subject through scope
    parsing, member declaration, RouteMetadata, DemandVector and the source path and digest, or
    a refusal by name.

    Both sides used to trim, so a member declaring `"…/zz-review-future "` and a ref naming it
    matched *because two errors cancelled*, while the glob spelling `…future[ ]` was admitted
    against a decayed member (gemini and codex at `63bf526e4`). Repairing one side alone breaks
    the cancellation and turns a refusing case into an admitting one — measured, which is why
    this lands on every site at once rather than on the one the finding pointed at.

    Blank-skipping is a different question and stays with the callers: `""` cannot name a file,
    while `" "` can. Backslash spelling is separately held and is untouched here.
    """
    text = ref.replace("\\", "/")
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
    text = ref.replace("\\", "/")  # no-trim rule, stated at _filesystem_scope_parts
    segments, scope_pattern, dirlike = _filesystem_scope_parts(ref)
    absolute = text.startswith("/")
    dirlike = dirlike or scope_pattern is not None
    joined = ("/" if absolute else "") + "/".join(segments)
    # `expanduser` is a resolution step and fails on its own terms: with no resolvable home
    # directory it raises RuntimeError, which reached the caller as an unhandled traceback rather
    # than as a refusal naming the ref and a remedy (review finding, codex, at `069e726dc`). The
    # `is_dir` block below was already inside the contract; the expansion that precedes it was
    # not, so a `~`-relative SCOPE ref failed outside the refusal contract while an absolute one
    # failed inside it — the same gap the member-roots loop closed at `_member_location`, left in
    # its sibling. Kept as its own cause and remedy rather than folded into
    # `_unresolved_scope_component`: a missing home directory is repaired differently from an
    # unresolved component, and one message for two conditions names the wrong one for half.
    try:
        path = Path(joined).expanduser() if joined else Path(".")
    except (OSError, RuntimeError) as exc:
        error = UndecidableScopeContainment(
            f"cannot expand scope ref {ref!r}: {exc}; containment is undecidable"
        )
        error.remedy = (
            f"declare {ref!r} as an absolute path in mutation_scope_refs, or repair "
            "home-directory resolution, then retry the dispatch"
        )
        raise error from exc
    if not path.is_absolute():
        # The base is the checkout whose tree already holds the ref's first segment: a ref names
        # a file that may not exist yet (the work is about to create it), so the decision is made
        # on the nearest ancestor, never on the leaf.
        first = Path(segments[0]) if segments else Path(".")
        # `exists()` and `is_symlink()` are filesystem questions and fail on their own terms — a
        # permission fault on an ancestor, or a symlink loop — and this selection sat OUTSIDE the
        # refusal contract while the expansion immediately above it and the `is_dir` check
        # immediately below it were both inside (review finding, codex, at `81962feab`).
        #
        # **Fifth instance of this family, and I made this one.** I converted `expanduser` four
        # commits ago for exactly this reason and did not read the next statement in the same
        # function. R2b's docstring says noting a pattern is not searching for its other members;
        # this is that sentence costing a fifth round rather than being acted on.
        #
        # Its own cause and remedy, not folded into `_unresolved_scope_component`: choosing the
        # anchor is a different failure from resolving a component, and one message for two
        # conditions names the wrong repair for half the cases.
        # **UNSUPPRESSED, and this one REDIRECTS rather than shrinks.** `Path.exists` swallows
        # the ignorable errnos and answers False, and `is_symlink` does the same, so an
        # unreadable anchor candidate silently loses to the next one and the scope is resolved
        # **against a different tree** — `all_inside` goes False and dispatch admits (review
        # finding, codex, at `e9a5b4acb`, reproduced with an ELOOP on the first anchor). Every
        # other instance of this family made a surface smaller; this one moves the question to
        # another checkout entirely, which is why it is worth naming separately.
        #
        # **`is_symlink` is asked FIRST, and the order is the whole repair.** It is `lstat`-based
        # so it answers about the LINK rather than its target and cannot fault on an unreadable
        # target. Putting the unsuppressed read first — as I did on the previous attempt —
        # raises on a genuinely self-referential link before `is_symlink` is ever consulted,
        # which replaced the specific "names the link and its target" refusal with the generic
        # anchor one. A committed row caught that, and it is the same pre-empting-a-better-
        # diagnosis mistake as the scope-side over-conversion earlier today.
        #
        # So: a link anchors on being a link, and only a NON-link candidate is stat-ed — where
        # an unreadable answer is genuinely unknown rather than a decided negative.
        try:
            base = next(
                (
                    b
                    for b in (council_root, vault_root)
                    if (b / first).is_symlink() or _classified_exists(b / first)
                ),
                council_root,
            )
        except (OSError, RuntimeError) as exc:
            error = UndecidableScopeContainment(
                f"cannot choose a checkout anchor for relative scope ref {ref!r}: {exc}; "
                "containment is undecidable"
            )
            error.remedy = (
                f"repair filesystem access for {council_root} and {vault_root}, or declare "
                f"{ref!r} as an absolute path in mutation_scope_refs, then retry the dispatch"
            )
            raise error from exc
        path = base / path
    # Keep entries below the root lexical, as fs.glob does. A member comparison checks symlinks
    # against that member's root; resolving here would erase the very entry it enumerated.
    #
    # `absolute()` reads the process working directory, which fails on its own terms — a deleted
    # or unreadable cwd — and this was the LAST unguarded statement in a function whose expansion
    # and anchor selection I converted earlier today. Found by faulting every risky `Path` method
    # in turn rather than by reading, which is the only reason it was not an eighth report.
    try:
        path = path.absolute()
    except (OSError, RuntimeError) as exc:
        raise _unresolved_scope_component(path, exc) from exc
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
    # `\A`/`\Z`, never `^`/`$`: Python's `$` also matches just BEFORE a trailing newline, so
    # `^a\.txt$` matched the filename "a.txt\n" — and a newline is a legal POSIX filename
    # character, so those are two different files (review finding, codex, at `850ccfdbb`;
    # reproduced as True/True for the patterns '*.txt', 'a.txt' and '*').
    #
    # Same family as the whitespace findings this row has already closed: a declared subject
    # silently equated with a different one. A member selecting `a.txt` was treated as selecting
    # `a.txt\n` too, so a scope naming the newline twin compared against the wrong surface.
    # `re.DOTALL`, because a newline is a legal character in a path COMPONENT and `.` does not
    # match one by default. Without it `**/` compiles to `(?:.*/)?` and never matched a file
    # under a directory whose name contains a newline, so `**/*.txt` did not select `a.txt`
    # below `dir\nwith-newline/` — and the unselected file then drove a mutual recursion between
    # `_canonical_member_entries` and `_check_member_symlinks` to a RecursionError (review
    # finding, cx-blue, at `93f5fceb1`; twelve reader fixtures, 10/2 -> 12/0 with DOTALL alone).
    #
    # **This gap PREDATES the `\A`/`\Z` anchoring below and was not caused by it** (cx-blue,
    # 2026-09-08; I claimed the opposite in the `b420f26c9` commit message and was wrong).
    # Measured against the same path, holding the regex body fixed and varying only anchors and
    # flags:
    #
    #     ^...$   no DOTALL   ->  no match     <- the state before the anchor repair
    #     \A..\Z  no DOTALL   ->  no match
    #     \A..\Z  DOTALL      ->  match
    #
    # The anchors are orthogonal: `.` has never matched a newline here. The commit message
    # stands as written because history is not rewritten; this is the correction beside it.
    #
    # This does NOT weaken the `\A`/`\Z` anchoring above, and the two answer different questions.
    # DOTALL governs what `.` may match INSIDE the pattern; the anchors govern where the match
    # may end. `*` already compiles to `[^/]*`, which a character class makes newline-permitting
    # regardless of DOTALL, so `*.txt` still refuses `a.txt\n` — that negative control is
    # deliberately preserved and is asserted in row S1.
    return re.compile(r"\A" + "".join(out) + r"\Z", re.DOTALL)


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


def _finite_scope_language(pattern: str | None, *, limit: int = 64) -> tuple[str, ...] | None:
    """Every name a pattern denotes, when that set is finite and exhaustively enumerable.

    `None` means the language is UNBOUNDED and cannot be enumerated: `*` and `?` admit names that
    do not exist yet, a directory spelling admits anything placed under it later, and a range or
    negated class is left undecidable exactly as `_literal_scope_glob` leaves it.

    This is the line the 2026-09-08 prospective-effect-scope ruling draws. A present expansion
    cannot prove containment of an unbounded language, because the language includes files nobody
    has created — but a FINITE language is a closed set of names, and the ruling is explicit that
    valid whole-language containment proofs are not removed. `alias[12]` denotes exactly two
    names; if both are the decayed file under another name, the whole scope really is inside.

    The `limit` refuses rather than truncating: a language too large to enumerate is not a shorter
    language, and returning a prefix of it would prove containment from a sample.
    """
    if pattern is None:
        return None
    names: list[str] = [""]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char in "*?":
            return None
        if char == "[":
            end = pattern.find("]", index + 2)
            characters = pattern[index + 1 : end] if end != -1 else ""
            if not characters or characters[0] == "!" or "-" in characters:
                return None
            choices = tuple(dict.fromkeys(characters))
            names = [name + choice for name in names for choice in choices]
            if len(names) > limit:
                return None
            index = end + 1
        else:
            names = [name + char for name in names]
            index += 1
    return tuple(dict.fromkeys(names))


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


def _require_scannable(root: Path, pattern: str, *, component_faults_recorded: bool) -> None:
    """Refuse when the directories a glob must read cannot be read.

    ``component_faults_recorded`` is REQUIRED, with no default, because the two enumerations this
    guards need opposite answers and a default would silently give a new call site the wrong one:

    * **The member enumeration passes True.** Nothing downstream of it diagnoses a fault on a
      selected component: `Path.glob` suppresses the same `DirEntry.is_dir()` failure, so the
      entry leaves the member's surface with no trace, the comparison is made against a short
      surface, and a decayed hard link is ADMITTED (review finding, codex, at `f74f36cf6`,
      reproduced with `[s-s]bin/fsck.ext2` over a directory alias; row S2h). An earlier comment
      here asserted that such a fault was "already diagnosed downstream" — it is not, on this
      path, and a comment asserting a mitigation that does not run is the same defect as no
      mitigation.
    * **The scope expansions pass False.** They DO resolve every component explicitly afterwards,
      through `_canonical_path_forms` and `_resolve_scope_directory_prefix`, and that refusal is
      strictly better: it names the declared scope ref and the member root the operator must act
      on, where this function can only name a root and a pattern. Recording here pre-empts it and
      loses the ref — measured, as the `unresolved-directory` dispatch control going red on a
      self-referential `lbin` symlink.

    The difference is structural, not a belief about runtime state: one enumeration resolves its
    components and one does not. Splitting is what the third fallback rule prescribes for a
    handler whose single flag was standing in for two distinct conditions.

    **`Path.glob` and `Path.rglob` SUPPRESS the scan errors underneath them.** `os.scandir`
    raising `PermissionError` on a directory yields no entries and no exception, so an unreadable
    member root produced an EMPTY surface, `all_inside` became False, and the dispatcher returned
    no refusal — the exact failure this consumer exists to prevent, reached through a fault
    instead of a spelling (review finding, two families, at `b420f26c9`, reproduced on
    `/usr/bin` with patterns `['fsck.ext[234]']`: all_inside True normally, False with
    `os.scandir` faulted, True again on restore).

    This is also the gap in my own `Path`-method sweep, and worth naming precisely: faulting
    `Path.glob` produced a named refusal there, so the sweep reported the layer as covered. The
    suppression happens BENEATH `Path.glob`, at the syscall it wraps, which a sweep over `Path`
    methods cannot reach. A bound stated at the wrong layer looks like coverage.

    **Called AFTER a successful enumeration, and for EVERY result — not only an empty one.**
    Placing it first pre-empted the existing, more specific refusals, so it moved after the glob;
    it was then also restricted to empty results, and **that restriction was a fail-open of its
    own**. A partial listing decides containment on what survived: with an `fs.glob` member at
    `/usr` and patterns `['*/fs*']`, faulting `os.scandir` for `/usr/bin` left
    `/usr/include/fstab.h` in the expansion, skipped this check, and ADMITTED `/usr/bin/e2fsck`
    — a hard link to the selected `fsck.ext2` (review finding, at `acd163574`, reproduced here).

    The restriction existed to stop this function pre-empting better diagnoses, but the three
    real causes of that were separately repaired — a missing directory is no longer a failure, an
    unmatched sibling's fault is no longer recorded, and a component fault defers downstream. It
    was a workaround for my own defects that outlived them and became one. Removing it closes the
    partial-listing case and leaves all eleven dispatch controls passing.

    An earlier version of this docstring named the partial-subtree case as a surviving BOUND. It
    was reported as a defect and it was one: a stated bound on a fail-open is still a fail-open.

    **Cost, measured rather than assumed.** Running on every enumeration rather than only empty
    ones looked like it would double a traversal. It does not: on a 1110-entry tree this check
    is 0.23x the `**/*.txt` glob it accompanies, 0.41x for `*/*/*.txt`, because it reads
    DIRECTORIES while the glob also stats and yields every file. I expected a regression and
    there is none, which is the only reason that sentence is here rather than a caveat.
    """
    try:
        if not root.is_dir():
            return
    except (OSError, RuntimeError) as exc:
        raise _unresolved_scope_component(root, exc) from exc

    failures: list[OSError] = []

    def _record(error: OSError) -> None:
        # **A directory that does not exist is not a directory that cannot be read.** Absence is
        # a decided negative — the glob simply matches nothing there, which is an answer — while
        # an unreadable directory is the unknown this function exists to refuse. Recording both
        # turned every ordinary missing-path arrangement into a refusal and reddened ten
        # committed dispatch controls; they were right, and the distinction is the same one this
        # module keeps making between a refuted and an unreadable answer. I made the collapse
        # inside the repair for it.
        if isinstance(error, FileNotFoundError | NotADirectoryError):
            return
        failures.append(error)

    def _descend(base: Path) -> list[Path]:
        """Every directory below `base`, recording BOTH scan and classification failures.

        This replaced `os.walk`, which reports a scan failure through `onerror` but suppresses
        an `OSError` from `DirEntry.is_dir()` WITHOUT reporting it at all — it silently treats
        the entry as a non-directory and never descends. So the recursive branch bypassed the
        classification handler `_children` had just been repaired to keep, on exactly the path
        where `**` puts the whole subtree in scope, and a decayed hard link was ADMITTED (review
        finding, codex, at `4863a74f8`, reproduced with `**/fsck.ext2` and a fault on `bin`).

        Two rows added with that repair looked like they covered this and did not: one faults
        entry classification without recursion, the other faults `scandir` recursively. Three
        of four cells, and the pair read as coverage of the surface because each held one axis.
        Doing the descent here rather than delegating is what makes the recursive and
        non-recursive paths share one mechanism instead of agreeing by coincidence.

        `follow_symlinks=False` keeps `os.walk`'s traversal rule deliberately: a directory alias
        is reached by `_children` on the segments AFTER `**`, which is the repair at
        `f74f36cf6`, not by descending into it here.
        """
        reached: list[Path] = []
        seen: set[Path] = set()
        stack = [base]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            reached.append(current)
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            is_directory = entry.is_dir(follow_symlinks=False)
                        except OSError as exc:  # noqa: PERF203
                            # `**` selects every entry, so there is no unrelated sibling here:
                            # anything that cannot be classified is inside the declared grammar.
                            if component_faults_recorded:
                                _record(exc)
                            continue
                        if is_directory:
                            stack.append(Path(entry.path))
            except (OSError, RuntimeError) as exc:
                _record(exc if isinstance(exc, OSError) else OSError(str(exc)))
            if failures:
                break
        return reached

    def _children(base: Path, segment: str) -> list[Path]:
        """Scan one directory, recording a failure, and return the subdirectories it selects."""
        selected: list[Path] = []
        try:
            with os.scandir(base) as entries:
                for entry in entries:
                    # Match the NAME first. Asking `is_dir()` of every entry made an unrelated
                    # sibling's fault everyone's: a self-referential symlink beside the selected
                    # directory raised ELOOP, was recorded, and refused every scope under that
                    # base — including ones whose pattern never names it. Ten committed dispatch
                    # controls caught that, and they were right; a fault outside the declared
                    # grammar is not this scope's concern, which is the same narrowness the
                    # grammar walk itself exists to keep.
                    if not fnmatch.fnmatch(entry.name, segment):
                        continue
                    try:
                        if not entry.is_dir():
                            continue
                    except OSError as exc:  # noqa: PERF203
                        # A fault on a component the pattern NAMES — the name match two lines up
                        # has already run, so an unrelated sibling never reaches here. Whether
                        # losing it is survivable depends entirely on whether the caller resolves
                        # its components afterwards, which is what the parameter states; see the
                        # docstring for the two cases and the control that holds each.
                        if component_faults_recorded:
                            _record(exc)
                        continue
                    selected.append(Path(entry.path))
        except (OSError, RuntimeError) as exc:
            _record(exc if isinstance(exc, OSError) else OSError(str(exc)))
        return selected

    # Walk the DECLARED GRAMMAR, not an assumption about it. Every segment but the last selects
    # directories, so each level the pattern traverses must be readable — and `sub/*.txt` and
    # `*/*.txt` traverse a nested level without containing `**` at all. Treating `**` as the only
    # nested form left a persistent fault on `surface/sub` undetected, the glob silently empty,
    # and an outside hard-link alias ADMITTED (review finding, root via cx-blue, at `d8794d7c6`;
    # the `**/*.txt` twin refused correctly, which is what isolates the assumption).
    #
    # It is also the narrow form: only directories the pattern actually reaches are required to
    # be readable, so an unrelated unreadable corner of the tree does not refuse a scope that
    # never looks at it.
    # The SELECTOR's reading of the pattern, for the same reason `_definitely_outside_pattern`
    # uses it: splitting on "/" keeps a `.` that `Path.glob` normalizes away, so `_children`
    # matched the literal "." against real directory names, the frontier emptied, and this walk
    # silently checked nothing for a dot-prefixed pattern. Codex named both sites in one finding
    # (at `a465c0a99`) — I had repaired the relevance filter and left its twin here, which is
    # the "fix the instance shown" shape this row keeps meeting.
    segments = list(PurePosixPath(pattern).parts)
    frontier = [root]
    for segment in segments[:-1]:
        if segment == "**":
            # From here down the grammar can reach anything, so the whole subtree must be
            # readable AND classifiable. `_descend` records both, which `os.walk` does not.
            #
            # It does NOT follow symlinks, and the remaining segments must still be walked
            # from every directory it reached: `**` matches zero or more levels, so an
            # EXPLICIT component after it — `**/sbin/fsck.ext2` — resolves through a directory
            # alias that `os.walk` itself will not descend. Discarding the suffix here left
            # such an alias unchecked, and faulting it admitted a decayed hard link (review
            # finding, at `0b2d8e6fb`, reproduced with a content-query member and `usr/sbin`
            # aliasing `bin`). `_children` asks `is_dir()`, which follows the link, so
            # continuing the walk is what reaches it.
            reached: list[Path] = []
            for base in frontier:
                reached.extend(_descend(base))
                if failures:
                    break
            # `**` matches zero levels too, so the bases must stay reachable for the segments
            # after it — and they do because `_descend` yields each base as its own first
            # entry, which is the mechanism.
            #
            # An earlier revision carried the bases separately, as `[*frontier, *reached]`, and
            # said in a comment that the extra term was what handled zero-level matching. That
            # was false: `os.walk` yields its own top as well, so the term never changed the
            # frontier and deleting it left 516 rows green. Measured three ways before removing
            # it — a walk yields its top first, does so even when the top is a symlinked
            # directory, and when the top is unreadable it yields nothing and reports the
            # failure, which breaks out above. A stated mechanism that does no work is worth
            # more to remove than to keep, because the next reader preserves it as load-bearing.
            frontier = list(dict.fromkeys(reached))
            if failures:
                break
            continue
        frontier = [child for base in frontier for child in _children(base, segment)]
        if failures or not frontier:
            break

    # The directories that hold the matched FILES are read too, by the final segment.
    for base in frontier:
        try:
            with os.scandir(base) as entries:
                for _entry in entries:
                    pass
        except (OSError, RuntimeError) as exc:
            _record(exc if isinstance(exc, OSError) else OSError(str(exc)))

    if failures:
        error = UndecidableScopeContainment(
            f"cannot enumerate {root} for pattern {pattern!r}: {failures[0]}; an unreadable "
            "directory is not an empty one, and containment cannot be decided over it"
        )
        error.remedy = (
            f"repair read access for {root} and the directories beneath it, then retry the dispatch"
        )
        raise error


#: Whether this runtime exposes the seam :func:`_observed_glob` needs. `pathlib.Path.glob`
#: reaches its directory scans through ``type(parent)._scandir`` and preserves the receiver's
#: class down the tree via ``with_segments``, so a subclass sees the glob's OWN scans. That is a
#: PRIVATE binding, pinned to the interpreter this was measured on (3.12.13) and not a portable
#: guarantee — hence a checked capability rather than an assumption.
#:
#: **Absence REFUSES; it does not fall back.** An earlier revision degraded to the separate
#: readability walk here and offered, as evidence the fallback was safe, that forcing the seam
#: off left every row passing but S2k. The coordinator's reading is the correct one: that
#: measurement is a discriminator AGAINST the fallback, not a justification for it — it says in
#: one line that the known intermittent-fault fail-open returns wherever the seam is missing. A
#: stated bound on a fail-open is still a fail-open, which is this row's own most-repeated
#: finding, and I reproduced it in the repair for it.
_GLOB_SCAN_SEAM = hasattr(Path, "_scandir")

#: The errnos `pathlib.Path.is_dir` swallows, read from the runtime rather than restated, so the
#: observing override answers exactly what pathlib answers instead of approximating it.
_PATHLIB_IGNORED_ERRNOS: frozenset[int] = frozenset(
    getattr(
        pathlib_module, "_IGNORED_ERRNOS", (errno.ENOENT, errno.ENOTDIR, errno.EBADF, errno.ELOOP)
    )
)

#: The subset that means DECIDED ABSENCE rather than an unreadable answer: the glob matches
#: nothing there, which is a result. The rest — a bad descriptor, a symlink loop — are the
#: unknown this module refuses over.
_DECIDED_ABSENCE_ERRNOS: frozenset[int] = frozenset({errno.ENOENT, errno.ENOTDIR})


def _refuse_unobservable_enumeration(root: Path, pattern: str) -> UndecidableScopeContainment:
    """Refuse by name where the supplying traversal cannot be observed on this runtime."""
    error = UndecidableScopeContainment(
        f"cannot decide containment for member pattern {pattern!r} below {root} on this "
        f"interpreter: expanding it uses pathlib's own directory scans, which suppress their "
        "errors, and this runtime does not expose the seam that observes them — so a short "
        "surface could not be told from a complete one"
    )
    error.remedy = (
        "run governed dispatch on an interpreter whose pathlib exposes Path._scandir "
        "(measured on 3.12), or qualify and bind the equivalent seam for this runtime; "
        "do not disable the check"
    )
    return error


#: **SITE LEDGER for the canonical/anchor family — four roles, each rolled back on its own.**
#:
#: Measured 2026-09-08 against `tests/scripts/test_frame_scope_grammar.py` and
#: `tests/shared/test_frame_verdicts.py` (458 baseline), one site reverted to the suppressing
#: method at a time, source restored between each:
#:
#: === ==================================== ============================== ==================
#: #   site and role                          rollback                       disposition
#: === ==================================== ============================== ==================
#: 1   `resolve_scope_ref`: which BASE the    2 killed: `R2c[suppressed-    PINNED
#:     ref anchors to                         eloop]`, `S2w`
#: 2   `ref_within_member`: which containment 1 killed: `S2w`               PINNED
#:     QUESTION the literal-glob candidate
#:     is asked
#: 3   `_refuse_in_root_alias_reaching_       0 killed (458 pass)           UNPINNED
#:     surface`: is the resolved alias
#:     target a FILE, with no scope pattern
#: 4   `_refuse_in_root_alias_reaching_       0 killed (458 pass)           UNPINNED
#:     surface`: the `dirlike` argument of
#:     its recursive containment call
#: === ==================================== ============================== ==================
#:
#: **Roles 3 and 4 are unpinned, and that is all that is established about them.** An earlier
#: revision of this note called them "correct in principle" and said they "cost nothing"; the
#: coordinator withdrew both, and they are withdrawn here. Neither is supported: no control
#: distinguishes the converted source from the native one at either site, so their correctness
#: is untested rather than principled, and a conversion whose behaviour is unmeasured has an
#: unmeasured cost. Role 4 additionally carried a comment asserting the hazard was "reachable
#: here" because no strict resolution precedes it — the rollback kills nothing, so that
#: sentence claimed more than anything demonstrates and has been corrected at the site.
#:
#: **History, preserved rather than rewritten.** What was tried, and what it showed:
#:
#: * Every `canonical_*` classification is downstream of `_resolve_external_scope_path`, whose
#:   `resolve(strict=True)` does NOT suppress, so a steady fault raises there first and never
#:   reaches the classifier. That much is measured and still holds.
#: * "Reachable only by call-ordinal injection" was my claim and it was too strong. The
#:   coordinator proposed a stage-triggered discriminator: run the real resolver, then arm a
#:   path-specific BACKEND fault after its successful return, so the injection survives a
#:   rollback and arming does not touch the mitigation. Built and run exactly that way — the
#:   refusal still arrives from a LATER `resolve`, same `cannot resolve scope component`
#:   message under both the converted and the rolled-back source. A legitimate decision
#:   intercepts the fault.
#: * Reaching the classifier from either site would mean relaxing the resolution that refuses
#:   first, which is arranging for a desired branch rather than testing one. Recorded as
#:   unreached rather than engineered around.
#:
#: **TWO sites of role 4's shape are NOT converted** — the two `canonical_path.is_dir()` calls
#: inside `ref_within_member`, found while rolling role 4 back. Converting them would add
#: unpinned changes of a role whose only converted instance kills nothing, which is uniform
#: replacement by spelling wearing a role's name. The same argument would apply to a future
#: third, but a hypothetical one is not a site and counting it as though it were made the
#: sentence say three where the tree holds two (coordinator correction, at `7293a1ee9`).
#:
#: The discovery, identity, selected-file and canonical-forms conversions are different: those
#: are pinned by controls that go red when reverted.


def _classified_exists(entry: Path) -> bool:
    """``entry.exists()`` from an UNSUPPRESSED stat. Absence answers False; unreadable raises.

    Companion to :func:`_classified_is_file` and :func:`_classified_is_dir`, and added for the
    same reason at a third pair of sites: `Path.exists` and `Path.is_dir` swallow the ignorable
    errnos, so the `except OSError` handlers around them **cannot fire**, and an unreadable
    answer silently becomes a negative one — a shorter checkout set, an identity read that never
    happens, and a scope admitted (review finding, codex, at `eda8b35a0`). Both of those sites
    carried a comment saying an unreadable answer must not become a negative one; neither could
    detect the case the comment described.
    """
    try:
        entry.stat()
    except OSError as exc:
        if exc.errno in _DECIDED_ABSENCE_ERRNOS:
            return False
        raise
    except ValueError:
        return False
    return True


def _classified_is_dir(entry: Path) -> bool:
    """``entry.is_dir()`` from an UNSUPPRESSED stat; see :func:`_classified_exists`."""
    try:
        status = entry.stat()
    except OSError as exc:
        if exc.errno in _DECIDED_ABSENCE_ERRNOS:
            return False
        raise
    except ValueError:
        return False
    return stat_module.S_ISDIR(status.st_mode)


def _classified_is_file(entry: Path) -> bool:
    """``entry.is_file()`` from an UNSUPPRESSED stat, so a classification fault can be refused.

    `Path.is_file` swallows the same ignorable errnos as `Path.is_dir` and answers False, which
    makes a faulting entry indistinguishable from an absent one — and this classification decides
    whether a selected file is in the member's surface at all. A silently smaller surface is not
    a smaller answer but a wrong one.

    **Absence stays a decided negative** (ENOENT, ENOTDIR): the entry is genuinely not a file and
    dropping it is correct. Everything else in pathlib's ignore set — a bad descriptor, a symlink
    loop — is the unknown, and is raised for the caller to convert into a named refusal.
    Non-ignorable errors propagate exactly as pathlib would raise them.
    """
    try:
        status = entry.stat()
    except OSError as exc:
        if exc.errno in _DECIDED_ABSENCE_ERRNOS:
            return False
        raise
    except ValueError:
        return False
    return stat_module.S_ISREG(status.st_mode)


def _observed_glob(root: Path, pattern: str) -> tuple[list[Path], list[OSError]]:
    """Expand ``pattern`` under ``root`` and return the failures THAT expansion hit.

    **A check of a re-run is not a check of the run.** `Path.glob` suppresses its own scan
    errors, and the readability walk beside it is a second, independent traversal of the same
    tree — so an INTERMITTENT fault, present for the enumeration and gone for the check, left a
    short surface vouched for as complete and admitted a decayed hard link (review finding,
    codex, at `87ae8c419`, reproduced with `os.scandir` failing on calls 1 and 3; row S2k).

    Every earlier candidate was unsound: enumerating ourselves risks diverging from the
    producer's own `Path.glob` selection, checking before and after closes one call pattern and
    is two guards on one hazard, and globbing twice agrees with itself on the reported case. The
    route that works is to observe the supplying traversal from inside — which the coordinator
    found in the installed pathlib and is measured here rather than assumed.

    **The subclass is built per call.** Class-level collection would be shared state across
    concurrent invocations, which is the bound the re-entrancy guard already had to state once;
    there is no reason to acquire a second one.

    **Classification is captured too, and relevance is decided separately from capture.** An
    earlier revision observed only directory scans and left per-entry `DirEntry` classification
    to the later walk — which reproduces the very defect one layer down, because that walk is
    again a re-run. The coordinator's rule is the right one: *preserve the actual
    supplying-traversal error, then prove it irrelevant to the selected grammar or refuse;
    unknown relevance is not demonstrated disjointness.* So a classification fault is recorded
    unless the entry can be shown definitely outside what the pattern selects, and
    `_definitely_outside_pattern` claims that only where it can prove it.
    """
    failures: list[OSError] = []

    class _ObservedEntry:
        """A `DirEntry` whose classification faults are recorded before they are suppressed."""

        __slots__ = ("_entry",)

        def __init__(self, entry: os.DirEntry) -> None:
            self._entry = entry

        def __getattr__(self, name: str):  # noqa: ANN202
            return getattr(self._entry, name)

        def is_dir(self, *args, **kwargs):  # noqa: ANN202
            try:
                return self._entry.is_dir(*args, **kwargs)
            except OSError as exc:
                if not _definitely_outside_pattern(Path(self._entry.path), root, pattern):
                    failures.append(exc)
                raise

        def is_file(self, *args, **kwargs):  # noqa: ANN202
            try:
                return self._entry.is_file(*args, **kwargs)
            except OSError as exc:
                if not _definitely_outside_pattern(Path(self._entry.path), root, pattern):
                    failures.append(exc)
                raise

    class _ObservedScan:
        """Wraps one scandir result, preserving the context-manager and iterator protocols."""

        def __init__(self, inner) -> None:
            self._inner = inner

        def __enter__(self):  # noqa: ANN204
            # THE PROTOCOL LAYER, and the fourth place this one defect lives. Entering and
            # leaving the scan can fail on their own, native pathlib catches those, and they
            # then disappear exactly as the other three did (review finding, root, at
            # `8c3302d49`, eight cases). Semantics are unchanged — the error is recorded and
            # re-raised, so every caller still sees what it saw.
            try:
                self._inner.__enter__()
            except OSError as exc:
                failures.append(exc)
                raise
            return self

        def __exit__(self, *exc_info) -> None:
            try:
                self._inner.__exit__(*exc_info)
            except OSError as exc:
                failures.append(exc)
                raise

        def __iter__(self):  # noqa: ANN204
            return self

        def __next__(self):  # noqa: ANN204
            try:
                return _ObservedEntry(next(self._inner))
            except StopIteration:
                raise
            except OSError as exc:
                # THE THIRD LAYER. Opening a scandir, ITERATING it, and classifying an entry
                # each fail separately, and an earlier revision caught only the first — so an
                # iterator that raised mid-walk still shortened the surface silently (review
                # finding, codex, at `7d3a6e8d4`). Relevance cannot be established for an
                # iteration failure, because the entry it would have yielded is precisely what
                # was not produced; unknown relevance is not demonstrated disjointness, so it
                # is recorded.
                failures.append(exc)
                raise

        def close(self) -> None:
            close = getattr(self._inner, "close", None)
            if close is not None:
                close()

    class _ObservedPath(type(root)):  # type: ignore[misc]
        def is_dir(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            # THE FIFTH LAYER, and it runs BEFORE any scan. `Path.glob` asks
            # `parent_path.is_dir()` first, and `Path.is_dir` swallows an ignorable `OSError`
            # from its `stat` and answers False — so a root whose classification faults produced
            # an empty selection with nothing recorded, and the enumeration never reached the
            # scan hooks at all (review finding, codex, at `c761b2942`, reproduced with a
            # transient fault on the root's own stat).
            #
            # Observed by stat-ing first and delegating unchanged, so the answer this returns is
            # still pathlib's. The extra stat is the cost of seeing the error before the method
            # that hides it.
            # **ONE read, and it is the one that decides.** An earlier revision stat-ed first and
            # then delegated to `super().is_dir()`, which stats AGAIN — so a transient fault
            # hitting only the second read was never observed, and the observation hook had the
            # very same-observation defect it was built to close, one level down (coordinator,
            # static concern on `538e5bcd5`; structural, so repaired without waiting for the
            # matrix to reproduce it). Two reads where one decides is a defect by construction.
            #
            # `pathlib.Path.is_dir` is mirrored exactly rather than approximated: it ignores
            # errno 2/20/9/40 and answers False, and re-raises anything else. **Absence is a
            # decided negative and is not recorded** — ENOENT and ENOTDIR mean the glob simply
            # matches nothing there, which is an answer. EBADF and ELOOP are the unknown this
            # exists to refuse, and are exactly the transient faults the finding used.
            #
            # Recording absence is the collapse `_record` was written to prevent, and the first
            # version of this hook reintroduced it, reddening nine committed dispatch controls
            # including this row's own whole-scope predicate. Stating the errnos keeps the
            # distinction where a reader can check it against the runtime.
            try:
                status = self.stat()
            except OSError as exc:
                if exc.errno not in _PATHLIB_IGNORED_ERRNOS:
                    raise
                if exc.errno not in _DECIDED_ABSENCE_ERRNOS and not _definitely_outside_pattern(
                    Path(self), root, pattern
                ):
                    failures.append(exc)
                return False
            except ValueError:
                return False
            return stat_module.S_ISDIR(status.st_mode)

        def _scandir(self):  # noqa: ANN202
            try:
                return _ObservedScan(super()._scandir())
            except OSError as exc:
                failures.append(exc)
                raise

    return list(_ObservedPath(root).glob(pattern)), failures


def _definitely_outside_pattern(entry: Path, root: Path, pattern: str) -> bool:
    """Whether ``entry`` provably cannot be on any path ``pattern`` selects beneath ``root``.

    **Conservative by construction: it answers True only where it can prove it**, because the
    caller spends a False as "record this failure" and a wrong True is a fail-open. Unknown
    relevance is not demonstrated disjointness.

    A `**` at or before the entry's own depth can reach any descendant, INCLUDING descendants of
    a directory whose own name matches nothing in the pattern — so once one is in play nothing
    below is provably outside and this answers False. Without one, each segment must match its
    positional counterpart, and an entry deeper than the pattern is only outside if the pattern
    cannot extend to it.

    Native matching is untouched: this decides only whether a FAILURE is the scope's business,
    never which files are selected.
    """
    try:
        relative = entry.relative_to(root)
    except ValueError:
        return True
    # **The RUNTIME's parsed components, not a second normalization grammar.** Splitting the
    # pattern on "/" kept `.` and empty segments that pathlib's own selector removes, so
    # `./[b]ranch/selected.txt` compared the entry `branch` against the segment `.`, failed the
    # match, and declared a relevant fault irrelevant — the selection went short with no error
    # recorded (review finding, root, at `8c3302d49`, with the `.//` spelling as its twin).
    # Writing a parallel grammar to reason about the first one is how the two drift apart; the
    # only sound reading of a pattern is the one the selector itself uses.
    segments = list(PurePosixPath(pattern).parts)
    parts = relative.parts
    if not segments or ".." in segments:
        # A parent segment can climb back into anything; nothing below is provably outside.
        return False
    for index, part in enumerate(parts):
        if index >= len(segments):
            # Deeper than the pattern reaches, and no `**` was passed on the way down.
            return "**" not in segments
        if segments[index] == "**":
            return False
        if not fnmatch.fnmatch(part, segments[index]):
            return True
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
            # OBSERVED, like the member enumeration. This is the seventh place the same
            # pathlib suppression was found, and the sixth time I repaired one call site while
            # leaving its siblings: these forms are what disjointness is established against, so
            # a scan failure here omits an ALIAS from the declaration and admits a scope the
            # complete forms would have refused (review finding, codex, at `eda8b35a0`).
            #
            # Enumerating the remaining call sites rather than waiting for the next one to be
            # reported is the correction; `_pattern_matches` at :1490 is prose, `_observed_glob`
            # is the observer itself, and the other three are converted alongside this one.
            observed, glob_failures = _observed_glob(
                path, f"**/{directory_pattern}" if recursive else directory_pattern
            )
            if glob_failures:
                error = UndecidableScopeContainment(
                    f"cannot enumerate canonical forms for {pattern!r} below {path}: "
                    f"{glob_failures[0]}; a declaration missing one of its own aliases cannot "
                    "establish disjointness"
                )
                error.remedy = (
                    f"repair read access for {path} and the directories beneath it, then retry "
                    "the dispatch"
                )
                raise error
            for entry in observed:
                canonical = _resolve_external_scope_path(entry)
                # Unsuppressed, and note WHERE this sits: directly beside the enumeration
                # observed in the previous commit. I converted the glob and left the
                # classification of its own results suppressed one line later, so an ELOOP here
                # still removed the alias from the forms disjointness is established against
                # (review finding, codex, at `45b076c53`). Eighth boundary of this family, and
                # the second time the repair stopped one layer short of its own neighbour.
                if _classified_is_dir(canonical):
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
        # Whether the canonical path is a file decides whether this returns without refusing, so
        # an unreadable answer here is not a negative one. Same family as the anchor and identity
        # reads; found by the method sweep rather than by a report.
        #
        # **And the sentence above was written beside a call that could not honour it.**
        # `Path.is_file` suppresses the ignorable errnos and answers False, so the handler
        # beneath never fired and an unreadable answer became exactly the negative one the
        # comment forbids. I wrote that comment, naming this family, and used the suppressing
        # method anyway — which is the same defect the comment describes, one line above itself.
        #
        # **UNPINNED — role 3 in the ledger above; 0 controls killed by a rollback.** The branch
        # is guarded by `scope_pattern is None`, and across four arrangements — root and in-root
        # alias, with and without a pattern, matching and non-matching — this function is either
        # not entered or returns before reaching here, so no caller obligation is demonstrated
        # either. Reaching it would mean relaxing a guard to arrive at a chosen branch.
        try:
            canonical_is_file = _classified_is_file(canonical_path)
        except (OSError, RuntimeError) as exc:
            raise _unresolved_scope_component(canonical_path, exc) from exc
        if canonical_is_file:
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
            # Decides WHICH containment question is asked, like the candidate classification in
            # `ref_within_member` itself, so it reads the stat rather than the suppressing
            # method.
            #
            # **UNPINNED — role 4 in the ledger above; 0 controls killed by a rollback.** This
            # comment used to end "unlike that one this site has no earlier strict resolution in
            # front of it, so the hazard is reachable here." Reverting the call leaves all 458
            # controls green, so nothing demonstrates that reachability and the sentence is
            # withdrawn. The absence of a preceding strict resolve is a fact about the code
            # path; it is not evidence that a fault arrives here, and reading it as though it
            # were is the same step this file has had to retract at several other sites.
            canonical_pattern is not None or _classified_is_dir(canonical_path),
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
            found = list(path.glob(scope_pattern))
            # **NOT observed, and that is the same split as `component_faults_recorded`.**
            # Enumerating this module's glob call sites was the right move after six rounds of
            # repairing one at a time; converting them uniformly was not. This is the SCOPE
            # side: the declared components are resolved below and that refusal names the ref,
            # so observing here pre-empts a better diagnosis — measured, as two committed
            # controls going red the moment I converted it, including the self-referential
            # `lbin` row that caught the same over-reach earlier today.
            #
            # The member enumeration, the canonical FORMS and the member file match are
            # observed, because those decide containment and have nothing better downstream.
            # The two scope expansions are not. **Three of five, not all of them** — the
            # earlier wording here said the sites had been converted, which stopped being true
            # the moment I reverted this one and stayed in the file anyway.
            _require_scannable(path, scope_pattern, component_faults_recorded=False)
            paths.extend(found)
        except NonCanonicalScopeRef:
            # As at the other two sites: do not re-wrap a refusal that names its own repair.
            raise
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


#: Members whose canonical surface is being computed right now. `_canonical_member_entries` and
#: `_check_member_symlinks` are MUTUALLY RECURSIVE — the first calls the second per entry, and the
#: second rebuilds the whole surface when an entry is lexically disjoint — and nothing bounded
#: that cycle structurally. It terminated only because some entry usually matches the member's
#: patterns, which is a fact about the data, not about the code.
#:
#: Measured at `93f5fceb1`: with `**/*` failing to match under a directory whose name contains a
#: newline, EVERY entry became disjoint and the pair recursed 478 times each into a RecursionError
#: (review finding, cx-blue). A RecursionError is a crash, not a refusal, so it escaped the
#: contract entirely — the same shape as the unguarded filesystem faults, arrived at differently.
#:
#: The `re.DOTALL` repair removes that trigger. This removes the CYCLE, which is what makes the
#: family closed rather than one instance repaired: any future gap between what a member's
#: patterns select and what its root contains re-enters here, and re-entry is now a named
#: undecidable refusal instead of a stack overflow.
#:
#: **What re-entry proves, stated precisely (cx-blue, 2026-09-08).** It proves this CONSUMER's
#: calculation is self-dependent for this member. It does NOT prove that none of the member's
#: entries match, and it does NOT establish that the producer's `location.patterns` are
#: defective — the counterexample that reaches it perturbs the consumer's own regex and leaves a
#: perfectly valid declaration in place. The refusal below therefore diagnoses the consumer and
#: explicitly tells the reader the declaration needs no change; an earlier wording sent them to
#: repair a correct one.
#:
#: **Bound, not a claim:** this is module-global state, so its behaviour under CONCURRENT calls
#: into the consumer is unqualified. Nothing here asserts that a current caller is concurrent —
#: only that if one ever is, this guard has not been reasoned about for that case.
_SURFACE_IN_PROGRESS: set[int] = set()


def _canonical_member_entries(member: DecayedMember) -> dict[Path, Path]:
    """Close the producer's selected file entries over their canonical byte targets.

    Keep each reader's pathlib traversal and exclusions. Content-query predicates are
    evaluated on the selected entries at comparison time. Resolve before is_file(), which
    silently drops dangling links, and retain fs.glob's traversal/escape remedies.
    """
    token = id(member)
    if token in _SURFACE_IN_PROGRESS:
        # The surface is being asked for as part of computing itself. A partial answer is not a
        # smaller surface, it is a wrong one — a weaker comparison that would silently admit —
        # so this refuses by name rather than returning what has been collected so far.
        error = UndecidableScopeContainment(
            f"this consumer cannot compute member {member.member_id!r} canonical surface: the "
            "calculation re-entered itself, so containment cannot be decided for this dispatch"
        )
        error.remedy = (
            "report this consumer defect with the member id and the scope ref; the declaration "
            "is not implicated and needs no change. Re-run the dispatch once the consumer is "
            "repaired"
        )
        raise error
    _SURFACE_IN_PROGRESS.add(token)
    try:
        return _canonical_member_entries_uncached(member)
    finally:
        _SURFACE_IN_PROGRESS.discard(token)


def _canonical_member_entries_uncached(member: DecayedMember) -> dict[Path, Path]:
    surface: dict[Path, Path] = {}
    content_query = member.reader == "fs.content_query"
    patterns = member.patterns if content_query else member.patterns or ("**/*",)
    for root in member.roots:
        for pattern in patterns:
            try:
                glob_pattern = f"**/{pattern}" if content_query else pattern
                if not _GLOB_SCAN_SEAM:
                    raise _refuse_unobservable_enumeration(root, pattern)
                entries, enumeration_failures = _observed_glob(root, glob_pattern)
                if enumeration_failures:
                    # The failure came from THIS enumeration, so no later traversal can clear
                    # it — which is the whole point of observing from inside.
                    error = UndecidableScopeContainment(
                        f"cannot enumerate member pattern {pattern!r} below {root}: "
                        f"{enumeration_failures[0]}; the expansion that produced this surface "
                        "could not read or classify every entry it traversed, and a short "
                        "surface is not a smaller answer but a wrong one"
                    )
                    error.remedy = (
                        f"repair read access for {root} and the directories beneath it, "
                        "then retry the dispatch"
                    )
                    raise error
                # Member side: nothing below resolves these components, so a lost one leaves a
                # short surface and a silently weaker comparison. Row S2h holds it.
                _require_scannable(
                    root,
                    f"**/{pattern}" if content_query else pattern,
                    component_faults_recorded=True,
                )
            except NonCanonicalScopeRef:
                # `UndecidableScopeContainment` IS a `ValueError`, so this broad handler used to
                # catch the typed refusal `_require_scannable` had just raised and replace it —
                # keeping the fact but discarding the remedy, so a broken read-permission was
                # reported as advice to narrow the glob (review finding, codex, at `4863a74f8`).
                # A refusal that names its own repair must reach the caller as itself.
                raise
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
                # An unreadable entry must not silently drop OUT of the member's surface: a
                # smaller surface is a weaker comparison, and this one decides what the member
                # is taken to select. The `try` a few lines above already converts the traversal
                # faults; this sibling call was outside it.
                # **The handler above could never fire.** `Path.is_file` suppresses an ignorable
                # `OSError` internally and answers False, exactly as `Path.is_dir` does, so a
                # selected file whose classification faulted DROPPED OUT of the surface with no
                # exception to convert — and this runs after `enumeration_failures` is checked,
                # so the observing enumerator does not cover it either (review finding, codex,
                # at `538e5bcd5`, reproduced with transient faults on the selected file's stat).
                # A comment two lines up said this sibling call had been brought inside the
                # conversion; it had been given a handler, which is not the same thing.
                try:
                    entry_is_file = _classified_is_file(entry)
                except (OSError, RuntimeError) as exc:
                    raise _unresolved_scope_component(entry, exc) from exc
                if entry_is_file and not _member_path_is_excluded(entry, root, member):
                    surface[entry] = canonical
    return surface


def _canonical_scope_entries(
    path: Path, pattern: str, member: DecayedMember, *, include_directories: bool = False
) -> dict[Path, Path]:
    """Expand in the producer tree before resolving every entry, including broken links."""
    try:
        # **THE CLAIMED DOWNSTREAM DIAGNOSIS DOES NOT OCCUR.** This site kept plain `Path.glob`
        # on my reasoning that `_resolve_scope_directory_prefix` diagnoses a component fault here
        # with the ref in hand, so observing would replace a better refusal with a worse. Codex
        # measured that reasoning false at the pinned head: decay `/usr/bin` with patterns
        # `['fsck.ext2']` and scope `/usr/bin/[e-e]2fsck`, whose target is the SAME INODE, then
        # fail only the scope-glob scans — receipt-only `main()` goes from exit 10 to exit 0,
        # "eligible", and restoring the scans restores 10. No downstream refusal fires.
        #
        # The fault it takes is TRANSIENT, which is why `_require_scannable` cannot stand in for
        # observing: its walk happens after the glob's, and a fault that is gone by then was
        # never visible to it. That is the same sentence I wrote into the member side this
        # morning — a check of a re-run is not a check of the run — and I reasoned about this
        # side using only steady faults, which its later walk does catch.
        if not _GLOB_SCAN_SEAM:
            raise _refuse_unobservable_enumeration(path, pattern)
        entries, enumeration_failures = _observed_glob(path, pattern)
        if enumeration_failures:
            # **Name the DECLARED scope, not only the base and the relative pattern.** This
            # message split the ref into two halves that never appear adjacent, so an operator
            # holding a `mutation_scope_refs` list could not find the entry it is about, and
            # `test_dispatch_empty_member_glob_directory_prefix[unresolved-directory]` said so
            # from the moment this refusal was introduced at `614dc6581`. The comment above
            # records that the path it replaced diagnosed "with the ref in hand"; the
            # replacement dropped exactly that and I then reported the failure three times as
            # predating this arm, on the strength of it also being red one commit later.
            # Both halves of the comparison, in the vocabulary the sibling refusals already use:
            # the DECLARED scope and the member roots it is being decided against, and the phrase
            # `containment is undecidable`. A refusal that names one side says which path is
            # broken and not which question went unanswered.
            # The `scope_containment_undecidable:` code is spelled by hand at six other sites and
            # this is the seventh. One refusal code written out at seven sites is the same shape
            # this arm keeps filing against the scanner, and it belongs in a follow-up rather than
            # in a row already under review — recorded here so the follow-up has a reason.
            error = UndecidableScopeContainment(
                f"scope_containment_undecidable: cannot enumerate declared scope "
                f"{path / pattern} against member root "
                f"{', '.join(str(root) for root in member.roots)}: "
                f"{enumeration_failures[0]}; the expansion that produced this scope could not "
                "read or classify every entry it traversed, a short scope is not a smaller "
                "answer but a wrong one, and containment is undecidable"
            )
            # **The default remedy is the wrong one for this failure and it fires by omission.**
            # `UndecidableScopeContainment` defaults to "use narrower globs", which is right when
            # a scope is too broad to decide and is actively misleading when the scope could not
            # be READ: narrowing the glob does not repair a permission or a loop, and following
            # the instruction changes the declaration rather than the fault. The member-side scan
            # failure already sets its own; this one inherited the default because I raised the
            # class directly instead of building the error and naming its repair (review finding,
            # root, at `614dc6581`, two Next-action cases).
            error.remedy = (
                f"repair read access for {path} and the directories beneath it, "
                "then retry the dispatch"
            )
            raise error
        # Kept: the readability walk still runs, because it diagnoses steady component faults
        # with a remedy the enumeration failure above does not carry. Observing does not replace
        # it; it covers the window the walk cannot see.
        _require_scannable(path, pattern, component_faults_recorded=False)
    except NonCanonicalScopeRef:
        # As at the member site: the typed refusal carries its own remedy and must not be
        # re-wrapped by a handler that catches ValueError.
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise UndecidableScopeContainment(
            f"cannot inspect scope glob {pattern!r} below {path}: {exc}; containment is undecidable"
        ) from exc
    canonical = {}
    for entry in entries:
        try:
            # The producer reads files. Terminal ** can yield only directories; those
            # entries supply no evidence about containment of the recursive file language.
            #
            # **A SEPARATE BOUNDARY FROM THE ENUMERATION, and codex says so explicitly:
            # observing glob errors alone will not fix it.** `Path.is_file` suppresses ELOOP and
            # answers False, so an entry that exists and cannot be classified dropped silently
            # out of the canonical scope even when the enumeration succeeded — and a missing
            # entry removes the identity witness, which lets disjointness be asserted over a
            # wholly decayed singleton scope. Measured on the same hard-link fixture: injecting
            # ELOOP only into the stat this classification consumes takes receipt-only `main()`
            # from exit 10 to exit 0, and restoring it returns 10.
            #
            # The consequence is at `_local_disjoint_established`, which consults the branch that
            # returns the undecidable answer only `if denoted` — so an emptied expansion skips
            # the refusal rather than triggering it.
            if _classified_is_dir(entry) and not include_directories:
                continue
            for root in member.roots:
                if member.reader != "fs.content_query" and root in entry.parents:
                    _check_member_symlinks(entry, root, member, scope_pattern=None)
            target = _resolve_external_scope_path(entry)
            if _classified_is_file(entry) or (include_directories and _classified_is_dir(entry)):
                canonical[entry] = target
        except (UndecidableScopeContainment, OSError, RuntimeError) as exc:
            cause = (
                exc
                if isinstance(exc, UndecidableScopeContainment)
                else _unresolved_scope_component(entry, exc)
            )
            error = UndecidableScopeContainment(f"scope glob expansion {entry}: {cause}")
            # The component remedy is the RIGHT one here and this line is deliberately unchanged.
            # It was briefly rewritten to ask for read access, on the strength of a test row of
            # mine that asserted that wording; `test_dispatch_canonical_closure_unresolved_entry_
            # names_remedy` refuted it. Its `loop` case is a self-referential symlink — an entry
            # the enumeration yields and the classification then cannot resolve, the identical
            # situation — and for that the fix really is the declaration's intended target, not
            # access. The row that looked like a second remedy defect was an over-specified
            # assertion, not a defect.
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
        # Observed, and classified without pathlib's suppression: this decides whether a file is
        # in the member's surface, so a lost entry or a hidden classification fault is the same
        # silently-smaller-surface hazard as the enumeration site. Last of the module's glob
        # call sites; `_pattern_matches` mentions `glob` only in prose.
        selected, glob_failures = _observed_glob(root, pattern)
        if glob_failures:
            raise UndecidableScopeContainment(
                f"cannot enumerate member pattern {pattern!r} below {root}: {glob_failures[0]}"
            )
        return any(p == path and _classified_is_file(p) for p in selected)
    except (OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, UndecidableScopeContainment):
            raise
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
    about to create is unaffected. **A stat that FAILS is a different fact from a file that is
    absent**, and this returns ``None`` for it. An earlier revision of this docstring said a failed
    stat "leaves the lexical answer standing, which is the behaviour that was there before" — which
    let an unreadable filesystem certify disjointness, the exact substitution this check exists to
    stop (root, 2026-09-07; row Q pins it by faulting `Path.stat` around the real comparison).

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
    # **A regular file spelled as a directory is refused however the member reached it.** The
    # check below covers `location.files`, so a DECLARED file refused; a file the reader SELECTED
    # through `location.patterns` was ruled outside by `_local_disjoint_established` first and
    # never arrived here — receipt-only `main()` returned 10 for `…/dumpe2fs` and 0 for
    # `…/dumpe2fs/`, the same file under two spellings bound to the same hash (review critical,
    # four families, at `d1d7a8204` onward).
    #
    # Placed above `broad` so it precedes the partial-scope logic entirely.
    #
    # **Not gated on `scope_pattern is None`, because a wildcard tail is the same subject.**
    # It was, and `file/*`, `file/**` and `file/**/*` therefore carried a pattern and skipped the
    # guard: the literal and the bare directory spelling refused while all three tails admitted
    # with `ok=True, reason=eligible`, against a member selecting that very file (review critical,
    # codex, at `f68d19e7e`). Appending a descendant pattern to a REGULAR FILE does not make it a
    # partial scope; it makes it the same inconsistent file-as-directory subject in another dress,
    # and the empty descendant expansion is what let it through.
    #
    # The legitimate partial scope survives on the OTHER half of the gate, not this one: in
    # `…/hostname*` the base is the containing DIRECTORY and the pattern is a sibling selector, so
    # `path` is not in the selected surface and the guard never fires. That is why removing this
    # restriction closes the three tails without touching the case it was there to protect.
    #
    # `_member_selected_surface` and not the pattern set — a content-query entry that fails its
    # own predicate is off the surface, so an alias of a pattern-matched, query-rejected file is
    # still not refused here. Building this on patterns would have re-broken that.
    #
    # `path in surface` is tested before `_identity_reaches_surface`, which raises rather than
    # answering False when a comparison cannot be made: the cheap exact match answers first and
    # only an alias question reaches the comparison that can refuse for a different reason.
    if dirlike:
        surface = _member_selected_surface(member)
        if path in surface or _identity_reaches_surface((path,), surface):
            _refuse_directory_spelled_file(path)
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
                # Unsuppressed: this decides which containment QUESTION is asked of the
                # candidate, so a swallowed ELOOP answering False would reframe a directory as
                # a file. Converted by decision ROLE, not as a blanket substitution.
                #
                # **PINNED — role 2 in the ledger above.** Rolling this call back to
                # `candidate.is_dir()` reddens `S2w`, which pins the caller obligation: this
                # function, not some later one, must make the classification it decides on.
                #
                # It was carried as UNPINNED for several rounds and the label was right at the
                # time: a steady fault raises in `_resolve_external_scope_path`'s
                # `resolve(strict=True)` first — at `:2385` for a literal spelling, through the
                # scope-glob wrapper at `:3055` otherwise — so no fault-injecting arrangement
                # reached it. The caller obligation is a different claim from end-to-end
                # reachability, and it is the one that could be pinned.
                candidate_is_dir = _classified_is_dir(candidate)
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
    if aliased:
        # CURRENT STATE: identity is ASKED, and only for its refusal — an unreadable comparison
        # must raise rather than quietly become "not contained". Its positive answer is NOT a
        # containment proof. The paragraph below is the repaired defect's history, in the past
        # tense; it is not a record of an outstanding contradiction. A reviewer read an earlier
        # version of this block as recording one, which is a fair reading of prose that narrates
        # a defect at the site of its fix, so the state is now stated before the story.
        #
        # HISTORY. `return all(...)` over the CURRENT expansion declared the whole scope contained
        # whenever every file the directory happened to hold today was a selection or an alias of
        # one. Reproduced by codex at `81962feab` on a real pair — an `fs.glob` member rooted at
        # `/usr/bin` with patterns `['fsck.ext2']` and its hard link `e2fsck`, where the scope
        # `e2fsck*` returned all_inside=True and was refused, while `e2fsckscope` was
        # independently admitted and the partial-scope predicate returned True for that same glob.
        #
        # A present expansion cannot establish exhaustive containment of an unbounded prospective
        # language: `e2fsck*` names files that do not exist yet, and those are not in the member.
        # This is the rule already written 35 lines above in this same function — *existing files
        # can disprove containment, but cannot establish the proof* — and the coordinator's
        # 2026-09-08 ruling, which is explicit that prospective effect scope is not restricted to
        # trailing-slash directory notation and applies to a declared glob's denoted language.
        #
        # So the identity hit is OVERLAP, and the aliases join the surface for the existing
        # partial-scope rules to decide — which is what this block's own comment above already
        # said it did. Those rules then establish an outside witness or return a NAMED UNDECIDABLE
        # refusal; neither an any-overlap veto nor indiscriminate broad admission follows.
        _identity_reaches_surface(aliased, identity_surface)

    # A FINITE language keeps its whole-language proof, which the ruling explicitly preserves.
    # `alias[12]` denotes exactly two names, so the set can be closed and checked; `tool*` cannot.
    # The names are enumerated from the PATTERN, never from the current expansion — a name the
    # language denotes but nobody has created is not inside the member, and proving containment
    # from the files that happen to exist is the defect this block was reported for.
    language = _finite_scope_language(scope_pattern)
    if language is not None:
        denoted = tuple(path / name for name in language)
        return all(
            target in identity_surface or _identity_reaches_surface((target,), identity_surface)
            for target in denoted
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


def _unreadable_repository_identity(checkout: Path, exc: Exception) -> UndecidableScopeContainment:
    """One refusal for every way the identity read can fail to answer."""
    error = UndecidableScopeContainment(
        f"repository identity of {checkout} cannot be read: {exc}; an unreadable history is "
        "not evidence that two checkouts are unrelated"
    )
    error.remedy = (
        f"repair git access for {checkout} (it must answer `git rev-parse --show-toplevel` "
        "and `git rev-list --max-parents=0 HEAD`), then retry the dispatch"
    )
    return error


def _repository_identity(checkout: Path) -> frozenset[str] | None:
    """Verify a checkout root and identify its history without reading remote credentials.

    THREE states, and only two of them are answers (review finding, claude, at `850ccfdbb`,
    reproduced by injecting `TimeoutExpired` into the identity read):

    - a verified history -> the frozenset of root commits;
    - **not this repository's root**, or no root commits -> ``None``, a decided negative;
    - the identity CANNOT BE READ -> raises, because it is not a negative at all.

    Collapsing the third into ``None`` made an unreadable git call establish disjointness. The
    caller drops non-matching checkouts, so a timeout silently removed the declared member's
    checkout from the candidate list, containment was never tried there, and a scope the guard
    refuses with git working was ADMITTED with git unavailable — measured as all_inside True then
    False on one arrangement. Unknown repository identity cannot establish disjointness, and this
    is the same verified/refuted/unknown collapse the rest of this module refuses elsewhere.
    """
    try:
        # A path that is not a directory cannot be a checkout, and git cannot even be asked: it
        # fails with "cannot change to ...", which carries no "not a git repository" and would
        # otherwise be read as unknown. Decided here, from the filesystem, before running git.
        # UNSUPPRESSED, for the same reason as the discovery check: `Path.is_dir` answers False
        # for an unreadable directory and this handler would never see it, so "cannot read"
        # became "not a directory" and the identity read was skipped entirely.
        if not _classified_is_dir(checkout):
            return None
    except (OSError, RuntimeError) as exc:
        raise _unreadable_repository_identity(checkout, exc) from exc
    try:
        top = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        if not top or Path(top).resolve() != checkout.resolve():
            return None
        roots = subprocess.run(
            ["git", "-C", str(checkout), "rev-list", "--max-parents=0", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.splitlines()
    except subprocess.CalledProcessError as exc:
        # A NONZERO EXIT IS NOT AN ANSWER (review finding, all four families, at `e6fe8780c`).
        # My first split put the line at the exception type and read `CalledProcessError` as
        # "git ran and said no". It does not say that: git exits 128 both for a directory that
        # is not a repository AND for a repository it cannot read — a corrupt object store, a
        # permission fault, an unborn HEAD. Treating the exit status as a verdict erased the
        # projections of a checkout that exists and could not be read, and admitted work wholly
        # inside it.
        #
        # So ASK GIT, which is the authority on the question, rather than inferring from the
        # exit code or guessing at `.git`'s shape. Measured:
        #
        #     empty `.git` dir   rc=128  "fatal: not a git repository ..."
        #     no `.git` at all   rc=128  "fatal: not a git repository ..."
        #     real, unborn HEAD  rev-parse rc=0; rev-list "ambiguous argument 'HEAD'"
        #
        # Only git's own "not a git repository" is a decided negative. Every other failure is
        # unknown, and unknown cannot establish disjointness.
        if "not a git repository" in (exc.stderr or ""):
            return None
        raise _unreadable_repository_identity(checkout, exc) from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        # git could not run or did not finish. Nothing was answered, so nothing is refuted.
        raise _unreadable_repository_identity(checkout, exc) from exc
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
    text = ref.replace("\\", "/")  # no-trim rule, stated at _filesystem_scope_parts
    if text.startswith("/") or text.startswith("~"):
        return []
    segments, _, _ = _filesystem_scope_parts(ref)
    # An empty literal prefix still names the repository root; apply its glob there.
    relative = Path(*segments)
    roots: set[Path] = set()
    for member in verdicts.decayed:
        for location in (*member.roots, *member.files):
            for candidate in (location, *location.parents):
                # Discovering the checkout is itself a filesystem question, and it decides which
                # candidates exist at all: a permission fault on one ancestor silently yields a
                # SHORTER root set, so containment is never tried under the checkout that was
                # skipped and the scope is admitted (review finding, codex, at `850ccfdbb`).
                # Seventh instance of this family in this module, and the same shape as the
                # identity read directly below — an unreadable answer becoming a negative one.
                try:
                    # UNSUPPRESSED. `Path.exists` swallows the ignorable errnos, so the handler
                    # below could not fire and the comment above described a case the code could
                    # not detect (review finding, codex, at `eda8b35a0`).
                    discovered = _classified_exists(candidate / ".git")
                    resolved = candidate.resolve() if discovered else None
                except (OSError, RuntimeError) as exc:
                    error = UndecidableScopeContainment(
                        f"checkout discovery for declared location {location} cannot inspect "
                        f"{candidate}: {exc}; a checkout that cannot be found is not a checkout "
                        "that is absent"
                    )
                    error.remedy = (
                        f"repair filesystem access for {candidate}, then retry the dispatch"
                    )
                    raise error from exc
                if resolved is not None:
                    roots.add(resolved)
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


def _member_selected_surface(member: DecayedMember) -> frozenset[Path]:
    """The files this member's READER selects, canonicalised — not what its patterns match.

    A content-query member's entry that fails its own predicate is off the surface; the
    concrete-alias loop in `_local_disjoint_established` says so and skips it. Counting such an
    entry here made one function give two answers about one file, and refused a candidate that
    aliased something the member never selected (review finding, codex, 2026-09-07; measured as
    `UndecidableScopeContainment` on an alias of a pattern-matched, query-rejected file).
    Declared `location.files` are selected by declaration, so no predicate filters them.
    """

    return frozenset(
        target
        for entry, target in _canonical_member_entries(member).items()
        if not (
            member.reader == "fs.content_query"
            and member.content_query is not None
            and not _content_query_matches(entry, member.content_query)
        )
    ) | {_resolve_external_scope_path(file) for file in _selected_member_files(member)}


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
    # Every comparison below is between path STRINGS, and `_resolve_external_scope_path` unifies
    # symlinks but not hard links — two directory entries sharing an inode stay two distinct
    # canonical names. So this predicate certified disjointness for a scope holding a file that IS
    # one of the member's selected files under another spelling, and said so while containment said
    # the opposite about the same pair (review finding, glm/gemini/codex, 2026-09-07; measured as
    # contained=True and disjoint_established=True together).
    #
    # A BROAD spelling makes the same false claim about the files it currently expands to: the
    # literal repair alone left `tool*` and `elsewhere/` certifying disjointness over a directory
    # holding a hard link the literal spelling of refused (four families, 2026-09-07; measured as
    # disjoint=True for both broad spellings beside disjoint=None for the literal one).
    #
    # Only the disjointness CLAIM is repaired, which is why this belongs here and not in the
    # witness. This predicate answers "is the candidate outside", never "is the scope wholly
    # inside": withholding it leaves `_scope_admission_established` free to fall through to the
    # partial-scope witness, which admits these scopes exactly as before, and containment keeps its
    # own answer for the wholly-aliased case. Putting the same check in the witness is what made
    # the withdrawn `aa5939179` a policy change instead of a repair.
    surface = _member_selected_surface(member)
    if surface:
        # ONE question, asked of every spelling: do the concrete files this candidate denotes
        # include one of the member's selected files under another name? Only the input differs —
        # a literal candidate denotes itself, a glob or a directory denotes what it currently
        # expands to. Written as an if/else around two separate identity calls this read as a
        # narrowing to the literal case, and two reviewer families in a row reported the broad
        # spellings as unguarded on that reading (gemini and claude, 2026-09-07). They were
        # wrong about the behaviour and right that the shape invited it; this says the same
        # thing with one predicate and one exit.
        #
        # **The limit, stated because the prose above overstated it.** A directory spelling of a
        # REGULAR FILE expands to nothing — a file has no descendants — so `denoted` is empty and
        # no identity comparison happens here at all. This predicate therefore says nothing about
        # that spelling, in either direction. It is refused earlier now, by the selected-surface
        # guard in `ref_within_member`, and NOT by anything on this path (review finding, codex).
        # Nothing below is changed by that note: the guard is placed where the declared-file
        # refusal already lived, deliberately not here, for the reason recorded above about
        # `aa5939179`.
        if not dirlike and scope_pattern is None:
            denoted: tuple[Path, ...] = (path,)
        else:
            expansion = _canonical_scope_entries(path, scope_pattern or "**/*", member)
            denoted = tuple(target for target in expansion.values() if target not in surface)
        if denoted and _identity_reaches_surface(denoted, surface):
            return None
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

    **Two search strategies, one predicate.** `_glob_witnesses` samples the first choice in each
    character class rather than exhausting it, so `alias[123]` and `alias[312]` name one finite
    language and got two answers — the first refused, the second admitted, on identical files
    (root, 2026-09-07). Generating names is a heuristic for finding a witness; it is not what the
    predicate means. An entry the scope ACTUALLY expands to is a witness in exactly the same
    sense, and observing one costs no glob-language solving at all. Observed entries are tried
    first for that reason.

    This is a second way to find the same witness, not a second rule: the entry still has to be a
    file, still has to be the same relative tail under every checkout projection, and still has to
    be established outside EVERY member.

    **Correction, 2026-09-08.** This docstring used to end "a scope whose entries are all decayed
    finds nothing here", and that is false — measured, not argued. It holds for the OBSERVED
    strategy only. For a dirlike scope over a directory whose single entry is a hard link to a
    member's selected file, the observed tail yields `None` exactly as intended, and the
    generated strategy below then supplies `scope` — a name that does not exist — which is
    trivially outside every selection, so the scope is admitted:

        observed  'selected-alias.txt'  exists=True   disjoint_established=None
        generated 'scope'               exists=False  disjoint_established=True

    The two strategies do not answer the same question. An observed entry is a fact about what
    the scope holds; a generated name is a fact about the scope's LANGUAGE — that it can name
    files no member selects, including future ones. Under the language reading this admission is
    correct and consistent: `selected-alias[.]txt` denotes one name and is refused as wholly
    decayed, while `aliased/` denotes unboundedly many and is partial.

    Whether that is the RIGHT reading when every file the directory currently holds is a decayed
    file under another name is a policy question, and it is not settled here. Substituting an
    alias-overlap veto for this predicate is the withdrawn `aa5939179`, which root reproduced as
    a regression through receipt-only `main()`; reviewer convergence is evidence about a
    mechanism, not authority over a policy. Raised for the owner with the measurement above
    rather than decided by editing this function.
    """
    if not dirlike and scope_pattern is None:
        return False
    pattern = scope_pattern or "**/*"

    def _witnessed(witness: str) -> bool:
        # The same relative tail must work in every equivalent checkout. Independent
        # witnesses per checkout can each land inside another projection's decayed union.
        candidates = tuple(root / witness for root in (path, *projections))
        if any(candidate.is_dir() for candidate in candidates):
            return False
        return all(
            _local_disjoint_established(candidate, False, None, member) is True
            for candidate in candidates
            for member in members
        )

    for witness in sorted(_observed_scope_tails(path, pattern, members)):
        if _witnessed(witness):
            return True
    for witness in _glob_witnesses(pattern):
        if not _pattern_matches(witness, pattern):
            continue
        if _witnessed(witness):
            return True
    return False


def _observed_scope_tails(
    path: Path, pattern: str, members: tuple[DecayedMember, ...]
) -> frozenset[str]:
    """Relative tails the scope currently expands to, agreed by every member's expansion.

    Expansion is validated per member — a traversal one member refuses is not evidence about that
    member's surface — so only tails every member's expansion produced are offered as witnesses.
    An expansion that cannot be made yields nothing rather than a smaller set: a failed
    observation is not a shorter list of files.
    """

    agreed: frozenset[str] | None = None
    for member in members:
        try:
            entries = _canonical_scope_entries(path, pattern, member)
        except (OSError, RuntimeError, UndecidableScopeContainment):
            return frozenset()
        tails = set()
        for entry in entries:
            try:
                tails.add(entry.relative_to(path).as_posix())
            except ValueError:
                continue
        agreed = frozenset(tails) if agreed is None else (agreed & frozenset(tails))
    return agreed or frozenset()


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
    # `frame_vault_root()` ends in `expanduser()`, which raises RuntimeError when no home
    # directory can be resolved — so the DEFAULT vault root escaped the refusal contract while an
    # explicitly passed one could not fail at all (review finding, claude, at `24574cc4f`).
    #
    # **Sixth instance of this family, and this one is on the line directly above a comment I
    # wrote today.** R2's docstring named the pattern, R2b repeated the naming, R2c said noting a
    # pattern is not searching for its other members — and I then edited the three lines below
    # this call without reading it. The lesson is not the fix: it is that a fault family is
    # closed by enumerating its call sites once, not by recognising it six times.
    if vault_root is None:
        try:
            vault_root = frame_vault_root()
        except (OSError, RuntimeError) as exc:
            error = UndecidableScopeContainment(
                f"the default frame vault root cannot be resolved: {exc}; scope containment "
                "cannot be decided against it"
            )
            error.remedy = (
                f"set {FRAME_VAULT_ROOT_ENV} to an absolute path, or repair home-directory "
                "resolution, then retry the dispatch"
            )
            raise error from exc
    matches: list[ScopeMatch] = []
    outside: list[str] = []
    # Blank rule, stated once here and pointed at from the other site that takes a declared
    # subject. A reference is ABSENT only when it is the empty string. `" "` is a legal POSIX
    # filename, so it is a declaration and must be answered — matched, or refused by name.
    #
    # `.strip()` truthiness made a whitespace-only reference EVAPORATE, and the loss was not only
    # its name (review finding, codex, at `5007ed238`). An emptied list also skips the guard just
    # below, which is `if declared_refs and verdicts.unmatchable` — so a scope of `[" "]` against
    # a member with no containable location returned "not inside" where an ordinary reference
    # raised `UncontainableMemberLocation`. Trimming a name to nothing turned a refusal into a
    # verdict, which is a fail-open on the undecidable path.
    declared_refs: list[str] = []
    for index, ref in enumerate(refs):
        text = str(ref)
        if not text:
            raise NonCanonicalScopeRef(
                f"mutation_scope_refs[{index}] is the empty string, which cannot name a surface. "
                "An unrepresentable declaration is refused by name; emptying the scope instead "
                "would make it indistinguishable from declaring no scope at all"
            )
        declared_refs.append(text)
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
        # No-trim rule, stated at _filesystem_scope_parts. `declared_refs` above already
        # dropped blank entries, which is the separate question; this must not edit a name.
        text = str(ref)
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
