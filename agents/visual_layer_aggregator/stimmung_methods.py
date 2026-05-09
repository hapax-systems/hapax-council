"""Stimmung and biometric update methods for the VisualLayerAggregator.

These are standalone functions that operate on the aggregator instance,
extracted to reduce aggregator.py size.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path
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

    # 5b. Audio self-perception — broadcast egress loopback + signal flow
    _update_audio_self_perception(agg)

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

    # 6b. DMN health
    update_dmn_health(agg._stimmung_collector)

    # 6c. Exploration deficit
    try:
        from shared.exploration_writer import ExplorationReader

        reader = ExplorationReader()
        signals = reader.read_all()
        if signals:
            boredom_vals = sorted(
                (s.get("boredom_index", 0.0) for s in signals.values()),
                reverse=True,
            )
            # Top-k aggregation: worst-case components drive deficit
            # (stigmergic: dead-end trail triggers redistribution)
            k = max(3, len(boredom_vals) // 3)
            deficit = max(0.0, min(1.0, sum(boredom_vals[:k]) / k))
            agg._stimmung_collector.update_exploration(deficit)
    except Exception:
        log.debug("Exploration deficit read failed", exc_info=True)

    # 6d. Audience engagement — chat activity + viewer count signal.
    # Engagement = 0.0 (nobody) → 1.0 (active audience).
    # The StimmungCollector inverts this (0.0 = good engagement,
    # 1.0 = no engagement) to match stimmung convention.
    try:
        engagement = 0.0
        # Chat activity: unique_authors in the last monitoring window
        chat_path = Path("/dev/shm/hapax-compositor/chat-state.json")
        if chat_path.exists():
            chat = json.loads(chat_path.read_text(encoding="utf-8"))
            chat_age = time.time() - chat.get("generated_at", 0)
            if chat_age < 120:
                authors = int(chat.get("unique_authors", 0))
                messages = int(chat.get("total_messages", 0))
                # 1+ unique authors → 0.3 base; scale with messages
                if authors > 0:
                    engagement = min(1.0, 0.3 + 0.1 * authors + 0.05 * messages)

        # Viewer count: baseline presence signal
        viewer_path = Path("/dev/shm/hapax-youtube/viewer-count.json")
        if viewer_path.exists():
            vc = json.loads(viewer_path.read_text(encoding="utf-8"))
            vc_age = time.time() - vc.get("timestamp", 0)
            if vc_age < 120:
                viewers = int(vc.get("concurrent_viewers", 0))
                if viewers > 0 and engagement < 0.1:
                    engagement = min(1.0, 0.1 + 0.02 * viewers)

        agg._stimmung_collector.update_audience_engagement(engagement)
    except Exception:
        log.debug("Audience engagement read failed", exc_info=True)

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


def update_dmn_health(
    collector,
    status_path: Path | None = None,
) -> None:
    """Read DMN status and feed health signal into stimmung.

    Degrades health when:
    - DMN hasn't ticked in >30s (stale)
    - DMN has 0 buffer entries after >60s uptime (empty buffer)
    """
    if status_path is None:
        status_path = Path("/dev/shm/hapax-dmn/status.json")
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
        age = time.time() - data.get("timestamp", 0)
        if age > 30:
            collector.update_health(0, 1, failed_checks=["dmn_stale"])
        elif data.get("buffer_entries", 0) == 0 and data.get("uptime_s", 0) > 60:
            collector.update_health(0, 1, failed_checks=["dmn_empty_buffer"])
    except (OSError, json.JSONDecodeError, KeyError):
        pass  # DMN not running — not an error


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
        multi_scale_ctx = agg._multi_scale.context()
        bands = agg._temporal_formatter.format(ring, multi_scale=multi_scale_ctx)
        xml = agg._temporal_formatter.format_xml(bands)
        payload = {
            "xml": xml,
            "max_surprise": bands.max_surprise,
            "retention_count": len(bands.retention),
            "protention_count": len(bands.protention),
            "surprise_count": len(bands.surprises),
            "impression": bands.impression,
            "minute_count": len(bands.minute_summaries),
            "has_session": bands.current_session is not None,
            "timestamp": time.time(),
        }
        _c.TEMPORAL_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _c.TEMPORAL_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.rename(_c.TEMPORAL_FILE)
    except Exception:
        log.debug("Failed to write temporal bands", exc_info=True)


# ── Audio self-perception ──────────────────────────────────────────────────

_EGRESS_LOOPBACK_PATH = Path("/dev/shm/hapax-broadcast/egress-loopback.json")
_SIGNAL_FLOW_PATH = Path("/dev/shm/hapax-audio/signal-flow.json")
_EGRESS_MAX_AGE_S = 60.0


def _update_audio_self_perception(agg: VisualLayerAggregator) -> None:
    """Read broadcast audio SHM and feed into stimmung collector.

    Only records audio health when the egress loopback witness file exists —
    absent SHM means no broadcast monitor is running, not that audio is broken.
    """
    has_loopback = False
    rms_dbfs = -60.0
    silence_ratio = 1.0
    witness_age_s = 0.0
    witness_error: str | None = None
    classification = ""

    # Egress loopback witness
    try:
        if _EGRESS_LOOPBACK_PATH.exists():
            has_loopback = True
            data = json.loads(_EGRESS_LOOPBACK_PATH.read_text(encoding="utf-8"))
            from datetime import UTC, datetime

            checked_str = data.get("checked_at", "")
            if checked_str:
                checked = datetime.fromisoformat(checked_str)
                witness_age_s = (datetime.now(UTC) - checked.astimezone(UTC)).total_seconds()
            rms_dbfs = float(data.get("rms_dbfs", -60.0))
            silence_ratio = float(data.get("silence_ratio", 1.0))
            witness_error = data.get("error")
    except (OSError, json.JSONDecodeError, ValueError):
        log.debug("Audio self-perception: egress loopback read failed", exc_info=True)

    # Signal flow classification at OBS-bound stage
    try:
        if _SIGNAL_FLOW_PATH.exists():
            has_loopback = True
            flow = json.loads(_SIGNAL_FLOW_PATH.read_text(encoding="utf-8"))
            stages = flow.get("stages", {})
            obs_stage = stages.get("hapax-obs-broadcast-remap") or stages.get(
                "hapax-broadcast-normalized", {}
            )
            if isinstance(obs_stage, dict):
                classification = str(obs_stage.get("classification", ""))
    except (OSError, json.JSONDecodeError):
        log.debug("Audio self-perception: signal flow read failed", exc_info=True)

    if not has_loopback:
        return

    agg._stimmung_collector.update_audio_self_perception(
        rms_dbfs=rms_dbfs,
        silence_ratio=silence_ratio,
        witness_age_s=witness_age_s,
        witness_error=witness_error,
        classification=classification,
    )
