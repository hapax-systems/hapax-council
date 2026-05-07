"""MoodCoherenceEngine — Phase 6b-iii.A mood-claim Bayesian wrapper.

Per Universal Bayesian Claim-Confidence research §Phase 6b ("Mood
claims — stimmung dimensions, each becomes a `ClaimEngine[float]` with
continuous posterior"): mood-coherence benefits from posterior framing
— `P(operator's mood/autonomic state is currently low-coherence |
observed_signals)` — over ad-hoc threshold gates on HRV variability /
respiration / movement-jitter. This module ships the third of the
Phase 6b cluster (alpha-canonical) following MoodArousalEngine (#1368)
and MoodValenceEngine (#1371) using the quantize-into-tiers approach
(option 1 from beta dispatch 02:18Z): `ClaimEngine[bool]` over a
quantized low-coherence tier. Continuous-posterior `ClaimEngine[float]`
lands later if option 1 proves insufficient.

"Coherence" here is the physiological sense — autonomic-respiratory
coordination, beat-to-beat stability, and motor-control consistency.
The claim is `coherence_is_low` (the negative tier) so the asserted
posterior corresponds to dysregulated autonomic state — the inverse
mapping (HEALTHY/COHERENT as default, INCOHERENT as the asserted
state) mirrors SystemDegradedEngine's HEALTHY/DEGRADED orientation.

Mirrors MoodArousalEngine (#1368), MoodValenceEngine (#1371),
SystemDegradedEngine (#1357), and SpeakerIsOperatorEngine (#1355):
- ``ClaimEngine[bool]`` internal delegate
- Slow-enter / slower-exit ``TemporalProfile`` (k_enter=4, k_exit=8 —
  don't catastrophize on a single high-variability reading; incoherence
  persists, so recovery to COHERENT requires sustained stability)
- ``LRDerivation``-typed signal weights (HPX003 compliant)
- Prior provenance ref into ``shared/prior_provenance.yaml`` (HPX004)
- ``HAPAX_BAYESIAN_BYPASS=1`` flows through the engine automatically

Phase 6b-iii.A scope (this PR): module + signal contract + tests +
prior provenance entry. Phase 6b-iii.B (deferred): wire the four
signal sources into a perception adapter + add the consumer wire-in.
This PR completes the 3-claim mood cluster (mood_arousal_high,
mood_valence_negative, mood_coherence_low) suggested in beta's
dispatch.
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
# Mirrors SystemDegradedEngine's DEGRADED/UNCERTAIN/HEALTHY pattern but
# uses INCOHERENT/UNCERTAIN/COHERENT for autonomic-coherence semantics.
# The "asserted" state corresponds to incoherent (high posterior on the
# low-coherence claim); "retracted" corresponds to coherent baseline.
_ENGINE_STATE_TO_COHERENCE_STATE: dict[ClaimState, str] = {
    "ASSERTED": "INCOHERENT",
    "UNCERTAIN": "UNCERTAIN",
    "RETRACTED": "COHERENT",
}


# Default LR weights per signal. Each (p_incoherent, p_coherent) tuple
# represents (P(signal-fires | low-coherence), P(signal-fires | high-
# coherence-or-baseline)). Tuned for slow-enter / slower-exit semantics:
# incoherence accumulates over multiple signals across minutes; recovery
# requires sustained stability (k_exit=8) before flipping back to
# COHERENT — autonomic regulation re-establishes slowly.
DEFAULT_SIGNAL_WEIGHTS: dict[str, tuple[float, float]] = {
    # Pixel Watch HRV beat-to-beat coefficient-of-variation high.
    # Strong autonomic-instability proxy; bidirectional because low CV
    # genuinely evidences high coherence (steady parasympathetic tone).
    "hrv_variability_high": (0.78, 0.18),
    # Pixel Watch respiration rate variance high (irregular breathing
    # rhythm). Positive-only — steady respiration is the baseline state
    # but its absence isn't strong evidence (could be normal task-driven
    # variation rather than dysregulation).
    "respiration_irregular": (0.72, 0.15),
    # Pixel Watch accelerometer micro-movement noise high (restlessness,
    # fidgeting, postural instability). Positive-only — stillness is
    # ambiguous (could be focused-quiet OR shallow disengagement).
    "movement_jitter_high": (0.65, 0.20),
    # Pixel Watch skin temperature varying rapidly (unstable
    # thermoregulation). Positive-only — stable temperature is the
    # baseline; volatility is informative, stability is not.
    "skin_temp_volatility_high": (0.68, 0.18),
}


class MoodCoherenceEngine:
    """Bayesian posterior over P(mood_coherence_is_low).

    Provides the same surface other Phase 6 cluster engines do —
    ``contribute(observations)``, ``posterior``, ``state``, ``reset()``,
    ``_required_ticks_for_transition`` — so consumers can swap between
    engines uniformly. State vocabulary is INCOHERENT/UNCERTAIN/COHERENT
    rather than ASSERTED/UNCERTAIN/RETRACTED.

    The Logos API tick loop wires the four signal sources through
    ``mood_coherence_observation``. Each tick also updates scrape-visible
    posterior and contributed-signal metrics for Phase D observability.
    """

    name: str = "mood_coherence_engine"
    provides: tuple[str, ...] = ("mood_coherence_low_probability", "mood_coherence_state")

    def __init__(
        self,
        prior: float = 0.15,  # Low coherence rare; coherent default
        enter_threshold: float = 0.65,
        exit_threshold: float = 0.30,
        enter_ticks: int = 4,
        exit_ticks: int = 8,
        signal_weights: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        weights = signal_weights or DEFAULT_SIGNAL_WEIGHTS
        # Positive-only flag: respiration_irregular, movement_jitter_high,
        # and skin_temp_volatility_high are positive-only (their absence
        # doesn't strongly evidence coherence). hrv_variability_high is
        # bidirectional because low CV genuinely evidences high coherence.
        positive_only_signals = {
            "respiration_irregular",
            "movement_jitter_high",
            "skin_temp_volatility_high",
        }
        self._positive_only_signals = frozenset(positive_only_signals)
        lr_records: dict[str, LRDerivation] = {
            name: LRDerivation(
                signal_name=name,
                claim_name="mood_coherence_low",
                source_category="expert_elicitation_shelf",
                p_true_given_h1=p_incoherent,
                p_true_given_h0=p_coherent,
                positive_only=name in positive_only_signals,
                estimation_reference=(
                    "DEFAULT_SIGNAL_WEIGHTS calibrated 2026-04-25 against "
                    "Pixel Watch biometric channels (HRV CV, respiration, "
                    "accelerometer, skin temp); refined in 6b-iii.B wire-in"
                ),
            )
            for name, (p_incoherent, p_coherent) in weights.items()
        }
        self._engine: ClaimEngine[bool] = ClaimEngine(
            name="mood_coherence_low",
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
        recruitment pipeline observes the autonomic-coherence shift as
        a bus event.
        """
        self._engine.tick(observations)
        new_state = self.state
        new_posterior = self._engine.posterior
        try:
            from shared.mood_engine_metrics import record_mood_engine_tick

            record_mood_engine_tick(
                "mood_coherence",
                new_posterior,
                observations,
                positive_only_signals=self._positive_only_signals,
            )
        except Exception:
            log.debug("mood_coherence metrics update failed", exc_info=True)
        if new_state != self._prev_state:
            try:
                emit_state_transition_impingement(
                    source="mood_coherence",
                    claim_name="mood-coherence-low",
                    from_state=self._prev_state,
                    to_state=new_state,
                    posterior=new_posterior,
                    prev_posterior=self._prev_posterior,
                    active_signals={k: v for k, v in observations.items() if v is not None},
                )
            except Exception:
                log.debug("mood_coherence impingement emit failed", exc_info=True)
        self._prev_state = new_state
        self._prev_posterior = new_posterior

    @property
    def posterior(self) -> float:
        return self._engine.posterior

    @property
    def state(self) -> str:
        return _ENGINE_STATE_TO_COHERENCE_STATE[self._engine.state]

    def reset(self) -> None:
        self._engine.reset()
        self._prev_state = self.state
        self._prev_posterior = self._engine.posterior

    def _required_ticks_for_transition(self, frm: str, to: str) -> int:
        """Test-introspection helper. Translates INCOHERENT/COHERENT
        back to the engine's ASSERTED/RETRACTED vocabulary then delegates."""
        translation: dict[str, ClaimState] = {
            "INCOHERENT": "ASSERTED",
            "UNCERTAIN": "UNCERTAIN",
            "COHERENT": "RETRACTED",
        }
        return self._engine._required_ticks_for_transition(translation[frm], translation[to])


__all__ = [
    "DEFAULT_SIGNAL_WEIGHTS",
    "MoodCoherenceEngine",
]
