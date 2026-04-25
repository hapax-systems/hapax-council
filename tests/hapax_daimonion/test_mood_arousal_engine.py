"""Tests for MoodArousalEngine — Phase 6b-i.A mood-claim.

Mirrors the SystemDegradedEngine (#1357) regression-pin pattern:
- Empty-input drift toward prior
- Posterior monotonicity under sustained evidence
- State transition timing (CALM→UNCERTAIN→AROUSED in enter_ticks;
  AROUSED holds through exit_ticks of recovery before transitioning)
- Surface invariance (name, provides, _required_ticks_for_transition)
- ClaimEngine delegation invariants
- HAPAX_BAYESIAN_BYPASS flow
- Positive-only signal semantics for contact_mic_onset_rate_high

Phase 6b-i.B wire-in tests live alongside the perception adapter in a
follow-up PR — these tests pin the engine math only.
"""

from __future__ import annotations

from agents.hapax_daimonion.mood_arousal_engine import MoodArousalEngine


def _aroused() -> dict[str, bool | None]:
    """All four default signals firing — strong arousal evidence."""
    return {
        "ambient_audio_rms_high": True,
        "contact_mic_onset_rate_high": True,
        "midi_clock_bpm_high": True,
        "hr_bpm_above_baseline": True,
    }


def _calm() -> dict[str, bool | None]:
    """All four default signals quiet — strong calm evidence (where applicable).

    contact_mic_onset_rate_high is positive-only, so False contributes no
    evidence either way for that signal — the other three carry the
    bidirectional weight.
    """
    return {
        "ambient_audio_rms_high": False,
        "contact_mic_onset_rate_high": False,
        "midi_clock_bpm_high": False,
        "hr_bpm_above_baseline": False,
    }


# ── Empty-input drift ────────────────────────────────────────────────


class TestEmptyInputDecay:
    def test_no_signals_drifts_toward_prior(self):
        eng = MoodArousalEngine(prior=0.3)
        for _ in range(10):
            eng.contribute({})
        # No observations → posterior decays toward prior 0.3.
        assert abs(eng.posterior - 0.3) < 0.05


# ── Posterior monotonicity ───────────────────────────────────────────


class TestPosteriorMonotonicity:
    def test_strong_arousal_drives_posterior_high(self):
        eng = MoodArousalEngine(prior=0.3)
        prior_p = eng.posterior
        for _ in range(5):
            eng.contribute(_aroused())
        assert eng.posterior > prior_p
        assert eng.posterior > 0.9

    def test_strong_calm_drives_posterior_low(self):
        # Start with arousal belief and then apply sustained calm.
        eng = MoodArousalEngine(prior=0.7)
        for _ in range(8):
            eng.contribute(_calm())
        assert eng.posterior < 0.5


# ── State transition timing ──────────────────────────────────────────


class TestStateTransitionTiming:
    def test_uncertain_to_aroused_in_enter_ticks(self):
        eng = MoodArousalEngine(prior=0.3, enter_ticks=3)
        # Tick 1: posterior shoots up but state still UNCERTAIN due to dwell.
        eng.contribute(_aroused())
        assert eng.state == "UNCERTAIN"
        # Tick 2: dwell partial.
        eng.contribute(_aroused())
        assert eng.state == "UNCERTAIN"
        # Tick 3: dwell satisfied, transitions to AROUSED.
        eng.contribute(_aroused())
        assert eng.state == "AROUSED"

    def test_aroused_holds_during_brief_calm_burst(self):
        """AROUSED→CALM uses exit_ticks=4 dwell so a single calm burst
        doesn't flip the system back into CALM prematurely."""
        eng = MoodArousalEngine(prior=0.3, enter_ticks=3, exit_ticks=4)
        # Get to AROUSED first
        for _ in range(4):
            eng.contribute(_aroused())
        assert eng.state == "AROUSED"
        # Apply a single calm tick — must hold AROUSED through dwell.
        eng.contribute(_calm())
        assert eng.state == "AROUSED"

    def test_uncertain_to_calm_uses_4_tick_dwell(self):
        """UNCERTAIN-state transitions use the k_uncertain=4 dwell from
        TemporalProfile, mirroring PresenceEngine semantics."""
        eng = MoodArousalEngine(prior=0.5)
        # Sustained calm → eventually transitions to CALM.
        for _ in range(15):
            eng.contribute(_calm())
        assert eng.state in ("UNCERTAIN", "CALM")


# ── Surface invariance ───────────────────────────────────────────────


class TestSurface:
    def test_name(self):
        assert MoodArousalEngine.name == "mood_arousal_engine"

    def test_provides(self):
        eng = MoodArousalEngine()
        assert "mood_arousal_high_probability" in eng.provides
        assert "mood_arousal_state" in eng.provides

    def test_required_ticks_helper(self):
        eng = MoodArousalEngine(enter_ticks=3, exit_ticks=4)
        assert eng._required_ticks_for_transition("UNCERTAIN", "AROUSED") == 3
        assert eng._required_ticks_for_transition("AROUSED", "CALM") == 4
        assert eng._required_ticks_for_transition("UNCERTAIN", "CALM") == 4
        assert eng._required_ticks_for_transition("CALM", "UNCERTAIN") == 4


# ── ClaimEngine delegation invariants ────────────────────────────────


class TestDelegationInvariants:
    def test_internal_engine_is_claim_engine(self):
        from shared.claim import ClaimEngine

        eng = MoodArousalEngine()
        assert isinstance(eng._engine, ClaimEngine)

    def test_engine_state_translates_to_arousal_state(self):
        """ASSERTED ↔ AROUSED, UNCERTAIN ↔ UNCERTAIN, RETRACTED ↔ CALM."""
        eng = MoodArousalEngine(prior=0.3, enter_ticks=3)
        for _ in range(4):
            eng.contribute(_aroused())
        assert eng._engine.state == "ASSERTED"
        assert eng.state == "AROUSED"

    def test_posterior_matches_engine_posterior(self):
        eng = MoodArousalEngine()
        eng.contribute(_aroused())
        assert eng.posterior == eng._engine.posterior

    def test_reset_returns_to_prior(self):
        eng = MoodArousalEngine(prior=0.3)
        for _ in range(5):
            eng.contribute(_aroused())
        assert eng.posterior > 0.5
        eng.reset()
        assert eng.posterior == 0.3
        assert eng.state == "UNCERTAIN"


# ── Positive-only signal semantics ────────────────────────────────────


class TestPositiveOnlySemantics:
    def test_contact_mic_onset_rate_high_false_does_not_subtract(self):
        """contact_mic_onset_rate_high is positive-only — when False it
        contributes no evidence either way (the engine skips the LR
        update for that signal). Two engines, one fed False and one fed
        None for that signal, must arrive at the same posterior."""
        eng_false = MoodArousalEngine(prior=0.3)
        eng_none = MoodArousalEngine(prior=0.3)
        for _ in range(5):
            eng_false.contribute(
                {
                    "ambient_audio_rms_high": True,
                    "contact_mic_onset_rate_high": False,
                    "midi_clock_bpm_high": True,
                    "hr_bpm_above_baseline": True,
                }
            )
            eng_none.contribute(
                {
                    "ambient_audio_rms_high": True,
                    "contact_mic_onset_rate_high": None,
                    "midi_clock_bpm_high": True,
                    "hr_bpm_above_baseline": True,
                }
            )
        assert abs(eng_false.posterior - eng_none.posterior) < 1e-9

    def test_bidirectional_signal_false_does_subtract(self):
        """ambient_audio_rms_high is bidirectional — False genuinely
        evidences low arousal. Two engines, one fed True and one fed
        False for that signal, must diverge."""
        eng_true = MoodArousalEngine(prior=0.5)
        eng_false = MoodArousalEngine(prior=0.5)
        for _ in range(5):
            eng_true.contribute({"ambient_audio_rms_high": True})
            eng_false.contribute({"ambient_audio_rms_high": False})
        assert eng_true.posterior > eng_false.posterior


# ── HAPAX_BAYESIAN_BYPASS flows through ──────────────────────────────


class TestBypassFlow:
    def test_bypass_freezes_posterior_at_prior(self, monkeypatch):
        monkeypatch.setenv("HAPAX_BAYESIAN_BYPASS", "1")
        eng = MoodArousalEngine(prior=0.4)
        for _ in range(20):
            eng.contribute(_aroused())
        assert eng._engine.posterior == 0.4
        assert eng.state == "UNCERTAIN"
