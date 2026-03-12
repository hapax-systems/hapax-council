"""FastAPI sensor receiver — writes atomic JSON files to filesystem-as-bus.

Receives batched sensor data from the Pixel Watch 4 Wear OS app and writes
atomic JSON files to ~/hapax-state/watch/. Each file is a complete JSON
document, atomically replaced via tmp + rename.

Usage:
    uvicorn agents.watch_receiver:app --host 0.0.0.0 --port 8042
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from shared.config import HAPAX_HOME

WATCH_STATE_DIR: Path = HAPAX_HOME / "hapax-state" / "watch"
ALLOWED_DEVICE_IDS: set[str] = {"pw4"}

# Rolling windows — in-memory, 1 hour max
_WINDOW_MAX_AGE_S = 3600
_hr_window: deque[tuple[float, float]] = deque()  # (epoch, bpm)
_hrv_window: deque[tuple[float, float]] = deque()  # (epoch, rmssd_ms)


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
    ts: int  # epoch ms
    device_id: str
    readings: list[SensorReading]
    battery_pct: int | None = None


class VoiceTriggerPayload(BaseModel):
    device_id: str


# ── Helpers ──────────────────────────────────────────────────────────────

def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically via tmp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=f".{path.stem}_"
    )
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

def _handle_heart_rate(reading: SensorReading, now: float) -> None:
    """Process heart rate reading, update rolling window, write file."""
    if reading.bpm is None:
        return
    _prune_window(_hr_window, now)
    _hr_window.append((now, reading.bpm))
    _atomic_write(_get_watch_state_dir() / "heartrate.json", {
        "source": "pixel_watch_4",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "current": {
            "bpm": reading.bpm,
            "confidence": reading.confidence or "UNKNOWN",
        },
        "window_1h": _window_stats(_hr_window),
    })


def _handle_hrv(reading: SensorReading, now: float) -> None:
    """Process HRV reading."""
    if reading.rmssd_ms is None:
        return
    _prune_window(_hrv_window, now)
    _hrv_window.append((now, reading.rmssd_ms))
    _atomic_write(_get_watch_state_dir() / "hrv.json", {
        "source": "pixel_watch_4",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "current": {"rmssd_ms": reading.rmssd_ms},
        "window_1h": _window_stats(_hrv_window),
    })


def _handle_eda(reading: SensorReading) -> None:
    """Process EDA reading."""
    _atomic_write(_get_watch_state_dir() / "eda.json", {
        "source": "pixel_watch_4",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "current": {
            "eda_event": reading.eda_event or False,
            "duration_seconds": reading.duration_seconds or 0,
        },
    })


def _handle_skin_temp(reading: SensorReading) -> None:
    """Process skin temperature reading."""
    _atomic_write(_get_watch_state_dir() / "skin_temp.json", {
        "source": "pixel_watch_4",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "current": {"temp_c": reading.temp_c},
    })


def _handle_activity(reading: SensorReading) -> None:
    """Process activity state reading."""
    _atomic_write(_get_watch_state_dir() / "activity.json", {
        "source": "pixel_watch_4",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "state": reading.state or "UNKNOWN",
    })


_HANDLERS: dict[str, Any] = {
    "heart_rate": lambda r, now: _handle_heart_rate(r, now),
    "hrv": lambda r, now: _handle_hrv(r, now),
    "eda": lambda r, now: _handle_eda(r),
    "skin_temp": lambda r, now: _handle_skin_temp(r),
    "activity": lambda r, now: _handle_activity(r),
}


def _update_connection(payload: SensorPayload) -> None:
    """Update connection.json on every POST."""
    _atomic_write(_get_watch_state_dir() / "connection.json", {
        "last_seen_epoch": time.time(),
        "device_id": payload.device_id,
        "battery_pct": payload.battery_pct,
    })


# ── App factory ──────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    _app = FastAPI(title="Hapax Watch Receiver", version="0.1.0")

    @_app.post("/watch/sensors")
    async def ingest_sensors(payload: SensorPayload) -> dict[str, str]:
        if payload.device_id not in ALLOWED_DEVICE_IDS:
            raise HTTPException(status_code=403, detail="Unknown device")
        now = time.time()
        _update_connection(payload)
        for reading in payload.readings:
            handler = _HANDLERS.get(reading.type)
            if handler:
                handler(reading, now)
        return {"status": "ok", "readings_processed": str(len(payload.readings))}

    @_app.get("/watch/status")
    async def watch_status() -> dict[str, Any]:
        conn_file = _get_watch_state_dir() / "connection.json"
        conn = {}
        if conn_file.exists():
            conn = json.loads(conn_file.read_text())
        return {"status": "ok", "connection": conn}

    @_app.post("/watch/voice-trigger")
    async def voice_trigger(payload: VoiceTriggerPayload) -> dict[str, str]:
        if payload.device_id not in ALLOWED_DEVICE_IDS:
            raise HTTPException(status_code=403, detail="Unknown device")
        _atomic_write(_get_watch_state_dir() / "voice_trigger.json", {
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "device_id": payload.device_id,
        })
        return {"status": "ok"}

    return _app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agents.watch_receiver:app", host="0.0.0.0", port=8042, reload=True)
