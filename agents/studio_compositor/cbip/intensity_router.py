"""CBIP intensity router — maps stimmung state to enhancement intensity.

Spec §6.1. Given a stimmung snapshot, returns the CBIP enhancement
intensity to use:

* ``FULL`` (1.0) — apply Family 2 (Poster Print: Kuwahara + Posterize)
* ``MID`` (0.5) — apply Family 1 only (Palette Lineage swatch overlay)
* ``OFF`` (0.0) — Phase 0 deterministic tint only (no enhancement)

The router is degradation-biased: when ``physiological_coherence`` falls
below the degraded threshold, force OFF regardless of stance — recognizability
trumps interesting-ness when the operator is under stress.

Pure logic: no I/O. Caller passes a dict of dimensions (typically read
from ``/dev/shm/hapax-stimmung/state.json``).

The override surface (``cbip.override``) takes precedence: when set to
0–100% via the Logos slider, the manual value wins over the stimmung-
derived default.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

# Below this physiological_coherence value, force OFF — operator is under
# enough stress that recognizability is more valuable than enhancement.
DEGRADED_COHERENCE_THRESHOLD = 0.30


class CbipIntensity(StrEnum):
    """Three levels of CBIP enhancement applied to platter imagery."""

    OFF = "off"
    MID = "mid"
    FULL = "full"


# Stance → intensity mapping. Per the spec, NOMINAL and SEEKING get full
# enhancement; CAUTIOUS gets mid; DEGRADED and CRITICAL get OFF.
_STANCE_INTENSITY: dict[str, CbipIntensity] = {
    "nominal": CbipIntensity.FULL,
    "seeking": CbipIntensity.FULL,
    "cautious": CbipIntensity.MID,
    "degraded": CbipIntensity.OFF,
    "critical": CbipIntensity.OFF,
}


def _coerce_float(value: Any, default: float) -> float:
    """Read a numeric field from a stimmung dimension dict."""
    if isinstance(value, dict):
        value = value.get("value", default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def intensity_for_stimmung(stimmung: dict[str, Any]) -> CbipIntensity:
    """Derive a default CBIP intensity from a stimmung snapshot.

    Reads:
    * ``overall_stance`` — the worst non-stale dimension (StrEnum value)
    * ``physiological_coherence`` — degradation gate

    Unknown stance falls back to MID (conservative middle ground).
    """
    coherence = _coerce_float(stimmung.get("physiological_coherence"), 1.0)
    if coherence < DEGRADED_COHERENCE_THRESHOLD:
        return CbipIntensity.OFF

    stance_raw = stimmung.get("overall_stance")
    if isinstance(stance_raw, dict):
        stance_raw = stance_raw.get("value")
    stance = str(stance_raw).lower() if stance_raw is not None else ""
    return _STANCE_INTENSITY.get(stance, CbipIntensity.MID)


def resolve_effective_intensity(
    stimmung: dict[str, Any],
    *,
    override: float | None = None,
) -> CbipIntensity:
    """Combine stimmung default with operator override.

    ``override``: ``None`` means "auto" (use stimmung). A value in
    ``[0.0, 1.0]`` overrides the stimmung-derived intensity:
    * < 0.25 → OFF
    * < 0.75 → MID
    * ≥ 0.75 → FULL

    Out-of-band overrides (negative or > 1.0) are clamped to the valid
    range before bucketing.
    """
    if override is None:
        return intensity_for_stimmung(stimmung)
    clamped = max(0.0, min(1.0, override))
    if clamped < 0.25:
        return CbipIntensity.OFF
    if clamped < 0.75:
        return CbipIntensity.MID
    return CbipIntensity.FULL
