"""Tests for the overlay/research-marker substrate adapter."""

from __future__ import annotations

from shared.director_read_model_public_event_gate import derive_public_event_moves
from shared.overlay_research_marker_substrate_adapter import (
    DEFAULT_FRESHNESS_TTL_S,
    OVERLAY_ZONE_SUBSTRATE_ID,
    PRODUCER,
    REQUIRED_RENDER_TARGET_REFS,
    RESEARCH_MARKER_SUBSTRATE_ID,
    SUBSTRATE_REFS,
    TASK_ANCHOR,
    OverlayHealthState,
    OverlayProducerEvidence,
    ResearchMarkerEvidence,
    derive_idempotency_key,
    project_overlay_research_marker_substrate,
)

NOW = 1_779_123_456.0


def _overlay(
    *,
    observed_offset_s: float = -2.0,
    render_target_refs: tuple[str, ...] = REQUIRED_RENDER_TARGET_REFS,
    health_state: OverlayHealthState = "ok",
    layout_registered: bool = True,
) -> OverlayProducerEvidence:
    return OverlayProducerEvidence(
        observed_at=NOW + observed_offset_s,
        evidence_ref="overlay-producer:state:2026-05-05T02:30:00Z",
        render_target_refs=render_target_refs,
        health_state=health_state,
        layout_registered=layout_registered,
    )


def _marker(
    *,
    marker_id: str = "marker-cond-001",
    condition_id: str = "cond-visible-001",
    occurred_offset_s: float = -1.0,
    provenance_token: str | None = "prov-token-001",
    provenance_evidence_refs: tuple[str, ...] = ("research-marker:condition:cond-visible-001",),
    egress_public_claim_ref: str | None = "egress-public-claim:overlay-marker:001",
) -> ResearchMarkerEvidence:
    return ResearchMarkerEvidence(
        marker_id=marker_id,
        condition_id=condition_id,
        occurred_at=NOW + occurred_offset_s,
        provenance_token=provenance_token,
        provenance_evidence_refs=provenance_evidence_refs,
        egress_public_claim_ref=egress_public_claim_ref,
    )


class TestFreshMarker:
    def test_fresh_marker_maps_to_public_eligible_condition_event(self) -> None:
        candidates, rejections = project_overlay_research_marker_substrate(
            [_marker()],
            overlay=_overlay(),
            now=NOW,
        )

        assert rejections == []
        assert len(candidates) == 1
        candidate = candidates[0]
        event = candidate.event

        assert candidate.substrate_refs == SUBSTRATE_REFS
        assert OVERLAY_ZONE_SUBSTRATE_ID in candidate.substrate_refs
        assert RESEARCH_MARKER_SUBSTRATE_ID in candidate.substrate_refs
        assert candidate.render_target_refs == REQUIRED_RENDER_TARGET_REFS
        assert candidate.public_eligible is True
        assert candidate.producer_lag_s == 2.0

        assert event.event_type == "condition.changed"
        assert event.state_kind == "research_observation"
        assert event.condition_id == "cond-visible-001"
        assert event.source.substrate_id == OVERLAY_ZONE_SUBSTRATE_ID
        assert event.source.producer == PRODUCER
        assert event.source.task_anchor == TASK_ANCHOR
        assert event.provenance.token == "prov-token-001"
        assert event.privacy_class == "public_safe"
        assert event.surface_policy.claim_live is False
        assert event.surface_policy.claim_archive is True
        assert event.surface_policy.fallback_action == "hold"
        assert event.surface_policy.requires_egress_public_claim is True
        assert event.surface_policy.requires_provenance is True
        assert event.surface_policy.requires_human_review is True
        assert event.surface_policy.dry_run_reason is None

        joined = "|".join(event.provenance.evidence_refs)
        assert "render_target:overlay_zones" in joined
        assert "render_target:research_marker_overlay" in joined
        assert "egress-public-claim:overlay-marker:001" in joined
        assert "substrate:research_marker_overlay" in joined

    def test_internal_condition_event_does_not_emit_director_public_moves(self) -> None:
        candidates, _ = project_overlay_research_marker_substrate(
            [_marker()],
            overlay=_overlay(),
            now=NOW,
        )

        assert derive_public_event_moves([candidates[0].event]) == []

    def test_no_egress_claim_keeps_marker_dry_run_not_public_safe(self) -> None:
        candidates, rejections = project_overlay_research_marker_substrate(
            [_marker(egress_public_claim_ref=None)],
            overlay=_overlay(),
            now=NOW,
        )

        assert rejections == []
        candidate = candidates[0]
        assert candidate.public_eligible is False
        assert candidate.event.privacy_class == "unknown"
        assert candidate.event.surface_policy.claim_archive is False
        assert candidate.event.surface_policy.fallback_action == "dry_run"
        assert candidate.event.surface_policy.dry_run_reason is not None
        assert "egress_public_claim_missing" in candidate.event.surface_policy.dry_run_reason


class TestBlocking:
    def test_missing_marker_provenance_blocks_public_marker_claim(self) -> None:
        candidates, rejections = project_overlay_research_marker_substrate(
            [_marker(provenance_token=None)],
            overlay=_overlay(),
            now=NOW,
        )

        assert candidates == []
        assert len(rejections) == 1
        rejection = rejections[0]
        assert rejection.reason == "missing_marker_provenance"
        assert rejection.emits_public_event is False
        assert "no public research marker claim" in rejection.dry_run_reason

    def test_stale_overlay_producer_emits_noop_rejection(self) -> None:
        candidates, rejections = project_overlay_research_marker_substrate(
            [_marker()],
            overlay=_overlay(observed_offset_s=-(DEFAULT_FRESHNESS_TTL_S + 1.0)),
            now=NOW,
        )

        assert candidates == []
        assert len(rejections) == 1
        rejection = rejections[0]
        assert rejection.reason == "stale_overlay_producer"
        assert rejection.emits_public_event is False
        assert "no-op" in rejection.dry_run_reason
        assert "ttl=10.00" in rejection.detail

    def test_layout_registration_without_render_target_refs_is_insufficient(self) -> None:
        candidates, rejections = project_overlay_research_marker_substrate(
            [_marker()],
            overlay=_overlay(render_target_refs=(), layout_registered=True),
            now=NOW,
        )

        assert candidates == []
        assert len(rejections) == 1
        rejection = rejections[0]
        assert rejection.reason == "missing_render_target_evidence"
        assert rejection.emits_public_event is False
        assert "layout_registered=true" in rejection.detail
        assert "layout registration is insufficient" in rejection.dry_run_reason

    def test_unhealthy_overlay_producer_blocks_marker_claim(self) -> None:
        candidates, rejections = project_overlay_research_marker_substrate(
            [_marker()],
            overlay=_overlay(health_state="degraded"),
            now=NOW,
        )

        assert candidates == []
        assert rejections[0].reason == "overlay_producer_unhealthy"


class TestIdempotency:
    def test_seen_marker_key_is_rejected_as_duplicate(self) -> None:
        marker = _marker()
        key = derive_idempotency_key(marker)
        candidates, rejections = project_overlay_research_marker_substrate(
            [marker],
            overlay=_overlay(),
            now=NOW,
            seen_keys=[key],
        )

        assert candidates == []
        assert len(rejections) == 1
        assert rejections[0].reason == "duplicate"

    def test_identical_markers_dedupe_within_one_call(self) -> None:
        marker = _marker()
        candidates, rejections = project_overlay_research_marker_substrate(
            [marker, marker],
            overlay=_overlay(),
            now=NOW,
        )

        assert len(candidates) == 1
        assert len(rejections) == 1
        assert rejections[0].reason == "duplicate"


class TestEmptyInput:
    def test_empty_marker_stream_returns_empty_pair(self) -> None:
        candidates, rejections = project_overlay_research_marker_substrate(
            [],
            overlay=_overlay(),
            now=NOW,
        )

        assert candidates == []
        assert rejections == []
