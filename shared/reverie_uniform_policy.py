"""Live-surface bounds for Reverie/imagination uniforms.

Reverie is an external generated visual source, not a camera preset. That
means generator nodes can be valid there while remaining blocked from direct
camera/live-surface preset graphs. The shared contract is still strict:
generated texture may add atmosphere, but it must not become a full-frame
replacement, dimmer, or attention-grabbing pulse over the livestream.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class UniformBound:
    min_value: float | None = None
    max_value: float | None = None

    def apply(self, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        out = float(value)
        if not math.isfinite(out):
            return value
        if self.min_value is not None:
            out = max(out, self.min_value)
        if self.max_value is not None:
            out = min(out, self.max_value)
        return out


def _max(value: float) -> UniformBound:
    return UniformBound(max_value=value)


def _range(low: float, high: float) -> UniformBound:
    return UniformBound(min_value=low, max_value=high)


REVERIE_LIVE_UNIFORM_BOUNDS: dict[str, UniformBound] = {
    # Generative substrate: useful as texture, not as an opaque replacement.
    "noise.amplitude": _range(0.0, 0.25),
    "noise.speed": _range(0.0, 0.08),
    # Reaction-diffusion should stay in a structured basin.
    "rd.amount": _max(0.15),
    # Content slots are overlays, not dominant layers.
    "content.salience": _range(0.0, 0.35),
    "content.intensity": _range(0.0, 0.35),
    # The incident standard forbids global dimming/pumping.
    "post.vignette_strength": _range(0.0, 0.25),
    "post.sediment_strength": _range(0.0, 0.05),
    "post.master_opacity": _range(0.85, 1.0),
    # Traces may mark attention but cannot become a full-screen mask.
    "fb.trace_strength": _range(0.0, 0.25),
}


def clamp_reverie_live_uniforms(values: Mapping[str, object]) -> dict[str, object]:
    """Return ``values`` clipped to the live Reverie visual-surface contract."""

    out = dict(values)
    for key, bound in REVERIE_LIVE_UNIFORM_BOUNDS.items():
        if key in out:
            out[key] = bound.apply(out[key])
    return out


def reverie_uniform_bound_violations(values: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """Return keys whose values would be changed by the live uniform bounds."""

    bounded = clamp_reverie_live_uniforms(values)
    violations: dict[str, dict[str, object]] = {}
    for key, value in values.items():
        if key in bounded and bounded[key] != value:
            violations[key] = {"value": value, "bounded": bounded[key]}
    return violations


__all__ = [
    "REVERIE_LIVE_UNIFORM_BOUNDS",
    "UniformBound",
    "clamp_reverie_live_uniforms",
    "reverie_uniform_bound_violations",
]
