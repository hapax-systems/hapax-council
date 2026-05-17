"""Information density field compute module.

Computes per-source information density with three temporal modes:
- NEWS: signal just changed (high surprise)
- ROUTINE: expected staleness (stable, low surprise)
- ALARM: should have changed but didn't (absence is informative)

Writes state to /dev/shm/hapax-density-field/state.json for consumption
by the programme planner, director, and compositor.
"""

from __future__ import annotations

import time

_STANCE_DENSITY: dict[str, float] = {
    "nominal": 0.1,
    "seeking": 0.6,
    "cautious": 0.4,
    "degraded": 0.8,
    "critical": 1.0,
}

_PREVIOUS_VALUES: dict[str, float] = {}
_STALE_COUNTS: dict[str, int] = {}

# Number of consecutive identical ticks before ALARM fires
_ALARM_THRESHOLD: int = 10

# ALARM density — absence is informative, not empty
_ALARM_DENSITY: float = 0.7


def reset_state() -> None:
    """Reset all tracking state. Use in tests to avoid pollution."""
    _PREVIOUS_VALUES.clear()
    _STALE_COUNTS.clear()


def _change_density(key: str, current: float, threshold: float = 0.05) -> tuple[float, str]:
    """Compute change-based density and temporal mode for a signal."""
    prev = _PREVIOUS_VALUES.get(key, current)
    _PREVIOUS_VALUES[key] = current
    delta = abs(current - prev)

    if delta > threshold:
        # Signal changed — reset stale counter, mode is NEWS
        _STALE_COUNTS[key] = 0
        return min(1.0, delta / max(threshold * 10, 0.01)), "NEWS"

    # Signal didn't change — increment stale counter
    _STALE_COUNTS[key] = _STALE_COUNTS.get(key, 0) + 1

    if _STALE_COUNTS[key] >= _ALARM_THRESHOLD:
        # Stale beyond expected cadence — ALARM
        return _ALARM_DENSITY, "ALARM"

    return max(0.0, 1.0 - delta / max(threshold, 0.01)) * 0.1, "ROUTINE"


def compute_density_state(
    *,
    perception_data: dict[str, object],
    stimmung_stance: str,
    audio_energy: float,
    epoch: int = 0,
) -> dict[str, object]:
    """Compute the information density field state.

    Returns a dict with aggregate_density, dominant_zone, dominant_mode,
    and per-zone density/mode/top_signal.
    """
    presence = float(perception_data.get("presence_probability", 0.0) or 0.0)
    activity = str(perception_data.get("production_activity", "idle") or "idle")

    perc_density, perc_mode = _change_density("perception", presence)
    if activity != _PREVIOUS_VALUES.get("_last_activity", "idle"):
        perc_density = max(perc_density, 0.5)
        perc_mode = "NEWS"
        _STALE_COUNTS["perception"] = 0
    _PREVIOUS_VALUES["_last_activity"] = activity

    stimmung_density = _STANCE_DENSITY.get(stimmung_stance, 0.1)
    stim_prev = _PREVIOUS_VALUES.get("stimmung_stance_str", stimmung_stance)
    if stimmung_stance != stim_prev:
        stim_mode = "NEWS"
        _STALE_COUNTS["stimmung"] = 0
    else:
        _STALE_COUNTS["stimmung"] = _STALE_COUNTS.get("stimmung", 0) + 1
        if _STALE_COUNTS["stimmung"] >= _ALARM_THRESHOLD:
            stim_mode = "ALARM"
            stimmung_density = max(stimmung_density, _ALARM_DENSITY)
        else:
            stim_mode = "ROUTINE"
    _PREVIOUS_VALUES["stimmung_stance_str"] = stimmung_stance

    voice_density, voice_mode = _change_density("audio_energy", audio_energy, threshold=0.02)

    zones = {
        "perception": {
            "density": round(perc_density, 3),
            "mode": perc_mode,
            "top_signal": f"activity={activity} presence={presence:.2f}",
        },
        "stimmung": {
            "density": round(stimmung_density, 3),
            "mode": stim_mode,
            "top_signal": f"stance={stimmung_stance}",
        },
        "voice": {
            "density": round(voice_density, 3),
            "mode": voice_mode,
            "top_signal": f"audio_energy={audio_energy:.3f}",
        },
    }

    densities = [z["density"] for z in zones.values()]
    aggregate = sum(densities) / len(densities) if densities else 0.0
    dominant_zone = max(zones, key=lambda z: zones[z]["density"])
    dominant_mode = zones[dominant_zone]["mode"]

    return {
        "computed_at": time.time(),
        "epoch": epoch,
        "aggregate_density": round(aggregate, 3),
        "dominant_zone": dominant_zone,
        "dominant_mode": dominant_mode,
        "zones": zones,
    }
