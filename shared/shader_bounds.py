"""Per-shader-family maximum-intensity bounds loader + clamp helper.

Implements Phase 1 of the pixel-sort intensity cap amendment
(`docs/superpowers/amendments/2026-04-21-pixel-sort-intensity-cap.md`).

The bounds file lives at `presets/shader_intensity_bounds.json` and
declares the maximum strength and spatial-coverage fraction for each
shader family. This module exposes:

- :func:`load_bounds` — reads + caches the JSON file; returns a typed
  dataclass mapping node_type → cap entry
- :func:`clamp_params` — given a ``node_type`` and a uniforms dict,
  returns ``(clamped, was_clamped)``. Never raises; missing bounds
  (unknown node_type, bounds file missing) return input unchanged.

Callers (the WGSL compiler in Phase 1, the ward stimmung modulator in
Phase 2) use the return tuple to decide whether to emit a WARNING log.

The spatial-coverage bound is stored for Phase 2 (runtime GPU-side
coverage gate); the compile-time path enforces only ``max_strength``
scaled across the caller-declared parameter names.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

_BOUNDS_PATH = Path(__file__).parent.parent / "presets" / "shader_intensity_bounds.json"


@dataclass(frozen=True)
class NodeCap:
    """Per-shader-family intensity cap."""

    node_type: str
    max_strength: float
    spatial_coverage_max_pct: float
    clamp_params: tuple[str, ...] = field(default_factory=tuple)


@lru_cache(maxsize=1)
def load_bounds(path: Path | None = None) -> dict[str, NodeCap]:
    """Load + cache per-shader bounds.

    Returns empty dict if the file is missing or malformed — callers
    fall back to no clamping, which preserves existing behavior.
    Cache cleared on first call with a different path (tests).
    """
    bounds_path = path or _BOUNDS_PATH
    try:
        raw = json.loads(bounds_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.debug("shader_bounds: %s not present; clamp is no-op", bounds_path)
        return {}
    except json.JSONDecodeError as e:
        log.warning("shader_bounds: %s parse error — clamp disabled: %s", bounds_path, e)
        return {}

    out: dict[str, NodeCap] = {}
    for node_type, entry in raw.get("node_caps", {}).items():
        if not isinstance(entry, dict):
            continue
        out[node_type] = NodeCap(
            node_type=node_type,
            max_strength=float(entry.get("max_strength", 1.0)),
            spatial_coverage_max_pct=float(entry.get("spatial_coverage_max_pct", 1.0)),
            clamp_params=tuple(entry.get("clamp_params", []) or []),
        )
    return out


def clamp_params(
    node_type: str,
    uniforms: dict[str, float],
    *,
    bounds: dict[str, NodeCap] | None = None,
) -> tuple[dict[str, float], bool]:
    """Apply per-family cap to uniforms. Return (clamped, was_clamped_flag).

    The cap is applied to each parameter name in ``cap.clamp_params``
    (case-sensitive match), clipped at ``cap.max_strength``. Parameters
    not in ``clamp_params`` pass through untouched. Unknown node types
    (no cap entry) return the input dict unchanged.

    Never mutates the input; returns a new dict when clamping fires,
    or the input dict when no clamp was needed (identity preserved so
    callers can skip log spam on the hot path).
    """
    table = bounds if bounds is not None else load_bounds()
    cap = table.get(node_type)
    if cap is None or not cap.clamp_params:
        return uniforms, False

    out = dict(uniforms)
    clamped = False
    for key in cap.clamp_params:
        if key in out and isinstance(out[key], (int, float)):
            original = float(out[key])
            if original > cap.max_strength:
                out[key] = cap.max_strength
                clamped = True
                log.warning(
                    "shader_bounds: clamped %s.%s %.3f → %.3f",
                    node_type,
                    key,
                    original,
                    cap.max_strength,
                )
    return (out, True) if clamped else (uniforms, False)
