"""Fortress governance as a Capability in the impingement cascade.

Wraps the existing FortressDaemon's governance logic as a Capability
that self-selects on fortress-related impingements. When activated,
triggers immediate governance evaluation (bypassing the normal tick cycle).
"""

from __future__ import annotations

import logging
from typing import Any

from shared.impingement import Impingement

log = logging.getLogger("fortress.capability")

# Affordances this capability can resolve
FORTRESS_AFFORDANCES = {
    "drink",
    "food",
    "population",
    "extinction",
    "threat",
    "stress",
    "fortress",
    "stimmung_critical",
    "drink_per_capita",
    "extinction_risk",
}

# Function-free description for affordance retrieval (McCaffrey 2012)
FORTRESS_DESCRIPTION = (
    "Evaluates resource adequacy and threat levels in a managed simulation. "
    "Produces strategic recommendations and dispatches management commands. "
    "Monitors drink, food, population, military readiness, and infrastructure gaps. "
    "Operates on 2-second governance tick cycle. No GPU required."
)


class FortressGovernanceCapability:
    """Fortress governance as a Capability in the activation cascade."""

    def __init__(self) -> None:
        self._activation_level = 0.0
        self._last_impingement: Impingement | None = None

    @property
    def name(self) -> str:
        return "fortress_governance"

    @property
    def affordance_signature(self) -> set[str]:
        return FORTRESS_AFFORDANCES

    @property
    def activation_cost(self) -> float:
        return 0.3  # moderate — triggers governance eval, may call LLM

    @property
    def activation_level(self) -> float:
        return self._activation_level

    @property
    def consent_required(self) -> bool:
        return False  # fortress governance doesn't touch person-adjacent data

    @property
    def priority_floor(self) -> bool:
        return False  # fortress is not safety-critical for the operator

    def can_resolve(self, impingement: Impingement) -> float:
        """Match fortress-related impingements."""
        content = impingement.content
        metric = content.get("metric", "")

        # Direct metric match
        if any(aff in metric for aff in FORTRESS_AFFORDANCES):
            return impingement.strength

        # Source match
        if "fortress" in impingement.source:
            return impingement.strength * 0.8

        return 0.0

    def activate(self, impingement: Impingement, level: float) -> dict[str, Any]:
        """Activate fortress governance in response to impingement.

        Returns a dict with the impingement details for the governance
        loop to consume on its next cycle.
        """
        self._activation_level = level
        self._last_impingement = impingement
        log.info(
            "Fortress governance activated: %s (strength=%.2f, level=%.2f)",
            impingement.content.get("metric", impingement.source),
            impingement.strength,
            level,
        )
        return {
            "source": "impingement_cascade",
            "metric": impingement.content.get("metric", ""),
            "strength": impingement.strength,
            "content": impingement.content,
        }

    def deactivate(self) -> None:
        """Return to dormant state."""
        self._activation_level = 0.0
        self._last_impingement = None

    def has_pending_impingement(self) -> bool:
        """Check if there's an unprocessed impingement activation."""
        return self._last_impingement is not None

    def consume_impingement(self) -> Impingement | None:
        """Consume and return the pending impingement."""
        imp = self._last_impingement
        self._last_impingement = None
        return imp
