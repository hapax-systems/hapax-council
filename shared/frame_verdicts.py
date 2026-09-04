"""The frame's accountability verdicts, read at a work-selection point.

Stated with no estate noun in it: a work-selection point admits a unit of work only after
consulting the current accountability verdicts; work whose declared effect surface lies wholly
inside surfaces the verdicts mark as out of accountability is refused with the remedy named, and a
verdict set that is absent or older than its producer's cadence refuses too, naming the producer to
run. That is the whole architecture. Everything below it is a binding, declared here so it can be
swapped:

- the verdict set is the newest epoch of the frame procedure (``_runs/epochs/<ts>-<id>/elements.json``),
  produced by ``hapax-frame-iteration.timer`` every :data:`FRAME_ITERATION_CADENCE_S`;
- the surfaces are the members of the procedure's ``declaration/mass.yaml`` and their declared
  filesystem locations;
- the effect surface of a unit of work is its task row's ``mutation_scope_refs``;
- "out of accountability" is a TRUE verdict under one of :data:`DECAY_RELATIONS`, the same three
  relations the consumer-side producer scanner treats as producer decay.

Members whose location is not a filesystem path (``gh://``, ``podium:``, any host-qualified or
scheme-qualified root) cannot contain a filesystem ref; they are reported as unmatchable rather
than silently treated as empty, so a verdict about them is never mistaken for "nothing matched".
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

PRODUCER_REMEDY = (
    "run the frame producer — `systemctl --user start hapax-frame-iteration.service`, or from "
    "~/Documents/Personal/30-areas/hapax: `uv run --with pyyaml python -m frame.procedure.run` — "
    "then retry the dispatch"
)

_EPOCH_NAME = re.compile(r"^(\d{8}T\d{6}Z)-[0-9a-f]+$")
_NON_FILESYSTEM_ROOT = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_WILDCARD = re.compile(r"[*?\[]")


class NonCanonicalScopeRef(ValueError):
    """A declared ref cannot be contained by any member because it climbs out of its own tree."""


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


@dataclass(frozen=True)
class FrameVerdicts:
    epoch: str
    elements_path: Path
    produced_at: datetime
    decayed: tuple[DecayedMember, ...]
    #: decayed members whose declared location is not a filesystem path — a verdict this reader
    #: cannot apply to a ref, stated rather than dropped
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


def _member_location(
    member: dict[str, object],
) -> tuple[tuple[Path, ...], tuple[str, ...], tuple[Path, ...], bool]:
    """Filesystem roots, file patterns, explicit files, and whether any root was non-filesystem."""
    location = member.get("location")
    if not isinstance(location, dict):
        return (), (), (), False
    raw_roots: list[str] = []
    if isinstance(location.get("path"), str):
        raw_roots.append(str(location["path"]))
    if isinstance(location.get("roots"), list):
        raw_roots.extend(str(item) for item in location["roots"] if isinstance(item, str))
    roots: list[Path] = []
    foreign = False
    for raw in raw_roots:
        if _NON_FILESYSTEM_ROOT.match(raw):
            foreign = True
            continue
        roots.append(Path(raw).expanduser().absolute())
    patterns = location.get("patterns")
    globs = tuple(str(item) for item in patterns) if isinstance(patterns, list) else ()
    files_raw = location.get("files")
    files = (
        tuple(
            Path(str(item)).expanduser().absolute()
            for item in files_raw
            if isinstance(item, str) and not _NON_FILESYSTEM_ROOT.match(item)
        )
        if isinstance(files_raw, list)
        else ()
    )
    return tuple(roots), globs, files, foreign


def load_frame_verdicts(
    procedure_root: Path | None = None,
    *,
    now: datetime | None = None,
    max_age_s: int = FRAME_EPOCH_MAX_AGE_S,
) -> FrameVerdicts:
    """Read the newest epoch's verdicts and the mass they are about; refuse when either is unusable.

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
    epoch_dir = latest_epoch_dir(root)
    if epoch_dir is None:
        raise FrameVerdictsUnavailable(
            f"no frame epoch with an elements.json under {root / '_runs' / 'epochs'}"
        )
    produced_at = epoch_produced_at(epoch_dir.name)
    assert produced_at is not None  # latest_epoch_dir only returns parseable names
    current = now if now is not None else datetime.now(UTC)
    age = current - produced_at
    if age > timedelta(seconds=max_age_s):
        raise FrameVerdictsUnavailable(
            f"latest frame epoch {epoch_dir.name} is {int(age.total_seconds()) // 60} min old, "
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
    rows: list[dict[str, object]] = []
    malformed = 0
    for element in elements:
        payload = element.get("payload") if isinstance(element, dict) else None
        verdicts = payload.get("verdicts") if isinstance(payload, dict) else None
        if isinstance(verdicts, list):
            for row in verdicts:
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    malformed += 1
    if malformed:
        # Skipping a malformed row empties the decayed set and the guard admits everything — failing
        # open at the one point it exists to fail closed (review finding, four families,
        # 2026-09-04). A report this reader cannot read whole is a report it must not act on.
        raise FrameVerdictsUnavailable(
            f"{elements_path} carries {malformed} verdict row(s) this reader cannot parse; a "
            "partially readable report would silently shrink the decayed set"
        )
    if not rows:
        raise FrameVerdictsUnavailable(
            f"{elements_path} carries no verdict rows (no element has payload.verdicts); the "
            "epoch is not a frame-reduction run"
        )
    decay: dict[str, set[str]] = {}
    unknown_true: set[str] = set()
    for row in rows:
        subject = row.get("subject")
        relation = str(row.get("relation") or "")
        verdict = row.get("verdict")
        is_true = verdict is True or str(verdict).upper() == "TRUE"
        if not relation:
            raise FrameVerdictsUnavailable(
                f"{elements_path} carries a verdict row with no relation; this reader cannot tell "
                "whether it decays a member"
            )
        if is_true and relation not in DECAY_RELATIONS and relation not in MODEL_RELATIONS:
            unknown_true.add(relation)
        if (
            isinstance(subject, dict)
            and isinstance(subject.get("member_id"), str)
            and relation in DECAY_RELATIONS
            and is_true
        ):
            decay.setdefault(str(subject["member_id"]), set()).add(relation)
    if unknown_true:
        # The producer gained a relation this reader does not classify. Guessing either way is a
        # decision about accountability made by omission, so it refuses and names the relation.
        raise FrameVerdictsUnavailable(
            f"{elements_path} carries TRUE verdicts under relation(s) "
            f"{sorted(unknown_true)} that this reader does not classify as decay or model; the "
            "producer's relation set has moved"
        )

    coverage_path = epoch_dir / "coverage.json"
    epoch_identities: dict[str, str] = {}
    if coverage_path.is_file():
        try:
            coverage_rows = json.loads(coverage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FrameVerdictsUnavailable(
                f"{coverage_path} is unreadable or malformed: {exc}; the verdicts cannot be bound "
                "to the declaration they were computed against"
            ) from exc
        if isinstance(coverage_rows, list):
            for row in coverage_rows:
                if isinstance(row, dict) and isinstance(row.get("member_id"), str):
                    identity = row.get("member_declaration_identity")
                    if isinstance(identity, str) and identity:
                        epoch_identities[row["member_id"]] = identity

    mass_path = root / "declaration" / "mass.yaml"
    try:
        mass = yaml.safe_load(mass_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FrameVerdictsUnavailable(f"{mass_path} is unreadable or malformed: {exc}") from exc
    members = mass.get("members") if isinstance(mass, dict) else None
    if not isinstance(members, list):
        raise FrameVerdictsUnavailable(f"{mass_path} must declare a members list")

    exclusions = mass.get("exclusions") or []
    decayed: list[DecayedMember] = []
    unmatchable: list[str] = []
    unbound: list[str] = []
    seen: set[str] = set()
    for member in members:
        if not isinstance(member, dict):
            continue
        member_id = str(member.get("id"))
        if member_id not in decay:
            continue
        seen.add(member_id)
        # The verdict was computed against the member as the epoch declared it. If the declaration
        # has moved since, applying the verdict would decay a surface nobody witnessed (review
        # finding, glm and codex, 2026-09-04). The identity is the producer's own, recomputed here
        # by the same rule; a test pins that it reproduces a real epoch's recorded value.
        epoch_identity = epoch_identities.get(member_id)
        if epoch_identity and epoch_identity != _member_declaration_identity(member, exclusions):
            unbound.append(member_id)
            continue
        roots, patterns, files, foreign = _member_location(member)
        for relation in sorted(decay[member_id]):
            decayed.append(DecayedMember(member_id, relation, roots, patterns, files))
        if foreign and not roots and not files:
            unmatchable.append(member_id)
    # A verdict about a member the mass no longer declares is still a verdict; it cannot be
    # matched, and saying so beats dropping it. A member whose declaration moved since the epoch is
    # named separately, because the remedy differs: re-run the producer.
    unmatchable.extend(sorted(set(decay) - seen))
    unmatchable.extend(sorted(unbound))
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


def _repo_relative_candidates(
    ref: str, verdicts: FrameVerdicts, *, council_root: Path
) -> list[Path]:
    """The same repository-relative ref rooted at each decayed member's declared repository root.

    In production the dispatcher runs from the activation worktree, while the mass declares council
    members at the canonical checkout, so a ref like `scripts/x.py` resolved against the running
    tree could never match — the guard would have been inert exactly where it runs (review finding,
    codex, 2026-09-04). A repo-relative ref is therefore also tried under each declared root whose
    basename matches the running checkout's repository name.
    """
    text = ref.strip().replace("\\", "/")
    if text.startswith("/") or text.startswith("~"):
        return []
    repo_name = council_root.name
    segments = [segment for segment in text.split("/") if segment not in ("", ".")]
    while segments and _WILDCARD.search(segments[-1]):
        segments.pop()
    if not segments:
        return []
    relative = Path(*segments)
    roots: set[Path] = set()
    for member in verdicts.decayed:
        for root in member.roots:
            for candidate in (root, *root.parents):
                if candidate.name == repo_name:
                    roots.add(candidate)
                    break
    roots.discard(council_root)
    return [root / relative for root in sorted(roots)]


def scope_within_decayed(
    refs: list[str] | tuple[str, ...],
    verdicts: FrameVerdicts,
    *,
    council_root: Path,
    vault_root: Path,
) -> ScopeVerdict:
    matches: list[ScopeMatch] = []
    outside: list[str] = []
    for ref in refs:
        if not str(ref).strip():
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
