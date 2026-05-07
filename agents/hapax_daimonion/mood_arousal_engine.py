"""MoodArousalEngine — Phase 6b-i.A mood-claim Bayesian wrapper.

Per Universal Bayesian Claim-Confidence research §Phase 6b ("Mood claims
— stimmung dimensions, each becomes a `ClaimEngine[float]` with continuous
posterior"): mood-claims benefit from posterior framing — `P(mood is
high-arousal | observed_signals)` — over ad-hoc threshold gates on the
stimmung dimensions themselves. This module ships the first such engine
in the cluster (alpha-canonical lane per beta dispatch 02:18Z) using the
quantize-into-tiers approach (option 1): `ClaimEngine[bool]` over a
quantized arousal tier. Continuous-posterior `ClaimEngine[float]` lands
in Phase 6b-i.B if option 1 proves insufficient.

Mirrors SystemDegradedEngine (#1357) and SpeakerIsOperatorEngine (#1355):
- ``ClaimEngine[bool]`` internal delegate
- Symmetric-ish ``TemporalProfile`` (k_enter=3, k_exit=4 — mood shifts
  more readily in both directions than presence or degradation, but
  arousal-asserting events still get a slight head start over recovery)
- ``LRDerivation``-typed signal weights (HPX003 compliant)
- Prior provenance ref into ``shared/prior_provenance.yaml`` (HPX004)
- ``HAPAX_BAYESIAN_BYPASS=1`` flows through the engine automatically

Phase 6b-i.A scope (this PR): module + signal contract + tests + prior
provenance entry. Phase 6b-i.B (deferred): wire the four signal sources
into a perception adapter + add the consumer wire-in. Phase 6b-i.C may
extend to additional mood dimensions (mood_valence_negative,
mood_coherence_low) following the same template.
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
# Mirrors PresenceEngine's PRESENT/UNCERTAIN/AWAY pattern but uses
# AROUSED/UNCERTAIN/CALM for mood-claim semantics.
_ENGINE_STATE_TO_AROUSAL_STATE: dict[ClaimState, str] = {
    "ASSERTED": "AROUSED",
    "UNCERTAIN": "UNCERTAIN",
    "RETRACTED": "CALM",
}


# Default LR weights per signal. Each (p_aroused, p_calm) tuple represents
# (P(signal-fires | high-arousal), P(signal-fires | low-arousal)). Tuned
# for slightly-fast-enter / moderate-exit semantics: arousal can lift on
# any single strong cue within 1-2 ticks; recovery to CALM benefits from
# brief sustained quiet (k_exit=4) to avoid flicker.
DEFAULT_SIGNAL_WEIGHTS: dict[str, tuple[float, float]] = {
    # Ambient room mic RMS energy above operator's recent quantile.
    # Strong arousal proxy (loud environment correlates with operator
    # engaging energetically) but bidirectional — quiet rooms genuinely
    # downvote arousal.
    "ambient_audio_rms_high": (0.78, 0.18),
    # Contact mic onset rate (taps/strikes per second) above quantile.
    # Strong positive — physically aroused operator tends to make more
    # discrete impacts (typing bursts, drumming, percussive interaction).
    # Positive-only because absence of impacts is ambiguous (could be
    # focused-quiet flow, not low arousal).
    "contact_mic_onset_rate_high": (0.80, 0.10),
    # OXI One MIDI clock pulse rate above tempo threshold (operator is
    # actively driving a fast-tempo musical context). Strong positive —
    # MIDI clock is a direct artefact of operator action.
    "midi_clock_bpm_high": (0.85, 0.08),
    # Pixel Watch heart rate above operator's session baseline.
    # Bidirectional — HR below baseline is genuine evidence for CALM.
    # Calibration window matches PresenceEngine's watch_hr (120s BLE
    # staleness cutoff).
    "hr_bpm_above_baseline": (0.75, 0.20),
}


class MoodArousalEngine:
    """Bayesian posterior over P(mood_arousal_is_high).

    Provides the same surface other Phase 6 cluster engines do —
    ``contribute(observations)``, ``posterior``, ``state``, ``reset()``,
    ``_required_ticks_for_transition`` — so consumers can swap between
    engines uniformly. State vocabulary is AROUSED/UNCERTAIN/CALM rather
    than ASSERTED/UNCERTAIN/RETRACTED.

    The Logos API tick loop wires the four signal sources through
    ``mood_arousal_observation``. Each tick also updates scrape-visible
    posterior and contributed-signal metrics for Phase D observability.
    """

    name: str = "mood_arousal_engine"
    provides: tuple[str, ...] = ("mood_arousal_high_probability", "mood_arousal_state")

    def __init__(
        self,
        prior: float = 0.30,  # Arousal not the default state but not rare
        enter_threshold: float = 0.65,
        exit_threshold: float = 0.30,
        enter_ticks: int = 3,
        exit_ticks: int = 4,
        signal_weights: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        weights = signal_weights or DEFAULT_SIGNAL_WEIGHTS
        # Positive-only flag: contact_mic_onset_rate_high is positive-only
        # (absence of impacts is ambiguous between focused-quiet and
        # low-arousal). Other three signals are bidirectional.
        positive_only_signals = {"contact_mic_onset_rate_high"}
        self._positive_only_signals = frozenset(positive_only_signals)
        lr_records: dict[str, LRDerivation] = {
            name: LRDerivation(
                signal_name=name,
                claim_name="mood_arousal_high",
                source_category="expert_elicitation_shelf",
                p_true_given_h1=p_aroused,
                p_true_given_h0=p_calm,
                positive_only=name in positive_only_signals,
                estimation_reference=(
                    "DEFAULT_SIGNAL_WEIGHTS calibrated 2026-04-25 against "
                    "PresenceEngine signal precedents (Cortado contact mic, "
                    "OXI MIDI clock, Pixel Watch HR, Blue Yeti room mic); "
                    "refined in 6b-i.B wire-in"
                ),
            )
            for name, (p_aroused, p_calm) in weights.items()
        }
        self._engine: ClaimEngine[bool] = ClaimEngine(
            name="mood_arousal_high",
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

        On a hysteresis state transition, publishes a richly-narrated
        impingement to ``/dev/shm/hapax-dmn/impingements.jsonl`` so the
        recruitment pipeline observes the mood shift as a bus event.
        """
        self._engine.tick(observations)
        new_state = self.state
        new_posterior = self._engine.posterior
        try:
            from shared.mood_engine_metrics import record_mood_engine_tick

            record_mood_engine_tick(
                "mood_arousal",
                new_posterior,
                observations,
                positive_only_signals=self._positive_only_signals,
            )
        except Exception:
            log.debug("mood_arousal metrics update failed", exc_info=True)
        if new_state != self._prev_state:
            try:
                emit_state_transition_impingement(
                    source="mood_arousal",
                    claim_name="mood-arousal-high",
                    from_state=self._prev_state,
                    to_state=new_state,
                    posterior=new_posterior,
                    prev_posterior=self._prev_posterior,
                    active_signals={k: v for k, v in observations.items() if v is not None},
                )
            except Exception:
                log.debug("mood_arousal impingement emit failed", exc_info=True)
        self._prev_state = new_state
        self._prev_posterior = new_posterior

    @property
    def posterior(self) -> float:
        return self._engine.posterior

    @property
    def state(self) -> str:
        return _ENGINE_STATE_TO_AROUSAL_STATE[self._engine.state]

    def reset(self) -> None:
        self._engine.reset()
        self._prev_state = self.state
        self._prev_posterior = self._engine.posterior

    def _required_ticks_for_transition(self, frm: str, to: str) -> int:
        """Test-introspection helper. Translates AROUSED/CALM back to the
        engine's ASSERTED/RETRACTED vocabulary then delegates."""
        translation: dict[str, ClaimState] = {
            "AROUSED": "ASSERTED",
            "UNCERTAIN": "UNCERTAIN",
            "CALM": "RETRACTED",
        }
        return self._engine._required_ticks_for_transition(translation[frm], translation[to])


__all__ = [
    "DEFAULT_SIGNAL_WEIGHTS",
    "MoodArousalEngine",
]
