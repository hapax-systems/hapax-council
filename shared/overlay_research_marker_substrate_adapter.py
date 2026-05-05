"""Overlay / research-marker substrate adapter.

Projects explicit overlay producer evidence plus research-marker provenance into
``ResearchVehiclePublicEvent`` records without mutating the compositor or
claiming public research state from layout registration alone.

The adapter is intentionally fixture-backed and side-effect free. Runtime
producers can call it once they have an overlay state snapshot, marker
provenance token, and render-target evidence; until then the adapter emits
rejections with dry-run/no-op reasons.

Spec: ``config/adapter-tranche-selection-memo.json`` row
``overlay-research-marker-substrate-adapter``.
Cc-task: ``overlay-research-marker-substrate-adapter``.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from shared.research_vehicle_public_event import (
    PublicEventProvenance,
    PublicEventSource,
    PublicEventSurfacePolicy,
    ResearchVehiclePublicEvent,
    StateKind,
    Surface,
)

OVERLAY_ZONE_SUBSTRATE_ID: Literal["overlay_zones"] = "overlay_zones"
RESEARCH_MARKER_SUBSTRATE_ID: Literal["research_marker_overlay"] = "research_marker_overlay"
SUBSTRATE_REFS: tuple[str, str] = (
    OVERLAY_ZONE_SUBSTRATE_ID,
    RESEARCH_MARKER_SUBSTRATE_ID,
)
REQUIRED_RENDER_TARGET_REFS: tuple[str, str] = (
    "render_target:overlay_zones",
    "render_target:research_marker_overlay",
)

PRODUCER: Literal["shared.overlay_research_marker_substrate_adapter"] = (
    "shared.overlay_research_marker_substrate_adapter"
)
TASK_ANCHOR: Literal["overlay-research-marker-substrate-adapter"] = (
    "overlay-research-marker-substrate-adapter"
)

DEFAULT_FRESHNESS_TTL_S: float = float(
    os.environ.get("HAPAX_OVERLAY_MARKER_SUBSTRATE_FRESHNESS_TTL_S", "10.0")
)

MarkerEventType = Literal["condition.changed", "programme.boundary"]
OverlayHealthState = Literal["ok", "degraded", "missing"]
RejectionReason = Literal[
    "missing_overlay_producer",
    "overlay_producer_unhealthy",
    "stale_overlay_producer",
    "missing_render_target_evidence",
    "missing_marker_identity",
    "missing_marker_provenance",
    "duplicate",
]

_NON_DISPATCH_ALLOWED_SURFACES: tuple[Surface, ...] = ("health", "archive", "replay")
_DRY_RUN_ALLOWED_SURFACES: tuple[Surface, ...] = ("health",)
_DENIED_PUBLICATION_SURFACES: tuple[Surface, ...] = (
    "youtube_description",
    "youtube_cuepoints",
    "youtube_chapters",
    "youtube_captions",
    "youtube_shorts",
    "mastodon",
    "bluesky",
    "discord",
    "omg_statuslog",
    "omg_weblog",
    "omg_now",
    "monetization",
)


@dataclass(frozen=True)
class OverlayProducerEvidence:
    """A non-mutating snapshot from the overlay producer.

    ``layout_registered`` is diagnostic only. The adapter requires concrete
    ``render_target_refs`` for both substrate refs, so a class registered in the
    compositor does not become an implied mounted/public marker lane.
    """

    observed_at: float
    evidence_ref: str
    render_target_refs: tuple[str, ...]
    health_state: OverlayHealthState = "ok"
    producer_ref: str = "agents.studio_compositor.overlay_zones"
    layout_registered: bool = False


@dataclass(frozen=True)
class ResearchMarkerEvidence:
    """One research marker or programme-boundary marker observation."""

    marker_id: str
    condition_id: str
    occurred_at: float
    provenance_token: str | None
    provenance_evidence_refs: tuple[str, ...]
    event_type: MarkerEventType = "condition.changed"
    broadcast_id: str | None = None
    programme_id: str | None = None
    egress_public_claim_ref: str | None = None
    salience: float = 0.55
    rights_basis: str = "operator original research marker metadata"


@dataclass(frozen=True)
class OverlayResearchMarkerCandidate:
    """One marker cleared into the substrate projection layer."""

    event: ResearchVehiclePublicEvent
    marker_id: str
    condition_id: str
    idempotency_key: str
    producer_lag_s: float
    substrate_refs: tuple[str, str]
    render_target_refs: tuple[str, ...]
    public_eligible: bool


@dataclass(frozen=True)
class OverlayResearchMarkerRejection:
    """One marker considered but not projected into a public-event row."""

    marker_id: str | None
    condition_id: str | None
    reason: RejectionReason
    detail: str = ""
    dry_run_reason: str = ""
    emits_public_event: bool = False


def derive_idempotency_key(marker: ResearchMarkerEvidence) -> str:
    """Stable key for marker identity, event kind, timestamp, and provenance."""

    payload = "|".join(
        (
            marker.event_type,
            marker.marker_id,
            marker.condition_id,
            f"{marker.occurred_at:.6f}",
            marker.provenance_token or "",
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def project_overlay_research_marker_substrate(
    markers: Iterable[ResearchMarkerEvidence],
    *,
    overlay: OverlayProducerEvidence | None,
    now: float,
    freshness_ttl_s: float = DEFAULT_FRESHNESS_TTL_S,
    seen_keys: Iterable[str] = (),
) -> tuple[list[OverlayResearchMarkerCandidate], list[OverlayResearchMarkerRejection]]:
    """Split marker evidence into substrate candidates and no-op rejections."""

    marker_list = list(markers)
    overlay_rejection = _overlay_rejection(
        overlay=overlay,
        marker=marker_list[0] if marker_list else None,
        now=now,
        freshness_ttl_s=freshness_ttl_s,
    )
    if overlay_rejection is not None:
        return [], [
            _with_marker(rejection=overlay_rejection, marker=marker) for marker in marker_list
        ]

    assert overlay is not None
    producer_lag_s = now - overlay.observed_at
    seen: set[str] = set(seen_keys)
    candidates: list[OverlayResearchMarkerCandidate] = []
    rejections: list[OverlayResearchMarkerRejection] = []

    for marker in marker_list:
        if not marker.marker_id or not marker.condition_id:
            rejections.append(
                OverlayResearchMarkerRejection(
                    marker_id=marker.marker_id or None,
                    condition_id=marker.condition_id or None,
                    reason="missing_marker_identity",
                    detail="marker_id and condition_id are required",
                    dry_run_reason="marker_identity_missing: no overlay marker row emitted",
                )
            )
            continue

        if not marker.provenance_token or not marker.provenance_evidence_refs:
            rejections.append(
                OverlayResearchMarkerRejection(
                    marker_id=marker.marker_id,
                    condition_id=marker.condition_id,
                    reason="missing_marker_provenance",
                    detail="provenance token and provenance evidence refs are required",
                    dry_run_reason=(
                        "marker_provenance_missing: no public research marker claim emitted"
                    ),
                )
            )
            continue

        key = derive_idempotency_key(marker)
        if key in seen:
            rejections.append(
                OverlayResearchMarkerRejection(
                    marker_id=marker.marker_id,
                    condition_id=marker.condition_id,
                    reason="duplicate",
                    detail=f"idempotency_key={key[:12]}",
                    dry_run_reason="duplicate_marker_suppressed",
                )
            )
            continue
        seen.add(key)

        public_eligible = bool(marker.egress_public_claim_ref)
        event = _build_marker_event(
            marker=marker,
            overlay=overlay,
            now=now,
            producer_lag_s=producer_lag_s,
            idempotency_key=key,
            public_eligible=public_eligible,
        )
        candidates.append(
            OverlayResearchMarkerCandidate(
                event=event,
                marker_id=marker.marker_id,
                condition_id=marker.condition_id,
                idempotency_key=key,
                producer_lag_s=producer_lag_s,
                substrate_refs=SUBSTRATE_REFS,
                render_target_refs=overlay.render_target_refs,
                public_eligible=public_eligible,
            )
        )

    return candidates, rejections


def _overlay_rejection(
    *,
    overlay: OverlayProducerEvidence | None,
    marker: ResearchMarkerEvidence | None,
    now: float,
    freshness_ttl_s: float,
) -> OverlayResearchMarkerRejection | None:
    if overlay is None:
        return OverlayResearchMarkerRejection(
            marker_id=marker.marker_id if marker else None,
            condition_id=marker.condition_id if marker else None,
            reason="missing_overlay_producer",
            detail="overlay producer evidence is absent",
            dry_run_reason="overlay_producer_missing: no-op until producer state exists",
        )

    if overlay.health_state != "ok":
        return OverlayResearchMarkerRejection(
            marker_id=marker.marker_id if marker else None,
            condition_id=marker.condition_id if marker else None,
            reason="overlay_producer_unhealthy",
            detail=f"health_state={overlay.health_state}",
            dry_run_reason="overlay_producer_unhealthy: no-op until producer recovers",
        )

    lag_s = now - overlay.observed_at
    if lag_s > freshness_ttl_s:
        return OverlayResearchMarkerRejection(
            marker_id=marker.marker_id if marker else None,
            condition_id=marker.condition_id if marker else None,
            reason="stale_overlay_producer",
            detail=f"lag_s={lag_s:.2f} exceeds ttl={freshness_ttl_s:.2f}",
            dry_run_reason="overlay_producer_stale: no-op rather than implied availability",
        )

    missing = _missing_render_target_refs(overlay.render_target_refs)
    if missing:
        layout_detail = (
            "layout_registered=true" if overlay.layout_registered else "layout_registered=false"
        )
        return OverlayResearchMarkerRejection(
            marker_id=marker.marker_id if marker else None,
            condition_id=marker.condition_id if marker else None,
            reason="missing_render_target_evidence",
            detail=f"missing={','.join(missing)}; {layout_detail}",
            dry_run_reason="render_target_evidence_missing: layout registration is insufficient",
        )

    return None


def _with_marker(
    *,
    rejection: OverlayResearchMarkerRejection,
    marker: ResearchMarkerEvidence,
) -> OverlayResearchMarkerRejection:
    return OverlayResearchMarkerRejection(
        marker_id=marker.marker_id or rejection.marker_id,
        condition_id=marker.condition_id or rejection.condition_id,
        reason=rejection.reason,
        detail=rejection.detail,
        dry_run_reason=rejection.dry_run_reason,
        emits_public_event=False,
    )


def _missing_render_target_refs(render_target_refs: tuple[str, ...]) -> tuple[str, ...]:
    present = set(render_target_refs)
    return tuple(ref for ref in REQUIRED_RENDER_TARGET_REFS if ref not in present)


def _build_marker_event(
    *,
    marker: ResearchMarkerEvidence,
    overlay: OverlayProducerEvidence,
    now: float,
    producer_lag_s: float,
    idempotency_key: str,
    public_eligible: bool,
) -> ResearchVehiclePublicEvent:
    evidence_refs = [
        overlay.evidence_ref,
        *overlay.render_target_refs,
        *marker.provenance_evidence_refs,
        f"substrate:{RESEARCH_MARKER_SUBSTRATE_ID}",
    ]
    if marker.egress_public_claim_ref:
        evidence_refs.append(marker.egress_public_claim_ref)

    dry_run_reason = None
    if not public_eligible:
        dry_run_reason = "egress_public_claim_missing: overlay marker remains dry-run only"

    return ResearchVehiclePublicEvent(
        event_id=f"{marker.event_type}:overlay-marker:{idempotency_key}",
        event_type=marker.event_type,
        occurred_at=_iso_from_epoch(marker.occurred_at),
        broadcast_id=marker.broadcast_id,
        programme_id=marker.programme_id,
        condition_id=marker.condition_id,
        source=PublicEventSource(
            producer=PRODUCER,
            substrate_id=OVERLAY_ZONE_SUBSTRATE_ID,
            task_anchor=TASK_ANCHOR,
            evidence_ref=overlay.evidence_ref,
            freshness_ref=f"overlay_producer.lag_s={producer_lag_s:.2f}",
        ),
        salience=marker.salience,
        state_kind=_state_kind_for(marker.event_type),
        rights_class="operator_original",
        privacy_class="public_safe" if public_eligible else "unknown",
        provenance=PublicEventProvenance(
            token=marker.provenance_token,
            generated_at=_iso_from_epoch(now),
            producer=PRODUCER,
            evidence_refs=evidence_refs,
            rights_basis=marker.rights_basis,
            citation_refs=[],
        ),
        public_url=None,
        frame_ref=None,
        chapter_ref=None,
        attribution_refs=[],
        surface_policy=PublicEventSurfacePolicy(
            allowed_surfaces=list(
                _NON_DISPATCH_ALLOWED_SURFACES if public_eligible else _DRY_RUN_ALLOWED_SURFACES
            ),
            denied_surfaces=list(_DENIED_PUBLICATION_SURFACES),
            claim_live=False,
            claim_archive=public_eligible,
            claim_monetizable=False,
            requires_egress_public_claim=True,
            requires_audio_safe=False,
            requires_provenance=True,
            requires_human_review=True,
            rate_limit_key="overlay.research_marker",
            redaction_policy="none",
            fallback_action="hold" if public_eligible else "dry_run",
            dry_run_reason=dry_run_reason,
        ),
    )


def _state_kind_for(event_type: MarkerEventType) -> StateKind:
    if event_type == "programme.boundary":
        return "programme_state"
    return "research_observation"


def _iso_from_epoch(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


__all__ = [
    "DEFAULT_FRESHNESS_TTL_S",
    "MarkerEventType",
    "OVERLAY_ZONE_SUBSTRATE_ID",
    "OverlayHealthState",
    "OverlayProducerEvidence",
    "OverlayResearchMarkerCandidate",
    "OverlayResearchMarkerRejection",
    "PRODUCER",
    "REQUIRED_RENDER_TARGET_REFS",
    "RESEARCH_MARKER_SUBSTRATE_ID",
    "ResearchMarkerEvidence",
    "RejectionReason",
    "SUBSTRATE_REFS",
    "TASK_ANCHOR",
    "derive_idempotency_key",
    "project_overlay_research_marker_substrate",
]
