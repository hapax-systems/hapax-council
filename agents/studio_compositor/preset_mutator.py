"""Preset parametric mutation — Phase 1 of the preset variety expansion epic.

Applies bounded numeric jitter to a preset graph's parameters so that
identical stance ticks don't always produce identical visual output.
Family entropy rises from ``log2(family_size)`` toward
``log2(family_size) + log2(N_perceptual)`` where ``N_perceptual`` is the
number of perceptually-distinguishable renditions of the same base
preset (empirically ~8-16 at 30% variance; was ~4-8 at the prior 15%
default before the 2026-05-03 visual-monoculture rebalance).

**Structure preservation invariant.** The mutator MUST NOT add, remove,
rename, or rewire nodes or edges. Only numeric leaf values inside
``nodes[*].params`` (and ``passes[*].params`` for the alternate preset
shape used by Reverie) change. Strings, enums, booleans, lists, and the
graph topology are copied through untouched.

Phase 2 (temporal modulation) and Phase 3 (multi-family fan-out) live
downstream of this module — see
``docs/superpowers/specs/2026-04-18-preset-variety-expansion-design.md``.
"""

from __future__ import annotations

import copy
import logging
import os
from random import Random
from typing import Any

log = logging.getLogger(__name__)

# Wider per-instance jitter (was 0.15 → now 0.30) per the researcher
# visual-monoculture audit (2026-05-03). 0.15 was empirically too narrow
# to produce visibly distinct renditions of the same base preset, so
# the same preset within the same family read as one repeated frame.
# 0.30 roughly doubles the perceptually-distinguishable rendition
# count per base preset (~4–8 at 0.15 → ~8–16 at 0.30) and pairs with
# the family-weight rebalance in `shared/visual_mode_bias.py` to break
# up the visual monoculture without preset-corpus changes.
DEFAULT_VARIANCE = 0.30
FEATURE_FLAG_ENV = "HAPAX_PRESET_VARIETY_ACTIVE"


def variety_enabled() -> bool:
    """Return True when parametric mutation should run (default ON).

    Controlled by the ``HAPAX_PRESET_VARIETY_ACTIVE`` environment
    variable. Any value in ``{"0", "false", "no", "off"}`` (case-
    insensitive) disables mutation; unset or anything else enables it.
    This lets the operator kill the mutator at runtime without a
    redeploy when a preset renders poorly under jitter.
    """
    raw = os.environ.get(FEATURE_FLAG_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _jitter_numeric(
    value: int | float,
    rng: Random,
    variance: float,
) -> int | float:
    """Apply symmetric multiplicative jitter within ``[-variance, +variance]``.

    Uses ``rng.uniform`` rather than a Gaussian to keep output bounded
    without clipping artifacts. Booleans are rejected by the caller
    (``isinstance(bool)`` check) — Python's ``bool`` subclasses ``int``
    and would otherwise get jittered into numeric noise.

    Integer inputs return integers (rounded). Float inputs return floats.
    Zero-valued inputs are left untouched — multiplicative jitter on
    zero produces zero, which is aesthetically correct (a disabled knob
    stays disabled) and matches operator expectation that zero means
    "off".
    """
    if value == 0:
        return value
    factor = 1.0 + rng.uniform(-variance, variance)
    jittered = value * factor
    if isinstance(value, int):
        return int(round(jittered))
    return jittered


def _mutate_params(
    params: dict[str, Any],
    rng: Random,
    variance: float,
) -> dict[str, Any]:
    """Return a new params dict with numeric leaves jittered.

    Non-numeric values (strings for enums, lists, nested dicts, bools,
    ``None``) pass through unchanged. Nested dicts recurse; nested lists
    are copied shallowly (list-of-numbers jitter is not in Phase 1 scope
    because no current preset shape uses numeric lists as tunable
    params).
    """
    out: dict[str, Any] = {}
    for key, val in params.items():
        if isinstance(val, bool):
            out[key] = val
        elif isinstance(val, (int, float)):
            out[key] = _jitter_numeric(val, rng, variance)
        elif isinstance(val, dict):
            out[key] = _mutate_params(val, rng, variance)
        else:
            out[key] = copy.deepcopy(val)
    return out


def mutate_preset(
    preset: dict[str, Any],
    rng: Random | None = None,
    variance: float = DEFAULT_VARIANCE,
    *,
    seed: int | None = None,
) -> dict[str, Any]:
    """Return a new preset dict with numeric params jittered by ``variance``.

    Parameters
    ----------
    preset
        Preset graph dict as loaded from ``presets/*.json``. Expected
        shape: ``{"nodes": {name: {"type": ..., "params": {...}}}, "edges": [...], ...}``.
        Alternate shape supported: ``{"passes": [{"params": {...}}, ...]}``
        (used by the Reverie vocabulary plan and the effect-graph v2
        plan schema).
    rng
        Optional pre-seeded ``random.Random`` instance. Callers that
        want deterministic mutation for a given stance tick should pass
        ``Random(stance_tick)`` (or use the ``seed`` kwarg).
    variance
        Maximum fractional deviation per numeric param. Default 0.15
        per spec §3. Values outside ``[0, 1]`` are clamped.
    seed
        Convenience kwarg: if ``rng`` is None and ``seed`` is set, a
        new ``Random(seed)`` is constructed. If both are None, a fresh
        ``Random()`` is used (non-deterministic).

    Returns
    -------
    dict
        A NEW preset dict. The input is not mutated in place. Graph
        structure (nodes, edges, topology, modulations) is preserved;
        only numeric leaves inside ``params`` change.
    """
    if rng is None:
        rng = Random(seed) if seed is not None else Random()
    variance = max(0.0, min(1.0, variance))

    out = copy.deepcopy(preset)

    nodes = out.get("nodes")
    if isinstance(nodes, dict):
        for node in nodes.values():
            if not isinstance(node, dict):
                continue
            params = node.get("params")
            if isinstance(params, dict):
                node["params"] = _mutate_params(params, rng, variance)

    passes = out.get("passes")
    if isinstance(passes, list):
        for pass_def in passes:
            if not isinstance(pass_def, dict):
                continue
            params = pass_def.get("params")
            if isinstance(params, dict):
                pass_def["params"] = _mutate_params(params, rng, variance)

    return out


__all__ = [
    "DEFAULT_VARIANCE",
    "FEATURE_FLAG_ENV",
    "mutate_preset",
    "variety_enabled",
]
