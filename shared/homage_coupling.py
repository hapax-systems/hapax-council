"""HOMAGE Phase 6 — shader → ward reverse-path coupling payload.

Spec: `docs/superpowers/specs/2026-04-18-homage-framework-design.md` §4.6.

HOMAGE Phase 5 closed the forward path: the choreographer writes a
4-float payload into ``uniforms.custom[slot]`` so shaders can read
ward transition energy. Phase 6 closes the reverse path — the shader
substrate reports aggregate energy / drift back to the choreographer
via a small file-bus payload so ward pacing can respond to GPU state.

Publisher (not in this commit; follow-up): whoever computes shader
energy (Reverie mixer or a compositor-side shim) writes
``/dev/shm/hapax-compositor/homage-shader-reading.json``.

Consumer: the HOMAGE choreographer reads it every tick (missing file
is always valid — consumer falls back to pure timer pacing).

The payload is deliberately tiny: 3 scalars + timestamp. Keep it that
way. The reverse channel is a pacing nudge, not a second control
loop.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SHADER_READING_PATH: Path = Path("/dev/shm/hapax-compositor/homage-shader-reading.json")
"""Canonical file-bus location for shader → ward coupling payloads."""

SUBSTRATE_FRESH_MAX_AGE_S: float = 2.0
"""A reading older than this is treated as substrate-stale, not fresh."""


@dataclass(frozen=True, slots=True)
class ShaderCouplingReading:
    """Reverse-path payload: shader reports back to HOMAGE choreographer.

    All three scalars are clamped to ``[0.0, 1.0]`` at parse time so
    downstream code never needs to re-validate them. ``timestamp`` is
    seconds since the compositor monotonic clock epoch (same clock the
    choreographer uses).

    ``substrate_fresh`` is a cheap boolean hint from the publisher: it
    means "the Reverie frame I derived this from landed within the
    last ~2 s". The consumer additionally checks
    ``now - timestamp <= SUBSTRATE_FRESH_MAX_AGE_S`` so a stale-but-
    marked-fresh payload is still rejected.
    """

    timestamp: float
    shader_energy: float
    shader_drift: float
    substrate_fresh: bool

    def is_fresh(self, *, now: float) -> bool:
        """True iff the reading is within the freshness window AND the
        publisher also marked the substrate itself as fresh."""
        if not self.substrate_fresh:
            return False
        return (now - self.timestamp) <= SUBSTRATE_FRESH_MAX_AGE_S

    def to_dict(self) -> dict[str, float | bool]:
        return {
            "timestamp": self.timestamp,
            "shader_energy": self.shader_energy,
            "shader_drift": self.shader_drift,
            "substrate_fresh": self.substrate_fresh,
        }


def _clamp_unit(value: object) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    f = float(value)
    if f != f:  # NaN
        return None
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def parse_shader_reading(raw: object) -> ShaderCouplingReading | None:
    """Parse a raw JSON-decoded dict into a ``ShaderCouplingReading``.

    Returns ``None`` when the payload is malformed in any way. The
    consumer treats ``None`` identically to "file missing" — default
    timer pacing.
    """
    if not isinstance(raw, dict):
        return None
    timestamp = raw.get("timestamp")
    energy = _clamp_unit(raw.get("shader_energy"))
    drift = _clamp_unit(raw.get("shader_drift"))
    fresh = raw.get("substrate_fresh")
    if not isinstance(timestamp, (int, float)):
        return None
    if energy is None or drift is None:
        return None
    if not isinstance(fresh, bool):
        return None
    return ShaderCouplingReading(
        timestamp=float(timestamp),
        shader_energy=energy,
        shader_drift=drift,
        substrate_fresh=fresh,
    )


def read_shader_reading(path: Path = SHADER_READING_PATH) -> ShaderCouplingReading | None:
    """Read the reverse-path payload from ``path``.

    Missing file, unreadable file, and malformed content all collapse
    to ``None``. Callers never see an exception from this function.
    """
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.debug("homage-shader-reading.json unreadable", exc_info=True)
        return None
    return parse_shader_reading(data)


# ── Pacing modulation ──────────────────────────────────────────────────────

# Thresholds + multipliers are spec-driven and kept as module constants
# so tests can reference them without duplicating magic numbers.

HIGH_ENERGY_THRESHOLD: float = 0.75
"""Above this shader_energy, extend ward holds (let the shader breathe)."""

HIGH_DRIFT_THRESHOLD: float = 0.8
"""Above this shader_drift, shorten ward holds (break the feedback trance)."""

HOLD_EXTEND_MULTIPLIER: float = 1.20
"""+20% hold duration under high shader energy."""

HOLD_SHORTEN_MULTIPLIER: float = 0.85
"""-15% hold duration under high shader drift."""


def hold_multiplier(reading: ShaderCouplingReading | None, *, now: float) -> float:
    """Compute the pacing multiplier the choreographer applies to ward holds.

    Precedence: drift beats energy (drift breaks feedback lock-in,
    which is the priority failure mode). Stale / missing readings
    collapse to ``1.0`` (pure timer pacing).
    """
    if reading is None or not reading.is_fresh(now=now):
        return 1.0
    if reading.shader_drift > HIGH_DRIFT_THRESHOLD:
        return HOLD_SHORTEN_MULTIPLIER
    if reading.shader_energy > HIGH_ENERGY_THRESHOLD:
        return HOLD_EXTEND_MULTIPLIER
    return 1.0


__all__ = [
    "HIGH_DRIFT_THRESHOLD",
    "HIGH_ENERGY_THRESHOLD",
    "HOLD_EXTEND_MULTIPLIER",
    "HOLD_SHORTEN_MULTIPLIER",
    "SHADER_READING_PATH",
    "SUBSTRATE_FRESH_MAX_AGE_S",
    "ShaderCouplingReading",
    "hold_multiplier",
    "parse_shader_reading",
    "read_shader_reading",
]
