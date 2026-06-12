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
import re
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
CHECKLIST_ITEM_RE = re.compile(r"^- \[ \] (?P<slug>[a-z0-9-]+):", re.MULTILINE)
CHECKLIST_VALUES = frozenset({"pass", "finding", "na"})
TRUTHY_ENV_VALUES = frozenset({"1", "true", "yes", "on"})


def gate_disabled() -> bool:
    """True when the operator killswitch disables the review-team gate."""

    return os.environ.get(GATE_KILLSWITCH_ENV, "").strip().lower() in TRUTHY_ENV_VALUES


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


# --- Task-note + charter lookup ----------------------------------------------


def _note_frontmatter(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        parsed = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


def find_task_note(
    vault_root: Path,
    *,
    pr_number: int | None = None,
    head_ref: str | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    """The cc-task note linked to a PR: by ``pr`` field first, else by branch."""

    branch_match: tuple[Path, dict[str, Any]] | None = None
    for folder in ("active", "closed"):
        root = vault_root / folder
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            fm = _note_frontmatter(path)
            if not fm or fm.get("type") != "cc-task":
                continue
            try:
                note_pr = int(fm.get("pr")) if fm.get("pr") is not None else None
            except (TypeError, ValueError):
                note_pr = None
            if pr_number is not None and note_pr == pr_number:
                return path, fm
            if branch_match is None and head_ref and str(fm.get("branch") or "") == head_ref:
                branch_match = (path, fm)
    return branch_match


def charter_text(lens: str, lens_dir: Path | None = None) -> str:
    """Full charter markdown for a lens (raises if the charter is missing)."""

    return ((lens_dir or LENS_DIR) / f"{lens}.md").read_text(encoding="utf-8")


def charter_checklist_items(lens: str, lens_dir: Path | None = None) -> tuple[str, ...]:
    """Checklist item slugs declared by a lens charter."""

    return tuple(CHECKLIST_ITEM_RE.findall(charter_text(lens, lens_dir)))


# --- Dossier synthesis --------------------------------------------------------


def _unresolved_criticals(reviews: Sequence[Mapping[str, Any]]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for review in reviews:
        for finding in review.get("findings") or []:
            if not isinstance(finding, Mapping):
                continue
            if str(finding.get("severity", "")).lower() == "critical" and not finding.get(
                "resolved"
            ):
                out.append((str(review.get("id")), dict(finding)))
    return out


def _accepting(reviews: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [r for r in reviews if str(r.get("verdict", "")).lower() in ACCEPT_VERDICTS]


def _review_checklist_blockers(
    review: Mapping[str, Any],
    lenses: Sequence[str],
    *,
    lens_dir: Path | None = None,
) -> tuple[str, ...]:
    verdict = str(review.get("verdict", "")).lower()
    if verdict not in ACCEPT_VERDICTS and verdict != "block":
        return ()

    checklist = review.get("checklist")
    reviewer = str(review.get("id") or "unknown")
    if not isinstance(checklist, Mapping):
        return (f"review_dossier_checklist_missing:{reviewer}",)

    blockers: list[str] = []
    for lens in lenses:
        lens_checklist = checklist.get(lens)
        if not isinstance(lens_checklist, Mapping):
            blockers.append(f"review_dossier_checklist_missing:{reviewer}:{lens}")
            continue
        try:
            expected = charter_checklist_items(str(lens), lens_dir=lens_dir)
        except OSError:
            blockers.append(f"review_dossier_checklist_lens_unreadable:{lens}")
            continue
        for item in expected:
            value = str(lens_checklist.get(item) or "").strip().lower()
            if value not in CHECKLIST_VALUES:
                blockers.append(f"review_dossier_checklist_item_missing:{reviewer}:{lens}:{item}")
    return tuple(blockers)


def _checklist_complete_accepts(
    reviews: Sequence[Mapping[str, Any]],
    lenses: Sequence[str],
) -> list[Mapping[str, Any]]:
    return [r for r in _accepting(reviews) if not _review_checklist_blockers(r, lenses)]


def _required_team_size(sizing: Mapping[str, Any]) -> int:
    return int(sizing.get("team_size") or sizing.get("team_size_min") or 1)


def _int_field(value: Any, field: str, blockers: list[str]) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        blockers.append(
            f"review_dossier_malformed:{field}:{value if value is not None else 'missing'}"
        )
        return None


def _task_class_floor(frontmatter: Mapping[str, Any] | None) -> str | None:
    if frontmatter is None:
        return None
    risk = str(frontmatter.get("risk_tier") or "").strip().upper()
    if risk == "T1":
        return "t1_critical"
    return None


def synthesize_dossier(
    *,
    task_id: str,
    pr_number: int,
    head_sha: str,
    team_class: str,
    registry: Mapping[str, Any],
    reviews: Sequence[Mapping[str, Any]],
    lenses: Sequence[str],
    constituted_at: str,
    constitution_notes: Sequence[str] = (),
) -> dict[str, Any]:
    """Reconcile blind reviews into a dossier (the synthesizer, spec §3/§5).

    Verdict ladder: any unresolved named critical -> ``blocked`` (criticals are
    resolved, not outvoted); else accepts >= quorum (t1 additionally needs >=1
    accept from EVERY roster family) -> ``quorum-accept``; else ``no-quorum``.
    Cross-family verdict splits and blocks without a named critical are
    escalated to the top of the dossier — family disagreement is signal.
    """

    sizing = registry["sizing"][team_class]
    roster = [entry["family"] for entry in registry["families"]]
    accepts = _checklist_complete_accepts(reviews, lenses)
    accept_families = {str(r.get("family")) for r in accepts}
    block_reviews = [r for r in reviews if str(r.get("verdict", "")).lower() == "block"]
    criticals = _unresolved_criticals(reviews)

    escalations: list[dict[str, Any]] = []
    for reviewer_id, finding in criticals:
        escalations.append(
            {
                "kind": "unresolved-critical",
                "reviewer": reviewer_id,
                "title": finding.get("title"),
                "file": finding.get("file"),
                "line": finding.get("line"),
                "lens": finding.get("lens"),
            }
        )
    if accepts and block_reviews:
        blocking_families = {str(r.get("family")) for r in block_reviews}
        if blocking_families - accept_families or accept_families - blocking_families:
            for review in block_reviews:
                escalations.append(
                    {
                        "kind": "cross-family-split",
                        "reviewer": str(review.get("id")),
                        "family": str(review.get("family")),
                        "detail": "family verdicts split — disagreement is signal, reconcile first",
                    }
                )
    for review in block_reviews:
        named = [
            f
            for f in review.get("findings") or []
            if isinstance(f, Mapping) and str(f.get("severity", "")).lower() == "critical"
        ]
        if not named:
            escalations.append(
                {
                    "kind": "block-without-named-critical",
                    "reviewer": str(review.get("id")),
                    "family": str(review.get("family")),
                    "detail": "BLOCK verdict without a named critical finding does not block on its own",
                }
            )
    for review in reviews:
        for blocker in _review_checklist_blockers(review, lenses):
            escalations.append(
                {
                    "kind": "checklist-incomplete",
                    "reviewer": str(review.get("id")),
                    "family": str(review.get("family")),
                    "detail": blocker,
                }
            )

    if criticals and sizing.get("block_on_named_critical", True):
        verdict = "blocked"
    else:
        quorum_met = len(accepts) >= int(sizing["quorum_accept"])
        min_families = int(sizing.get("min_families", 1))
        if quorum_met and len(accept_families) < min_families:
            quorum_met = False
        if quorum_met and sizing.get("require_all_families"):
            quorum_met = set(roster) <= accept_families
        verdict = QUORUM_ACCEPT if quorum_met else "no-quorum"

    return {
        "dossier_schema": 1,
        "task_id": task_id,
        "pr": pr_number,
        "head_sha": head_sha,
        "team_class": team_class,
        "quorum_required": int(sizing["quorum_accept"]),
        "constituted_at": constituted_at,
        "constitution_notes": list(constitution_notes),
        "lenses": list(lenses),
        "reviewers": [dict(r) for r in reviews],
        "escalations": escalations,
        "accept_count": len(accepts),
        "review_team_verdict": verdict,
    }


# --- Admission gate (consumed by scripts/cc-pr-autoqueue.py) ------------------


def review_dossier_path(note_path: Path, task_id: str) -> Path:
    """Canonical dossier location: ``<task_id>.review-dossier.yaml`` beside the note."""

    return note_path.parent / f"{task_id}{REVIEW_DOSSIER_SUFFIX}"


def _dossier_validity_blockers(
    dossier: Mapping[str, Any],
    *,
    pr_head_sha: str | None,
    registry: Mapping[str, Any],
    frontmatter: Mapping[str, Any] | None = None,
    expected_task_id: str | None = None,
    pr_number: int | None = None,
    changed_files: Sequence[str] | None = None,
    changed_file_count: int | None = None,
) -> tuple[str, ...]:
    blockers: list[str] = []
    scoped_files = (
        tuple(f.strip() for f in changed_files if f and f.strip())
        if changed_files is not None
        else None
    )

    if expected_task_id is not None:
        dossier_task_id = str(dossier.get("task_id") or "").strip()
        if dossier_task_id != expected_task_id:
            blockers.append(
                f"review_dossier_task_id_mismatch:{dossier_task_id or 'missing'}!={expected_task_id}"
            )
    if pr_number is not None:
        dossier_pr = _int_field(dossier.get("pr"), "pr", blockers)
        if dossier_pr is not None and dossier_pr != pr_number:
            blockers.append(f"review_dossier_pr_mismatch:{dossier_pr}!={pr_number}")

    dossier_sha = str(dossier.get("head_sha") or "")
    if not dossier_sha:
        blockers.append("review_dossier_malformed:missing_head_sha")
    elif not pr_head_sha:
        blockers.append("review_dossier_current_head_unknown")
    elif dossier_sha != pr_head_sha:
        blockers.append(f"review_dossier_stale_head:dossier={dossier_sha[:8]},pr={pr_head_sha[:8]}")

    team_class = str(dossier.get("team_class") or "")
    sizing = (registry.get("sizing") or {}).get(team_class)
    if not isinstance(sizing, Mapping):
        blockers.append(f"review_dossier_malformed:unknown_team_class:{team_class or 'missing'}")
        return tuple(blockers)
    if changed_files is not None:
        if not scoped_files:
            blockers.append("review_dossier_changed_files_unknown")
        elif changed_file_count is not None and len(scoped_files) < changed_file_count:
            blockers.append(
                f"review_dossier_changed_files_truncated:{len(scoped_files)}/{changed_file_count}"
            )
        else:
            expected_team_class = team_class_for(frontmatter or {}, scoped_files, registry)
            if team_class != expected_team_class:
                blockers.append(
                    f"review_dossier_team_class_scope_mismatch:{team_class}!={expected_team_class}"
                )
    else:
        class_floor = _task_class_floor(frontmatter)
        if class_floor is not None and team_class != class_floor:
            blockers.append(
                f"review_dossier_team_class_below_task_floor:{team_class}!={class_floor}"
            )

    reviews = dossier.get("reviewers")
    if not isinstance(reviews, list) or not all(isinstance(r, Mapping) for r in reviews):
        blockers.append("review_dossier_malformed:reviewers_not_a_list")
        return tuple(blockers)
    roster = {entry["family"] for entry in registry["families"]}
    unknown_reviewer_families = {str(r.get("family") or "missing") for r in reviews} - roster
    if unknown_reviewer_families:
        blockers.append(
            "review_dossier_unknown_reviewer_family:" + ",".join(sorted(unknown_reviewer_families))
        )
    unknown_verdicts = {
        str(r.get("verdict") or "missing").lower()
        for r in reviews
        if str(r.get("verdict") or "missing").lower() not in REVIEWER_VERDICTS
    }
    if unknown_verdicts:
        blockers.append(
            "review_dossier_unknown_reviewer_verdict:" + ",".join(sorted(unknown_verdicts))
        )

    required_size = _required_team_size(sizing)
    if len(reviews) < required_size:
        blockers.append(f"review_dossier_team_undersized:{len(reviews)}/{required_size}")

    criticals = _unresolved_criticals(reviews)
    if criticals and sizing.get("block_on_named_critical", True):
        blockers.append(f"review_dossier_unresolved_critical:{len(criticals)}")

    lenses = dossier.get("lenses") or []
    if not isinstance(lenses, list) or not all(isinstance(l, str) for l in lenses):
        blockers.append("review_dossier_malformed:lenses")
        lenses = []
    required_lenses = set(
        lenses_for_files(scoped_files, registry)
        if scoped_files is not None
        else registry.get("always_on_lenses") or []
    )
    missing_required_lenses = required_lenses - set(lenses)
    if missing_required_lenses:
        blockers.append(
            "review_dossier_missing_required_lenses:" + ",".join(sorted(missing_required_lenses))
        )
    for review in reviews:
        blockers.extend(_review_checklist_blockers(review, lenses))

    accepts = _checklist_complete_accepts(reviews, lenses)
    unknown_accept_families = {str(r.get("family")) for r in accepts} - roster
    if unknown_accept_families:
        blockers.append(
            "review_dossier_unknown_accept_family:" + ",".join(sorted(unknown_accept_families))
        )
    required_quorum = _int_field(sizing.get("quorum_accept"), "sizing.quorum_accept", blockers)
    if required_quorum is None:
        return tuple(blockers)
    recorded_quorum = dossier.get("quorum_required")
    parsed_recorded_quorum = (
        _int_field(recorded_quorum, "quorum_required", blockers)
        if recorded_quorum is not None
        else None
    )
    if parsed_recorded_quorum is not None and parsed_recorded_quorum != required_quorum:
        blockers.append(f"review_dossier_quorum_mismatch:{recorded_quorum}!={required_quorum}")
    if len(accepts) < required_quorum:
        blockers.append(f"review_dossier_quorum_not_met:{len(accepts)}/{required_quorum}")
    accept_families = {str(r.get("family")) for r in accepts}
    min_families = _int_field(sizing.get("min_families", 1), "sizing.min_families", blockers)
    if min_families is not None and len(accept_families) < min_families:
        blockers.append(
            f"review_dossier_family_diversity:accept_families={len(accept_families)}/{min_families}"
        )
    if sizing.get("require_all_families"):
        missing_families = roster - {str(r.get("family")) for r in accepts}
        if missing_families:
            blockers.append(
                "review_dossier_family_diversity:missing_accept_from="
                + ",".join(sorted(missing_families))
            )
    if frontmatter is not None and accepts:
        writer_family = writer_family_for_lane(str(frontmatter.get("assigned_to") or ""), registry)
        writer_accepts = sum(1 for r in accepts if str(r.get("family")) == writer_family)
        if writer_accepts > len(accepts) // 2:
            blockers.append(
                f"review_dossier_writer_family_majority:{writer_family}:{writer_accepts}/{len(accepts)}"
            )

    verdict = str(dossier.get("review_team_verdict") or "missing").lower()
    if verdict != QUORUM_ACCEPT:
        blockers.append(f"review_team_verdict_not_quorum_accept:{verdict}")
    return tuple(blockers)


def review_dossier_validity_blockers(
    frontmatter: Mapping[str, Any],
    note_path: Path,
    *,
    pr_head_sha: str | None = None,
    pr_number: int | None = None,
    changed_files: Sequence[str] | None = None,
    changed_file_count: int | None = None,
    registry: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """Validate a recorded review dossier without honoring any gate killswitch."""

    task_id = str(frontmatter.get("task_id") or "").strip()
    if not task_id:
        return ("review_dossier_unkeyable:missing_task_id",)
    dossier_file = review_dossier_path(note_path, task_id)
    if not dossier_file.is_file():
        return ("missing_review_dossier",)
    try:
        loaded = yaml.safe_load(dossier_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return (f"review_dossier_malformed:{type(exc).__name__}",)
    if not isinstance(loaded, Mapping):
        return (f"review_dossier_malformed:not_a_mapping:{type(loaded).__name__}",)
    if loaded.get("dossier_schema") != 1:
        return (f"review_dossier_malformed:dossier_schema:{loaded.get('dossier_schema')}",)
    if registry is None:
        try:
            registry = load_lens_registry()
        except (OSError, ValueError, yaml.YAMLError) as exc:
            return (f"review_lens_registry_unreadable:{type(exc).__name__}",)
    return _dossier_validity_blockers(
        loaded,
        pr_head_sha=pr_head_sha,
        registry=registry,
        frontmatter=frontmatter,
        expected_task_id=task_id,
        pr_number=pr_number,
        changed_files=changed_files,
        changed_file_count=changed_file_count,
    )


def review_team_verdict_blockers(
    frontmatter: Mapping[str, Any],
    note_path: Path,
    *,
    pr_head_sha: str | None = None,
    pr_number: int | None = None,
    changed_files: Sequence[str] | None = None,
    changed_file_count: int | None = None,
    registry: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """Admission blockers from the review-team quorum gate (no quorum, no merge).

    Fail-closed: a missing/malformed/stale dossier blocks; the verdict field is
    never trusted alone — quorum, criticals, team size, mandatory lenses, and
    family diversity are recomputed from the recorded reviews. When changed
    files are supplied, the recorded team class and lens set must match the
    same surface-derived scope used by the dispatcher.
    ``HAPAX_REVIEW_TEAM_GATE_OFF=1`` is the documented emergency bypass for
    admission only; durable receipt minting must use
    :func:`review_dossier_validity_blockers` instead.
    """

    if gate_disabled():
        return ()
    return review_dossier_validity_blockers(
        frontmatter,
        note_path,
        pr_head_sha=pr_head_sha,
        pr_number=pr_number,
        changed_files=changed_files,
        changed_file_count=changed_file_count,
        registry=registry,
    )
