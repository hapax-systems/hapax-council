"""FastAPI sensor receiver — writes atomic JSON files to filesystem-as-bus.

Receives batched sensor data from the Pixel Watch 4 Wear OS app and writes
atomic JSON files to ~/hapax-state/watch/. Each file is a complete JSON
document, atomically replaced via tmp + rename.

Usage:
    uvicorn agents.watch_receiver:app --host 0.0.0.0 --port 8042
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from shared.config import HAPAX_HOME

log = logging.getLogger(__name__)

try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass
from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

WATCH_STATE_DIR: Path = HAPAX_HOME / "hapax-state" / "watch"
ALLOWED_DEVICE_IDS: set[str] = {"pw4", "pixel10"}
DEVICE_NAMES: dict[str, str] = {"pw4": "pixel_watch_4", "pixel10": "pixel_10"}

# Rolling windows — in-memory, 1 hour max
_WINDOW_MAX_AGE_S = 3600
_hr_window: deque[tuple[float, float]] = deque()  # (epoch, bpm)
_hrv_window: deque[tuple[float, float]] = deque()  # (epoch, rmssd_ms)
_window_lock = threading.Lock()


def _get_watch_state_dir() -> Path:
    """Return the current WATCH_STATE_DIR (supports test patching)."""
    return sys.modules[__name__].WATCH_STATE_DIR


# ── Pydantic models ─────────────────────────────────────────────────────


class SensorReading(BaseModel):
    type: str
    ts: str
    bpm: float | None = None
    confidence: str | None = None
    rmssd_ms: float | None = None
    eda_value: float | None = None
    eda_event: bool | None = None
    duration_seconds: float | None = None
    temp_c: float | None = None
    state: str | None = None
    value: float | None = None


class SensorPayload(BaseModel):
    ts: int = Field(ge=0)  # epoch ms, must be non-negative
    device_id: str
    readings: list[SensorReading]
    battery_pct: int | None = Field(default=None, ge=0, le=100)


class HealthSummaryPayload(BaseModel):
    device_id: str
    date: str  # YYYY-MM-DD
    resting_hr: float | None = None
    hr_min: float | None = None
    hr_max: float | None = None
    hr_mean: float | None = None
    hrv_mean_ms: float | None = None
    steps: int | None = None
    active_minutes: int | None = None
    sleep_start: str | None = None
    sleep_end: str | None = None
    sleep_duration_min: int | None = None
    deep_min: int | None = None
    rem_min: int | None = None
    spo2_mean: float | None = None
    skin_temp_deviation_c: float | None = None
    eda_events: int | None = None


class VoiceTriggerPayload(BaseModel):
    device_id: str


class GesturePayload(BaseModel):
    device_id: str
    gesture: str  # "double_tap", "wrist_twist", "cover"
    timestamp: str


class PhoneContextPayload(BaseModel):
    device_id: str
    ts: int = Field(ge=0)
    activity_type: str = "still"  # still, walking, running, in_vehicle, on_bicycle
    activity_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    screen_on: bool = False
    ringer_mode: str = "normal"  # normal, vibrate, silent
    battery_pct: int = Field(default=100, ge=0, le=100)
    charging: bool = False
    network_type: str = "none"  # wifi, cellular, none


# ── Helpers ──────────────────────────────────────────────────────────────


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically via tmp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=f".{path.stem}_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.rename(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically via tmp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=f".{path.stem}_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.rename(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _prune_window(window: deque[tuple[float, float]], now: float) -> None:
    """Remove entries older than _WINDOW_MAX_AGE_S."""
    cutoff = now - _WINDOW_MAX_AGE_S
    while window and window[0][0] < cutoff:
        window.popleft()


def _window_stats(window: deque[tuple[float, float]]) -> dict[str, Any]:
    """Compute min/max/mean/readings from a rolling window."""
    if not window:
        return {"min": 0, "max": 0, "mean": 0, "readings": 0}
    values = [v for _, v in window]
    return {
        "min": min(values),
        "max": max(values),
        "mean": round(sum(values) / len(values), 1),
        "readings": len(values),
    }


# ── Handlers ─────────────────────────────────────────────────────────────


def _handle_heart_rate(reading: SensorReading, now: float, source: str = "pixel_watch_4") -> None:
    """Process heart rate reading, update rolling window, write file."""
    if reading.bpm is None:
        return
    with _window_lock:
        _prune_window(_hr_window, now)
        _hr_window.append((now, reading.bpm))
        stats = _window_stats(_hr_window)
    _atomic_write(
        _get_watch_state_dir() / "heartrate.json",
        {
            "source": source,
            "updated_at": datetime.now(UTC).isoformat(),
            "current": {
                "bpm": reading.bpm,
                "confidence": reading.confidence or "UNKNOWN",
            },
            "window_1h": stats,
        },
    )


def _handle_hrv(reading: SensorReading, now: float, source: str = "pixel_watch_4") -> None:
    """Process HRV reading."""
    if reading.rmssd_ms is None:
        return
    with _window_lock:
        _prune_window(_hrv_window, now)
        _hrv_window.append((now, reading.rmssd_ms))
        stats = _window_stats(_hrv_window)
    _atomic_write(
        _get_watch_state_dir() / "hrv.json",
        {
            "source": source,
            "updated_at": datetime.now(UTC).isoformat(),
            "current": {"rmssd_ms": reading.rmssd_ms},
            "window_1h": stats,
        },
    )


def _handle_eda(reading: SensorReading, source: str = "pixel_watch_4") -> None:
    """Process EDA reading."""
    _atomic_write(
        _get_watch_state_dir() / "eda.json",
        {
            "source": source,
            "updated_at": datetime.now(UTC).isoformat(),
            "current": {
                "eda_event": reading.eda_event or False,
                "duration_seconds": reading.duration_seconds or 0,
            },
        },
    )


def _handle_skin_temp(reading: SensorReading, source: str = "pixel_watch_4") -> None:
    """Process skin temperature reading."""
    _atomic_write(
        _get_watch_state_dir() / "skin_temp.json",
        {
            "source": source,
            "updated_at": datetime.now(UTC).isoformat(),
            "current": {"temp_c": reading.temp_c},
        },
    )


def _handle_activity(reading: SensorReading, source: str = "pixel_watch_4") -> None:
    """Process activity state reading."""
    _atomic_write(
        _get_watch_state_dir() / "activity.json",
        {
            "source": source,
            "updated_at": datetime.now(UTC).isoformat(),
            "state": reading.state or "UNKNOWN",
        },
    )


_HANDLERS: dict[str, Any] = {
    "heart_rate": lambda r, now, src: _handle_heart_rate(r, now, src),
    "hrv": lambda r, now, src: _handle_hrv(r, now, src),
    "eda": lambda r, now, src: _handle_eda(r, src),
    "skin_temp": lambda r, now, src: _handle_skin_temp(r, src),
    "activity": lambda r, now, src: _handle_activity(r, src),
}


def _update_connection(payload: SensorPayload) -> None:
    """Update connection file on every POST. Phone writes phone_connection.json."""
    filename = "phone_connection.json" if payload.device_id == "pixel10" else "connection.json"
    _atomic_write(
        _get_watch_state_dir() / filename,
        {
            "last_seen_epoch": time.time(),
            "device_id": payload.device_id,
            "battery_pct": payload.battery_pct,
        },
    )


# ── App factory ──────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    _app = FastAPI(title="Hapax Watch Receiver", version="0.1.0")

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(_app)
    except Exception:
        pass

    @_app.post("/watch/sensors")
    async def ingest_sensors(payload: SensorPayload) -> dict[str, str]:
        if payload.device_id not in ALLOWED_DEVICE_IDS:
            raise HTTPException(status_code=403, detail="Unknown device")
        now = time.time()
        source = DEVICE_NAMES.get(payload.device_id, payload.device_id)
        _update_connection(payload)
        for reading in payload.readings:
            handler = _HANDLERS.get(reading.type)
            if handler:
                handler(reading, now, source)
            else:
                log.warning(
                    "Unknown sensor type: %s from device %s", reading.type, payload.device_id
                )
        return {"status": "ok", "readings_processed": str(len(payload.readings))}

    @_app.get("/watch/status")
    async def watch_status() -> dict[str, Any]:
        conn_file = _get_watch_state_dir() / "connection.json"
        conn = {}
        if conn_file.exists():
            try:
                conn = json.loads(conn_file.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Failed to parse connection.json: %s", exc)
        return {"status": "ok", "connection": conn}

    @_app.post("/phone/health-summary")
    async def phone_health_summary(payload: HealthSummaryPayload) -> dict[str, str]:
        if payload.device_id not in ALLOWED_DEVICE_IDS:
            raise HTTPException(status_code=403, detail="Unknown device")
        # Write phone_health_summary.json atomically
        summary_data = payload.model_dump()
        summary_data["source"] = DEVICE_NAMES.get(payload.device_id, payload.device_id)
        summary_data["updated_at"] = datetime.now(UTC).isoformat()
        _atomic_write(_get_watch_state_dir() / "phone_health_summary.json", summary_data)

        # Write RAG markdown using health_connect_parser formatter
        from agents.health_connect_parser import format_daily_summary

        day_data = {
            k: v for k, v in payload.model_dump().items() if v is not None and k != "device_id"
        }
        md_content = format_daily_summary(day_data)
        # Override device in frontmatter to reflect phone source
        md_content = md_content.replace(
            "device: pixel_watch_4",
            f"device: {DEVICE_NAMES.get(payload.device_id, payload.device_id)}",
        )
        md_content = md_content.replace(
            "source_device: pixel_watch_4",
            f"source_device: {DEVICE_NAMES.get(payload.device_id, payload.device_id)}",
        )
        rag_dir = HAPAX_HOME / "documents" / "rag-sources" / "health-connect"
        rag_dir.mkdir(parents=True, exist_ok=True)
        rag_file = rag_dir / f"health-{payload.date}.md"
        _atomic_write_text(rag_file, md_content)
        return {"status": "ok", "date": payload.date}

    @_app.post("/watch/voice-trigger")
    async def voice_trigger(payload: VoiceTriggerPayload) -> dict[str, str]:
        if payload.device_id not in ALLOWED_DEVICE_IDS:
            raise HTTPException(status_code=403, detail="Unknown device")
        _atomic_write(
            _get_watch_state_dir() / "voice_trigger.json",
            {
                "triggered_at": datetime.now(UTC).isoformat(),
                "device_id": payload.device_id,
            },
        )
        return {"status": "ok"}

    @_app.post("/watch/gesture")
    async def watch_gesture(payload: GesturePayload) -> dict[str, str]:
        """Receive gesture intent from watch accelerometer/gyro/proximity."""
        if payload.device_id not in ALLOWED_DEVICE_IDS:
            raise HTTPException(status_code=403, detail="Unknown device")
        _atomic_write(
            _get_watch_state_dir() / "gesture.json",
            {
                "gesture": payload.gesture,
                "timestamp": payload.timestamp,
                "device_id": payload.device_id,
                "received_at": datetime.now(UTC).isoformat(),
            },
        )
        log.info("Watch gesture received: %s from %s", payload.gesture, payload.device_id)
        return {"status": "ok", "gesture": payload.gesture}

    @_app.post("/phone/context")
    async def phone_context(payload: PhoneContextPayload) -> dict[str, str]:
        """Receive coarse context from phone (activity, screen, ringer)."""
        if payload.device_id not in ALLOWED_DEVICE_IDS:
            raise HTTPException(status_code=403, detail="Unknown device")
        _atomic_write(
            _get_watch_state_dir() / "phone_context.json",
            {
                "source": DEVICE_NAMES.get(payload.device_id, payload.device_id),
                "updated_at": datetime.now(UTC).isoformat(),
                "activity_type": payload.activity_type,
                "activity_confidence": payload.activity_confidence,
                "screen_on": payload.screen_on,
                "ringer_mode": payload.ringer_mode,
                "battery_pct": payload.battery_pct,
                "charging": payload.charging,
                "network_type": payload.network_type,
            },
        )
        return {"status": "ok"}

    return _app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    # Bind to localhost only. For remote access (e.g. phone), use Tailscale/WireGuard.
    uvicorn.run("agents.watch_receiver:app", host="127.0.0.1", port=8042, reload=True)
