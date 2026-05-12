"""Perception fusion layer — aggregate multi-source perception into a single snapshot.

Reads from three SHM sources on a 2s cadence and writes a unified
/dev/shm/hapax-perception/fused.json with per-source freshness tracking.
Designed to be the canonical perception read-point for segment prep and
any agent that needs a complete environmental picture.

Sources:
  1. Audio perception — /dev/shm/hapax-perception/audio.json
  2. IR fleet — /dev/shm/hapax-ir_perception/health.json + presence engine
  3. Compositor cameras — /dev/shm/hapax-compositor/camera-classifications.json

Run: ``uv run python -m agents.perception_fusion``
Systemd: ``systemd/units/hapax-perception-fusion.service``
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

TICK_INTERVAL_S: float = 2.0
SHM_OUT_DIR: Path = Path("/dev/shm/hapax-perception")
SHM_OUT_FILE: Path = SHM_OUT_DIR / "fused.json"

AUDIO_PATH: Path = Path("/dev/shm/hapax-perception/audio.json")
IR_HEALTH_PATH: Path = Path("/dev/shm/hapax-ir_perception/health.json")
CAMERA_PATH: Path = Path("/dev/shm/hapax-compositor/camera-classifications.json")
LAYOUT_MODE_PATH: Path = Path("/dev/shm/hapax-compositor/layout-mode.txt")
PRESENCE_PATH: Path = Path("/dev/shm/hapax-daimonion/consent-state.json")
STIMMUNG_PATH: Path = Path("/dev/shm/hapax-stimmung/state.json")

STALE_THRESHOLD_S: float = 30.0

_shutdown = False


def _handle_signal(signum: int, _frame: object) -> None:
    global _shutdown
    _shutdown = True
    log.info("Received signal %d, shutting down", signum)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _age_s(path: Path) -> float:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return float("inf")


def _read_audio() -> dict:
    data = _read_json(AUDIO_PATH)
    age = _age_s(AUDIO_PATH)
    if data is None:
        return {"available": False, "age_s": round(age, 1), "stale": True}
    return {
        "available": True,
        "age_s": round(age, 1),
        "stale": age > STALE_THRESHOLD_S,
        "is_speech": data.get("is_speech"),
        "music_playing": data.get("music_playing", False),
        "scene": data.get("scene", "unknown"),
        "confidence": data.get("confidence", 0.0),
        "genre": data.get("genre"),
        "bpm": data.get("bpm"),
        "key": data.get("key"),
        "speech_ratio": data.get("speech_ratio"),
        "vad_available": data.get("vad_available", False),
    }


def _read_ir() -> dict:
    health = _read_json(IR_HEALTH_PATH)
    age = _age_s(IR_HEALTH_PATH)
    if health is None:
        return {"available": False, "age_s": round(age, 1), "stale": True}
    ir_error = health.get("error", 0.0)
    return {
        "available": True,
        "age_s": round(age, 1),
        "stale": age > STALE_THRESHOLD_S,
        "fleet_healthy": ir_error < 0.5,
        "error": ir_error,
    }


def _read_cameras() -> dict:
    data = _read_json(CAMERA_PATH)
    age = _age_s(CAMERA_PATH)
    if data is None:
        return {"available": False, "age_s": round(age, 1), "stale": True}

    cameras: dict[str, dict] = {}
    operator_visible = False
    for cam_id, info in data.items():
        if not isinstance(info, dict):
            continue
        vis = info.get("operator_visible", False)
        cameras[cam_id] = {
            "role": info.get("semantic_role", "unknown"),
            "operator_visible": vis,
        }
        if vis:
            operator_visible = True

    layout_mode = "unknown"
    try:
        layout_mode = LAYOUT_MODE_PATH.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        pass

    return {
        "available": True,
        "age_s": round(age, 1),
        "stale": age > STALE_THRESHOLD_S,
        "camera_count": len(cameras),
        "cameras": cameras,
        "operator_visible": operator_visible,
        "layout_mode": layout_mode,
    }


def _derive_activity(audio: dict, cameras: dict) -> str:
    scene = audio.get("scene", "unknown")
    operator_visible = cameras.get("operator_visible", False)

    if scene == "speech" and operator_visible:
        return "speaking"
    if scene == "speech":
        return "speaking_off_camera"
    if audio.get("music_playing"):
        return "music"
    if scene == "typing":
        return "coding"
    if scene == "silence" and operator_visible:
        return "present_idle"
    if scene == "silence":
        return "away"
    return "active"


def _fuse() -> dict:
    audio = _read_audio()
    ir = _read_ir()
    cameras = _read_cameras()

    sources_available = sum(1 for src in (audio, ir, cameras) if src.get("available", False))
    any_stale = any(src.get("stale", True) for src in (audio, ir, cameras))

    activity = _derive_activity(audio, cameras)

    return {
        "timestamp": time.time(),
        "sources_available": sources_available,
        "sources_total": 3,
        "any_stale": any_stale,
        "derived_activity": activity,
        "audio": audio,
        "ir": ir,
        "cameras": cameras,
    }


def _write_fused(payload: dict) -> None:
    SHM_OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SHM_OUT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.rename(SHM_OUT_FILE)


def _tick() -> None:
    fused = _fuse()
    _write_fused(fused)
    log.debug(
        "fused: sources=%d/%d activity=%s stale=%s",
        fused["sources_available"],
        fused["sources_total"],
        fused["derived_activity"],
        fused["any_stale"],
    )


def read_fused_perception() -> dict | None:
    """Read the latest fused perception snapshot. Returns None if unavailable."""
    return _read_json(SHM_OUT_FILE)


def format_perception_context(fused: dict | None) -> str:
    """Format fused perception as a one-line context string for LLM prompts."""
    if fused is None:
        return ""
    parts: list[str] = []
    activity = fused.get("derived_activity", "unknown")
    parts.append(f"activity={activity}")

    audio = fused.get("audio", {})
    if audio.get("available"):
        scene = audio.get("scene", "unknown")
        parts.append(f"audio={scene}")
        if audio.get("music_playing") and audio.get("genre"):
            parts.append(f"genre={audio['genre']}")
        if audio.get("bpm"):
            parts.append(f"bpm={audio['bpm']}")

    cameras = fused.get("cameras", {})
    if cameras.get("available"):
        parts.append(f"cameras={cameras.get('camera_count', 0)}")
        if cameras.get("operator_visible"):
            parts.append("operator_visible")

    ir = fused.get("ir", {})
    if ir.get("available"):
        parts.append("ir_fleet=ok" if ir.get("fleet_healthy") else "ir_fleet=degraded")

    return "Perception: " + ", ".join(parts) if parts else ""


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in sys.argv else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info("Perception fusion daemon starting (interval=%.1fs)", TICK_INTERVAL_S)

    while not _shutdown:
        t0 = time.monotonic()
        try:
            _tick()
        except Exception:
            log.exception("Fusion tick failed")
        elapsed = time.monotonic() - t0
        sleep_s = max(0.1, TICK_INTERVAL_S - elapsed)
        time.sleep(sleep_s)

    log.info("Perception fusion daemon stopped")


if __name__ == "__main__":
    main()
