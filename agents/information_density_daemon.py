"""Information Density Daemon — reads perceptual sources, computes density field.

Runs as a systemd service. Reads from existing SHM files and perception
state, feeds the InformationDensityField, and writes the aggregate to
/dev/shm/hapax-density-field/state.json every tick.

Every source participates. Sources are auto-discovered from SHM paths.
New sources can be added by appending to SOURCE_REGISTRY.
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Any

from shared.information_density import InformationDensityField

log = logging.getLogger(__name__)

TICK_INTERVAL_S = 0.5


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _extract_float(data: dict[str, Any] | None, *keys: str, default: float = 0.0) -> float:
    if data is None:
        return default
    for key in keys:
        val = data.get(key)
        if isinstance(val, (int, float)) and math.isfinite(val):
            return float(val)
    return default


SOURCE_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "audio.broadcast_rms",
        "shm": "/dev/shm/hapax-audio-self-perception/state.json",
        "keys": ["rms", "rms_dbfs"],
        "obs_min": -60.0,
        "obs_max": 0.0,
    },
    {
        "id": "audio.spectral_centroid",
        "shm": "/dev/shm/hapax-audio-self-perception/state.json",
        "keys": ["spectral_centroid"],
        "obs_min": 0.0,
        "obs_max": 8000.0,
    },
    {
        "id": "perception.presence",
        "shm": "/dev/shm/hapax-daimonion/perception-fused.json",
        "keys": ["presence_probability", "presence_score"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "perception.vad_confidence",
        "shm": "/dev/shm/hapax-daimonion/perception-fused.json",
        "keys": ["vad_confidence"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "stimmung.health",
        "shm": "/dev/shm/hapax-stimmung/state.json",
        "keys": ["health"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "stimmung.exploration_deficit",
        "shm": "/dev/shm/hapax-stimmung/state.json",
        "keys": ["exploration_deficit"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "stimmung.operator_stress",
        "shm": "/dev/shm/hapax-stimmung/state.json",
        "keys": ["operator_stress"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "compositor.mood_valence",
        "shm": "/dev/shm/hapax-compositor/mood-state.json",
        "keys": ["valence", "mood_valence"],
        "obs_min": -1.0,
        "obs_max": 1.0,
    },
    {
        "id": "compositor.pace",
        "shm": "/dev/shm/hapax-compositor/pace-state.json",
        "keys": ["pace", "pace_value"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "mixer.energy",
        "shm": "/dev/shm/hapax-perception/audio.json",
        "keys": ["mixer_energy", "energy"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "mixer.beat",
        "shm": "/dev/shm/hapax-perception/audio.json",
        "keys": ["mixer_beat", "beat"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "desk.activity",
        "shm": "/dev/shm/hapax-perception/audio.json",
        "keys": ["desk_energy", "contact_energy"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "ir.motion_delta",
        "shm": "/dev/shm/hapax-perception/fused.json",
        "keys": ["ir_motion_delta"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
    {
        "id": "biometric.heart_rate",
        "shm": "/dev/shm/hapax-sensors/watch.json",
        "keys": ["heart_rate_bpm", "hr_bpm"],
        "obs_min": 40.0,
        "obs_max": 180.0,
    },
    {
        "id": "system.gpu_utilization",
        "shm": "/dev/shm/hapax-stimmung/state.json",
        "keys": ["resource_pressure"],
        "obs_min": 0.0,
        "obs_max": 1.0,
    },
]


def run_density_daemon() -> None:
    """Main loop — read sources, compute density, write SHM."""
    field = InformationDensityField()

    for src in SOURCE_REGISTRY:
        field.register_source(
            src["id"],
            obs_min=src.get("obs_min", -1.0),
            obs_max=src.get("obs_max", 1.0),
        )

    log.info("information_density_daemon: started with %d sources", len(SOURCE_REGISTRY))

    while True:
        try:
            for src in SOURCE_REGISTRY:
                shm_path = Path(src["shm"])
                data = _read_json(shm_path)
                value = _extract_float(data, *src["keys"])
                field.update(src["id"], value)

            field.write_shm()

            agg = field.aggregate_density()
            top = field.top_sources(3)
            if top and top[0].density > 0.5:
                log.debug(
                    "density tick: agg=%.3f top=%s(%.3f)",
                    agg,
                    top[0].source_id,
                    top[0].density,
                )
        except Exception:
            log.debug("density tick failed", exc_info=True)

        time.sleep(TICK_INTERVAL_S)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    run_density_daemon()
