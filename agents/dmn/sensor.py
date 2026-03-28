"""DMN sensor reader — reads perception, stimmung, fortress, and watch state.

All reads are non-blocking JSON polls from /dev/shm. Returns structured
dicts suitable for DMN pulse consumption. Never writes to any source.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("dmn.sensor")

# Sensor file locations
STIMMUNG_STATE = Path("/dev/shm/hapax-stimmung/state.json")
FORTRESS_STATE = Path("/dev/shm/hapax-df/state.json")
WATCH_DIR = Path.home() / "hapax-state" / "watch"
VOICE_PERCEPTION = Path("/dev/shm/hapax-voice/perception-state.json")

# Staleness threshold — sensors older than this are marked stale
STALE_THRESHOLD_S = 30.0


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


def read_perception() -> dict:
    """Read visual layer perception state."""
    data = _read_json(VOICE_PERCEPTION) or {}
    age = _age_s(VOICE_PERCEPTION)
    return {
        "source": "perception",
        "age_s": round(age, 1),
        "stale": age > STALE_THRESHOLD_S,
        "flow_score": data.get("flow_score", 0.0),
        "activity": data.get("activity", "unknown"),
        "audio_energy": data.get("audio_energy", 0.0),
        "presence": data.get("presence", "unknown"),
    }


def read_stimmung() -> dict:
    """Read system stimmung state."""
    data = _read_json(STIMMUNG_STATE)
    if not data:
        return {"source": "stimmung", "age_s": float("inf"), "stale": True, "stance": "unknown"}
    age = _age_s(STIMMUNG_STATE)
    return {
        "source": "stimmung",
        "age_s": round(age, 1),
        "stale": age > STALE_THRESHOLD_S,
        "stance": data.get("overall_stance", "nominal"),
        "operator_stress": data.get("operator_stress", {}).get("value", 0.0),
        "error_rate": data.get("error_rate", {}).get("value", 0.0),
        "grounding_quality": data.get("grounding_quality", {}).get("value", 0.0),
    }


def read_fortress() -> dict | None:
    """Read fortress state. Returns None if DF is not running."""
    data = _read_json(FORTRESS_STATE)
    if not data:
        return None
    age = _age_s(FORTRESS_STATE)
    return {
        "source": "fortress",
        "age_s": round(age, 1),
        "stale": age > STALE_THRESHOLD_S,
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


def read_watch() -> dict:
    """Read watch biometric state."""
    hr_data = _read_json(WATCH_DIR / "heartrate.json")
    age = _age_s(WATCH_DIR / "heartrate.json")
    return {
        "source": "watch",
        "age_s": round(age, 1),
        "stale": age > 600.0,  # watch data stales at 10 min
        "heart_rate": hr_data.get("current", {}).get("bpm", 0) if hr_data else 0,
    }


VISUAL_SURFACE_FRAME = Path("/dev/shm/hapax-visual/frame.jpg")
IMAGINATION_CURRENT = Path("/dev/shm/hapax-imagination/current.json")


def read_visual_surface(
    frame_path: Path | None = None,
    imagination_path: Path | None = None,
) -> dict:
    """Read visual surface state (frame age + current imagination fragment)."""
    fp = frame_path or VISUAL_SURFACE_FRAME
    ip = imagination_path or IMAGINATION_CURRENT
    frame_age = _age_s(fp)
    imagination_data = _read_json(ip) or {}
    return {
        "source": "visual_surface",
        "age_s": round(frame_age, 1),
        "stale": frame_age > STALE_THRESHOLD_S,
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


def read_all() -> dict:
    """Read all sensor sources. Returns a unified snapshot."""
    return {
        "timestamp": time.time(),
        "perception": read_perception(),
        "stimmung": read_stimmung(),
        "fortress": read_fortress(),
        "watch": read_watch(),
        "visual_surface": read_visual_surface(),
        "sensors": read_sensors(),
    }
