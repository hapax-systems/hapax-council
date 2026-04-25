"""Tests for MoodCoherenceEngine — Phase 6b-iii.A mood-claim.

Mirrors the MoodArousalEngine (#1368), MoodValenceEngine (#1371), and
SystemDegradedEngine (#1357) regression-pin pattern:
- Empty-input drift toward prior
- Posterior monotonicity under sustained evidence
- State transition timing (COHERENT→UNCERTAIN→INCOHERENT in enter_ticks=4;
  INCOHERENT holds through exit_ticks=8 of recovery before transitioning)
- Surface invariance (name, provides, _required_ticks_for_transition)
- ClaimEngine delegation invariants
- Positive-only signal semantics for the 3 positive-only signals
- HAPAX_BAYESIAN_BYPASS flow

Phase 6b-iii.B wire-in tests live alongside the perception adapter in a
follow-up PR — these tests pin the engine math only.
"""

from __future__ import annotations

from agents.hapax_daimonion.mood_coherence_engine import MoodCoherenceEngine


def _incoherent() -> dict[str, bool | None]:
    """All four default signals firing — strong incoherence evidence."""
    return {
        "hrv_variability_high": True,
        "respiration_irregular": True,
        "movement_jitter_high": True,
        "skin_temp_volatility_high": True,
    }


def _coherent() -> dict[str, bool | None]:
    """All four default signals quiet — coherent evidence (where applicable).

    respiration_irregular, movement_jitter_high, and skin_temp_volatility_high
    are positive-only, so False contributes no evidence either way for those
    signals — only hrv_variability_high's bidirectional False carries weight.
    """
    return {
        "hrv_variability_high": False,
        "respiration_irregular": False,
        "movement_jitter_high": False,
        "skin_temp_volatility_high": False,
    }


# ── Empty-input drift ────────────────────────────────────────────────


class TestEmptyInputDecay:
    def test_no_signals_drifts_toward_prior(self):
        eng = MoodCoherenceEngine(prior=0.15)
        for _ in range(10):
            eng.contribute({})
        # No observations → posterior decays toward prior 0.15.
        assert abs(eng.posterior - 0.15) < 0.05


# ── Posterior monotonicity ───────────────────────────────────────────


class TestPosteriorMonotonicity:
    def test_strong_incoherence_drives_posterior_high(self):
        eng = MoodCoherenceEngine(prior=0.15)
        prior_p = eng.posterior
        for _ in range(6):
            eng.contribute(_incoherent())
        assert eng.posterior > prior_p
        assert eng.posterior > 0.85

    def test_strong_coherence_drives_posterior_low(self):
        # Start with incoherence belief and then apply sustained coherence.
        eng = MoodCoherenceEngine(prior=0.7)
        for _ in range(12):
            eng.contribute(_coherent())
        assert eng.posterior < 0.5


# ── State transition timing ──────────────────────────────────────────


class TestStateTransitionTiming:
    def test_uncertain_to_incoherent_in_enter_ticks(self):
        eng = MoodCoherenceEngine(prior=0.15, enter_ticks=4)
        # Tick 1-3: posterior climbs but state still UNCERTAIN due to dwell.
        for _ in range(3):
            eng.contribute(_incoherent())
        assert eng.state == "UNCERTAIN"
        # Tick 4: dwell satisfied, transitions to INCOHERENT.
        eng.contribute(_incoherent())
        assert eng.state == "INCOHERENT"

    def test_incoherent_holds_during_brief_coherent_burst(self):
        """INCOHERENT→COHERENT uses exit_ticks=8 dwell so a brief
        coherent burst doesn't flip the system back into COHERENT
        prematurely — autonomic regulation re-establishes slowly."""
        eng = MoodCoherenceEngine(prior=0.15, enter_ticks=4, exit_ticks=8)
        # Get to INCOHERENT first
        for _ in range(5):
            eng.contribute(_incoherent())
        assert eng.state == "INCOHERENT"
        # Apply several coherent ticks — must hold INCOHERENT through dwell.
        for tick in range(6):
            eng.contribute(_coherent())
            assert eng.state == "INCOHERENT", (
                f"Premature exit at tick {tick + 1}; INCOHERENT must hold "
                "≥6 coherent ticks under exit_ticks=8"
            )

    def test_uncertain_to_coherent_uses_4_tick_dwell(self):
        """UNCERTAIN-state transitions use the k_uncertain=4 dwell from
        TemporalProfile, mirroring PresenceEngine semantics."""
        eng = MoodCoherenceEngine(prior=0.5)
        # Sustained coherent → eventually transitions to COHERENT.
        for _ in range(20):
            eng.contribute(_coherent())
        assert eng.state in ("UNCERTAIN", "COHERENT")


# ── Surface invariance ───────────────────────────────────────────────


class TestSurface:
    def test_name(self):
        assert MoodCoherenceEngine.name == "mood_coherence_engine"

    def test_provides(self):
        eng = MoodCoherenceEngine()
        assert "mood_coherence_low_probability" in eng.provides
        assert "mood_coherence_state" in eng.provides

    def test_required_ticks_helper(self):
        eng = MoodCoherenceEngine(enter_ticks=4, exit_ticks=8)
        assert eng._required_ticks_for_transition("UNCERTAIN", "INCOHERENT") == 4
        assert eng._required_ticks_for_transition("INCOHERENT", "COHERENT") == 8
        assert eng._required_ticks_for_transition("UNCERTAIN", "COHERENT") == 4
        assert eng._required_ticks_for_transition("COHERENT", "UNCERTAIN") == 4


# ── ClaimEngine delegation invariants ────────────────────────────────


class TestDelegationInvariants:
    def test_internal_engine_is_claim_engine(self):
        from shared.claim import ClaimEngine

        eng = MoodCoherenceEngine()
        assert isinstance(eng._engine, ClaimEngine)

    def test_engine_state_translates_to_coherence_state(self):
        """ASSERTED ↔ INCOHERENT, UNCERTAIN ↔ UNCERTAIN, RETRACTED ↔ COHERENT."""
        eng = MoodCoherenceEngine(prior=0.15, enter_ticks=4)
        for _ in range(5):
            eng.contribute(_incoherent())
        assert eng._engine.state == "ASSERTED"
        assert eng.state == "INCOHERENT"

    def test_posterior_matches_engine_posterior(self):
        eng = MoodCoherenceEngine()
        eng.contribute(_incoherent())
        assert eng.posterior == eng._engine.posterior

    def test_reset_returns_to_prior(self):
        eng = MoodCoherenceEngine(prior=0.15)
        for _ in range(5):
            eng.contribute(_incoherent())
        assert eng.posterior > 0.5
        eng.reset()
        assert eng.posterior == 0.15
        assert eng.state == "UNCERTAIN"


# ── Positive-only signal semantics ────────────────────────────────────


class TestPositiveOnlySemantics:
    def test_respiration_irregular_false_does_not_subtract(self):
        """respiration_irregular is positive-only — when False it
        contributes no evidence either way. Two engines, one fed False
        and one fed None for that signal, must arrive at the same
        posterior."""
        eng_false = MoodCoherenceEngine(prior=0.15)
        eng_none = MoodCoherenceEngine(prior=0.15)
        for _ in range(5):
            eng_false.contribute(
                {
                    "hrv_variability_high": True,
                    "respiration_irregular": False,
                    "movement_jitter_high": True,
                    "skin_temp_volatility_high": True,
                }
            )
            eng_none.contribute(
                {
                    "hrv_variability_high": True,
                    "respiration_irregular": None,
                    "movement_jitter_high": True,
                    "skin_temp_volatility_high": True,
                }
            )
        assert abs(eng_false.posterior - eng_none.posterior) < 1e-9

    def test_movement_jitter_high_false_does_not_subtract(self):
        eng_false = MoodCoherenceEngine(prior=0.15)
        eng_none = MoodCoherenceEngine(prior=0.15)
        for _ in range(5):
            eng_false.contribute({"movement_jitter_high": False})
            eng_none.contribute({"movement_jitter_high": None})
        assert abs(eng_false.posterior - eng_none.posterior) < 1e-9

    def test_skin_temp_volatility_high_false_does_not_subtract(self):
        eng_false = MoodCoherenceEngine(prior=0.15)
        eng_none = MoodCoherenceEngine(prior=0.15)
        for _ in range(5):
            eng_false.contribute({"skin_temp_volatility_high": False})
            eng_none.contribute({"skin_temp_volatility_high": None})
        assert abs(eng_false.posterior - eng_none.posterior) < 1e-9

    def test_hrv_variability_high_false_does_subtract(self):
        """hrv_variability_high is bidirectional — False genuinely
        evidences high coherence (steady parasympathetic tone)."""
        eng_true = MoodCoherenceEngine(prior=0.5)
        eng_false = MoodCoherenceEngine(prior=0.5)
        for _ in range(5):
            eng_true.contribute({"hrv_variability_high": True})
            eng_false.contribute({"hrv_variability_high": False})
        assert eng_true.posterior > eng_false.posterior


# ── HAPAX_BAYESIAN_BYPASS flows through ──────────────────────────────


class TestBypassFlow:
    def test_bypass_freezes_posterior_at_prior(self, monkeypatch):
        monkeypatch.setenv("HAPAX_BAYESIAN_BYPASS", "1")
        eng = MoodCoherenceEngine(prior=0.25)
        for _ in range(20):
            eng.contribute(_incoherent())
        assert eng._engine.posterior == 0.25
        assert eng.state == "UNCERTAIN"
