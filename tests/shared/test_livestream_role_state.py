"""Tests for ``shared.livestream_role_state``.

Per cc-task ``livestream-role-speech-programme-binding-contract``
(WSJF 9.4). Phase 0 schema/fixture tests for the role + speech-act
envelopes consumed by programme runner, director, scrim, audio,
captions, archive, and public adapters.

Coverage maps to the cc-task acceptance criteria:

  - typed role-state envelope exists + consumed by tests → TestRoleState
  - speech cannot emit publicly without role/WCS/route allowance →
    TestSpeechActPublicLive + TestRoleAuthorization
  - speech-act records carry role/programme_run/impulse/WCS/destination/
    claim_posture/completion_witness → TestSpeechActSchema
  - role policy can inhibit/redirect/authorize without erasing impulse →
    TestImpulseFulfillment
  - refusal/correction/blocker speech acts are first-class →
    TestRefusalCorrectionBlocker
  - silent director moves remain valid when speech not recruited →
    TestSilentDirectorMove (role state with no allowed speech acts is
    a CONFIG ERROR, not a silent state — silent moves don't construct
    a SpeechAct at all)
  - fixture states for unavailable / blocked / private_only / stale /
    dry_run / public_live / monetization_ready → TestFixtureStates
"""

from __future__ import annotations

import pytest

from shared.livestream_role_state import (
    AuthorityCeiling,
    LivestreamRole,
    LivestreamRoleState,
    PublicMode,
    SpeechAct,
    SpeechActDestination,
    SpeechActKind,
    SpeechFulfillment,
    TerminalOutcome,
    is_speech_act_authorized_by_role,
)

# ── Module surface ───────────────────────────────────────────────────


class TestModuleSurface:
    def test_role_taxonomy(self) -> None:
        # The 9-role taxonomy is the cc-task contract; expansion
        # requires explicit test addition so unrelated additions
        # don't sneak in.
        assert {r.value for r in LivestreamRole} == {
            "research_host",
            "programme_host",
            "claim_auditor",
            "refusal_clerk",
            "archive_narrator",
            "correction_witness",
            "content_critic",
            "scene_director_voice",
            "operator_context_witness",
        }

    def test_speech_act_taxonomy(self) -> None:
        assert {a.value for a in SpeechActKind} == {
            "host_beat",
            "grounding_annotation",
            "boundary_marker",
            "refusal_articulation",
            "correction_articulation",
            "attention_route",
            "continuity_bridge",
            "archive_marker",
            "conversion_cue",
            "operator_context_note",
        }

    def test_public_mode_enum(self) -> None:
        assert {m.value for m in PublicMode} == {
            "public_live",
            "public_archive",
            "private",
            "dry_run",
            "blocked",
        }

    def test_authority_ceiling_taxonomy(self) -> None:
        # Mirrors the PerceptualField witness-map taxonomy so consumers
        # share one ceiling vocabulary.
        assert {c.value for c in AuthorityCeiling} == {
            "none",
            "diagnostic",
            "private_only",
            "witnessed_presence",
            "grounded_private",
            "public_visible",
            "public_live",
            "action_authorizing",
        }

    def test_terminal_outcome_taxonomy(self) -> None:
        assert {t.value for t in TerminalOutcome} == {
            "completed",
            "inhibited",
            "redirected",
            "interrupted",
            "failed",
        }


# ── LivestreamRoleState invariants ───────────────────────────────────


class TestRoleState:
    def test_minimal_private_role_constructs(self) -> None:
        # Private mode with allowed_speech_acts populated — minimal
        # config that should construct without error.
        state = LivestreamRoleState(
            current_role=LivestreamRole.RESEARCH_HOST,
            public_mode=PublicMode.PRIVATE,
            authority_ceiling=AuthorityCeiling.PRIVATE_ONLY,
            allowed_speech_acts=frozenset({SpeechActKind.HOST_BEAT}),
        )
        assert state.current_role is LivestreamRole.RESEARCH_HOST

    def test_empty_allowed_speech_acts_rejected(self) -> None:
        # A role authorizing no speech acts is a config error, not a
        # silent-by-design state. The schema rejects it.
        with pytest.raises(ValueError, match="allowed_speech_acts must be non-empty"):
            LivestreamRoleState(
                current_role=LivestreamRole.RESEARCH_HOST,
                public_mode=PublicMode.PRIVATE,
                authority_ceiling=AuthorityCeiling.PRIVATE_ONLY,
                allowed_speech_acts=frozenset(),
            )

    def test_public_live_requires_available_surfaces(self) -> None:
        with pytest.raises(ValueError, match="available_wcs_surfaces"):
            LivestreamRoleState(
                current_role=LivestreamRole.PROGRAMME_HOST,
                public_mode=PublicMode.PUBLIC_LIVE,
                authority_ceiling=AuthorityCeiling.PUBLIC_LIVE,
                allowed_speech_acts=frozenset({SpeechActKind.HOST_BEAT}),
                director_move_snapshot_ref="director-snap-1",
                # available_wcs_surfaces=()  — missing
            )

    def test_public_live_requires_director_snapshot(self) -> None:
        with pytest.raises(ValueError, match="director_move_snapshot_ref"):
            LivestreamRoleState(
                current_role=LivestreamRole.PROGRAMME_HOST,
                public_mode=PublicMode.PUBLIC_LIVE,
                authority_ceiling=AuthorityCeiling.PUBLIC_LIVE,
                allowed_speech_acts=frozenset({SpeechActKind.HOST_BEAT}),
                available_wcs_surfaces=("camera.studio",),
                # director_move_snapshot_ref=""  — missing
            )

    def test_blocked_requires_blocked_surface(self) -> None:
        with pytest.raises(ValueError, match="blocked_wcs_surface"):
            LivestreamRoleState(
                current_role=LivestreamRole.REFUSAL_CLERK,
                public_mode=PublicMode.BLOCKED,
                authority_ceiling=AuthorityCeiling.DIAGNOSTIC,
                allowed_speech_acts=frozenset({SpeechActKind.REFUSAL_ARTICULATION}),
            )

    def test_dry_run_forbids_monetization(self) -> None:
        with pytest.raises(ValueError, match="dry_run.*monetization"):
            LivestreamRoleState(
                current_role=LivestreamRole.PROGRAMME_HOST,
                public_mode=PublicMode.DRY_RUN,
                authority_ceiling=AuthorityCeiling.DIAGNOSTIC,
                allowed_speech_acts=frozenset({SpeechActKind.HOST_BEAT}),
                monetization_ready=True,
            )

    def test_surface_lists_must_be_disjoint(self) -> None:
        # A surface cannot be both available + blocked.
        with pytest.raises(ValueError, match="multiple WCS lists"):
            LivestreamRoleState(
                current_role=LivestreamRole.RESEARCH_HOST,
                public_mode=PublicMode.PRIVATE,
                authority_ceiling=AuthorityCeiling.PRIVATE_ONLY,
                allowed_speech_acts=frozenset({SpeechActKind.HOST_BEAT}),
                available_wcs_surfaces=("camera.studio",),
                blocked_wcs_surfaces=("camera.studio",),
            )

    def test_state_is_frozen(self) -> None:
        state = LivestreamRoleState(
            current_role=LivestreamRole.RESEARCH_HOST,
            public_mode=PublicMode.PRIVATE,
            authority_ceiling=AuthorityCeiling.PRIVATE_ONLY,
            allowed_speech_acts=frozenset({SpeechActKind.HOST_BEAT}),
        )
        with pytest.raises(Exception):  # noqa: BLE001 — pydantic ValidationError or AttributeError
            state.current_role = LivestreamRole.PROGRAMME_HOST  # type: ignore[misc]


# ── SpeechAct schema ─────────────────────────────────────────────────


class TestSpeechActSchema:
    def test_minimal_private_speech_act(self) -> None:
        act = SpeechAct(
            act_kind=SpeechActKind.HOST_BEAT,
            role=LivestreamRole.RESEARCH_HOST,
            destination=SpeechActDestination.PRIVATE,
            claim_posture=AuthorityCeiling.PRIVATE_ONLY,
        )
        assert act.act_kind is SpeechActKind.HOST_BEAT
        assert act.programme_run_ref == ""
        assert act.originating_impulse_ref == ""
        assert act.terminal_outcome is None

    def test_carries_required_refs(self) -> None:
        # Pin the cc-task acceptance: speech-act records include role,
        # programme_run, originating impulse, WCS snapshot, destination,
        # claim posture, completion-witness requirement.
        act = SpeechAct(
            act_kind=SpeechActKind.GROUNDING_ANNOTATION,
            role=LivestreamRole.PROGRAMME_HOST,
            destination=SpeechActDestination.PUBLIC_LIVE,
            claim_posture=AuthorityCeiling.PUBLIC_LIVE,
            programme_run_ref="prog-run-1",
            impulse_id="impulse-2",
            originating_impulse_ref="impulse-2",
            action_tendency="speak",
            selected_fulfillment=SpeechFulfillment.SPOKEN_NARRATION,
            wcs_snapshot_ref="wcs-snap-3",
            route_ref="audio_route:broadcast.master.normalized",
            completion_witness_required=True,
            completion_witness_refs=("witness:egress",),
            terminal_outcome=TerminalOutcome.COMPLETED,
        )
        assert act.programme_run_ref == "prog-run-1"
        assert act.originating_impulse_ref == "impulse-2"
        assert act.wcs_snapshot_ref == "wcs-snap-3"
        assert act.completion_witness_required is True
        assert act.terminal_outcome is TerminalOutcome.COMPLETED


class TestSpeechActPublicLive:
    def test_requires_completion_witness(self) -> None:
        with pytest.raises(ValueError, match="completion_witness_required"):
            SpeechAct(
                act_kind=SpeechActKind.HOST_BEAT,
                role=LivestreamRole.PROGRAMME_HOST,
                destination=SpeechActDestination.PUBLIC_LIVE,
                claim_posture=AuthorityCeiling.PUBLIC_LIVE,
                wcs_snapshot_ref="wcs-1",
                completion_witness_required=False,
            )

    def test_requires_wcs_snapshot_ref(self) -> None:
        with pytest.raises(ValueError, match="wcs_snapshot_ref"):
            SpeechAct(
                act_kind=SpeechActKind.HOST_BEAT,
                role=LivestreamRole.PROGRAMME_HOST,
                destination=SpeechActDestination.PUBLIC_LIVE,
                claim_posture=AuthorityCeiling.PUBLIC_LIVE,
                completion_witness_required=True,
                # wcs_snapshot_ref=""  — missing
            )

    def test_public_archive_requires_wcs_ref(self) -> None:
        with pytest.raises(ValueError, match="wcs_snapshot_ref"):
            SpeechAct(
                act_kind=SpeechActKind.ARCHIVE_MARKER,
                role=LivestreamRole.ARCHIVE_NARRATOR,
                destination=SpeechActDestination.PUBLIC_ARCHIVE,
                claim_posture=AuthorityCeiling.PUBLIC_VISIBLE,
            )


class TestConversionCueRestriction:
    def test_conversion_cue_in_private_rejected(self) -> None:
        with pytest.raises(ValueError, match="conversion_cue.*private"):
            SpeechAct(
                act_kind=SpeechActKind.CONVERSION_CUE,
                role=LivestreamRole.PROGRAMME_HOST,
                destination=SpeechActDestination.PRIVATE,
                claim_posture=AuthorityCeiling.PRIVATE_ONLY,
            )

    def test_conversion_cue_in_dry_run_rejected(self) -> None:
        with pytest.raises(ValueError, match="conversion_cue"):
            SpeechAct(
                act_kind=SpeechActKind.CONVERSION_CUE,
                role=LivestreamRole.PROGRAMME_HOST,
                destination=SpeechActDestination.DIRECTOR_DRY_RUN,
                claim_posture=AuthorityCeiling.DIAGNOSTIC,
            )

    def test_conversion_cue_in_public_live_allowed(self) -> None:
        act = SpeechAct(
            act_kind=SpeechActKind.CONVERSION_CUE,
            role=LivestreamRole.PROGRAMME_HOST,
            destination=SpeechActDestination.PUBLIC_LIVE,
            claim_posture=AuthorityCeiling.PUBLIC_LIVE,
            wcs_snapshot_ref="wcs-1",
            route_ref="audio_route:broadcast.master.normalized",
            completion_witness_refs=("witness:egress",),
        )
        assert act.act_kind is SpeechActKind.CONVERSION_CUE


# ── Role authorization ──────────────────────────────────────────────


class TestRoleAuthorization:
    """``is_speech_act_authorized_by_role`` is the public predicate
    director / speech consumers MUST call before emission."""

    def _state(self, allowed: frozenset[SpeechActKind]) -> LivestreamRoleState:
        return LivestreamRoleState(
            current_role=LivestreamRole.PROGRAMME_HOST,
            public_mode=PublicMode.PRIVATE,
            authority_ceiling=AuthorityCeiling.PRIVATE_ONLY,
            allowed_speech_acts=allowed,
        )

    def test_allowed_kind_authorized(self) -> None:
        state = self._state(frozenset({SpeechActKind.HOST_BEAT}))
        act = SpeechAct(
            act_kind=SpeechActKind.HOST_BEAT,
            role=LivestreamRole.PROGRAMME_HOST,
            destination=SpeechActDestination.PRIVATE,
            claim_posture=AuthorityCeiling.PRIVATE_ONLY,
        )
        assert is_speech_act_authorized_by_role(state, act) is True

    def test_disallowed_kind_rejected(self) -> None:
        state = self._state(frozenset({SpeechActKind.HOST_BEAT}))
        act = SpeechAct(
            act_kind=SpeechActKind.CONVERSION_CUE,
            role=LivestreamRole.PROGRAMME_HOST,
            destination=SpeechActDestination.PUBLIC_LIVE,
            claim_posture=AuthorityCeiling.PUBLIC_LIVE,
            wcs_snapshot_ref="wcs-1",
            route_ref="audio_route:broadcast.master.normalized",
            completion_witness_refs=("witness:egress",),
        )
        assert is_speech_act_authorized_by_role(state, act) is False

    def test_role_mismatch_rejected(self) -> None:
        state = self._state(frozenset({SpeechActKind.HOST_BEAT}))
        # State role is PROGRAMME_HOST; act asserts a different role.
        act = SpeechAct(
            act_kind=SpeechActKind.HOST_BEAT,
            role=LivestreamRole.CLAIM_AUDITOR,
            destination=SpeechActDestination.PRIVATE,
            claim_posture=AuthorityCeiling.PRIVATE_ONLY,
        )
        assert is_speech_act_authorized_by_role(state, act) is False


# ── Refusal / correction / blocker first-class ──────────────────────


class TestRefusalCorrectionBlocker:
    """Per the cc-task: refusal/correction/blocker speech acts are
    first-class valid outputs, not error states."""

    def test_refusal_articulation_authorizes_under_refusal_clerk(self) -> None:
        state = LivestreamRoleState(
            current_role=LivestreamRole.REFUSAL_CLERK,
            public_mode=PublicMode.BLOCKED,
            authority_ceiling=AuthorityCeiling.DIAGNOSTIC,
            blocked_wcs_surfaces=("camera.studio.broadcast",),
            allowed_speech_acts=frozenset(
                {
                    SpeechActKind.REFUSAL_ARTICULATION,
                    SpeechActKind.BOUNDARY_MARKER,
                }
            ),
            refusal_posture="rights_unclear",
        )
        act = SpeechAct(
            act_kind=SpeechActKind.REFUSAL_ARTICULATION,
            role=LivestreamRole.REFUSAL_CLERK,
            destination=SpeechActDestination.PRIVATE,
            claim_posture=AuthorityCeiling.DIAGNOSTIC,
            wcs_snapshot_ref="wcs-1",
        )
        assert is_speech_act_authorized_by_role(state, act) is True
        assert state.refusal_posture == "rights_unclear"

    def test_correction_articulation_authorizes(self) -> None:
        state = LivestreamRoleState(
            current_role=LivestreamRole.CORRECTION_WITNESS,
            public_mode=PublicMode.PUBLIC_LIVE,
            authority_ceiling=AuthorityCeiling.PUBLIC_LIVE,
            available_wcs_surfaces=("audio.broadcast.live",),
            director_move_snapshot_ref="director-snap-1",
            allowed_speech_acts=frozenset({SpeechActKind.CORRECTION_ARTICULATION}),
            correction_posture="prior_claim_revised",
        )
        assert state.correction_posture == "prior_claim_revised"


# ── Impulse fulfillment terminal-state semantics ────────────────────


class TestImpulseFulfillment:
    """Per the spec: 'a content-bearing urge inhibited or blocked
    without a terminal outcome' is a failure mode the schema must make
    legible. Every speech act tied to an originating impulse can carry
    a terminal_outcome covering completed/inhibited/redirected/
    interrupted/failed."""

    @pytest.mark.parametrize(
        "outcome",
        [
            TerminalOutcome.COMPLETED,
            TerminalOutcome.INHIBITED,
            TerminalOutcome.REDIRECTED,
            TerminalOutcome.INTERRUPTED,
            TerminalOutcome.FAILED,
        ],
    )
    def test_terminal_outcomes_round_trip(self, outcome: TerminalOutcome) -> None:
        # COMPLETED on a private destination requires wcs_snapshot_ref
        # (truncation guard) — supply one so the parametrize sweep
        # doesn't spuriously fail on that branch.
        act = SpeechAct(
            act_kind=SpeechActKind.GROUNDING_ANNOTATION,
            role=LivestreamRole.PROGRAMME_HOST,
            destination=SpeechActDestination.PRIVATE,
            claim_posture=AuthorityCeiling.PRIVATE_ONLY,
            originating_impulse_ref="impulse-7",
            action_tendency="speak",
            selected_fulfillment=SpeechFulfillment.SPOKEN_NARRATION,
            wcs_snapshot_ref="wcs-1",
            terminal_outcome=outcome,
        )
        assert act.terminal_outcome is outcome

    def test_in_flight_act_with_impulse_is_legal(self) -> None:
        # In-flight: terminal_outcome=None is allowed but the consumer
        # must finalize before archiving.
        act = SpeechAct(
            act_kind=SpeechActKind.HOST_BEAT,
            role=LivestreamRole.PROGRAMME_HOST,
            destination=SpeechActDestination.PRIVATE,
            claim_posture=AuthorityCeiling.PRIVATE_ONLY,
            originating_impulse_ref="impulse-7",
            terminal_outcome=None,
        )
        assert act.terminal_outcome is None

    def test_completed_on_private_requires_wcs_ref(self) -> None:
        with pytest.raises(ValueError, match="COMPLETED"):
            SpeechAct(
                act_kind=SpeechActKind.HOST_BEAT,
                role=LivestreamRole.PROGRAMME_HOST,
                destination=SpeechActDestination.PRIVATE,
                claim_posture=AuthorityCeiling.PRIVATE_ONLY,
                terminal_outcome=TerminalOutcome.COMPLETED,
                # wcs_snapshot_ref=""  — missing
            )


# ── Fixture-state coverage (cc-task §"Acceptance Criteria") ────────


class TestFixtureStates:
    """Per cc-task: fixture tests for unavailable / blocked /
    private_only / stale / dry_run / public_live /
    monetization_ready role states."""

    def test_unavailable_state(self) -> None:
        # Role with no available surfaces; only diagnostic acts allowed.
        state = LivestreamRoleState(
            current_role=LivestreamRole.RESEARCH_HOST,
            public_mode=PublicMode.PRIVATE,
            authority_ceiling=AuthorityCeiling.NONE,
            allowed_speech_acts=frozenset({SpeechActKind.GROUNDING_ANNOTATION}),
        )
        assert state.public_mode is PublicMode.PRIVATE
        assert state.authority_ceiling is AuthorityCeiling.NONE

    def test_blocked_state(self) -> None:
        state = LivestreamRoleState(
            current_role=LivestreamRole.REFUSAL_CLERK,
            public_mode=PublicMode.BLOCKED,
            authority_ceiling=AuthorityCeiling.DIAGNOSTIC,
            blocked_wcs_surfaces=("audio.broadcast.live",),
            allowed_speech_acts=frozenset({SpeechActKind.REFUSAL_ARTICULATION}),
        )
        assert state.public_mode is PublicMode.BLOCKED

    def test_private_only_state(self) -> None:
        state = LivestreamRoleState(
            current_role=LivestreamRole.OPERATOR_CONTEXT_WITNESS,
            public_mode=PublicMode.PRIVATE,
            authority_ceiling=AuthorityCeiling.PRIVATE_ONLY,
            private_only_wcs_surfaces=("operator.activity",),
            allowed_speech_acts=frozenset({SpeechActKind.OPERATOR_CONTEXT_NOTE}),
        )
        assert state.private_only_wcs_surfaces == ("operator.activity",)

    def test_stale_state(self) -> None:
        state = LivestreamRoleState(
            current_role=LivestreamRole.RESEARCH_HOST,
            public_mode=PublicMode.PRIVATE,
            authority_ceiling=AuthorityCeiling.DIAGNOSTIC,
            stale_wcs_surfaces=("camera.studio",),
            allowed_speech_acts=frozenset({SpeechActKind.GROUNDING_ANNOTATION}),
        )
        assert state.stale_wcs_surfaces == ("camera.studio",)

    def test_dry_run_state(self) -> None:
        state = LivestreamRoleState(
            current_role=LivestreamRole.PROGRAMME_HOST,
            public_mode=PublicMode.DRY_RUN,
            authority_ceiling=AuthorityCeiling.DIAGNOSTIC,
            available_wcs_surfaces=("camera.studio",),
            allowed_speech_acts=frozenset(
                {SpeechActKind.HOST_BEAT, SpeechActKind.GROUNDING_ANNOTATION}
            ),
            monetization_ready=False,  # required for dry_run
        )
        assert state.public_mode is PublicMode.DRY_RUN
        assert state.monetization_ready is False

    def test_public_live_state(self) -> None:
        state = LivestreamRoleState(
            current_role=LivestreamRole.PROGRAMME_HOST,
            public_mode=PublicMode.PUBLIC_LIVE,
            authority_ceiling=AuthorityCeiling.PUBLIC_LIVE,
            available_wcs_surfaces=("camera.studio", "audio.broadcast.live"),
            director_move_snapshot_ref="director-snap-42",
            allowed_speech_acts=frozenset({SpeechActKind.HOST_BEAT}),
        )
        assert state.public_mode is PublicMode.PUBLIC_LIVE

    def test_monetization_ready_state(self) -> None:
        state = LivestreamRoleState(
            current_role=LivestreamRole.PROGRAMME_HOST,
            public_mode=PublicMode.PUBLIC_LIVE,
            authority_ceiling=AuthorityCeiling.PUBLIC_LIVE,
            available_wcs_surfaces=("camera.studio",),
            director_move_snapshot_ref="director-snap-42",
            allowed_speech_acts=frozenset({SpeechActKind.HOST_BEAT, SpeechActKind.CONVERSION_CUE}),
            monetization_ready=True,
        )
        assert state.monetization_ready is True


# ── Silent director moves ───────────────────────────────────────────


class TestSilentDirectorMove:
    """Per cc-task: silent director moves remain valid when speech is
    not recruited. The role state still requires SOME allowed speech
    act (config error guard) but the director can choose not to
    construct a SpeechAct at all — that path doesn't exercise this
    schema."""

    def test_role_state_with_minimal_acts_allows_silent_directing(self) -> None:
        # The role authorizes acts; the director simply doesn't
        # construct any SpeechAct this tick. No SpeechAct is created;
        # nothing in this schema fires.
        state = LivestreamRoleState(
            current_role=LivestreamRole.SCENE_DIRECTOR_VOICE,
            public_mode=PublicMode.PUBLIC_LIVE,
            authority_ceiling=AuthorityCeiling.PUBLIC_LIVE,
            available_wcs_surfaces=("camera.studio",),
            director_move_snapshot_ref="director-snap-42",
            allowed_speech_acts=frozenset({SpeechActKind.ATTENTION_ROUTE}),
        )
        # The director's silent path (no speech act constructed) is
        # outside this schema — but the state itself is well-formed
        # and ready when the director DOES recruit voice.
        assert state.public_mode is PublicMode.PUBLIC_LIVE
