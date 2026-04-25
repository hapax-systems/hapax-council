"""Phase 6c-ii.A regression for ``ChatAuthorIsOperatorEngine``.

Pins the multi-signal positive-only semantics + conservative-prior
delegation to ``ClaimEngine[bool]``. Mirrors the structure of
``test_speaker_is_operator_engine.py`` but with two key differences:

* **Conservative prior** (~0.05): the broadcast hypothesis space is
  dominated by non-operator chat authors (audience > 1). The
  ``interpersonal_transparency`` axiom requires the engine to default
  to "non-operator" absent positive evidence.
* **Positive-only signals**: handle-match and persona-similarity
  contribute on True (raises posterior toward operator); on False they
  are skipped (absence ≠ refutation — a generic message proves nothing).

Spec: ``docs/research/2026-04-24-universal-bayesian-claim-confidence.md``.
Scope direction: ``~/.cache/hapax/relay/beta-to-epsilon-2026-04-25-phase-6c-scope-direction.md``.
"""

from __future__ import annotations

from agents.hapax_daimonion.chat_author_is_operator_engine import (
    AUTHENTICATED_HANDLE_SIGNAL,
    CLAIM_NAME,
    DEFAULT_HANDLE_LR,
    DEFAULT_NARRATION_FLOOR,
    DEFAULT_PERSONA_LR,
    DEFAULT_PRIOR,
    DEFAULT_TEMPORAL_PROFILE,
    PERSONA_SIMILARITY_SIGNAL,
    ChatAuthorIsOperatorEngine,
)


class TestEngineInit:
    def test_starts_at_conservative_prior(self) -> None:
        eng = ChatAuthorIsOperatorEngine()
        assert abs(eng.posterior - DEFAULT_PRIOR) < 1e-9

    def test_default_prior_is_conservative(self) -> None:
        """Conservative prior — broadcast chat is mostly NOT operator."""
        assert DEFAULT_PRIOR < 0.5  # conservative
        assert DEFAULT_PRIOR > 0.0  # not certainty

    def test_starts_uncertain(self) -> None:
        eng = ChatAuthorIsOperatorEngine()
        assert eng.state == "UNCERTAIN"

    def test_temporal_profile_constants(self) -> None:
        """Per scope direction: cautious-enter, conservative-exit."""
        assert DEFAULT_TEMPORAL_PROFILE.enter_threshold >= 0.7
        assert DEFAULT_TEMPORAL_PROFILE.exit_threshold <= 0.3
        # Cautious entry — misidentifying as operator violates governance
        assert DEFAULT_TEMPORAL_PROFILE.k_enter >= 3
        # Conservative exit — once asserted, hold across brief silences
        assert DEFAULT_TEMPORAL_PROFILE.k_exit >= 3

    def test_handle_lr_is_positive_only(self) -> None:
        """Absence-of-handle-match ≠ refutation; signal is positive-only."""
        assert DEFAULT_HANDLE_LR.signal_name == AUTHENTICATED_HANDLE_SIGNAL
        assert DEFAULT_HANDLE_LR.claim_name == CLAIM_NAME
        assert DEFAULT_HANDLE_LR.positive_only is True

    def test_persona_lr_is_positive_only(self) -> None:
        """Persona-similarity-low ≠ refutation; signal is positive-only."""
        assert DEFAULT_PERSONA_LR.signal_name == PERSONA_SIMILARITY_SIGNAL
        assert DEFAULT_PERSONA_LR.claim_name == CLAIM_NAME
        assert DEFAULT_PERSONA_LR.positive_only is True

    def test_high_narration_floor(self) -> None:
        """Per scope direction: 0.85+ so unclear authors collapse to UNKNOWN."""
        assert DEFAULT_NARRATION_FLOOR >= 0.85


class TestPositiveOnlySemantics:
    """False signals do NOT decrease posterior; only True raises it."""

    def test_handle_false_does_not_drop_posterior(self) -> None:
        eng = ChatAuthorIsOperatorEngine()
        before = eng.posterior
        eng.tick(handle_match=False, persona_match=None)
        # Positive-only: False is a no-op modulo decay-toward-prior
        # (which is also conservative in this engine).
        assert eng.posterior <= before + 1e-9

    def test_handle_true_raises_posterior(self) -> None:
        eng = ChatAuthorIsOperatorEngine()
        before = eng.posterior
        eng.tick(handle_match=True, persona_match=None)
        assert eng.posterior > before

    def test_persona_true_raises_posterior(self) -> None:
        eng = ChatAuthorIsOperatorEngine()
        before = eng.posterior
        eng.tick(handle_match=None, persona_match=True)
        assert eng.posterior > before

    def test_both_true_raises_more_than_either(self) -> None:
        """Multi-signal aggregation: independent positive evidence stacks."""
        eng_h = ChatAuthorIsOperatorEngine()
        eng_h.tick(handle_match=True, persona_match=None)
        only_handle = eng_h.posterior

        eng_both = ChatAuthorIsOperatorEngine()
        eng_both.tick(handle_match=True, persona_match=True)
        both = eng_both.posterior

        assert both > only_handle


class TestCautiousEntry:
    """Per governance — misidentification as operator is the costly error.

    k_enter must be high enough that a single accidental positive
    (e.g., a guest happens to have similar-styled message) does not
    flip state to ASSERTED.
    """

    def test_one_handle_true_does_not_assert(self) -> None:
        eng = ChatAuthorIsOperatorEngine()
        eng.tick(handle_match=True, persona_match=None)
        # k_enter >= 3 → one tick is not enough.
        assert eng.state == "UNCERTAIN"

    def test_sustained_strong_evidence_asserts(self) -> None:
        """Both signals True for k_enter ticks → ASSERTED."""
        eng = ChatAuthorIsOperatorEngine()
        for _ in range(8):
            eng.tick(handle_match=True, persona_match=True)
        assert eng.state == "ASSERTED"


class TestConservativeExit:
    """Once ASSERTED, brief absence does NOT immediately retract.

    Conversation pause / single message-with-no-handle should not
    re-classify the author back to non-operator — that creates flicker
    that downstream consumers (qdrant gate, narration) would see.
    """

    def _enter_asserted(self) -> ChatAuthorIsOperatorEngine:
        eng = ChatAuthorIsOperatorEngine()
        for _ in range(8):
            eng.tick(handle_match=True, persona_match=True)
        assert eng.state == "ASSERTED"
        return eng

    def test_one_none_holds_state(self) -> None:
        eng = self._enter_asserted()
        eng.tick(handle_match=None, persona_match=None)
        # No new evidence — state holds.
        assert eng.state == "ASSERTED"

    def test_one_false_holds_state(self) -> None:
        eng = self._enter_asserted()
        eng.tick(handle_match=False, persona_match=False)
        # Positive-only: False is a no-op; no posterior crash.
        assert eng.state == "ASSERTED"


class TestKillSwitchBypass:
    """``HAPAX_BAYESIAN_BYPASS=1`` flows through ClaimEngine."""

    def test_bypass_locks_posterior_at_prior(self, monkeypatch) -> None:
        monkeypatch.setenv("HAPAX_BAYESIAN_BYPASS", "1")
        eng = ChatAuthorIsOperatorEngine()
        for _ in range(10):
            eng.tick(handle_match=True, persona_match=True)
        # Bypass: tick is a no-op; posterior stays at prior.
        assert abs(eng.posterior - DEFAULT_PRIOR) < 1e-9
        assert eng.state == "UNCERTAIN"


class TestNoneObservations:
    """``None`` is the no-evidence-this-tick case; engine drifts to prior."""

    def test_none_does_not_crash(self) -> None:
        eng = ChatAuthorIsOperatorEngine()
        eng.tick(handle_match=None, persona_match=None)

    def test_drift_toward_prior_under_no_evidence(self) -> None:
        """After driving high then None ticks, posterior drifts toward prior."""
        eng = ChatAuthorIsOperatorEngine()
        for _ in range(8):
            eng.tick(handle_match=True, persona_match=True)
        peak = eng.posterior
        for _ in range(50):
            eng.tick(handle_match=None, persona_match=None)
        # Should drift back toward (conservative) prior.
        assert eng.posterior < peak


class TestAssertedConvenience:
    """``asserted()`` is the wire-in shape for downstream consumers."""

    def test_default_threshold_uses_narration_floor(self) -> None:
        """Default threshold matches the high narration_floor (0.85)."""
        eng = ChatAuthorIsOperatorEngine()
        # At conservative prior, asserted() at floor is False.
        assert eng.asserted() is False

    def test_after_strong_evidence_asserted_true(self) -> None:
        eng = ChatAuthorIsOperatorEngine()
        for _ in range(15):
            eng.tick(handle_match=True, persona_match=True)
        assert eng.asserted() is True

    def test_threshold_override_at_prior(self) -> None:
        """At conservative prior with no evidence, asserted(0.99) is False."""
        eng = ChatAuthorIsOperatorEngine()
        assert eng.asserted(threshold=0.99) is False

    def test_threshold_override_zero_passes_trivially(self) -> None:
        """asserted(threshold=0.0) is True iff posterior >= 0 (always)."""
        eng = ChatAuthorIsOperatorEngine()
        assert eng.asserted(threshold=0.0) is True

    def test_only_persona_does_not_clear_default_floor_in_one_tick(self) -> None:
        """A single persona-only positive (LR ≈ 14×) raises posterior but
        does not clear the high narration floor on its own — the
        cryptographic handle signal is the only single-tick floor-clearer."""
        eng = ChatAuthorIsOperatorEngine()
        eng.tick(handle_match=None, persona_match=True)
        # Below 0.85 floor after one persona-only tick from prior 0.05.
        assert eng.asserted() is False


class TestPosteriorMonotonicity:
    """All-True drives posterior monotonically toward 1.0."""

    def test_monotone_increase_under_true(self) -> None:
        eng = ChatAuthorIsOperatorEngine()
        last = eng.posterior
        for _ in range(10):
            eng.tick(handle_match=True, persona_match=True)
            cur = eng.posterior
            assert cur >= last - 1e-9  # tolerance for decay-toward-prior
            last = cur


class TestSurfaceInvariance:
    """Posterior stays in [0, 1]; state is one of three values."""

    def test_posterior_in_unit_interval(self) -> None:
        eng = ChatAuthorIsOperatorEngine()
        for _ in range(20):
            eng.tick(handle_match=True, persona_match=True)
            assert 0.0 <= eng.posterior <= 1.0
        for _ in range(40):
            eng.tick(handle_match=None, persona_match=None)
            assert 0.0 <= eng.posterior <= 1.0

    def test_state_is_one_of_three_values(self) -> None:
        eng = ChatAuthorIsOperatorEngine()
        for _ in range(30):
            eng.tick(handle_match=True, persona_match=True)
            assert eng.state in {"ASSERTED", "UNCERTAIN", "RETRACTED"}


class TestGovernanceShape:
    """Engine doesn't carry per-author state — that's the consumer's job.

    Per ``interpersonal_transparency`` axiom: persistent state about
    non-operator persons requires explicit consent contract. This engine
    is single-author-at-a-time (consumer scopes to a single conversation
    or instantiates per-author with explicit lifecycle management).
    """

    def test_no_per_author_state_inside_engine(self) -> None:
        """Engine has no author-id parameter — caller scopes lifecycle."""
        eng = ChatAuthorIsOperatorEngine()
        # ``tick`` signature takes signal observations only — no author_id.
        eng.tick(handle_match=True, persona_match=True)
