"""Tests for director programme format/action read-model projection."""

from __future__ import annotations

from typing import Any, cast

import pytest

from shared.director_programme_format_actions import (
    REQUIRED_ACTION_STATES,
    DirectorProgrammeFormatActionRow,
    ProgrammeFormatActionState,
    SurfaceRefState,
    load_director_programme_format_action_projection,
)


def test_projection_covers_required_action_modes_from_programme_and_snapshot_fixtures() -> None:
    projection = load_director_programme_format_action_projection()

    assert {state.value for state in projection.action_states} == REQUIRED_ACTION_STATES
    assert {row.action_state.value for row in projection.actions} >= REQUIRED_ACTION_STATES
    assert len({row.action_id for row in projection.actions}) == len(projection.actions)
    assert projection.source_refs == (
        "DirectorWorldSurfaceSnapshot:director-wcs-snapshot-fixture-20260430",
        "config:content-programme-run-envelope-fixtures",
        "format_wcs_requirement_matrix",
    )

    for row in projection.actions:
        assert row.required_wcs_surfaces
        assert row.director_moves
        assert row.evidence_obligations
        assert row.conversion_obligations
        assert row.static_hint_authorizes_availability is False


def test_public_live_format_action_requires_claim_evidence_and_public_event_refs() -> None:
    projection = load_director_programme_format_action_projection()
    public_live = projection.require_action("programme-format-action:public_live_run")

    assert public_live.action_state is ProgrammeFormatActionState.PUBLIC_LIVE
    assert public_live.format_id == "rundown"
    assert public_live.requested_mode == "public_live"
    assert public_live.effective_mode == "public_live"
    assert public_live.public_claim_allowed is True
    assert public_live.public_live_claim_allowed is True
    assert public_live.public_event_refs
    assert public_live.witness_refs
    assert public_live.rights_refs
    assert public_live.blocked_reasons == ()
    assert public_live.missing_surface_refs == ()
    assert "public_event" in public_live.evidence_obligations
    assert "mark_boundary" in public_live.director_moves


def test_public_live_negative_missing_public_event_stays_blocked_not_authorized() -> None:
    projection = load_director_programme_format_action_projection()
    blocked = projection.require_action(
        "programme-format-action:public_live_negative_missing_public_event"
    )

    assert blocked.action_state is ProgrammeFormatActionState.BLOCKED
    assert blocked.requested_mode == "public_live"
    assert blocked.effective_mode == "dry_run"
    assert blocked.public_claim_allowed is False
    assert blocked.public_live_claim_allowed is False
    assert "wcs:public_event_adapter" in blocked.missing_surface_refs
    assert "public_event_readiness_missing" in blocked.blocked_reasons
    assert blocked.public_event_refs == ()
    assert any(
        surface.state is SurfaceRefState.MISSING
        and surface.surface_id == "wcs:public_event_adapter"
        for surface in blocked.blocked_surface_refs
    )


def test_monetization_blocked_action_preserves_archive_posture_and_blocks_revenue() -> None:
    projection = load_director_programme_format_action_projection()
    monetization_blocked = projection.require_action(
        "programme-format-action:monetization_blocked_run"
    )

    assert monetization_blocked.action_state is ProgrammeFormatActionState.MONETIZATION_BLOCKED
    assert monetization_blocked.requested_mode == "public_monetizable"
    assert monetization_blocked.effective_mode == "public_archive"
    assert monetization_blocked.public_claim_allowed is True
    assert monetization_blocked.archive_claim_allowed is True
    assert monetization_blocked.public_live_claim_allowed is False
    assert monetization_blocked.monetization_claim_allowed is False
    assert "monetization_readiness_missing" in monetization_blocked.blocked_reasons
    assert "monetization-readiness-ledger" in monetization_blocked.conversion_obligations
    assert "blocked:monetization" in monetization_blocked.conversion_obligations


def test_stale_and_unavailable_snapshot_surfaces_become_visible_blocked_actions() -> None:
    projection = load_director_programme_format_action_projection()
    stale = projection.rows_for_state(ProgrammeFormatActionState.STALE)[0]
    unavailable = projection.require_action(
        "programme-format-action:unavailable:model_provider.litellm.remote-route"
    )

    assert stale.public_claim_allowed is False
    assert stale.blocked_surface_refs[0].surface_id == "state_file:vision.classification-snapshot"
    assert stale.blocked_surface_refs[0].state is SurfaceRefState.STALE
    assert "stale_source" in stale.blocked_reasons

    assert unavailable.public_claim_allowed is False
    assert unavailable.format_id == "what_is_this"
    assert unavailable.blocked_surface_refs[0].state is SurfaceRefState.UNAVAILABLE
    assert "missing_runtime_witness" in unavailable.blocked_reasons


def test_static_prompt_hint_cannot_authorize_programme_action_availability() -> None:
    projection = load_director_programme_format_action_projection()
    static_hint = projection.require_action(
        "programme-format-action:unavailable:prompt_hint.director.static-surface-family"
    )

    assert static_hint.action_state is ProgrammeFormatActionState.UNAVAILABLE
    assert static_hint.public_claim_allowed is False
    assert any(ref.startswith("prompt-hint:") for ref in static_hint.source_refs)

    payload = cast("dict[str, Any]", static_hint.model_dump(mode="json"))
    payload["action_state"] = "public_live"
    payload["public_claim_allowed"] = True
    payload["public_live_claim_allowed"] = True
    payload["public_event_refs"] = ["public-event:synthetic"]
    payload["witness_refs"] = ["witness:synthetic"]
    payload["rights_refs"] = ["rights:synthetic"]
    payload["blocked_reasons"] = []
    payload["missing_surface_refs"] = []
    payload["blocked_surface_refs"] = []

    with pytest.raises(ValueError, match="static hints cannot authorize available"):
        DirectorProgrammeFormatActionRow.model_validate(payload)
