"""Impingement adapter -- routes internal events through CPAL control loop.

Impingements are not separate from conversation. They modulate the
control loop by adjusting gain and contributing error. A critical
system alert raises gain and produces high error. A mild imagination
fragment gently nudges gain and produces low error.

Scope: this adapter owns only gain/error modulation and the
``should_surface`` gate that triggers ``generate_spontaneous_speech``
from ``CpalRunner.process_impingement``. Other recruited-affordance
dispatch (notification delivery, Thompson learning for studio/world
recruitment, cross-modal ``ExpressionCoordinator`` coordination,
``_system_awareness`` and ``_discovery_handler`` activation) lives in
``agents.hapax_daimonion.run_loops_aux.impingement_consumer_loop``,
which is spawned as a separate background task next to the CPAL
impingement loop in ``run_inner.py``. Apperception cascade is owned by
``shared.apperception_tick.ApperceptionTick`` inside the visual-layer
aggregator. An earlier version of this docstring claimed this adapter
"Replaces: SpeechProductionCapability, impingement_consumer_loop
routing, ..." — that claim was incorrect and caused those downstream
effects to go silently dead after PR #555.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from agents.hapax_daimonion.cpal.programme_context import (
    ProgrammeProvider,
    null_provider,
)
from agents.hapax_daimonion.cpal.types import GainUpdate

log = logging.getLogger(__name__)


class BufferSpeechState(NamedTuple):
    """Snapshot of operator speech activity from the conversation buffer.

    Used as downward evidence on the surfacing posterior — NOT as a hard
    gate. When the operator is speaking, the posterior probability of
    surfacing decreases continuously.
    """

    speech_active: bool
    in_cooldown: bool


def _null_buffer_state() -> BufferSpeechState:
    return BufferSpeechState(speech_active=False, in_cooldown=False)


BufferStateProvider = Callable[[], BufferSpeechState]

# Gain deltas by impingement source
_GAIN_DELTAS: dict[str, float] = {
    "stimmung_critical": 0.3,  # force gain up for critical alerts
    "stimmung_degraded": 0.15,
    "system_alert": 0.25,
    "imagination": 0.05,  # gentle nudge
    "notification": 0.1,
    "operator_distress": 0.4,  # highest priority
}

# Phase 6: surface-threshold defaults + bounds. Threshold is a SOFT
# PRIOR — programmes shift it within [MIN, MAX] (multiplier in
# [0.5, 2.0] applied to the base). ALWAYS_SURFACE_AT is a soft ceiling,
# not a hard bypass — operator speech evidence can still dampen it.
DEFAULT_SURFACE_THRESHOLD: float = 0.7
SURFACE_MULTIPLIER_MIN: float = 0.5
SURFACE_MULTIPLIER_MAX: float = 2.0
ALWAYS_SURFACE_AT: float = 1.0

# Operator speech evidence: when the operator is speaking, the threshold
# rises by this additive amount. This is a continuous Bayesian evidence
# signal, not a hard gate — it reduces P(surfacing | operator_speaking)
# without setting it to zero.
OPERATOR_SPEECH_THRESHOLD_LIFT: float = 0.4
SPEECH_CAPABILITY_NAME: str = "speech_production"


@dataclass(frozen=True)
class ImpingementEffect:
    """The effect of an impingement on the CPAL control loop."""

    gain_update: GainUpdate | None  # how to modulate loop gain
    error_boost: float  # additional error magnitude (0.0-1.0)
    should_surface: bool  # whether this warrants vocal production
    narrative: str  # what to say if surfacing
    # Phase 6: the threshold actually used for the should_surface
    # decision. Surfaced for telemetry + tests so the soft-prior bias
    # is observable.
    surface_threshold: float = DEFAULT_SURFACE_THRESHOLD


class ImpingementAdapter:
    """Converts impingements into CPAL control loop effects.

    Called by the evaluator when impingements arrive. Returns an
    ImpingementEffect that the evaluator applies to gain and error.

    Phase 6: optional ``programme_provider`` callable returns the
    currently-active Programme so the adapter can bias the
    ``should_surface`` threshold per programme. When the provider
    returns ``None`` (no active programme, or test-default), the
    adapter falls back to ``DEFAULT_SURFACE_THRESHOLD`` and behaves
    as before.

    Operator speech evidence: optional ``buffer_state_provider``
    returns the conversation buffer's speech activity state. When the
    operator is speaking or in post-TTS cooldown, the surfacing
    threshold rises continuously — P(surfacing | operator_speaking)
    decreases without a hard gate. Per the conative-impingement spec:
    continuous suppression fields, not hard speak/don't-speak rules.
    """

    def __init__(
        self,
        *,
        programme_provider: ProgrammeProvider = null_provider,
        buffer_state_provider: BufferStateProvider = _null_buffer_state,
    ) -> None:
        self._programme_provider = programme_provider
        self._buffer_state_provider = buffer_state_provider

    def adapt(self, impingement: object) -> ImpingementEffect:
        """Convert an impingement to a CPAL control loop effect.

        Args:
            impingement: An Impingement object with source, strength,
                        content, and interrupt_token attributes.
        """
        source = getattr(impingement, "source", "")
        strength = getattr(impingement, "strength", 0.0)
        content = getattr(impingement, "content", {})
        interrupt_token = getattr(impingement, "interrupt_token", None)
        metric = content.get("metric", "")
        narrative = content.get("narrative", "")

        # Determine gain delta from source
        gain_key = source
        if "stimmung" in source and "critical" in metric:
            gain_key = "stimmung_critical"
        elif "stimmung" in source and "degraded" in metric:
            gain_key = "stimmung_degraded"
        elif interrupt_token == "operator_distress":
            gain_key = "operator_distress"

        base_delta = _GAIN_DELTAS.get(gain_key, 0.02)
        gain_delta = base_delta * strength

        gain_update = (
            GainUpdate(
                delta=gain_delta,
                source=f"impingement:{source}",
            )
            if gain_delta > 0.01
            else None
        )

        # Error boost: high-strength impingements increase error
        # (operator should know about this but doesn't yet)
        error_boost = strength * 0.3 if strength > 0.3 else 0.0

        # Phase 6: programme-biased threshold with operator-speech
        # evidence. The threshold is a posterior that incorporates
        # programme posture AND operator speech activity as evidence.
        surface_threshold = self._compose_threshold()

        # Safety-critical interrupt tokens bypass the posterior —
        # operator distress and population-critical events MUST surface.
        safety_override = interrupt_token in (
            "population_critical",
            "operator_distress",
        ) or gain_key in ("stimmung_critical", "operator_distress", "system_alert")
        # ALWAYS_SURFACE_AT is a soft ceiling, not a hard bypass.
        # Operator speech evidence dampens it so strength=1.0 alone
        # doesn't override the operator's active speech.
        should_surface = safety_override or strength >= surface_threshold

        # Narrative for vocal surfacing
        if not narrative:
            narrative = metric or f"{source} event"

        return ImpingementEffect(
            gain_update=gain_update,
            error_boost=error_boost,
            should_surface=should_surface,
            narrative=narrative,
            surface_threshold=surface_threshold,
        )

    def _compose_threshold(self) -> float:
        """Compose the should_surface threshold from programme + operator evidence.

        Composition:
          - base = ``programme.constraints.surface_threshold_prior`` if
            set, else ``DEFAULT_SURFACE_THRESHOLD``.
          - multiplier = ``programme.bias_multiplier(SPEECH_CAPABILITY_NAME)``
            clamped to ``[SURFACE_MULTIPLIER_MIN, SURFACE_MULTIPLIER_MAX]``.
          - operator_lift = ``OPERATOR_SPEECH_THRESHOLD_LIFT`` when the
            operator is speaking or in post-TTS cooldown. This is
            additive evidence, not a gate: P(surfacing appropriate |
            operator_speaking) is lower, expressed as a higher threshold.
          - threshold = base * multiplier + operator_lift, clamped to (0, 1].

        Returns ``DEFAULT_SURFACE_THRESHOLD`` when the provider returns
        no programme or raises. The clamp on the multiplier guarantees
        the bias is a true soft prior — even an extreme operator-
        authored bias can't pin the threshold to 0 (always surface) or
        infinity (never surface).
        """
        programme = self._safe_active_programme()
        if programme is None:
            base_threshold = DEFAULT_SURFACE_THRESHOLD
        else:
            try:
                base = programme.constraints.surface_threshold_prior
                base_threshold_raw = base if base is not None else DEFAULT_SURFACE_THRESHOLD
                raw_mult = float(programme.bias_multiplier(SPEECH_CAPABILITY_NAME))
                multiplier = min(SURFACE_MULTIPLIER_MAX, max(SURFACE_MULTIPLIER_MIN, raw_mult))
                base_threshold = base_threshold_raw * multiplier
            except Exception:
                log.debug("programme threshold composition failed", exc_info=True)
                base_threshold = DEFAULT_SURFACE_THRESHOLD

        # Operator speech evidence: continuous downward suppression.
        # When the buffer reports speech_active or in_cooldown, the
        # threshold rises — making surfacing less likely. This is a
        # Bayesian evidence signal: the observation "operator is
        # speaking" increases the posterior probability that surfacing
        # is inappropriate.
        operator_lift = 0.0
        try:
            buf_state = self._buffer_state_provider()
            if buf_state.speech_active or buf_state.in_cooldown:
                operator_lift = OPERATOR_SPEECH_THRESHOLD_LIFT
        except Exception:
            pass  # fail open — no evidence is neutral, not a veto

        threshold = base_threshold + operator_lift
        return min(1.0, max(0.01, threshold))

    def _safe_active_programme(self):
        try:
            return self._programme_provider()
        except Exception:
            log.debug("programme_provider raised", exc_info=True)
            return None
