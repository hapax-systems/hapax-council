"""Constrained parameter drift engine — continuous parametric surface evolution.

Replaces discrete preset switching with exponential convergence toward
attractor points in parameter space.  Each shader slot maintains a
drifting baseline that evolves toward a target state at a rate governed
by stimmung stance and energy level.

Architecture::

    effective_param = drifting_baseline + modulator_delta

The drifting baseline moves continuously (this module); the modulator
applies reactive audio deltas on top (``UniformModulator``).

Key parameters:
- τ (tau): time constant for exponential convergence.
  At τ=5s, params reach 63% of target in 5s, 95% in 15s.
  Governed by stimmung stance.
- σ (sigma): random walk magnitude per √second.
  Adds organic variation so the surface never fully settles.
"""

from __future__ import annotations

import logging
import math
import os
import random
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Environment variables for live tuning
_TAU_ENV = "HAPAX_DRIFT_TAU_S"
_SIGMA_ENV = "HAPAX_DRIFT_SIGMA"

# Default drift parameters
DEFAULT_TAU_S: float = 8.0
"""Default time constant (seconds).  63% convergence in τ seconds."""

DEFAULT_SIGMA: float = 0.003
"""Default random walk magnitude per √second.  0.3% of param range."""

# Stance-dependent τ multipliers
STANCE_TAU_MULTIPLIER: dict[str, float] = {
    "nominal": 1.0,
    "cautious": 2.5,
    "degraded": 6.0,
    "critical": 10.0,
}

# Params that should never drift (set by the render loop, not presets)
_EXCLUDED_PARAMS: frozenset[str] = frozenset({
    "time", "width", "height",
})


def _read_tau() -> float:
    raw = os.environ.get(_TAU_ENV)
    if raw is None:
        return DEFAULT_TAU_S
    try:
        return max(0.5, float(raw))
    except ValueError:
        return DEFAULT_TAU_S


def _read_sigma() -> float:
    raw = os.environ.get(_SIGMA_ENV)
    if raw is None:
        return DEFAULT_SIGMA
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_SIGMA


@dataclass
class SlotDriftState:
    """Per-slot drift state."""

    node_type: str | None = None
    current: dict[str, float] = field(default_factory=dict)
    target: dict[str, float] = field(default_factory=dict)
    # Parameter bounds from the shader registry
    bounds: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass
class ParameterDriftState:
    """Full drift state across all slots."""

    slots: list[SlotDriftState] = field(default_factory=list)
    rng: random.Random = field(default_factory=lambda: random.Random())
    initialized: bool = False


def init_drift_state(num_slots: int) -> ParameterDriftState:
    """Create a fresh drift state for N slots."""
    return ParameterDriftState(
        slots=[SlotDriftState() for _ in range(num_slots)],
    )


def snapshot_current_state(
    state: ParameterDriftState,
    slot_assignments: list[str | None],
    slot_base_params: list[dict],
    registry: object | None = None,
) -> None:
    """Capture the current slot pipeline state as the drift baseline.

    Called once after the first preset load to seed the drift engine
    with the current visual state.  After this, the drift engine owns
    the baseline and evolves it continuously.
    """
    for i, slot in enumerate(state.slots):
        if i >= len(slot_assignments):
            break
        slot.node_type = slot_assignments[i]
        if i < len(slot_base_params):
            slot.current = {
                k: v for k, v in slot_base_params[i].items()
                if isinstance(v, (int, float)) and k not in _EXCLUDED_PARAMS
            }
            slot.target = dict(slot.current)

        # Extract bounds from registry
        if registry is not None and slot.node_type is not None:
            try:
                defn = registry.get(slot.node_type)
                if defn:
                    for pname, pdef in defn.params.items():
                        lo = float(pdef.min) if pdef.min is not None else -100.0
                        hi = float(pdef.max) if pdef.max is not None else 100.0
                        slot.bounds[pname] = (lo, hi)
            except Exception:
                pass

    state.initialized = True
    log.info(
        "drift: initialized %d slots from current pipeline state",
        sum(1 for s in state.slots if s.node_type is not None),
    )


def set_drift_target(
    state: ParameterDriftState,
    slot_idx: int,
    node_type: str,
    target_params: dict[str, float],
) -> bool:
    """Set the attractor point for a slot.

    Returns True if the slot's node_type matches (param interpolation
    will work), False if topology differs (hard swap needed).
    """
    if slot_idx >= len(state.slots):
        return False
    slot = state.slots[slot_idx]
    if slot.node_type != node_type:
        return False
    # Update target, keeping only numeric params
    slot.target = {
        k: v for k, v in target_params.items()
        if isinstance(v, (int, float)) and k not in _EXCLUDED_PARAMS
    }
    return True


def drift_tick(
    state: ParameterDriftState,
    dt: float,
    stance: str = "nominal",
) -> dict[int, dict[str, float]]:
    """Advance all slot params toward their targets.

    Returns a dict of {slot_idx: {param: new_value}} for slots that
    changed.  Only returns slots with actual numeric changes to avoid
    unnecessary pipeline updates.

    Args:
        state: The drift state to advance.
        dt: Time delta in seconds since last tick.
        stance: Stimmung stance for τ scaling.
    """
    if not state.initialized or dt <= 0:
        return {}

    tau = _read_tau() * STANCE_TAU_MULTIPLIER.get(stance, 1.0)
    sigma = _read_sigma()
    # Exponential convergence factor: how much of the gap to close this tick
    alpha = 1.0 - math.exp(-dt / tau) if tau > 0 else 1.0

    updates: dict[int, dict[str, float]] = {}

    for i, slot in enumerate(state.slots):
        if slot.node_type is None:
            continue
        if not slot.target and not slot.current:
            continue

        changed = {}
        all_keys = set(slot.current) | set(slot.target)

        for key in all_keys:
            if key in _EXCLUDED_PARAMS:
                continue

            cur = slot.current.get(key)
            tgt = slot.target.get(key)

            if cur is None and tgt is not None:
                # New param — jump to target
                slot.current[key] = tgt
                changed[key] = tgt
                continue
            if cur is not None and tgt is None:
                # Param no longer in target — keep current, drift will
                # naturally stop since there's no attractor
                continue

            # Exponential convergence
            new_val = cur + (tgt - cur) * alpha

            # Random walk component for organic variation
            if sigma > 0:
                lo, hi = slot.bounds.get(key, (-100.0, 100.0))
                param_range = max(hi - lo, 0.01)
                noise = state.rng.gauss(0, sigma * param_range * math.sqrt(dt))
                new_val += noise

            # Clamp to bounds
            if key in slot.bounds:
                lo, hi = slot.bounds[key]
                new_val = max(lo, min(hi, new_val))

            # Only update if the change is perceptible
            if abs(new_val - cur) > 1e-6:
                slot.current[key] = new_val
                changed[key] = new_val

        if changed:
            updates[i] = changed

    return updates
