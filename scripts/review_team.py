"""review_team — PR review-team constitution, dossier synthesis, admission gate.

Pure logic for the PR review-team system (spec:
``~/Documents/Personal/30-areas/hapax/pr-review-team-design-2026-06-11.md``,
CASE-ROUTING-OPERATIONALIZATION-20260609):

- lens selection: changed files -> mandatory lens charters (registry §1)
- tactical sizing: task risk x touched surfaces -> team class (registry §2)
- strategic constitution: cross model-family seats, the writer's family never
  holds the majority alone (registry §3)
- dossier synthesis: blind reviewer verdicts -> quorum verdict + escalations
- admission gate: ``review_team_verdict_blockers`` consumed by
  ``scripts/cc-pr-autoqueue.py`` (no quorum, no merge)

Registry: ``config/review-lenses/registry.yaml``. Dossiers live beside the
cc-task note as ``<task_id>.review-dossier.yaml`` (same pattern as acceptance
receipts). Emergency bypass: ``HAPAX_REVIEW_TEAM_GATE_OFF=1`` disables only
the admission blockers; the dispatcher killswitch is
``HAPAX_REVIEW_TEAM_DISPATCH_OFF=1``.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = REPO_ROOT / "config" / "review-lenses" / "registry.yaml"
LENS_DIR = REPO_ROOT / "config" / "review-lenses"

#: Dossier filename suffix; the dossier lives beside the task note.
REVIEW_DOSSIER_SUFFIX = ".review-dossier.yaml"

#: The only dossier verdict that admits a PR.
QUORUM_ACCEPT = "quorum-accept"

#: Reviewer verdicts that count toward the accept quorum.
ACCEPT_VERDICTS = frozenset({"accept", "accept-with-findings"})

#: Reviewer verdicts the dispatcher may record. ``invalid-output`` is what an
#: unparseable reviewer reply becomes — it never counts as an accept.
REVIEWER_VERDICTS = frozenset({"accept", "accept-with-findings", "block", "invalid-output"})

GATE_KILLSWITCH_ENV = "HAPAX_REVIEW_TEAM_GATE_OFF"


def gate_disabled() -> bool:
    """True when the operator killswitch disables the review-team gate."""

    return os.environ.get(GATE_KILLSWITCH_ENV, "").strip() not in {"", "0"}


def load_lens_registry(path: Path | None = None) -> dict[str, Any]:
    registry_path = path or DEFAULT_REGISTRY_PATH
    loaded = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or loaded.get("registry_schema") != 1:
        raise ValueError(f"lens registry at {registry_path} is not a registry_schema:1 mapping")
    return loaded


def _matches(path: str, pattern: str) -> bool:
    """Glob match per registry semantics: ``dir/**`` is a prefix, else fnmatch."""

    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch.fnmatch(path, pattern)


def lenses_for_files(changed_files: Sequence[str], registry: Mapping[str, Any]) -> tuple[str, ...]:
    """Mandatory lenses for a diff: always-on + matched surfaces (+ tests-only)."""

    files = [f.strip() for f in changed_files if f and f.strip()]
    ordered: list[str] = list(registry["always_on_lenses"])
    for row in registry["surface_lenses"]:
        if any(_matches(f, glob) for f in files for glob in row["globs"]):
            ordered.extend(row["lenses"])
    if files and all(_matches(f, "tests/**") for f in files):
        ordered.extend(registry["tests_only_lenses"])
    seen: set[str] = set()
    out: list[str] = []
    for lens in ordered:
        if lens not in seen:
            seen.add(lens)
            out.append(lens)
    return tuple(out)


def team_class_for(
    frontmatter: Mapping[str, Any],
    changed_files: Sequence[str],
    registry: Mapping[str, Any],
) -> str:
    """Tactical sizing class. T1 surfaces beat docs-only (fail toward more review)."""

    files = [f.strip() for f in changed_files if f and f.strip()]
    risk = str(frontmatter.get("risk_tier") or "").strip().upper()
    if risk == "T1" or any(
        _matches(f, glob) for f in files for glob in registry["t1_surface_globs"]
    ):
        return "t1_critical"
    docs_globs = registry["docs_only_globs"]
    docs_only = bool(files) and all(any(_matches(f, g) for g in docs_globs) for f in files)
    if risk == "T3" or docs_only:
        return "t3_docs"
    return "t2_standard"


def writer_family_for_lane(lane: str | None, registry: Mapping[str, Any]) -> str:
    """Model family of the authoring lane (exact map, then prefixes, then default)."""

    lane_families = registry["lane_families"]
    lane_norm = (lane or "").strip().lower()
    if not lane_norm:
        return lane_families["default"]
    exact = lane_families.get("exact") or {}
    if lane_norm in exact:
        return exact[lane_norm]
    for prefix, family in (lane_families.get("prefixes") or {}).items():
        if lane_norm.startswith(prefix):
            return family
    return lane_families["default"]


@dataclass(frozen=True)
class Seat:
    id: str
    family: str


@dataclass(frozen=True)
class Constitution:
    team_class: str
    quorum_required: int
    seats: tuple[Seat, ...]
    notes: tuple[str, ...]


def constitute_team(
    team_class: str,
    writer_family: str,
    registry: Mapping[str, Any],
    *,
    pr_number: int,
    available_families: Sequence[str] | None = None,
) -> Constitution:
    """Constitute the review team for a class — deterministic, fail-closed.

    Rules (spec §2/§3): t3 = 2 seats / 2 families; t2 = 3 seats, >=2 families;
    t1 = 4-5 seats, ALL roster families or :class:`ValueError`. The writer's
    family never holds the majority alone (cap = ``size // 2``); non-writer
    families seat first, rotated by ``pr_number`` for fairness.
    """

    sizing = registry["sizing"][team_class]
    roster = [entry["family"] for entry in registry["families"]]
    if available_families is None:
        available = list(roster)
    else:
        wanted = {f for f in available_families}
        available = [f for f in roster if f in wanted]
    notes = [f"family_unavailable:{f}" for f in roster if f not in available]

    if team_class == "t1_critical":
        size = int(sizing["team_size_min"])
        if sizing.get("require_all_families"):
            missing = [f for f in roster if f not in available]
            if missing:
                raise ValueError(
                    "t1_critical requires every model family on the team; "
                    f"unavailable family: {','.join(missing)}"
                )
    else:
        size = int(sizing["team_size"])
    min_families = int(sizing.get("min_families", 1))
    if not available:
        raise ValueError("no reviewer families available")
    if len(available) < min_families:
        raise ValueError(
            f"{team_class} requires >={min_families} model families; "
            f"only available: {','.join(available)}"
        )

    rot = pr_number % len(available)
    rotated = available[rot:] + available[:rot]
    non_writer = [f for f in rotated if f != writer_family]
    writer_cap = size // 2  # strict-majority guard: writer seats can never reach size//2 + 1

    seat_families: list[str] = []
    for family in non_writer:  # one seat per non-writer family first
        if len(seat_families) < size:
            seat_families.append(family)
    writer_seats = 0
    if writer_family in rotated and len(seat_families) < size and writer_seats < writer_cap:
        seat_families.append(writer_family)
        writer_seats += 1
    fill = 0
    while len(seat_families) < size:
        if non_writer:
            seat_families.append(non_writer[fill % len(non_writer)])
            fill += 1
        elif writer_seats < writer_cap:
            seat_families.append(writer_family)
            writer_seats += 1
        else:
            raise ValueError(
                "cannot constitute team: only the writer's own family is available "
                "and it would hold the majority alone"
            )
    if len(set(seat_families)) < min_families:
        raise ValueError(
            f"constituted team spans {len(set(seat_families))} families; "
            f"{team_class} requires >={min_families}"
        )

    counts: dict[str, int] = {}
    seats: list[Seat] = []
    for family in seat_families:
        counts[family] = counts.get(family, 0) + 1
        seats.append(Seat(id=f"{family}-{counts[family]}", family=family))
    return Constitution(
        team_class=team_class,
        quorum_required=int(sizing["quorum_accept"]),
        seats=tuple(seats),
        notes=tuple(notes),
    )
