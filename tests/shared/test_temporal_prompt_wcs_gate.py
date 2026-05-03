"""Tests for WCS-gated temporal prompt blocks."""

from __future__ import annotations

from shared.temporal_prompt_wcs_gate import (
    TEMPORAL_PROMPT_AUTHORITY_FENCE,
    TEMPORAL_PROMPT_BLOCK_HEADER,
    TemporalPromptState,
    build_temporal_prompt_block,
    false_grounding_risk_causes,
    render_director_temporal_prompt_block,
    render_temporal_prompt_block,
    render_temporal_prompt_read_model,
)
from shared.world_surface_temporal_perceptual_health import (
    project_temporal_perceptual_health_records,
)


def _records_by_surface():
    records = project_temporal_perceptual_health_records()
    return {record.surface_id: record for record in records}


def _prompt_rows_by_surface():
    block = build_temporal_prompt_block(project_temporal_perceptual_health_records())
    return {row.surface_id: row for row in block.rows}


def test_render_includes_wcs_gate_metadata() -> None:
    rendered = render_temporal_prompt_block(project_temporal_perceptual_health_records())

    assert TEMPORAL_PROMPT_BLOCK_HEADER in rendered
    assert TEMPORAL_PROMPT_AUTHORITY_FENCE in rendered
    assert "checked_at=" in rendered
    assert "ttl_s=" in rendered
    assert "evidence_refs=" in rendered
    assert "authority_ceiling=" in rendered
    assert "temporal-evidence:" in rendered
    assert "authorizes_current_public_live_available_grounded=false" in rendered


def test_fresh_and_explicitly_degraded_rows_can_orient_without_claim_authority() -> None:
    rows = _prompt_rows_by_surface()

    fresh = rows["temporal.impression.broadcast_health.fresh.health"]
    assert fresh.prompt_state is TemporalPromptState.ORIENTING
    assert fresh.freshness == "fresh"
    assert fresh.authority_ceiling == "public_gate_required"
    assert not fresh.authorizes_current_public_live_available_grounded

    protention = rows["temporal.protention.audio_readiness.expected.health"]
    assert protention.prompt_state is TemporalPromptState.DEGRADED
    assert protention.freshness == "fresh"
    assert "protention_cannot_ground_current_or_action_happened_claim" in (
        protention.blocker_reason
    )
    assert not protention.authorizes_current_public_live_available_grounded

    records = _records_by_surface()
    assert not records[fresh.surface_id].satisfies_claimable_health()
    assert not records[protention.surface_id].satisfies_claimable_health()


def test_stale_missing_and_unknown_temporal_rows_render_as_blocked_state() -> None:
    rows = _prompt_rows_by_surface()

    stale = rows["temporal.retention.camera_scene.stale.health"]
    missing = rows["temporal.producer.missing.health"]
    unknown = rows["temporal.producer.unknown.health"]

    assert stale.prompt_state is TemporalPromptState.BLOCKED
    assert missing.prompt_state is TemporalPromptState.BLOCKED
    assert unknown.prompt_state is TemporalPromptState.BLOCKED
    assert "freshness:stale" in stale.blocker_reason
    assert "freshness:missing" in missing.blocker_reason
    assert "freshness:unknown" in unknown.blocker_reason


def test_false_grounding_risks_are_visible_in_prompt_rows() -> None:
    rows = _prompt_rows_by_surface()

    spanless = rows["perceptual_field.current_track.spanless.health"]
    inferred = rows["perceptual_field.camera.classifications.inferred.health"]

    assert spanless.prompt_state is TemporalPromptState.BLOCKED
    assert false_grounding_risk_causes(spanless) == ("spanless_perceptual_data",)
    assert inferred.prompt_state is TemporalPromptState.BLOCKED
    assert false_grounding_risk_causes(inferred) == ("inferred_perceptual_data",)


def test_static_hint_block_never_authorizes_current_public_live_or_grounded_state() -> None:
    block = build_temporal_prompt_block(project_temporal_perceptual_health_records())

    assert not block.authorizes_current_public_live_available_grounded
    assert "current, public, live, available, or grounded" in TEMPORAL_PROMPT_AUTHORITY_FENCE
    assert all(not row.authorizes_current_public_live_available_grounded for row in block.rows)


def test_prompt_block_does_not_emit_direct_temporal_xml_or_legacy_prose() -> None:
    rendered = render_temporal_prompt_block(project_temporal_perceptual_health_records())

    assert "<temporal_context>" not in rendered
    assert "retention = fading past" not in rendered
    assert "protention = anticipated near-future" not in rendered


def test_director_prompt_block_consumes_wcs_rows_not_direct_xml_or_prose() -> None:
    rendered = render_director_temporal_prompt_block(project_temporal_perceptual_health_records())

    assert "Temporal/Perceptual WCS Prompt Gate" in rendered
    assert "evidence_refs=temporal-evidence:" in rendered
    assert "<temporal_context>" not in rendered
    assert "SURPRISE detected" not in rendered
    assert "authorizes_current_public_live_available_grounded=false" in rendered


def test_missing_wcs_rows_fail_closed_to_blocked_prompt_state() -> None:
    block = build_temporal_prompt_block([])
    rendered = render_temporal_prompt_read_model(block)

    assert block.block_state is TemporalPromptState.BLOCKED
    assert block.blocker_reasons == ("temporal_perceptual_wcs_rows_missing",)
    assert "state=blocked" in rendered
    assert "authority_ceiling=no_claim" in rendered
