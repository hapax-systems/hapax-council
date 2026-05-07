"""MoodValenceEngine — Phase 6b-ii.A mood-claim Bayesian wrapper.

Per Universal Bayesian Claim-Confidence research §Phase 6b ("Mood
claims — stimmung dimensions, each becomes a `ClaimEngine[float]` with
continuous posterior"): mood-valence benefits from posterior framing
— `P(operator's mood is currently negative-valence | observed_signals)`
— over ad-hoc threshold gates on HRV / skin-temp / sleep readings.
This module ships the second of the Phase 6b cluster (alpha-canonical)
following MoodArousalEngine (#1368) using the quantize-into-tiers
approach (option 1 from beta dispatch 02:18Z): `ClaimEngine[bool]`
over a quantized negative-valence tier. Continuous-posterior
`ClaimEngine[float]` lands later if option 1 proves insufficient.

Mirrors MoodArousalEngine (#1368), SystemDegradedEngine (#1357), and
SpeakerIsOperatorEngine (#1355):
- ``ClaimEngine[bool]`` internal delegate
- Slightly slow-enter / slow-exit ``TemporalProfile`` (k_enter=4,
  k_exit=6 — don't catastrophize on a single low-HRV reading; negative
  mood persists, so recovery to POSITIVE benefits from sustained
  evidence too)
- ``LRDerivation``-typed signal weights (HPX003 compliant)
- Prior provenance ref into ``shared/prior_provenance.yaml`` (HPX004)
- ``HAPAX_BAYESIAN_BYPASS=1`` flows through the engine automatically

Phase 6b-ii.A scope (this PR): module + signal contract + tests + prior
provenance entry. Phase 6b-ii.B (deferred): wire the four signal sources
into a perception adapter + add the consumer wire-in.
"""

from __future__ import annotations

import logging

from shared.bayesian_impingement_emitter import emit_state_transition_impingement
from shared.claim import (
    ClaimEngine,
    ClaimState,
    LRDerivation,
    TemporalProfile,
)

log = logging.getLogger(__name__)


# Engine-state translation for callers reading state vocabulary directly.
# Mirrors MoodArousalEngine's AROUSED/UNCERTAIN/CALM but uses
# NEGATIVE/UNCERTAIN/POSITIVE for valence semantics. The "asserted"
# state corresponds to negative-valence (high posterior on the claim);
# "retracted" corresponds to positive/neutral mood.
_ENGINE_STATE_TO_VALENCE_STATE: dict[ClaimState, str] = {
    "ASSERTED": "NEGATIVE",
    "UNCERTAIN": "UNCERTAIN",
    "RETRACTED": "POSITIVE",
}


# Default LR weights per signal. Each (p_negative, p_positive) tuple
# represents (P(signal-fires | negative-valence), P(signal-fires |
# positive-or-neutral-valence)). Tuned for slow-enter / slow-exit
# semantics: negative-valence accumulates over multiple signals across
# minutes; recovery similarly takes sustained evidence.
DEFAULT_SIGNAL_WEIGHTS: dict[str, tuple[float, float]] = {
    # Pixel Watch HRV below operator's recent baseline.
    # Strong stress correlate; bidirectional because high HRV genuinely
    # evidences positive valence (parasympathetic dominance).
    "hrv_below_baseline": (0.78, 0.20),
    # Pixel Watch skin temperature drop from baseline (vasoconstriction
    # under stress). Positive-only — temperature staying stable is
    # ambiguous (could be neutral OR positive valence).
    "skin_temp_drop": (0.70, 0.15),
    # Accumulated sleep deficit above operator's tolerance threshold
    # (e.g. <6.5h average over recent nights). Positive-only — adequate
    # sleep doesn't actively evidence positive valence; it just removes
    # a known negative-valence driver.
    "sleep_debt_high": (0.65, 0.18),
    # Voice pitch elevated above operator's session baseline (stress
    # correlate in speech). Positive-only — pitch staying at baseline
    # is ambiguous (could be calm OR engaged-but-not-stressed).
    "voice_pitch_elevated": (0.72, 0.20),
}


class MoodValenceEngine:
    """Bayesian posterior over P(mood_valence_is_negative).

    Provides the same surface other Phase 6 cluster engines do —
    ``contribute(observations)``, ``posterior``, ``state``, ``reset()``,
    ``_required_ticks_for_transition`` — so consumers can swap between
    engines uniformly. State vocabulary is NEGATIVE/UNCERTAIN/POSITIVE
    rather than ASSERTED/UNCERTAIN/RETRACTED.

    The Logos API tick loop wires the four signal sources through
    ``mood_valence_observation``. Each tick also updates scrape-visible
    posterior and contributed-signal metrics for Phase D observability.
    """

    name: str = "mood_valence_engine"
    provides: tuple[str, ...] = ("mood_valence_negative_probability", "mood_valence_state")

    def __init__(
        self,
        prior: float = 0.20,  # Negative valence less common than baseline neutral/positive
        enter_threshold: float = 0.65,
        exit_threshold: float = 0.30,
        enter_ticks: int = 4,
        exit_ticks: int = 6,
        signal_weights: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        weights = signal_weights or DEFAULT_SIGNAL_WEIGHTS
        # Positive-only flag: skin_temp_drop, sleep_debt_high, and
        # voice_pitch_elevated are positive-only (their absence is
        # ambiguous between neutral and positive valence). hrv_below_baseline
        # is bidirectional because high HRV genuinely evidences positive
        # parasympathetic state.
        positive_only_signals = {"skin_temp_drop", "sleep_debt_high", "voice_pitch_elevated"}
        self._positive_only_signals = frozenset(positive_only_signals)
        lr_records: dict[str, LRDerivation] = {
            name: LRDerivation(
                signal_name=name,
                claim_name="mood_valence_negative",
                source_category="expert_elicitation_shelf",
                p_true_given_h1=p_negative,
                p_true_given_h0=p_positive,
                positive_only=name in positive_only_signals,
                estimation_reference=(
                    "DEFAULT_SIGNAL_WEIGHTS calibrated 2026-04-25 against "
                    "Pixel Watch biometric channels (HRV, skin temp, sleep) "
                    "and voice-pipeline pitch tracking; refined in 6b-ii.B "
                    "wire-in"
                ),
            )
            for name, (p_negative, p_positive) in weights.items()
        }
        self._engine: ClaimEngine[bool] = ClaimEngine(
            name="mood_valence_negative",
            prior=prior,
            temporal_profile=TemporalProfile(
                enter_threshold=enter_threshold,
                exit_threshold=exit_threshold,
                k_enter=enter_ticks,
                k_exit=exit_ticks,
                k_uncertain=4,
            ),
            signal_weights=lr_records,
        )
        # Track previous tick's state + posterior so transitions can be
        # broadcast on the impingement bus with a meaningful Δposterior.
        # Audit 3 fix #1: surface threshold crossings as cognitive-
        # substrate events, not just a scalar posterior.
        self._prev_state: str = self.state
        self._prev_posterior: float = self._engine.posterior

    def contribute(self, observations: dict[str, bool | None]) -> None:
        """Apply a single tick's worth of signal observations.

        Each key must match a ``LRDerivation.signal_name`` known to the
        engine; unknown keys are silently ignored by the engine's log-
        odds fusion so callers can pass extended-vocabulary dicts
        without breaking forward compatibility.

        On hysteresis state transition, publishes a richly-narrated
        impingement to ``/dev/shm/hapax-dmn/impingements.jsonl`` so the
        recruitment pipeline observes the valence shift as a bus event.
        """
        self._engine.tick(observations)
        new_state = self.state
        new_posterior = self._engine.posterior
        try:
            from shared.mood_engine_metrics import record_mood_engine_tick

            record_mood_engine_tick(
                "mood_valence",
                new_posterior,
                observations,
                positive_only_signals=self._positive_only_signals,
            )
        except Exception:
            log.debug("mood_valence metrics update failed", exc_info=True)
        if new_state != self._prev_state:
            try:
                emit_state_transition_impingement(
                    source="mood_valence",
                    claim_name="mood-valence-negative",
                    from_state=self._prev_state,
                    to_state=new_state,
                    posterior=new_posterior,
                    prev_posterior=self._prev_posterior,
                    active_signals={k: v for k, v in observations.items() if v is not None},
                )
            except Exception:
                log.debug("mood_valence impingement emit failed", exc_info=True)
        self._prev_state = new_state
        self._prev_posterior = new_posterior

    @property
    def posterior(self) -> float:
        return self._engine.posterior

    @property
    def state(self) -> str:
        return _ENGINE_STATE_TO_VALENCE_STATE[self._engine.state]

    def reset(self) -> None:
        self._engine.reset()
        self._prev_state = self.state
        self._prev_posterior = self._engine.posterior

    def _required_ticks_for_transition(self, frm: str, to: str) -> int:
        """Test-introspection helper. Translates NEGATIVE/POSITIVE back
        to the engine's ASSERTED/RETRACTED vocabulary then delegates."""
        translation: dict[str, ClaimState] = {
            "NEGATIVE": "ASSERTED",
            "UNCERTAIN": "UNCERTAIN",
            "POSITIVE": "RETRACTED",
        }
        return self._engine._required_ticks_for_transition(translation[frm], translation[to])


__all__ = [
    "DEFAULT_SIGNAL_WEIGHTS",
    "MoodValenceEngine",
]
