"""Impingement adapter -- routes internal events through CPAL control loop.

Impingements are not separate from conversation. They modulate the
control loop by adjusting gain and contributing error. A critical
system alert raises gain and produces high error. A mild imagination
fragment gently nudges gain and produces low error.

Replaces: SpeechProductionCapability, impingement_consumer_loop routing,
_handle_proactive_impingement, deliver_notification, generate_spontaneous_speech.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agents.hapax_daimonion.cpal.types import GainUpdate

log = logging.getLogger(__name__)

# Gain deltas by impingement source
_GAIN_DELTAS: dict[str, float] = {
    "stimmung_critical": 0.3,  # force gain up for critical alerts
    "stimmung_degraded": 0.15,
    "system_alert": 0.25,
    "imagination": 0.05,  # gentle nudge
    "notification": 0.1,
    "operator_distress": 0.4,  # highest priority
}


@dataclass(frozen=True)
class ImpingementEffect:
    """The effect of an impingement on the CPAL control loop."""

    gain_update: GainUpdate | None  # how to modulate loop gain
    error_boost: float  # additional error magnitude (0.0-1.0)
    should_surface: bool  # whether this warrants vocal production
    narrative: str  # what to say if surfacing


class ImpingementAdapter:
    """Converts impingements into CPAL control loop effects.

    Called by the evaluator when impingements arrive. Returns an
    ImpingementEffect that the evaluator applies to gain and error.
    """

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

        # Should surface vocally? Based on strength and source
        should_surface = (
            strength >= 0.7
            or interrupt_token in ("population_critical", "operator_distress")
            or gain_key in ("stimmung_critical", "operator_distress", "system_alert")
        )

        # Narrative for vocal surfacing
        if not narrative:
            narrative = metric or f"{source} event"

        return ImpingementEffect(
            gain_update=gain_update,
            error_boost=error_boost,
            should_surface=should_surface,
            narrative=narrative,
        )
