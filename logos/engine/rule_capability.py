"""Rule → Capability wrapper.

Wraps existing Rule objects (trigger_filter/produce) as Capability
protocol objects. Enables the reactive engine to use CapabilityRegistry
broadcast while keeping all 13 existing rules unchanged.

Rules stay written as Rules. They get wrapped at registration time.
No changes needed to rule definitions, handlers, or the executor.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from logos._impingement import Impingement
from logos.engine.models import Action, ChangeEvent
from logos.engine.rules import Rule

_log = logging.getLogger(__name__)

# Phase → activation_cost mapping
_PHASE_COST: dict[int, float] = {
    0: 0.0,  # deterministic — free
    1: 0.5,  # GPU-bounded
    2: 1.0,  # cloud LLM
}

_PHASE_LABEL: dict[int, str] = {
    0: "Deterministic, sub-second, no LLM",
    1: "GPU-bounded, may use local LLM",
    2: "Cloud LLM required, higher latency",
}


def generate_rule_description(rule: Rule) -> str:
    """Auto-generate a function-free description for a rule capability.

    Uses the rule's human-authored description as the semantic anchor
    for vector indexing in the affordance pipeline.
    """
    phase_label = _PHASE_LABEL.get(rule.phase, "Unknown phase")
    return (
        f"Reactive rule: {rule.description}. "
        f"{phase_label}. "
        f"Produces downstream actions when trigger conditions are met."
    )


class RuleCapability:
    """Adapts a Rule to the Capability protocol.

    The wrapper translates:
    - trigger_filter(ChangeEvent) → can_resolve(Impingement) → float
    - produce(ChangeEvent) → activate(Impingement, level) → list[Action]
    - phase → activation_cost
    - cooldown_s → inhibition of return (handled by CapabilityRegistry)
    """

    def __init__(self, rule: Rule) -> None:
        self._rule = rule
        self._activation_level = 0.0

    @property
    def name(self) -> str:
        return self._rule.name

    @property
    def affordance_signature(self) -> set[str]:
        return {self._rule.name}

    @property
    def activation_cost(self) -> float:
        return _PHASE_COST.get(self._rule.phase, 0.5)

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
        """Evaluate by reconstructing ChangeEvent and calling trigger_filter."""
        event = self._impingement_to_event(impingement)
        if event is None:
            return 0.0
        try:
            if self._rule.trigger_filter(event):
                return 1.0
        except Exception:
            _log.debug("Rule %s trigger_filter failed", self._rule.name, exc_info=True)
        return 0.0

    def activate(self, impingement: Impingement, level: float) -> list[Action]:
        """Produce actions by calling the wrapped rule's produce function."""
        self._activation_level = level
        event = self._impingement_to_event(impingement)
        if event is None:
            return []
        try:
            return self._rule.produce(event)
        except Exception:
            _log.debug("Rule %s produce failed", self._rule.name, exc_info=True)
            return []

    def deactivate(self) -> None:
        self._activation_level = 0.0

    @staticmethod
    def _impingement_to_event(impingement: Impingement) -> ChangeEvent | None:
        """Reconstruct a ChangeEvent from an impingement's content dict.

        Returns None if the impingement doesn't contain filesystem event data
        (e.g., it came from DMN or perception, not from the engine watcher).
        """
        content = impingement.content
        path_str = content.get("path")
        if not path_str:
            return None

        return ChangeEvent(
            path=Path(path_str),
            event_type=content.get("event_type", "modified"),
            doc_type=content.get("doc_type") or None,
            frontmatter=None,  # frontmatter not preserved in impingement
            timestamp=datetime.fromtimestamp(impingement.timestamp),
        )
