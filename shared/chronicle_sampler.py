"""shared/chronicle_sampler.py — Periodic 30-second state snapshots.

Assembles system state from stimmung, eigenform, and signal bus, then
records each snapshot as a ChronicleEvent. Runs as a long-lived asyncio
coroutine alongside other daemons.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from shared.chronicle import (
    ChronicleEvent,
    current_otel_ids,
)
from shared.chronicle import (
    record as chronicle_record,
)

log = logging.getLogger(__name__)

STIMMUNG_STATE = Path("/dev/shm/hapax-stimmung/state.json")
EIGENFORM_LOG = Path("/dev/shm/hapax-eigenform/state-log.jsonl")
SNAPSHOT_INTERVAL_S = 30


# ── Snapshot assembly ─────────────────────────────────────────────────────────


def assemble_snapshot(
    *,
    stimmung_path: Path = STIMMUNG_STATE,
    eigenform_path: Path = EIGENFORM_LOG,
    signal_bus_snapshot: dict[str, float] | None = None,
) -> dict:
    """Assemble a point-in-time state snapshot from available sources.

    Parameters
    ----------
    stimmung_path:
        Path to the stimmung state JSON file.  Missing or unreadable files
        are silently skipped — the key will be an empty dict.
    eigenform_path:
        Path to the eigenform JSONL log.  Only the *last* line is read.
        Missing or unreadable files are silently skipped.
    signal_bus_snapshot:
        Pre-built signal mapping passed in by the caller (e.g. from a live
        SignalBus object).  ``None`` is stored as an empty dict.

    Returns
    -------
    dict
        ``{"stimmung": {...}, "eigenform": {...}, "signals": {...}}``
    """
    return {
        "stimmung": _read_stimmung(stimmung_path),
        "eigenform": _read_eigenform(eigenform_path),
        "signals": signal_bus_snapshot or {},
    }


def _read_stimmung(path: Path) -> dict:
    """Return stance + dimensions from *path*, or {} on any failure."""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        result: dict = {}
        if "stance" in data:
            result["stance"] = data["stance"]
        if "dimensions" in data:
            result["dimensions"] = data["dimensions"]
        return result
    except Exception:  # noqa: BLE001
        return {}


def _read_eigenform(path: Path) -> dict:
    """Return the last entry from the JSONL log at *path*, or {} on failure."""
    try:
        raw = path.read_bytes()
        # Walk backwards to find the last non-empty line.
        lines = raw.decode("utf-8").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if line:
                return json.loads(line)
        return {}
    except Exception:  # noqa: BLE001
        return {}


# ── Coroutine ─────────────────────────────────────────────────────────────────


async def run_sampler(
    *,
    interval_s: float = SNAPSHOT_INTERVAL_S,
    stimmung_path: Path = STIMMUNG_STATE,
    eigenform_path: Path = EIGENFORM_LOG,
    signal_bus: object | None = None,
) -> None:
    """Long-lived coroutine that records state snapshots every *interval_s* seconds.

    Parameters
    ----------
    interval_s:
        Seconds between snapshots.  Defaults to 30.
    stimmung_path:
        Override for stimmung state file location (useful in tests).
    eigenform_path:
        Override for eigenform log file location (useful in tests).
    signal_bus:
        Optional object with a ``.snapshot()`` method that returns
        ``dict[str, float]``.  Called each cycle; failures are swallowed.

    The coroutine never raises — all exceptions are logged.
    """
    log.info("chronicle_sampler: starting (interval=%.0fs)", interval_s)
    while True:
        await asyncio.sleep(interval_s)
        try:
            bus_snapshot: dict[str, float] | None = None
            if signal_bus is not None:
                try:
                    bus_snapshot = signal_bus.snapshot()
                except Exception:  # noqa: BLE001
                    log.debug("chronicle_sampler: signal_bus.snapshot() failed", exc_info=True)

            payload = assemble_snapshot(
                stimmung_path=stimmung_path,
                eigenform_path=eigenform_path,
                signal_bus_snapshot=bus_snapshot,
            )
            trace_id, span_id = current_otel_ids()
            event = ChronicleEvent(
                ts=time.time(),
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=None,
                source="*",
                event_type="snapshot",
                payload=payload,
            )
            chronicle_record(event)
            log.debug("chronicle_sampler: snapshot recorded (ts=%.3f)", event.ts)
        except Exception:  # noqa: BLE001
            log.exception("chronicle_sampler: unhandled error during snapshot cycle")
