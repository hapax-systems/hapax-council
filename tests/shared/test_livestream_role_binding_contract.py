"""Integration tests for livestream role/programme/director/speech binding."""

from __future__ import annotations

import pytest

from agents.live_captions.reader import CaptionEvent
from agents.live_captions.routing import RoutingPolicy
from shared.caption_substrate_adapter import project_caption_substrate
from shared.conative_impingement import (
    ActionTendencyImpingement,
    action_tendency_impulse_from_impingement,
    narrative_drive_content_payload,
)
from shared.content_programme_run_store import build_fixture_envelope
from shared.director_world_surface_snapshot import load_director_world_surface_snapshot_fixtures
from shared.livestream_role_state import (
    AuthorityCeiling,
    LivestreamRole,
    LivestreamRoleState,
    PublicMode,
    SpeechAct,
    SpeechActDestination,
    SpeechActKind,
    SpeechPosture,
    authorize_speech_act,
)
from shared.scrim_wcs_claim_posture import (
    ScrimWCSClaimPostureInput,
    load_scrim_wcs_claim_posture_fixtures,
    resolve_fixture,
)

ROUTE_REF = "audio_route:broadcast.master.normalized"


def _public_live_role() -> LivestreamRoleState:
    return LivestreamRoleState(
        role_state_id="livestream-role-state:run-public",
        current_role=LivestreamRole.PROGRAMME_HOST,
        public_mode=PublicMode.PUBLIC_LIVE,
        expected_speech_posture=SpeechPosture.PUBLIC_NARRATION,
        authority_ceiling=AuthorityCeiling.PUBLIC_LIVE,
        grounding_question="What does this run ground from witnessed evidence?",
        active_programme_run_ref="run-public",
        director_move_snapshot_ref="director-wcs-snapshot-fixture-20260430",
        available_wcs_surfaces=(ROUTE_REF, "wcs:grounding.fixture"),
        allowed_speech_acts=frozenset(
            {SpeechActKind.HOST_BEAT, SpeechActKind.GROUNDING_ANNOTATION}
        ),
        completion_witness_requirements=("witness:egress.fixture",),
    )


def _private_role() -> LivestreamRoleState:
    return LivestreamRoleState(
        role_state_id="livestream-role-state:private",
        current_role=LivestreamRole.PROGRAMME_HOST,
        public_mode=PublicMode.PRIVATE,
        expected_speech_posture=SpeechPosture.PRIVATE_NOTE,
        authority_ceiling=AuthorityCeiling.PRIVATE_ONLY,
        allowed_speech_acts=frozenset({SpeechActKind.GROUNDING_ANNOTATION}),
    )


def _public_speech_act(*, route_ref: str = ROUTE_REF) -> SpeechAct:
    return SpeechAct(
        act_kind=SpeechActKind.GROUNDING_ANNOTATION,
        role=LivestreamRole.PROGRAMME_HOST,
        role_state_ref="livestream-role-state:run-public",
        destination=SpeechActDestination.PUBLIC_LIVE,
        claim_posture=AuthorityCeiling.PUBLIC_LIVE,
        programme_run_ref="run-public",
        wcs_snapshot_ref="wcs:grounding.fixture",
        route_ref=route_ref,
        completion_witness_refs=("witness:egress.fixture",),
    )


def test_public_director_speech_requires_role_wcs_route_and_public_event() -> None:
    decision = authorize_speech_act(
        _public_live_role(),
        _public_speech_act(),
        public_event_refs=("rvpe:run-public",),
    )

    assert decision.authorized is True
    assert decision.effective_destination is SpeechActDestination.PUBLIC_LIVE

    wrong_route = authorize_speech_act(
        _public_live_role(),
        _public_speech_act(route_ref="audio_route:unavailable"),
        public_event_refs=("rvpe:run-public",),
    )
    assert wrong_route.authorized is False
    assert "route_not_available_in_role_state" in wrong_route.reasons

    no_public_event = authorize_speech_act(_public_live_role(), _public_speech_act())
    assert no_public_event.authorized is False
    assert "public_event_ref_missing" in no_public_event.reasons


@pytest.mark.parametrize(
    "forbidden_flag",
    ["truth_source_allowed", "scheduler_action_allowed", "wcs_substitute_allowed"],
)
def test_speech_act_cannot_be_scheduler_truth_source_or_wcs_substitute(
    forbidden_flag: str,
) -> None:
    payload = _public_speech_act().model_dump(mode="json")
    payload[forbidden_flag] = True

    with pytest.raises(ValueError):
        SpeechAct.model_validate(payload)


def test_director_snapshot_authorizes_public_speech_through_bound_role_state() -> None:
    snapshot = (
        load_director_world_surface_snapshot_fixtures()
        .snapshots[0]
        .model_copy(update={"role_state": _public_live_role()})
    )

    decision = snapshot.authorize_speech_act(_public_speech_act())

    assert decision.authorized is True
    assert decision.role_state_ref == "livestream-role-state:run-public"


def test_programme_run_envelope_carries_current_role_and_expected_speech_posture() -> None:
    archive = build_fixture_envelope("public_archive_run")
    blocked = build_fixture_envelope("public_live_blocked_run")

    assert archive.role_state.active_programme_run_ref == archive.run_id
    assert archive.role_state.public_mode is PublicMode.PUBLIC_ARCHIVE
    assert archive.role_state.expected_speech_posture is SpeechPosture.ARCHIVE_ONLY
    assert archive.role_state.grounding_question == archive.grounding_question

    assert blocked.requested_public_private_mode == "public_live"
    assert blocked.public_private_mode == "dry_run"
    assert blocked.role_state.public_mode is PublicMode.DRY_RUN
    assert SpeechActKind.REFUSAL_ARTICULATION in blocked.role_state.allowed_speech_acts


def test_conative_impulse_carries_role_destination_claim_and_terminal_fulfillment() -> None:
    payload = narrative_drive_content_payload(
        impingement_id="role-bind",
        narrative="The run has a witnessed boundary worth narrating.",
        drive_name="narration",
        strength_posterior=0.52,
        chronicle_event_count=5,
        stimmung_stance="attentive",
        programme_role="programme_host",
        role_state_ref="livestream-role-state:run-public",
    )
    impulse = ActionTendencyImpingement.model_validate(
        {key: payload[key] for key in ActionTendencyImpingement.model_fields}
    )

    assert impulse.role_state_ref == "livestream-role-state:run-public"
    assert impulse.speech_destination == "public_live"
    assert impulse.claim_posture == "public_live"
    assert impulse.terminal_state == "pending"

    inhibited = action_tendency_impulse_from_impingement(
        type(
            "Impingement",
            (),
            {
                "id": "imp-role",
                "source": "endogenous.narrative_drive",
                "strength": 0.5,
                "content": {
                    "content_summary": "Route evidence is missing.",
                    "evidence_refs": ["source:endogenous.narrative_drive"],
                },
            },
        )(),
        terminal_state="inhibited",
        terminal_reason="route_missing",
        default_execution_refs=False,
    )
    assert inhibited.selected_fulfillment == "withheld"
    assert inhibited.terminal_state == "inhibited"


def test_caption_adapter_rejects_public_caption_when_role_state_is_private() -> None:
    events = [CaptionEvent(ts=100.0, text="public words", duration_ms=1200, speaker="oudepode")]
    routing = RoutingPolicy(allow=frozenset(), deny=frozenset(), default_allow=True)

    candidates, rejections = project_caption_substrate(
        events,
        routing=routing,
        now=100.5,
        av_offset_s=0.1,
        role_state=_private_role(),
    )

    assert candidates == []
    assert [rejection.reason for rejection in rejections] == ["role_state_blocks_public_caption"]


def test_scrim_role_state_mode_must_match_voice_role_posture() -> None:
    fixture = next(
        row
        for row in load_scrim_wcs_claim_posture_fixtures().fixtures
        if row.family == "fresh_public_safe"
    )
    resolved = resolve_fixture(fixture)
    data = resolved.model_dump(mode="json")
    data["livestream_role_state"] = LivestreamRoleState(
        role_state_id="livestream-role-state:scrim-archive",
        current_role=LivestreamRole.ARCHIVE_NARRATOR,
        public_mode=PublicMode.PUBLIC_ARCHIVE,
        expected_speech_posture=SpeechPosture.ARCHIVE_ONLY,
        authority_ceiling=AuthorityCeiling.PUBLIC_VISIBLE,
        allowed_speech_acts=frozenset({SpeechActKind.ARCHIVE_MARKER}),
    ).model_dump(mode="json")
    assert ScrimWCSClaimPostureInput.model_validate(data).livestream_role_state is not None

    data["livestream_role_state"] = _private_role().model_dump(mode="json")
    with pytest.raises(ValueError, match="public_private_mode must mirror"):
        ScrimWCSClaimPostureInput.model_validate(data)
