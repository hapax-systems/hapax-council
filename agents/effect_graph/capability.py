"""Shader graph as a Capability in the impingement cascade.

Visual expression recruited when system state warrants visual feedback.
Modulates shader parameters (bloom, noise, color grade, scanlines, etc.)
to express urgency, calm, flow state, or distress visually.
"""

from __future__ import annotations

import logging
from typing import Any

from shared.capability import CapabilityCategory, ResourceTier, SystemContext
from shared.impingement import Impingement

log = logging.getLogger("effect_graph.capability")

SHADER_DESCRIPTION = (
    "Modulates visual shader parameters to express system state through camera output. "
    "Controls bloom, noise, color grading, scanlines, vignette, and trail effects. "
    "Output is visual (not auditory), continuous (not discrete), and non-intrusive. "
    "Requires GPU. Latency under 16ms (real-time rendering). "
    "Can express urgency, calm, flow, distress, or neutral states."
)


class ShaderGraphCapability:
    """Visual expression via shader graph — recruited for visual feedback needs."""

    def __init__(self) -> None:
        self._activation_level = 0.0
        self._pending: list[Impingement] = []

    @property
    def name(self) -> str:
        return "shader_graph"

    @property
    def category(self) -> CapabilityCategory:
        return CapabilityCategory.EXPRESSION

    @property
    def resource_tier(self) -> ResourceTier:
        return ResourceTier.HEAVY

    def available(self, ctx: SystemContext) -> bool:
        from pathlib import Path

        return Path("/dev/shm/hapax-imagination/pipeline").exists()

    def degrade(self) -> str:
        return "Visual expression is unavailable — imagination pipeline not running."

    @property
    def activation_cost(self) -> float:
        return 0.2  # GPU but lightweight (parameter updates, not model inference)

    def activate(self, impingement: Impingement, level: float) -> dict[str, Any]:
        """Queue a visual expression request."""
        self._activation_level = level
        self._pending.append(impingement)
        log.info(
            "Shader graph recruited: %s (strength=%.2f)",
            impingement.content.get("metric", impingement.source),
            impingement.strength,
        )
        return {"visual_expression_requested": True, "impingement_id": impingement.id}

    def deactivate(self) -> None:
        self._activation_level = 0.0

    def has_pending(self) -> bool:
        return len(self._pending) > 0

    def consume_pending(self) -> Impingement | None:
        if self._pending:
            return self._pending.pop(0)
        return None
