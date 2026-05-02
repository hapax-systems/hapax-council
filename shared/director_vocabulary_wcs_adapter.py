"""WCS snapshot → director vocabulary entries adapter.

Projects rows from a `DirectorWorldSurfaceSnapshot` into
`DirectorVocabularyEntry` rows that the existing
`build_director_vocabulary()` envelope can consume alongside its substrate /
lane / ward / camera / private-control / cuepoint / programme inputs.

The adapter does NOT re-derive the substrate/lane vocabulary that
`build_director_vocabulary()` already builds — it only emits entries for the
narrower set of WCS-only target types (audio routes, video surfaces, control
surfaces, hardware devices, archives, public-event endpoints) plus a
substrate/spectacle-lane sibling for surfaces the WCS knows about that the
substrate seam does not yet enumerate.

Status semantics — every WCS move row maps to exactly one of seven director
vocabulary states, preserving the snapshot's claim posture and blocker
reasons fail-closed:

| WCS status                  | Vocabulary expression                      |
| ----------------------------|--------------------------------------------|
| MOUNTED                     | commandable; public_claim follows posture  |
| PUBLIC                      | commandable + public_claim_allowed         |
| PRIVATE                     | commandable; public_claim_allowed=False;   |
|                             | unavailable_reason = "private_only"        |
| DRY_RUN                     | hold-only; fallback_mode=dry_run;          |
|                             | unavailable_reason="dry_run_only"          |
| STALE                       | hold-only; unavailable_reason="stale";     |
|                             | fallback_mode mapped from WCS fallback     |
| BLOCKED / UNAVAILABLE /     | no verbs; unavailable_reason from WCS;     |
| BLOCKED_HARDWARE_NO_OP      | fallback_mode mapped from WCS fallback     |
"""

from __future__ import annotations

from collections.abc import Iterable

from shared.director_vocabulary import (
    DirectorVerb,
    DirectorVocabularyEntry,
    DirectorVocabularyEvidence,
)
from shared.director_vocabulary import EvidenceStatus as VocabEvidenceStatus
from shared.director_vocabulary import FallbackMode as VocabFallbackMode
from shared.director_vocabulary import GeneratedFrom as VocabGeneratedFrom
from shared.director_vocabulary import TargetType as VocabTargetType
from shared.director_world_surface_snapshot import (
    DirectorWorldSurfaceMoveRow,
    DirectorWorldSurfaceSnapshot,
    MoveStatus,
)
from shared.director_world_surface_snapshot import (
    EvidenceStatus as WcsEvidenceStatus,
)
from shared.director_world_surface_snapshot import (
    FallbackMode as WcsFallbackMode,
)
from shared.director_world_surface_snapshot import (
    TargetType as WcsTargetType,
)

_WCS_TO_VOCAB_TARGET_TYPE: dict[WcsTargetType, VocabTargetType] = {
    WcsTargetType.AUDIO_ROUTE: "substrate",
    WcsTargetType.VIDEO_SURFACE: "spectacle_lane",
    WcsTargetType.CONTROL_SURFACE: "private_control",
    WcsTargetType.PUBLIC_EVENT: "claim_binding",
    WcsTargetType.HARDWARE_DEVICE: "re_splay_device",
    WcsTargetType.ARCHIVE: "substrate",
}

_WCS_FALLBACK_TO_VOCAB: dict[WcsFallbackMode, VocabFallbackMode] = {
    WcsFallbackMode.NO_OP: "no_op",
    WcsFallbackMode.DRY_RUN: "dry_run",
    WcsFallbackMode.HOLD_LAST_SAFE: "hold_last_safe",
    WcsFallbackMode.SUPPRESS: "suppress",
    WcsFallbackMode.PRIVATE_ONLY: "private_only",
    WcsFallbackMode.OPERATOR_REASON: "operator_reason",
    WcsFallbackMode.DEGRADED_STATUS: "degraded_status",
    WcsFallbackMode.KILL_SWITCH: "kill_switch",
    WcsFallbackMode.FALLBACK_TARGET: "fallback",
}

_WCS_EVIDENCE_TO_VOCAB: dict[WcsEvidenceStatus, VocabEvidenceStatus] = {
    WcsEvidenceStatus.FRESH: "fresh",
    WcsEvidenceStatus.STALE: "stale",
    WcsEvidenceStatus.MISSING: "missing",
    WcsEvidenceStatus.UNKNOWN: "unknown",
    WcsEvidenceStatus.BLOCKED: "missing",
    WcsEvidenceStatus.PRIVATE_ONLY: "not_applicable",
    WcsEvidenceStatus.DRY_RUN: "not_applicable",
    WcsEvidenceStatus.NOT_APPLICABLE: "not_applicable",
}

_COMMANDABLE_VERBS: tuple[DirectorVerb, ...] = ("foreground", "hold")
_HOLD_ONLY_VERBS: tuple[DirectorVerb, ...] = ("hold",)
_BLOCKED_VERBS: tuple[DirectorVerb, ...] = ()


def vocabulary_entries_from_wcs_snapshot(
    snapshot: DirectorWorldSurfaceSnapshot,
) -> list[DirectorVocabularyEntry]:
    """Project a director WCS snapshot into vocabulary entries.

    The adapter emits at most one entry per move row whose `target_type`
    maps to a director-vocabulary scenic target type. Rows pointing at
    technical infrastructure (tools, model routes, state files, services,
    prompt hints) are filtered out — they are not part of the scenic
    vocabulary the director acts through.
    """

    return [
        entry for row in snapshot.all_moves() if (entry := _entry_from_wcs_move(row)) is not None
    ]


def _entry_from_wcs_move(
    row: DirectorWorldSurfaceMoveRow,
) -> DirectorVocabularyEntry | None:
    vocab_target = _WCS_TO_VOCAB_TARGET_TYPE.get(row.target_type)
    if vocab_target is None:
        return None

    verbs = _verbs_for_status(row.status)
    unavailable = _unavailable_reason_for_row(row)
    fallback = _fallback_mode_for_row(row)
    evidence = _evidence_for_row(row)
    generated_from = _generated_from_for_row(row)

    return DirectorVocabularyEntry(
        target_type=vocab_target,
        target_id=row.target_id,
        display_name=row.display_name,
        terms=_terms_for_row(row),
        verbs=list(verbs),
        source_refs=list(row.source_refs),
        generated_from=generated_from,
        evidence=[evidence],
        public_claim_allowed=row.public_claim_allowed,
        unavailable_reason=unavailable,
        fallback_mode=fallback,
    )


def _verbs_for_status(status: MoveStatus) -> Iterable[DirectorVerb]:
    if status in {MoveStatus.MOUNTED, MoveStatus.PUBLIC}:
        return _COMMANDABLE_VERBS
    if status is MoveStatus.PRIVATE:
        return _COMMANDABLE_VERBS
    if status in {MoveStatus.DRY_RUN, MoveStatus.STALE}:
        return _HOLD_ONLY_VERBS
    return _BLOCKED_VERBS


def _unavailable_reason_for_row(row: DirectorWorldSurfaceMoveRow) -> str | None:
    if row.status is MoveStatus.MOUNTED:
        return None
    if row.status is MoveStatus.PUBLIC:
        return None
    if row.status is MoveStatus.PRIVATE:
        return "private_only"
    if row.status is MoveStatus.DRY_RUN:
        return "dry_run_only"
    if row.status is MoveStatus.STALE:
        return "stale"
    if row.blocker_reason:
        return row.blocker_reason
    if row.blocked_reasons:
        return row.blocked_reasons[0]
    return row.status.value


def _fallback_mode_for_row(row: DirectorWorldSurfaceMoveRow) -> VocabFallbackMode:
    return _WCS_FALLBACK_TO_VOCAB.get(row.fallback.mode, "no_op")


def _evidence_for_row(row: DirectorWorldSurfaceMoveRow) -> DirectorVocabularyEvidence:
    return DirectorVocabularyEvidence(
        source_type="director_world_surface_snapshot",
        ref=row.move_id,
        status=_WCS_EVIDENCE_TO_VOCAB.get(row.evidence_status, "unknown"),
        observed_at=row.freshness.checked_at,
        age_s=float(row.freshness.observed_age_s)
        if row.freshness.observed_age_s is not None
        else None,
        ttl_s=float(row.freshness.ttl_s) if row.freshness.ttl_s is not None else None,
        detail=f"wcs_move:{row.move_id}/{row.status.value}",
    )


def _generated_from_for_row(
    row: DirectorWorldSurfaceMoveRow,
) -> list[VocabGeneratedFrom]:
    if row.target_type is WcsTargetType.PUBLIC_EVENT:
        return ["claim_binding"]
    if row.target_type is WcsTargetType.HARDWARE_DEVICE:
        return ["re_splay_probe"]
    if row.target_type is WcsTargetType.CONTROL_SURFACE:
        return ["private_control"]
    if row.target_type is WcsTargetType.VIDEO_SURFACE:
        return ["spectacle_lane"]
    return ["content_substrate"]


def _terms_for_row(row: DirectorWorldSurfaceMoveRow) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for term in (row.target_id, row.display_name, *row.intent_families):
        if term and term not in seen:
            seen.add(term)
            terms.append(term)
    return terms


__all__ = [
    "vocabulary_entries_from_wcs_snapshot",
]
