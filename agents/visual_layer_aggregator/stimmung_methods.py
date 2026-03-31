"""Stimmung and biometric update methods for the VisualLayerAggregator.

These are standalone functions that operate on the aggregator instance,
extracted to reduce aggregator.py size.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from typing import TYPE_CHECKING

from agents._telemetry import trace_stimmung_update

from . import constants as _c

if TYPE_CHECKING:
    from .aggregator import VisualLayerAggregator

log = logging.getLogger("visual_layer_aggregator")


def update_stimmung_sources(agg: VisualLayerAggregator) -> None:
    """Collect stimmung readings from all available data sources."""
    # 1. Health history
    try:
        text = _c.HEALTH_HISTORY_PATH.read_text(encoding="utf-8").strip()
        if text:
            last_line = text.split("\n")[-1]
            h = json.loads(last_line)
            healthy = h.get("healthy", 0)
            total = h.get("total", healthy + h.get("degraded", 0) + h.get("failed", 0))
            agg._stimmung_collector.update_health(healthy, total)
    except (OSError, json.JSONDecodeError, IndexError):
        log.debug("Health history read failed", exc_info=True)

    # 2. Infra snapshot -> GPU
    try:
        infra = json.loads(_c.INFRA_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        gpu = infra.get("gpu") or {}
        used = gpu.get("used_mb", 0)
        total = gpu.get("total_mb", 0)
        if total > 0:
            agg._stimmung_collector.update_gpu(used, total)
    except (OSError, json.JSONDecodeError):
        log.debug("Infra snapshot read failed", exc_info=True)

    # 3. Langfuse sync state
    try:
        lf = json.loads(_c.LANGFUSE_STATE_PATH.read_text(encoding="utf-8"))
        daily_costs = lf.get("daily_costs", {})
        today = date.today().isoformat()
        daily_cost = daily_costs.get(today, 0.0) if isinstance(daily_costs, dict) else 0.0
        agg._stimmung_collector.update_langfuse(
            daily_cost=float(daily_cost),
            error_count=int(lf.get("error_count", 0)),
            total_traces=int(lf.get("total_traces_synced", 0)),
        )
    except (OSError, json.JSONDecodeError):
        log.debug("Langfuse state read failed", exc_info=True)

    # 4. Biometrics (delegated)
    update_biometrics(agg)

    # 5. Perception freshness + confidence
    now = time.monotonic()
    perception_age = now - agg._ts_perception if agg._ts_perception else 60.0
    confidence = agg._last_perception_data.get("aggregate_confidence", 1.0)
    ir_detected = agg._last_perception_data.get("ir_person_detected", False)
    ir_hands = agg._last_perception_data.get("ir_hand_activity", "idle")
    if ir_detected or ir_hands not in ("idle", ""):
        confidence = max(float(confidence), 0.7)
    agg._stimmung_collector.update_perception(
        freshness_s=perception_age, confidence=float(confidence)
    )

    # 6. Grounding quality from voice session
    try:
        from pathlib import Path

        from agents._stimmung import _STALE_THRESHOLD_S

        gqi_path = Path("/dev/shm/hapax-daimonion/grounding-quality.json")
        if gqi_path.exists():
            gqi_data = json.loads(gqi_path.read_text())
            gqi_age = time.time() - gqi_data.get("timestamp", 0)
            if gqi_age < _STALE_THRESHOLD_S:
                gqi_val = gqi_data.get("gqi", 0.5)
                agg._stimmung_collector.update_grounding_quality(gqi_val)
                log.debug("GQI read: %.3f (age %.1fs)", gqi_val, gqi_age)
            else:
                log.debug("GQI stale (age %.1fs > 120s), skipping", gqi_age)
        else:
            log.debug("GQI shm file not found (no active voice session)")
    except Exception:
        log.debug("GQI read failed", exc_info=True)

    # 7. Snapshot
    prev_stance = agg._stimmung.overall_stance.value if agg._stimmung else "nominal"
    agg._stimmung = agg._stimmung_collector.snapshot()

    # 8. Telemetry
    trace_stimmung_update(
        stance=agg._stimmung.overall_stance.value,
        health=agg._stimmung.health.value,
        resource_pressure=agg._stimmung.resource_pressure.value,
        error_rate=agg._stimmung.error_rate.value,
        throughput=agg._stimmung.processing_throughput.value,
        perception_confidence=agg._stimmung.perception_confidence.value,
        llm_cost=agg._stimmung.llm_cost_pressure.value,
        prev_stance=prev_stance,
    )


def update_biometrics(agg: VisualLayerAggregator) -> None:
    """Read watch/phone biometric data and feed to stimmung collector."""
    from agents.hapax_daimonion.watch_signals import read_watch_signal

    hrv_current = None
    hrv_baseline = None
    hrv_cv = None
    hrv_data = read_watch_signal(_c.WATCH_STATE_DIR / "hrv.json")
    if hrv_data is not None:
        current = hrv_data.get("current", {})
        window = hrv_data.get("window_1h", {})
        hrv_current = current.get("rmssd_ms")
        hrv_baseline = window.get("mean")
        std = window.get("std")
        mean = window.get("mean")
        if std is not None and mean and mean > 0:
            hrv_cv = std / mean

    eda_active = False
    eda_data = read_watch_signal(_c.WATCH_STATE_DIR / "eda.json")
    if eda_data is not None:
        current = eda_data.get("current", {})
        eda_active = bool(current.get("eda_event") and current.get("duration_seconds", 0) > 120)

    frustration = agg._last_perception_data.get("frustration_score", 0.0)

    sleep_quality = None
    summary = read_watch_signal(
        _c.WATCH_STATE_DIR / "phone_health_summary.json", max_age_seconds=86400
    )
    if summary is not None:
        sleep_min = summary.get("sleep_duration_min")
        if sleep_min is not None:
            sleep_quality = max(0.0, min(1.0, float(sleep_min) / 480.0))

    activity_level = 0.0
    activity_data = read_watch_signal(_c.WATCH_STATE_DIR / "activity.json")
    if activity_data is not None:
        state = activity_data.get("state", "")
        activity_levels = {
            "still": 0.1,
            "walking": 0.4,
            "running": 0.8,
            "on_bicycle": 0.7,
            "in_vehicle": 0.2,
        }
        activity_level = activity_levels.get(state, 0.1)

    hr_zone = 0.0
    hr_data = read_watch_signal(_c.WATCH_STATE_DIR / "heartrate.json")
    if hr_data is not None:
        bpm = hr_data.get("current", {}).get("bpm")
        if bpm is not None:
            hr_zone = max(0.0, min(1.0, (bpm - 60) / 80.0))

    circadian = agg._last_perception_data.get("circadian_alignment", 0.5)

    agg._stimmung_collector.update_biometrics(
        hrv_current=hrv_current,
        hrv_baseline=hrv_baseline,
        eda_active=eda_active,
        frustration_score=float(frustration),
        sleep_quality=sleep_quality,
        circadian_alignment=float(circadian),
        activity_level=activity_level,
        hr_zone=hr_zone,
        hrv_cv=hrv_cv,
        desk_activity=agg._last_perception_data.get("desk_activity", ""),
        desk_energy=float(agg._last_perception_data.get("desk_energy", 0.0) or 0.0),
    )


def write_stimmung(agg: VisualLayerAggregator) -> None:
    """Write stimmung state to /dev/shm for external consumers."""
    if agg._stimmung is None:
        return
    try:
        _c.STIMMUNG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _c.STIMMUNG_FILE.with_suffix(".tmp")
        tmp.write_text(agg._stimmung.model_dump_json(), encoding="utf-8")
        tmp.rename(_c.STIMMUNG_FILE)
    except OSError:
        log.debug("Failed to write stimmung state", exc_info=True)


def write_temporal_bands(agg: VisualLayerAggregator) -> None:
    """Compute temporal bands from local perception ring and write to shm."""
    ring = agg._local_ring
    if len(ring) < 2:
        return

    try:
        bands = agg._temporal_formatter.format(ring)
        xml = agg._temporal_formatter.format_xml(bands)
        payload = {
            "xml": xml,
            "max_surprise": bands.max_surprise,
            "retention_count": len(bands.retention),
            "protention_count": len(bands.protention),
            "surprise_count": len(bands.surprises),
            "timestamp": time.time(),
        }
        _c.TEMPORAL_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _c.TEMPORAL_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.rename(_c.TEMPORAL_FILE)
    except Exception:
        log.debug("Failed to write temporal bands", exc_info=True)
