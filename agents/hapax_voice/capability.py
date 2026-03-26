"""Speech production as a Capability in the impingement cascade.

Speech is a tool — recruited when the resolution of an impingement
requires verbal output. Not a pipeline that's always listening,
but a capability that gets activated by contextual need.
"""

from __future__ import annotations

import logging
from typing import Any

from shared.impingement import Impingement

log = logging.getLogger("voice.capability")

SPEECH_AFFORDANCES = {
    "verbal_response",
    "operator_greeting",
    "alert_verbal",
    "spontaneous_speech",
    "stimmung_critical",
    "operator_stress",
}

# Function-free description for affordance retrieval (McCaffrey 2012)
SPEECH_DESCRIPTION = (
    "Produces audible natural language that reaches the operator's ears within 1 second. "
    "Requires GPU and speakers. Output is ephemeral (not persisted). "
    "Can convey urgency through prosody and tone. Interrupts silence but not active speech."
)


class SpeechProductionCapability:
    """Speech production as a Capability — recruited when verbal output is needed."""

    def __init__(self) -> None:
        self._activation_level = 0.0
        self._pending: list[Impingement] = []

    @property
    def name(self) -> str:
        return "speech_production"

    @property
    def affordance_signature(self) -> set[str]:
        return SPEECH_AFFORDANCES

    @property
    def activation_cost(self) -> float:
        return 0.3  # GPU for TTS

    @property
    def activation_level(self) -> float:
        return self._activation_level

    @property
    def consent_required(self) -> bool:
        return False

    @property
    def priority_floor(self) -> bool:
        return False

    def can_resolve(self, impingement: Impingement) -> float:
        """Match impingements that may warrant verbal output."""
        content = impingement.content
        metric = content.get("metric", "")

        # Direct affordance match
        if any(aff in metric for aff in SPEECH_AFFORDANCES):
            return impingement.strength

        # Interrupt tokens that warrant speech
        if impingement.interrupt_token in ("population_critical", "operator_distress"):
            return impingement.strength * 0.9

        # High-strength stimmung signals — the system should speak up
        if "stimmung" in impingement.source and impingement.strength > 0.8:
            return impingement.strength * 0.5

        return 0.0

    def activate(self, impingement: Impingement, level: float) -> dict[str, Any]:
        """Queue a spontaneous speech impingement for the voice daemon to consume."""
        self._activation_level = level
        self._pending.append(impingement)
        log.info(
            "Speech production recruited: %s (strength=%.2f)",
            impingement.content.get("metric", impingement.source),
            impingement.strength,
        )
        return {"speech_requested": True, "impingement_id": impingement.id}

    def deactivate(self) -> None:
        self._activation_level = 0.0

    def has_pending(self) -> bool:
        return len(self._pending) > 0

    def consume_pending(self) -> Impingement | None:
        """Consume the next pending speech request."""
        if self._pending:
            return self._pending.pop(0)
        return None
