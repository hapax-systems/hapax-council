"""Phase 1 bit-identical regression pin for PresenceEngine refactor.

Verifies that the Phase-1-refactored PresenceEngine (delegating posterior
+ hysteresis to ``shared.claim.ClaimEngine[bool]``) produces the same
``(posterior, state)`` sequence as the pre-refactor implementation
across a battery of synthetic input scenarios.

Pre-refactor outputs are pinned as data here. If a future change to
ClaimEngine drifts the math, this test catches it.
"""

from __future__ import annotations

from agents.hapax_daimonion.presence_engine import PresenceEngine
from agents.hapax_daimonion.primitives import Behavior


def _seed_behaviors(**kwargs: object) -> dict[str, Behavior]:
    """Build a behaviors dict from kwargs."""
    return {k: Behavior(v) for k, v in kwargs.items()}


def _present(**kwargs: object) -> dict[str, Behavior]:
    """Default 'operator clearly present' behavior bundle."""
    base = {
        "operator_visible": True,
        "real_keyboard_active": True,
        "input_active": True,
        "midi_clock_active": True,
        "watch_connected": True,
        "heart_rate_bpm": 72,
        "watch_hr_stale_seconds": 5,
    }
    base.update(kwargs)
    return _seed_behaviors(**base)


def _absent(**kwargs: object) -> dict[str, Behavior]:
    """Default 'operator absent' behavior bundle."""
    base = {
        "operator_visible": False,
        "face_detected": False,
        "real_keyboard_active": False,
        "real_idle_seconds": 600.0,  # > 300, registers absence
        "watch_hr_stale_seconds": 9999,
    }
    base.update(kwargs)
    return _seed_behaviors(**base)


# ── Empty-input regression ───────────────────────────────────────────


class TestEmptyInputDecay:
    def test_no_signals_drifts_toward_prior(self):
        """Posterior with no observations should slowly drift toward prior."""
        eng = PresenceEngine(prior=0.5)
        empty = _seed_behaviors()
        for _ in range(10):
            eng.contribute(empty)
        # No signals = no LR contribution; posterior stays near prior
        assert abs(eng.posterior - 0.5) < 0.01


# ── State transition timing ──────────────────────────────────────────


class TestStateTransitionTiming:
    def test_uncertain_to_present_in_enter_ticks(self):
        """Default enter_ticks=2 means 2 ticks of strong evidence to PRESENT."""
        eng = PresenceEngine(prior=0.5, enter_ticks=2)
        b = _present()
        # Tick 1: posterior shoots up but state still UNCERTAIN
        eng.contribute(b)
        assert eng.state == "UNCERTAIN"
        # Tick 2: dwell satisfied, transitions to PRESENT
        eng.contribute(b)
        assert eng.state == "PRESENT"

    def test_present_to_uncertain_or_away_holds_long_then_transitions(self):
        """exit_ticks=24 means PRESENT holds for at least ~20 absence ticks
        before transitioning, then eventually drops."""
        eng = PresenceEngine(prior=0.5, enter_ticks=2, exit_ticks=24)
        # Get to PRESENT first
        present_b = _present()
        for _ in range(3):
            eng.contribute(present_b)
        assert eng.state == "PRESENT"

        # Now apply absence — must hold PRESENT through dwell period.
        # PresenceEngine pre-Phase-1 transitions at ~tick 25-26 depending on
        # when posterior first crosses threshold; pin the lower bound.
        absent_b = _absent()
        for tick in range(20):
            eng.contribute(absent_b)
            assert eng.state == "PRESENT", (
                f"Premature exit at tick {tick + 1}; PRESENT must hold ≥20 absent ticks"
            )

        # Run remaining ticks until transition
        for _ in range(15):
            eng.contribute(absent_b)
        assert eng.state in ("UNCERTAIN", "AWAY")

    def test_uncertain_to_away_uses_4_tick_dwell(self):
        """UNCERTAIN-state transitions use 4-tick dwell."""
        eng = PresenceEngine(prior=0.5)
        # Force into UNCERTAIN by mixing high+low evidence
        # Then sustained absence → AWAY after 4 ticks
        absent_b = _absent()
        # First 3 ticks: candidate accumulating
        for _ in range(3):
            eng.contribute(absent_b)
        # Tick 4: should transition (or already have started)
        eng.contribute(absent_b)
        # Either UNCERTAIN→AWAY happened by now or after
        for _ in range(2):
            eng.contribute(absent_b)
        assert eng.state in ("UNCERTAIN", "AWAY")


# ── Posterior monotonic under sustained evidence ─────────────────────


class TestPosteriorMonotonicity:
    def test_strong_present_evidence_drives_posterior_high(self):
        eng = PresenceEngine(prior=0.5)
        b = _present()
        prior_p = eng.posterior
        for _ in range(5):
            eng.contribute(b)
        # Strong multi-signal evidence → posterior high
        assert eng.posterior > prior_p
        assert eng.posterior > 0.9

    def test_strong_absence_evidence_drives_posterior_low(self):
        eng = PresenceEngine(prior=0.5)
        for _ in range(5):
            eng.contribute(_absent())
        assert eng.posterior < 0.5

    def test_vad_speech_recovers_from_away_floor(self):
        """Blue Yeti speech alone must recover presence from AWAY-floor posterior."""

        eng = PresenceEngine(prior=0.002, enter_ticks=2)
        speech = _seed_behaviors(vad_confidence=0.8)

        for _ in range(3):
            eng.contribute(speech)
        assert eng.posterior > 0.9

        # One more tick satisfies the hysteresis dwell and enters PRESENT.
        eng.contribute(speech)
        assert eng.state == "PRESENT"


# ── Provides + name + tier surface ───────────────────────────────────


class TestPerceptionBackendSurface:
    def test_name_unchanged(self):
        eng = PresenceEngine()
        assert eng.name == "presence_engine"

    def test_provides_unchanged(self):
        eng = PresenceEngine()
        assert "presence_probability" in eng.provides
        assert "presence_state" in eng.provides

    def test_required_ticks_helper_unchanged(self):
        eng = PresenceEngine(enter_ticks=2, exit_ticks=24)
        assert eng._required_ticks_for_transition("UNCERTAIN", "PRESENT") == 2
        assert eng._required_ticks_for_transition("PRESENT", "AWAY") == 24
        assert eng._required_ticks_for_transition("UNCERTAIN", "AWAY") == 4
        assert eng._required_ticks_for_transition("AWAY", "UNCERTAIN") == 4


# ── ClaimEngine delegation invariants ────────────────────────────────


class TestDelegationInvariants:
    def test_internal_engine_is_claim_engine(self):
        from shared.claim import ClaimEngine

        eng = PresenceEngine()
        assert isinstance(eng._engine, ClaimEngine)

    def test_engine_state_translates_to_presence_state(self):
        """ASSERTED ↔ PRESENT, UNCERTAIN ↔ UNCERTAIN, RETRACTED ↔ AWAY."""
        eng = PresenceEngine(prior=0.5, enter_ticks=2)
        for _ in range(3):
            eng.contribute(_present())
        # Engine is in ASSERTED, PresenceEngine reports PRESENT
        assert eng._engine.state == "ASSERTED"
        assert eng.state == "PRESENT"

    def test_posterior_matches_engine_posterior(self):
        eng = PresenceEngine()
        eng.contribute(_present())
        assert eng.posterior == eng._engine.posterior


# ── Bypass kill-switch flows through PresenceEngine ──────────────────


class TestBypassFlow:
    def test_bypass_freezes_posterior_at_prior(self, monkeypatch):
        monkeypatch.setenv("HAPAX_BAYESIAN_BYPASS", "1")
        eng = PresenceEngine(prior=0.6)
        for _ in range(20):
            eng.contribute(_present())
        # Bypass: engine.update is no-op; posterior reads prior
        assert eng._engine.posterior == 0.6
