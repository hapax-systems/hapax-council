"""DMN sensor reader — reads perception, stimmung, fortress, and watch state.

All reads are non-blocking JSON polls from /dev/shm. Returns structured
dicts suitable for DMN pulse consumption. Never writes to any source.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("dmn.sensor")


@dataclass(frozen=True)
class SensorConfig:
    """Configurable sensor paths. Defaults match production /dev/shm layout."""

    stimmung_state: Path = Path("/dev/shm/hapax-stimmung/state.json")
    fortress_state: Path = Path("/dev/shm/hapax-df/state.json")
    watch_dir: Path = Path.home() / "hapax-state" / "watch"
    voice_perception: Path = Path("/dev/shm/hapax-daimonion/perception-state.json")
    visual_frame: Path = Path("/dev/shm/hapax-visual/frame.jpg")
    imagination_current: Path = Path("/dev/shm/hapax-imagination/current.json")
    stale_threshold_s: float = 30.0


_DEFAULT_CONFIG = SensorConfig()


def _read_json(path: Path) -> dict | None:
    """Read a JSON file, return None on any failure."""
    try:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return None
        return json.loads(text)
    except (OSError, json.JSONDecodeError):
        return None


def _age_s(path: Path) -> float:
    """Seconds since file was last modified. Returns inf if missing."""
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return float("inf")


def read_perception(config: SensorConfig | None = None) -> dict:
    """Read visual layer perception state."""
    cfg = config or _DEFAULT_CONFIG
    data = _read_json(cfg.voice_perception) or {}
    age = _age_s(cfg.voice_perception)
    return {
        "source": "perception",
        "age_s": round(age, 1),
        "stale": age > cfg.stale_threshold_s,
        "flow_score": data.get("flow_score", 0.0),
        "activity": data.get("activity", "unknown"),
        "audio_energy": data.get("audio_energy", 0.0),
        "presence": data.get("presence", "unknown"),
    }


def read_stimmung(config: SensorConfig | None = None) -> dict:
    """Read system stimmung state."""
    cfg = config or _DEFAULT_CONFIG
    data = _read_json(cfg.stimmung_state)
    if not data:
        return {"source": "stimmung", "age_s": float("inf"), "stale": True, "stance": "unknown"}
    age = _age_s(cfg.stimmung_state)
    return {
        "source": "stimmung",
        "age_s": round(age, 1),
        "stale": age > cfg.stale_threshold_s,
        "stance": data.get("overall_stance", "nominal"),
        "operator_stress": data.get("operator_stress", {}).get("value", 0.0),
        "error_rate": data.get("error_rate", {}).get("value", 0.0),
        "grounding_quality": data.get("grounding_quality", {}).get("value", 0.0),
    }


def read_fortress(config: SensorConfig | None = None) -> dict | None:
    """Read fortress state. Returns None if DF is not running."""
    cfg = config or _DEFAULT_CONFIG
    data = _read_json(cfg.fortress_state)
    if not data:
        return None
    age = _age_s(cfg.fortress_state)
    return {
        "source": "fortress",
        "age_s": round(age, 1),
        "stale": age > cfg.stale_threshold_s,
        "fortress_name": data.get("fortress_name", ""),
        "population": data.get("population", 0),
        "food": data.get("food_count", 0),
        "drink": data.get("drink_count", 0),
        "threats": data.get("active_threats", 0),
        "idle": data.get("idle_dwarf_count", 0),
        "jobs": data.get("job_queue_length", 0),
        "stress": data.get("most_stressed_value", 0),
        "year": data.get("year", 0),
        "season": data.get("season", 0),
        "day": data.get("day", 0),
    }


def read_watch(config: SensorConfig | None = None) -> dict:
    """Read watch biometric state."""
    cfg = config or _DEFAULT_CONFIG
    hr_data = _read_json(cfg.watch_dir / "heartrate.json")
    age = _age_s(cfg.watch_dir / "heartrate.json")
    return {
        "source": "watch",
        "age_s": round(age, 1),
        "stale": age > 600.0,  # watch data stales at 10 min
        "heart_rate": hr_data.get("current", {}).get("bpm", 0) if hr_data else 0,
    }


def read_visual_surface(
    frame_path: Path | None = None,
    imagination_path: Path | None = None,
) -> dict:
    """Read visual surface state (frame age + current imagination fragment)."""
    fp = frame_path or _DEFAULT_CONFIG.visual_frame
    ip = imagination_path or _DEFAULT_CONFIG.imagination_current
    frame_age = _age_s(fp)
    imagination_data = _read_json(ip) or {}
    return {
        "source": "visual_surface",
        "age_s": round(frame_age, 1),
        "stale": frame_age > _DEFAULT_CONFIG.stale_threshold_s,
        "frame_path": str(fp) if fp.exists() else None,
        "imagination_fragment_id": imagination_data.get("id"),
    }


def read_sensors() -> dict[str, dict]:
    """Read all /dev/shm/hapax-sensors/ state files.

    Returns dict of {sensor_name: state_dict} for sensors that have
    written state snapshots. Empty dict if no sensors have reported.
    """
    sensor_dir = Path("/dev/shm/hapax-sensors")
    if not sensor_dir.exists():
        return {}
    result = {}
    for f in sensor_dir.glob("*.json"):
        data = _read_json(f)
        if data:
            result[f.stem] = data
    return result


def read_all(config: SensorConfig | None = None) -> dict:
    """Read all sensor sources. Returns a unified snapshot."""
    return {
        "timestamp": time.time(),
        "perception": read_perception(config),
        "stimmung": read_stimmung(config),
        "fortress": read_fortress(config),
        "watch": read_watch(config),
        "visual_surface": read_visual_surface(),
        "sensors": read_sensors(),
    }
