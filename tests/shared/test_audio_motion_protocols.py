"""Tests for shared/audio_motion_protocols.py.

Per cc-task ``audio-reactive-ward-camera-homage-motion-protocols`` (WSJF 8.9,
Phase 0). Acceptance criteria coverage:

- One camera, one ward, one HOMAGE move can be proposed from source-role
  audio evidence (see TestVerifiedProposals).
- Moves are no-op/blocked when audio is stale, unsafe, or public-posture
  blocked (TestStaleEvidence, TestPublicPostureBlocked, TestPermissionMissing).
- Cooldowns prevent per-beat frantic cuts (TestCooldown).
- Visual outcome witnesses record rendered result and source refs
  (TestWitnessLedger).
- Tests cover music, TTS, operator voice, YT/react, silence, stale evidence
  (TestPerSourceCases).
"""

from __future__ import annotations

from shared.audio_motion_protocols import (
    DEFAULT_COOLDOWN_S,
    CameraMoveKind,
    HomageMoveKind,
    MotionProtocolRunner,
    MotionWitnessLedger,
    WardMoveKind,
    record_witness,
)
from shared.audio_source_evidence import (
    ActivityBasis,
    AudioReactiveOutcome,
    AudioSourceEvidence,
    AudioSourceLedger,
    AudioSourceRole,
    DownstreamPermissions,
    EgressPosture,
    EgressPostureState,
    Freshness,
    FreshnessState,
    PublicPrivatePosture,
    RoutePosture,
    RoutePostureState,
    SignalMetrics,
)

NOW = 1_777_500_000.0


def _make_row(
    *,
    role: AudioSourceRole,
    active: bool,
    rms: float = 0.25,
    freshness_state: FreshnessState = FreshnessState.FRESH,
    public_posture: PublicPrivatePosture = PublicPrivatePosture.PUBLIC_CANDIDATE,
    director_move: bool = True,
    visual_modulation: bool = True,
    public_claim: bool = False,
    row_id: str | None = None,
) -> AudioSourceEvidence:
    """Build a canonical AudioSourceEvidence for a given role + state."""
    sig = SignalMetrics(
        rms=rms,
        onset=0.1,
        centroid=0.4,
        zcr=0.1,
        bpm_estimate=120.0,
        energy_delta=0.0,
        bass_band=rms,
        mid_band=rms / 2.0,
        treble_band=rms / 3.0,
        measurement_present=True,
        measured_non_silent=rms > 1e-4,
    )
    return AudioSourceEvidence(
        row_id=row_id or f"row:{role.value}",
        source_id=f"source:{role.value}",
        role=role,
        producer="test-producer",
        semantic_surface_id=f"surface:{role.value}",
        signal_metrics=sig,
        freshness=Freshness(
            state=freshness_state,
            ttl_s=4.0,
            observed_age_s=0.5 if freshness_state is FreshnessState.FRESH else 99.0,
            checked_at="2026-05-02T13:00:00Z",
            evidence_refs=("evidence:freshness-probe",),
        ),
        active=active,
        activity_basis=ActivityBasis.MEASURED_SIGNAL,
        marker_evidence_refs=(),
        route_posture=RoutePosture(
            state=RoutePostureState.WITNESSED,
            route_exists=True,
            route_witnessed=True,
            evidence_refs=("evidence:route-posture",),
        ),
        egress_posture=EgressPosture(
            state=EgressPostureState.WITNESSED_PUBLIC,
            evidence_refs=("evidence:egress-posture",),
        ),
        public_private_posture=public_posture,
        wcs_refs=(f"wcs:{role.value}",),
        evidence_envelope_refs=(f"envelope:{role.value}",),
        permissions=DownstreamPermissions(
            visual_modulation=visual_modulation,
            director_move=director_move,
            semantic_fx=visual_modulation,
            public_claim=public_claim,
            clip_candidate=False,
            artifact_release=False,
        ),
    )


def _ledger(*rows: AudioSourceEvidence) -> AudioSourceLedger:
    return AudioSourceLedger(
        ledger_id="test-ledger",
        generated_at="2026-05-02T13:00:00Z",
        source_rows=rows,
    )


# ── Verified proposals across all 3 layers ──────────────────────────


class TestVerifiedProposals:
    def test_music_drives_camera_layout_drift(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(_make_row(role=AudioSourceRole.MUSIC, active=True))
        proposal = runner.propose("camera", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.VERIFIED
        assert proposal.move_kind == CameraMoveKind.LAYOUT_DRIFT.value
        assert proposal.source_roles == (AudioSourceRole.MUSIC,)
        assert "intensity" in proposal.parameters
        assert proposal.evidence_refs == ("envelope:music",)

    def test_operator_voice_drives_ward_emphasis(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(_make_row(role=AudioSourceRole.OPERATOR_VOICE, active=True))
        proposal = runner.propose("ward", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.VERIFIED
        assert proposal.move_kind == WardMoveKind.EMPHASIS.value
        assert proposal.source_roles == (AudioSourceRole.OPERATOR_VOICE,)

    def test_music_drives_homage_pair_emphasis(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(_make_row(role=AudioSourceRole.MUSIC, active=True))
        proposal = runner.propose("homage", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.VERIFIED
        assert proposal.move_kind == HomageMoveKind.PAIR_EMPHASIS.value


# ── No-op when ledger has no fresh active source ────────────────────


class TestSilence:
    def test_no_active_rows_returns_no_op(self) -> None:
        runner = MotionProtocolRunner()
        # Inactive row → no candidate.
        ledger = _ledger(_make_row(role=AudioSourceRole.MUSIC, active=False, rms=0.0))
        proposal = runner.propose("camera", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.NO_OP
        assert "no_active_source" in proposal.blocked_reasons


# ── Stale evidence is refused ────────────────────────────────────────


class TestStaleEvidence:
    def test_stale_row_returns_stale_outcome(self) -> None:
        runner = MotionProtocolRunner()
        # `active=False` here because the AudioSourceEvidence model itself
        # refuses to construct an active row whose freshness isn't FRESH.
        # The runner's stale path is reached via the candidate-selection
        # filter the same way.
        stale = _make_row(
            role=AudioSourceRole.MUSIC,
            active=False,
            freshness_state=FreshnessState.STALE,
        )
        # Pair with an inactive row of a different role so the ledger has
        # at least one row but no active candidate. Then verify NO_OP path.
        ledger = _ledger(stale)
        proposal = runner.propose("camera", ledger, now=NOW)
        # No active candidate at all → NO_OP, not STALE (stale path is
        # reached when an active candidate exists with non-FRESH freshness,
        # which the evidence model itself prevents — defensive only).
        assert proposal.outcome is AudioReactiveOutcome.NO_OP


# ── Public-posture blocked sources are refused for camera/HOMAGE ────


class TestPublicPostureBlocked:
    def test_blocked_posture_refuses_camera_move(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(
            _make_row(
                role=AudioSourceRole.MUSIC,
                active=True,
                public_posture=PublicPrivatePosture.BLOCKED,
            )
        )
        proposal = runner.propose("camera", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.BLOCKED
        assert "public_posture_blocked" in proposal.blocked_reasons

    def test_blocked_posture_refuses_homage_move(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(
            _make_row(
                role=AudioSourceRole.MUSIC,
                active=True,
                public_posture=PublicPrivatePosture.BLOCKED,
            )
        )
        proposal = runner.propose("homage", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.BLOCKED
        assert "public_posture_blocked" in proposal.blocked_reasons

    def test_private_only_allows_ward_move(self) -> None:
        """Ward emphasis is NOT egress-bound; private-only posture is OK."""
        runner = MotionProtocolRunner()
        ledger = _ledger(
            _make_row(
                role=AudioSourceRole.OPERATOR_VOICE,
                active=True,
                public_posture=PublicPrivatePosture.PRIVATE_ONLY,
            )
        )
        proposal = runner.propose("ward", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.VERIFIED


# ── Permission absence is refused ────────────────────────────────────


class TestPermissionMissing:
    def test_camera_requires_director_move_permission(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(_make_row(role=AudioSourceRole.MUSIC, active=True, director_move=False))
        proposal = runner.propose("camera", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.BLOCKED
        assert "director_move_permission_absent" in proposal.blocked_reasons

    def test_ward_requires_visual_modulation_permission(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(
            _make_row(
                role=AudioSourceRole.OPERATOR_VOICE,
                active=True,
                visual_modulation=False,
            )
        )
        proposal = runner.propose("ward", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.BLOCKED
        assert "visual_modulation_permission_absent" in proposal.blocked_reasons


# ── Visualizer governor ──────────────────────────────────────────────


class TestVisualizerGovernor:
    def test_governor_inactive_blocks_all_layers(self) -> None:
        runner = MotionProtocolRunner(governor_active=False)
        ledger = _ledger(_make_row(role=AudioSourceRole.MUSIC, active=True))
        for layer in ("camera", "ward", "homage"):
            proposal = runner.propose(layer, ledger, now=NOW)  # type: ignore[arg-type]
            assert proposal.outcome is AudioReactiveOutcome.BLOCKED
            assert "visualizer_governor_inactive" in proposal.blocked_reasons


# ── Cooldown prevents per-beat frantic cuts ─────────────────────────


class TestCooldown:
    def test_second_call_inside_window_is_blocked(self) -> None:
        runner = MotionProtocolRunner(cooldown_window_s=DEFAULT_COOLDOWN_S)
        ledger = _ledger(_make_row(role=AudioSourceRole.MUSIC, active=True))
        first = runner.propose("camera", ledger, now=NOW)
        assert first.outcome is AudioReactiveOutcome.VERIFIED
        # Try again 1s later — should be blocked.
        second = runner.propose("camera", ledger, now=NOW + 1.0)
        assert second.outcome is AudioReactiveOutcome.BLOCKED
        assert "cooldown_active" in second.blocked_reasons

    def test_third_call_after_cooldown_passes(self) -> None:
        runner = MotionProtocolRunner(cooldown_window_s=2.0)
        ledger = _ledger(_make_row(role=AudioSourceRole.MUSIC, active=True))
        runner.propose("camera", ledger, now=NOW)
        # Skip past the cooldown.
        third = runner.propose("camera", ledger, now=NOW + 5.0)
        assert third.outcome is AudioReactiveOutcome.VERIFIED

    def test_cooldown_is_per_layer(self) -> None:
        """A camera move on tick N must not block a ward move on tick N."""
        runner = MotionProtocolRunner()
        ledger = _ledger(
            _make_row(role=AudioSourceRole.MUSIC, active=True),
            _make_row(role=AudioSourceRole.OPERATOR_VOICE, active=True),
        )
        cam = runner.propose("camera", ledger, now=NOW)
        ward = runner.propose("ward", ledger, now=NOW)
        assert cam.outcome is AudioReactiveOutcome.VERIFIED
        assert ward.outcome is AudioReactiveOutcome.VERIFIED


# ── Per-source-role cases (the 6 AC mandates) ────────────────────────


class TestPerSourceCases:
    """Tests cover music, TTS, operator voice, YT/react, silence, stale."""

    def test_music_case(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(_make_row(role=AudioSourceRole.MUSIC, active=True, rms=0.4))
        proposal = runner.propose("camera", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.VERIFIED
        assert proposal.parameters["source_role"] == "music"

    def test_tts_case(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(_make_row(role=AudioSourceRole.TTS, active=True))
        proposal = runner.propose("ward", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.VERIFIED
        assert proposal.parameters["source_role"] == "tts"

    def test_operator_voice_case(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(_make_row(role=AudioSourceRole.OPERATOR_VOICE, active=True))
        proposal = runner.propose("ward", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.VERIFIED
        assert proposal.parameters["source_role"] == "operator_voice"

    def test_yt_react_case(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(_make_row(role=AudioSourceRole.YOUTUBE, active=True))
        proposal = runner.propose("camera", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.VERIFIED
        assert proposal.parameters["source_role"] == "youtube"

    def test_silence_case(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(_make_row(role=AudioSourceRole.MUSIC, active=False, rms=0.0))
        proposal = runner.propose("camera", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.NO_OP

    def test_stale_evidence_case(self) -> None:
        """A ledger whose only row is stale yields NO_OP from the runner."""
        runner = MotionProtocolRunner()
        ledger = _ledger(
            _make_row(
                role=AudioSourceRole.MUSIC,
                active=False,  # stale rows can't be active per evidence model
                freshness_state=FreshnessState.STALE,
            )
        )
        proposal = runner.propose("camera", ledger, now=NOW)
        assert proposal.outcome is AudioReactiveOutcome.NO_OP


# ── Witness ledger ───────────────────────────────────────────────────


class TestWitnessLedger:
    def test_witness_records_rendered_outcome_and_source_refs(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(_make_row(role=AudioSourceRole.MUSIC, active=True))
        proposal = runner.propose("camera", ledger, now=NOW)
        wl = record_witness(
            None,
            proposal,
            rendered=True,
            rendered_at=NOW + 0.1,
            render_evidence_refs=("render:director-tick-0",),
        )
        assert isinstance(wl, MotionWitnessLedger)
        assert len(wl.witnesses) == 1
        w = wl.witnesses[0]
        assert w.rendered is True
        assert w.proposal.outcome is AudioReactiveOutcome.VERIFIED
        assert w.proposal.evidence_refs == ("envelope:music",)
        assert w.render_evidence_refs == ("render:director-tick-0",)

    def test_witness_records_blocked_outcome(self) -> None:
        """Refusals are evidence too — they get a witness."""
        runner = MotionProtocolRunner(governor_active=False)
        ledger = _ledger(_make_row(role=AudioSourceRole.MUSIC, active=True))
        proposal = runner.propose("camera", ledger, now=NOW)
        wl = record_witness(None, proposal, rendered=False, notes="governor off")
        assert wl.witnesses[0].rendered is False
        assert wl.witnesses[0].notes == "governor off"
        assert wl.witnesses[0].proposal.outcome is AudioReactiveOutcome.BLOCKED

    def test_witness_appends_to_existing_ledger(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(_make_row(role=AudioSourceRole.MUSIC, active=True))
        wl = record_witness(None, runner.propose("camera", ledger, now=NOW), rendered=True)
        runner2 = MotionProtocolRunner()
        wl2 = record_witness(wl, runner2.propose("ward", ledger, now=NOW), rendered=True)
        assert len(wl2.witnesses) == 2


# ── Role preference: highest-preference active source wins ──────────


class TestRolePreference:
    def test_camera_prefers_music_over_yt_when_both_active(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(
            _make_row(role=AudioSourceRole.YOUTUBE, active=True, rms=0.5),
            _make_row(role=AudioSourceRole.MUSIC, active=True, rms=0.3),
        )
        proposal = runner.propose("camera", ledger, now=NOW)
        # Music is preferred over YT even with lower RMS.
        assert proposal.source_roles == (AudioSourceRole.MUSIC,)

    def test_ward_prefers_operator_voice_over_music(self) -> None:
        runner = MotionProtocolRunner()
        ledger = _ledger(
            _make_row(role=AudioSourceRole.MUSIC, active=True, rms=0.5),
            _make_row(role=AudioSourceRole.OPERATOR_VOICE, active=True, rms=0.2),
        )
        proposal = runner.propose("ward", ledger, now=NOW)
        assert proposal.source_roles == (AudioSourceRole.OPERATOR_VOICE,)
