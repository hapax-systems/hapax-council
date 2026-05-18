"""Density field compute module — ALARM temporal mode detection.

Reads the information density field from SHM and classifies temporal state
into one of four modes: BASELINE, RISING, SUSTAINED, ALARM. Downstream
consumers (programme planner, director loop) read this to modulate behavior
during density spikes.

The InformationDensityField (shared/information_density.py) handles per-source
density computation. This module adds temporal classification on top.
"""

from __future__ import annotations

import json
import logging
import time
from enum import StrEnum
from pathlib import Path
from typing import Any

from shared.information_density import DENSITY_FIELD_SHM

log = logging.getLogger(__name__)

TEMPORAL_STATE_PATH = Path("/dev/shm/hapax-density-field/temporal-mode.json")

ALARM_THRESHOLD = 0.75
SUSTAINED_THRESHOLD = 0.50
RISING_THRESHOLD = 0.30
ALARM_DURATION_S = 5.0


class DensityTemporalMode(StrEnum):
    BASELINE = "baseline"
    RISING = "rising"
    SUSTAINED = "sustained"
    ALARM = "alarm"


class DensityFieldCompute:
    """Classifies temporal density mode from the running density field."""

    def __init__(self) -> None:
        self._above_sustained_since: float | None = None
        self._last_density: float = 0.0
        self._mode: DensityTemporalMode = DensityTemporalMode.BASELINE

    def tick(self) -> DensityTemporalMode:
        aggregate = self._read_aggregate_density()
        now = time.time()

        if aggregate >= ALARM_THRESHOLD:
            if self._above_sustained_since is None:
                self._above_sustained_since = now
            elapsed = now - self._above_sustained_since
            self._mode = (
                DensityTemporalMode.ALARM
                if elapsed >= ALARM_DURATION_S
                else DensityTemporalMode.SUSTAINED
            )
        elif aggregate >= SUSTAINED_THRESHOLD:
            if self._above_sustained_since is None:
                self._above_sustained_since = now
            self._mode = DensityTemporalMode.SUSTAINED
        elif aggregate >= RISING_THRESHOLD:
            self._above_sustained_since = None
            self._mode = DensityTemporalMode.RISING
        else:
            self._above_sustained_since = None
            self._mode = DensityTemporalMode.BASELINE

        self._last_density = aggregate
        self._write_state(now)
        return self._mode

    @property
    def mode(self) -> DensityTemporalMode:
        return self._mode

    @property
    def last_density(self) -> float:
        return self._last_density

    def _read_aggregate_density(self) -> float:
        try:
            data = json.loads(DENSITY_FIELD_SHM.read_text(encoding="utf-8"))
            sources = data.get("sources", {})
            if not sources:
                return 0.0
            densities = [s.get("density", 0.0) for s in sources.values() if isinstance(s, dict)]
            return sum(densities) / len(densities) if densities else 0.0
        except (OSError, json.JSONDecodeError, ValueError):
            return 0.0

    def _write_state(self, now: float) -> None:
        state: dict[str, Any] = {
            "mode": self._mode.value,
            "aggregate_density": self._last_density,
            "timestamp": now,
        }
        try:
            TEMPORAL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = TEMPORAL_STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(state), encoding="utf-8")
            tmp.rename(TEMPORAL_STATE_PATH)
        except OSError:
            log.debug("Failed to write temporal mode state", exc_info=True)


def read_temporal_mode() -> DensityTemporalMode:
    """Read the current temporal mode from SHM. Defaults BASELINE on error."""
    try:
        data = json.loads(TEMPORAL_STATE_PATH.read_text(encoding="utf-8"))
        return DensityTemporalMode(data["mode"])
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return DensityTemporalMode.BASELINE
