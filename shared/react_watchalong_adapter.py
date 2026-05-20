"""React and watch-along media reference adapter.

Bridges the rights-safe media reference gate into content programming
formats (react, commentary, watch-along, review, comparison). Each
format proposes media references; the adapter evaluates them through
the gate and produces a RenderPlan that carries only rights-cleared
references.

Prohibited by design: stream ripping, raw commercial music/video,
full lyric display, arbitrary third-party footage as autonomous
broadcast inputs.

CC-task: react-watchalong-media-reference-adapter
Authority: CASE-AUTONOMOUS-CONTENT-20260429
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from shared.rights_safe_media_reference_gate import (
    Decision,
    GateResult,
    MediaReferenceProposal,
    ReferenceMode,
    RightsClass,
    evaluate_media_reference,
)

log = logging.getLogger(__name__)


class FormatKind(StrEnum):
    REACT = "react"
    COMMENTARY = "commentary"
    WATCH_ALONG = "watch_along"
    REVIEW = "review"
    COMPARISON = "comparison"
    TIER_LIST = "tier_list"
    RANKING = "ranking"


PROHIBITED_SOURCES = frozenset(
    {
        "stream_rip",
        "raw_commercial_music",
        "raw_commercial_video",
        "full_lyric_display",
        "unauthorized_footage",
    }
)


@dataclass(frozen=True)
class MediaReference:
    upstream_id: str
    upstream_title: str
    upstream_creator: str
    upstream_total_seconds: float
    source_type: str
    proposed_mode: ReferenceMode = ReferenceMode.METADATA_FIRST
    excerpt_seconds: float = 0.0
    commentary_seconds: float = 0.0
    transformation_evidence: str = ""
    non_substitution_rationale: str = ""
    disclosure_text: str = ""
    live_rights_kill_switch_active: bool = False
    content_id_match: str = ""
    rights_class: str = "unknown"


@dataclass(frozen=True)
class ResolvedReference:
    upstream_id: str
    upstream_title: str
    upstream_creator: str
    effective_mode: ReferenceMode
    gate_decision: Decision
    gate_reason: str
    show_timer: bool
    show_source_link: bool
    show_criteria: bool
    show_commentary: bool
    show_claim_trail: bool
    show_refusal_state: bool
    refusal_artifact: RefusalArtifact | None = None


@dataclass(frozen=True)
class RefusalArtifact:
    upstream_id: str
    reason: str
    refused_factors: tuple[str, ...]
    timestamp: str


@dataclass(frozen=True)
class RenderPlan:
    format_kind: FormatKind
    references: list[ResolvedReference]
    refusals: list[RefusalArtifact]
    created_at: str


def _to_proposal(ref: MediaReference) -> MediaReferenceProposal:
    return MediaReferenceProposal(
        upstream_id=ref.upstream_id,
        upstream_total_seconds=ref.upstream_total_seconds,
        rights_class=RightsClass(ref.rights_class),
        proposed_mode=ref.proposed_mode,
        excerpt_seconds=ref.excerpt_seconds,
        commentary_seconds=ref.commentary_seconds,
        transformation_evidence=ref.transformation_evidence,
        non_substitution_rationale=ref.non_substitution_rationale,
        disclosure_text=ref.disclosure_text,
        live_rights_kill_switch_active=ref.live_rights_kill_switch_active,
        content_id_match=ref.content_id_match,
    )


def _resolve_reference(ref: MediaReference, gate_result: GateResult) -> ResolvedReference:
    effective_mode = ref.proposed_mode
    if gate_result.decision == Decision.DOWNGRADE and gate_result.downgrade_to is not None:
        effective_mode = gate_result.downgrade_to
    elif gate_result.decision == Decision.REFUSE:
        effective_mode = ReferenceMode.METADATA_FIRST

    return ResolvedReference(
        upstream_id=ref.upstream_id,
        upstream_title=ref.upstream_title,
        upstream_creator=ref.upstream_creator,
        effective_mode=effective_mode,
        gate_decision=gate_result.decision,
        gate_reason=gate_result.reason,
        show_timer=True,
        show_source_link=True,
        show_criteria=True,
        show_commentary=True,
        show_claim_trail=True,
        show_refusal_state=gate_result.decision == Decision.REFUSE,
        refusal_artifact=RefusalArtifact(
            upstream_id=ref.upstream_id,
            reason=gate_result.reason,
            refused_factors=gate_result.refused_factors,
            timestamp=datetime.now(UTC).isoformat(),
        )
        if gate_result.decision == Decision.REFUSE
        else None,
    )


def check_prohibited_source(ref: MediaReference) -> RefusalArtifact | None:
    if ref.source_type in PROHIBITED_SOURCES:
        return RefusalArtifact(
            upstream_id=ref.upstream_id,
            reason=f"prohibited source type: {ref.source_type}",
            refused_factors=(f"source_type:{ref.source_type}",),
            timestamp=datetime.now(UTC).isoformat(),
        )
    return None


def build_render_plan(
    format_kind: FormatKind,
    references: list[MediaReference],
) -> RenderPlan:
    resolved: list[ResolvedReference] = []
    refusals: list[RefusalArtifact] = []

    for ref in references:
        prohibited = check_prohibited_source(ref)
        if prohibited is not None:
            refusals.append(prohibited)
            log.warning("react_watchalong: refused %s — %s", ref.upstream_id, prohibited.reason)
            continue

        proposal = _to_proposal(ref)
        gate_result = evaluate_media_reference(proposal)
        resolved_ref = _resolve_reference(ref, gate_result)
        resolved.append(resolved_ref)

        if resolved_ref.refusal_artifact is not None:
            refusals.append(resolved_ref.refusal_artifact)
            log.info("react_watchalong: refused %s — %s", ref.upstream_id, gate_result.reason)

    return RenderPlan(
        format_kind=format_kind,
        references=resolved,
        refusals=refusals,
        created_at=datetime.now(UTC).isoformat(),
    )
