"""Cross-modal expression coordination.

When imagination escalates a fragment and the affordance pipeline recruits
multiple modalities (speech + visual), the coordinator ensures they express
the same content — same ImaginationFragment, different media.

Phase 5 of capability parity (queue #021).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class ExpressionCoordinator:
    """Coordinates expression across modalities for a single impingement.

    When the affordance pipeline recruits both speech and visual capabilities
    for the same impingement, this coordinator distributes the source fragment
    to each recruited capability.
    """

    def __init__(self) -> None:
        self._last_fragment: dict | None = None

    def coordinate(
        self,
        impingement_content: dict,
        recruited: list[tuple[str, Any]],
    ) -> list[dict]:
        """Distribute expression across recruited capabilities.

        Args:
            impingement_content: The impingement's content dict (may contain
                "fragment" key with ImaginationFragment data)
            recruited: List of (capability_name, capability_instance) tuples
                from AffordancePipeline.select()

        Returns:
            List of activation records [{capability, modality, fragment}]
        """
        fragment = impingement_content.get("fragment") or impingement_content.get("narrative")
        if fragment is None:
            return []

        if isinstance(fragment, str):
            fragment = {"narrative": fragment}

        self._last_fragment = fragment
        activations: list[dict] = []

        for name, cap in recruited:
            modality = _infer_modality(name, cap)
            activations.append(
                {
                    "capability": name,
                    "modality": modality,
                    "fragment": fragment,
                }
            )
            log.info(
                "Cross-modal coordination: %s (%s) receives fragment",
                name,
                modality,
            )

        return activations

    @property
    def last_fragment(self) -> dict | None:
        """Most recently coordinated fragment (for debugging)."""
        return self._last_fragment


# ── Dimension mapping for visual expression ──────────────────────────────────

FRAGMENT_TO_SHADER: dict[str, str] = {
    "intensity": "noise.amplitude",
    "tension": "rd.feed_rate",
    "depth": "post.vignette_strength",
    "coherence": "noise.frequency_x",
    "spectral_color": "color.saturation",
    "temporal_distortion": "noise.speed",
    "degradation": "noise.octaves",
    "pitch_displacement": "color.hue_rotate",
    "diffusion": "rd.diffusion_a",
}

# Material is a shader UNIFORM in content_layer.wgsl, NOT a preset selector.
# The substrate graph stays constant; material controls how content interacts
# with the procedural field (water=flowing, fire=consuming, etc.)
MATERIAL_TO_UNIFORM: dict[str, float] = {
    "water": 0.0,
    "fire": 1.0,
    "earth": 2.0,
    "air": 3.0,
    "void": 4.0,
}


def map_fragment_to_visual(fragment: dict) -> dict[str, float]:
    """Map ImaginationFragment dimensions to shader parameter targets.

    Returns dict of {shader_param: value} for visual modulation.
    """
    dimensions = fragment.get("dimensions", {})
    result: dict[str, float] = {}
    for dim_name, shader_param in FRAGMENT_TO_SHADER.items():
        if dim_name in dimensions:
            result[shader_param] = float(dimensions[dim_name])
    return result


def map_fragment_to_material_uniform(fragment: dict) -> float:
    """Map ImaginationFragment material to its shader uniform value."""
    material = fragment.get("material", "water")
    if isinstance(material, str):
        return MATERIAL_TO_UNIFORM.get(material.lower(), 0.0)
    return 0.0


def _infer_modality(name: str, cap: Any) -> str:
    """Determine modality from capability's declared medium."""
    if hasattr(cap, "operational") and hasattr(cap.operational, "medium"):
        medium = cap.operational.medium
        if medium:
            return medium
    if hasattr(cap, "medium"):
        if cap.medium:
            return cap.medium
    return "unknown"


def normalize_dimension_activation(
    strength: float, dimensions: dict[str, float]
) -> dict[str, float]:
    """Strength-weighted normalization for dimension activations.

    Both visual and vocal chains must use this to ensure parity.
    """
    return {name: max(0.0, min(1.0, level * strength)) for name, level in dimensions.items()}
