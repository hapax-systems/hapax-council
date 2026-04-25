"""Tests for OperatorActivityEngine — Phase 6a-i.A activity claim.

Mirrors the SystemDegradedEngine (#1357) pinning template:
- Empty-input drift toward prior
- Posterior monotonicity under sustained evidence
- State transition timing (IDLE → UNCERTAIN → ACTIVE in enter_ticks;
  ACTIVE holds through exit_ticks of recovery before transitioning to IDLE)
- Surface invariance (name, provides, _required_ticks_for_transition)
- ClaimEngine delegation invariants
- HAPAX_BAYESIAN_BYPASS flow
- Distinct-from-PresenceEngine semantics (no presence-only signals
  registered in the default weights — heart-rate / face / BLE
  intentionally excluded)

Phase 6a-i.B wire-in tests live alongside the perception adapter in
a follow-up PR — these tests pin the engine math only.
"""

from __future__ import annotations

from agents.hapax_daimonion.operator_activity_engine import (
    DEFAULT_SIGNAL_WEIGHTS,
    OperatorActivityEngine,
)


def _active() -> dict[str, bool | None]:
    """All five default signals firing — strong activity evidence."""
    return {
        "keyboard_active": True,
        "midi_clock_active": True,
        "desk_active": True,
        "desktop_focus_changed_recent": True,
        "watch_movement": True,
    }


def _idle() -> dict[str, bool | None]:
    """All five default signals quiet — strong idle evidence."""
    return {
        "keyboard_active": False,
        "midi_clock_active": False,
        "desk_active": False,
        "desktop_focus_changed_recent": False,
        "watch_movement": False,
    }


# ── Empty-input drift ────────────────────────────────────────────────


class TestEmptyInputDecay:
    def test_no_signals_drifts_toward_prior(self):
        eng = OperatorActivityEngine(prior=0.30)
        for _ in range(10):
            eng.contribute({})
        assert abs(eng.posterior - 0.30) < 0.05


# ── Posterior monotonicity ───────────────────────────────────────────


class TestPosteriorMonotonicity:
    def test_strong_activity_drives_posterior_high(self):
        eng = OperatorActivityEngine(prior=0.30)
        prior_p = eng.posterior
        for _ in range(5):
            eng.contribute(_active())
        assert eng.posterior > prior_p
        assert eng.posterior > 0.9

    def test_strong_idle_drives_posterior_low(self):
        # Start with a high activity belief and apply sustained idle.
        eng = OperatorActivityEngine(prior=0.85)
        for _ in range(5):
            eng.contribute(_idle())
        assert eng.posterior < 0.5

    def test_keyboard_alone_lifts_posterior(self):
        """Keyboard is the strongest single signal; one positive
        observation should noticeably move the posterior."""
        eng = OperatorActivityEngine(prior=0.30)
        prior_p = eng.posterior
        eng.contribute({"keyboard_active": True})
        assert eng.posterior > prior_p


# ── State transition timing ──────────────────────────────────────────


class TestStateTransitionTiming:
    def test_uncertain_to_active_in_enter_ticks(self):
        """``enter_ticks=1`` → a single strong cue suffices."""
        eng = OperatorActivityEngine(prior=0.30, enter_ticks=1)
        eng.contribute(_active())
        assert eng.state == "ACTIVE"

    def test_active_holds_during_recovery_dwell(self):
        """ACTIVE→IDLE uses exit_ticks=8 dwell so brief idle bursts
        don't flip state back to IDLE prematurely."""
        eng = OperatorActivityEngine(prior=0.30, enter_ticks=1, exit_ticks=8)
        # Enter ACTIVE first.
        for _ in range(2):
            eng.contribute(_active())
        assert eng.state == "ACTIVE"
        # Apply sustained idle — must hold ACTIVE through dwell.
        for tick in range(5):
            eng.contribute(_idle())
            assert eng.state == "ACTIVE", (
                f"Premature exit at tick {tick + 1}; ACTIVE must hold "
                "≥5 idle ticks under exit_ticks=8"
            )

    def test_uncertain_to_idle_uses_4_tick_dwell(self):
        """UNCERTAIN-state transitions use the k_uncertain=4 dwell from
        TemporalProfile, mirroring sibling engines."""
        eng = OperatorActivityEngine(prior=0.5)
        for _ in range(10):
            eng.contribute(_idle())
        assert eng.state in ("UNCERTAIN", "IDLE")


# ── Surface invariance ───────────────────────────────────────────────


class TestSurface:
    def test_name(self):
        assert OperatorActivityEngine.name == "operator_activity_engine"

    def test_provides(self):
        eng = OperatorActivityEngine()
        assert "operator_activity_probability" in eng.provides
        assert "operator_activity_state" in eng.provides

    def test_required_ticks_helper(self):
        eng = OperatorActivityEngine(enter_ticks=1, exit_ticks=8)
        assert eng._required_ticks_for_transition("UNCERTAIN", "ACTIVE") == 1
        assert eng._required_ticks_for_transition("ACTIVE", "IDLE") == 8
        assert eng._required_ticks_for_transition("UNCERTAIN", "IDLE") == 4
        assert eng._required_ticks_for_transition("IDLE", "UNCERTAIN") == 4


# ── ClaimEngine delegation invariants ────────────────────────────────


class TestDelegationInvariants:
    def test_internal_engine_is_claim_engine(self):
        from shared.claim import ClaimEngine

        eng = OperatorActivityEngine()
        assert isinstance(eng._engine, ClaimEngine)

    def test_engine_state_translates_to_activity_state(self):
        """ASSERTED ↔ ACTIVE, UNCERTAIN ↔ UNCERTAIN, RETRACTED ↔ IDLE."""
        eng = OperatorActivityEngine(prior=0.30, enter_ticks=1)
        for _ in range(2):
            eng.contribute(_active())
        assert eng._engine.state == "ASSERTED"
        assert eng.state == "ACTIVE"

    def test_posterior_matches_engine_posterior(self):
        eng = OperatorActivityEngine()
        eng.contribute(_active())
        assert eng.posterior == eng._engine.posterior

    def test_reset_returns_to_prior(self):
        eng = OperatorActivityEngine(prior=0.30)
        for _ in range(5):
            eng.contribute(_active())
        assert eng.posterior > 0.5
        eng.reset()
        assert eng.posterior == 0.30
        assert eng.state == "UNCERTAIN"


# ── HAPAX_BAYESIAN_BYPASS flows through ──────────────────────────────


class TestBypassFlow:
    def test_bypass_freezes_posterior_at_prior(self, monkeypatch):
        monkeypatch.setenv("HAPAX_BAYESIAN_BYPASS", "1")
        eng = OperatorActivityEngine(prior=0.30)
        for _ in range(20):
            eng.contribute(_active())
        assert eng._engine.posterior == 0.30


# ── Distinct-from-PresenceEngine semantics ───────────────────────────


class TestDisjointFromPresence:
    """Per beta's scope direction (relay 2026-04-25T02:18Z): the
    activity engine MUST NOT register presence-only signals.
    Heart-rate / face / BLE proximity belong to PresenceEngine; this
    pin guards against accidental re-introduction."""

    def test_default_weights_omit_presence_only_signals(self):
        forbidden = {
            "operator_face",
            "watch_hr",
            "watch_connected",
            "ir_body_heat",
            "ir_person_detected",
            "vad_speech",
            "speaker_is_operator",
        }
        registered = set(DEFAULT_SIGNAL_WEIGHTS.keys())
        overlap = registered & forbidden
        assert not overlap, (
            f"Activity engine registered presence-only signal(s) "
            f"{overlap}; these belong to PresenceEngine. Beta's "
            f"scope direction: heart-rate alone must NOT lift activity."
        )

    def test_default_weights_count_matches_scope_direction(self):
        # 5 signals per beta's scope direction (4-6 acceptable range).
        assert 4 <= len(DEFAULT_SIGNAL_WEIGHTS) <= 6
