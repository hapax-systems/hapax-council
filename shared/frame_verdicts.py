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

#: Same set as ``scripts/check-producer-consumers.py``'s ``DECAY_RELATIONS``: a member that has
#: exited scope, been superseded, or been discharged is no longer a surface work may land on.
DECAY_RELATIONS = frozenset({"scope_exited", "superseded", "discharged"})

PRODUCER_REMEDY = (
    "run the frame producer — `systemctl --user start hapax-frame-iteration.service`, or from "
    "~/Documents/Personal/30-areas/hapax: `uv run --with pyyaml python -m frame.procedure.run` — "
    "then retry the dispatch"
)

_EPOCH_NAME = re.compile(r"^(\d{8}T\d{6}Z)-[0-9a-f]+$")
_NON_FILESYSTEM_ROOT = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_WILDCARD = re.compile(r"[*?\[]")


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

    @property
    def matchable(self) -> bool:
        return bool(self.roots or self.files)


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
    for element in elements:
        payload = element.get("payload") if isinstance(element, dict) else None
        verdicts = payload.get("verdicts") if isinstance(payload, dict) else None
        if isinstance(verdicts, list):
            rows.extend(row for row in verdicts if isinstance(row, dict))
    if not rows:
        raise FrameVerdictsUnavailable(
            f"{elements_path} carries no verdict rows (no element has payload.verdicts); the "
            "epoch is not a frame-reduction run"
        )
    decay: dict[str, set[str]] = {}
    for row in rows:
        subject = row.get("subject")
        relation = str(row.get("relation") or "")
        verdict = row.get("verdict")
        if (
            isinstance(subject, dict)
            and isinstance(subject.get("member_id"), str)
            and relation in DECAY_RELATIONS
            and (verdict is True or str(verdict).upper() == "TRUE")
        ):
            decay.setdefault(str(subject["member_id"]), set()).add(relation)

    mass_path = root / "declaration" / "mass.yaml"
    try:
        mass = yaml.safe_load(mass_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FrameVerdictsUnavailable(f"{mass_path} is unreadable or malformed: {exc}") from exc
    members = mass.get("members") if isinstance(mass, dict) else None
    if not isinstance(members, list):
        raise FrameVerdictsUnavailable(f"{mass_path} must declare a members list")

    decayed: list[DecayedMember] = []
    unmatchable: list[str] = []
    seen: set[str] = set()
    for member in members:
        if not isinstance(member, dict):
            continue
        member_id = str(member.get("id"))
        if member_id not in decay:
            continue
        seen.add(member_id)
        roots, patterns, files, foreign = _member_location(member)
        for relation in sorted(decay[member_id]):
            decayed.append(DecayedMember(member_id, relation, roots, patterns, files))
        if foreign and not roots and not files:
            unmatchable.append(member_id)
    # A verdict about a member the mass no longer declares is still a verdict; it cannot be
    # matched, and saying so beats dropping it.
    unmatchable.extend(sorted(set(decay) - seen))
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
    path = path.absolute()
    if path.is_dir():
        dirlike = True
    return path, dirlike


def ref_within_member(path: Path, dirlike: bool, member: DecayedMember) -> bool:
    if any(path == file for file in member.files):
        return True
    for root in member.roots:
        if path != root and root not in path.parents:
            continue
        if not member.patterns or dirlike or path == root:
            return True
        for pattern in member.patterns:
            if "**" in pattern or "/" in pattern:
                if fnmatch.fnmatch(path.relative_to(root).as_posix(), pattern.replace("**/", "*")):
                    return True
                if "**" in pattern:
                    return True
            elif fnmatch.fnmatch(path.name, pattern):
                return True
    return False


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
        hit = next(
            (member for member in verdicts.decayed if ref_within_member(path, dirlike, member)),
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
