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

from shared.governance.consent_label import ConsentLabel
from shared.labeled_trace import write_labeled_trace

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
    except (OSError, json.JSONDecodeError) as exc:
        log.debug("Failed to read %s: %s", path, exc)
        return None


def _age_s(path: Path) -> float:
    """Seconds since file was last modified. Returns inf if missing."""
    try:
        return time.time() - path.stat().st_mtime
    except OSError as exc:
        log.debug("Failed to stat %s: %s", path, exc)
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
        "imagination_narrative": imagination_data.get("narrative", ""),
        "imagination_salience": float(imagination_data.get("salience", 0.0)),
        "imagination_material": imagination_data.get("material", "void"),
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
        if f.name == "snapshot.json":
            continue  # skip our own output to prevent recursive nesting
        data = _read_json(f)
        if data:
            result[f.stem] = data
    return result


SNAPSHOT_PATH = Path("/dev/shm/hapax-sensors/snapshot.json")


def publish_snapshot(snapshot: dict, *, path: Path = SNAPSHOT_PATH) -> None:
    """Write sensor snapshot atomically to /dev/shm for cross-daemon consumption."""
    enriched = {**snapshot, "published_at": time.time()}
    write_labeled_trace(path, enriched, ConsentLabel.bottom())


def read_all(config: SensorConfig | None = None) -> dict:
    """Read all sensor sources. Returns a unified snapshot.

    The ``perceptual_field`` key carries the full structured PerceptualField
    Pydantic dump — every typed sub-field aggregated by
    ``shared.perceptual_field.build_perceptual_field`` (audio, visual, ir,
    album, chat, context, stimmung, presence, stream_health, tendency,
    homage, camera_classifications). The imagination loop's
    ``assemble_context`` widens its narrative prompt by embedding this
    block so the cosine-similarity recruitment query stops being born from
    a 4-key text snippet (meta-architectural Bayesian audit Fix #2,
    2026-05-03 — the fix that closes the "imagination-narrative born from
    8 scalars" bottleneck).

    The legacy slim keys (``perception`` / ``stimmung`` / ``watch`` /
    ``visual_surface`` / ``sensors`` / ``time`` / ``music`` / ``goals`` /
    ``fortress``) remain for backwards compatibility — chronicle,
    exploration, and the imagination context's legacy sections continue
    to read them. The PerceptualField build is wrapped so any sub-read
    failure degrades to an absent ``perceptual_field`` key, signalling
    "fall back to slim layout only" to ``assemble_context``.
    """
    result: dict = {
        "timestamp": time.time(),
        "perception": read_perception(config),
        "stimmung": read_stimmung(config),
        "fortress": read_fortress(config),
        "watch": read_watch(config),
        "visual_surface": read_visual_surface(),
        "sensors": read_sensors(),
    }

    # Full PerceptualField — 13 typed sub-fields aggregated from every
    # classifier/detector in the system. The director already reads this
    # via ``shared.perceptual_field.build_perceptual_field``; widening the
    # imagination snapshot to include it lets the imagination-narrative
    # recruitment cosine-similarity query draw from the same rich surface.
    # ``exclude_none=True`` drops null fields so the published payload
    # tracks the director's prompt-rendering convention. Failure is
    # non-fatal: a missing ``perceptual_field`` key signals "fall back to
    # the legacy slim layout" to ``assemble_context``.
    try:
        from shared.perceptual_field import build_perceptual_field

        pfield = build_perceptual_field()
        result["perceptual_field"] = pfield.model_dump(exclude_none=True)
    except Exception:
        log.debug("PerceptualField build failed — slim sensor snapshot only", exc_info=True)

    # Promote key sensors to top-level for imagination context
    sensors_dict = result.get("sensors", {})
    if "weather" in sensors_dict:
        result["weather"] = sensors_dict["weather"]

    # Time context (always available, no external dependency)
    now = time.localtime()
    result["time"] = {
        "hour": now.tm_hour,
        "minute": now.tm_min,
        "period": (
            "morning"
            if now.tm_hour < 12
            else "afternoon"
            if now.tm_hour < 17
            else "evening"
            if now.tm_hour < 21
            else "night"
        ),
        "weekday": time.strftime("%A"),
        "date": time.strftime("%Y-%m-%d"),
    }

    # Music context from perception activity
    perc = result.get("perception", {})
    if perc.get("activity") in ("making_music", "listening"):
        result["music"] = {
            "genre": perc.get("music_genre", "unknown"),
            "mixer_energy": perc.get("mixer_energy"),
        }

    # Goals from sprint sensor
    if "sprint" in sensors_dict:
        sprint_data = sensors_dict["sprint"]
        result["goals"] = {
            "active_count": sprint_data.get("active_measures", 0),
            "stale_count": sprint_data.get("stale_measures", 0),
            "top_domain": sprint_data.get("top_domain", "unknown"),
        }

    return result
