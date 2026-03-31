"""Apperception SHM bridge writers for the VisualLayerAggregator.

Standalone functions extracted from aggregator.py to stay under module size limits.
Each writes an atomic JSON file to /dev/shm/hapax-apperception/ for consumption
by the apperception tick loop.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .aggregator import VisualLayerAggregator

log = logging.getLogger("visual_layer_aggregator")

APPERCEPTION_SHM = Path("/dev/shm/hapax-apperception")

_RESONANCE_PAIRS: list[tuple[str, str]] = [
    ("sample-session", "production_session"),
    ("sample-session", "active_work"),
    ("conversation", "conversation"),
    ("conversation", "active_work"),
    ("vocal-note", "production_session"),
    ("vocal-note", "active_work"),
    ("listening-log", "production_session"),
    ("listening-log", "active_work"),
]


def write_cross_resonance(agg: VisualLayerAggregator) -> None:
    """Check audio-video classification agreement, write to SHM.

    Compares the current production_activity (audio-derived label) against
    video classification detections using a resonance pair lookup table.
    Writes ``cross-resonance.json`` atomically.
    """
    try:
        data = agg._last_perception_data
        if not data:
            return
        audio_label = data.get("production_activity", "") or ""
        if not audio_label:
            return

        matching_roles: list[str] = []
        for det in agg._classification_detections:
            for audio_pat, video_pat in _RESONANCE_PAIRS:
                if audio_pat in str(audio_label) and video_pat in det.label:
                    matching_roles.append(det.camera)
                    break

        n_detections = len(agg._classification_detections)
        score = min(1.0, len(matching_roles) / max(1, n_detections))

        out_dir = APPERCEPTION_SHM
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "cross-resonance.json"
        tmp_path = out_path.with_suffix(".tmp")
        payload = json.dumps(
            {
                "resonance_score": round(score, 3),
                "audio_label": audio_label,
                "matching_roles": matching_roles,
                "timestamp": time.time(),
            },
        )
        tmp_path.write_text(payload)
        tmp_path.rename(out_path)
    except Exception:
        log.debug("Cross-resonance write failed", exc_info=True)


def write_pattern_shifts(agg: VisualLayerAggregator) -> None:
    """Correlate BOCPD change points with active patterns, write to SHM.

    For each active pattern match (score > 0.3):
    - ``confirmed`` if score > 0.6 and no contradicting change point
    - ``contradicted`` if a recent change-point signal appears in the pattern
    Writes ``pattern-shifts.json`` atomically.
    """
    try:
        now_ts = time.time()
        recent_cps = [
            cp for cp in agg._last_change_points if now_ts - cp.get("timestamp", 0) < 120.0
        ]
        shifts: list[dict] = []
        for match in agg._active_patterns:
            score = match.score if hasattr(match, "score") else 0.0
            if score <= 0.3:
                continue
            pattern = match.pattern if hasattr(match, "pattern") else None
            if pattern is None:
                continue
            condition = getattr(pattern, "condition", "")
            prediction = getattr(pattern, "prediction", "")

            # Check for contradicting change point
            contradicted = False
            for cp in recent_cps:
                signal = cp.get("signal", "")
                if signal in condition or signal in prediction:
                    contradicted = True
                    break

            confirmed = score > 0.6 and not contradicted

            shifts.append(
                {
                    "condition": condition[:120],
                    "prediction": prediction[:120],
                    "score": round(score, 3),
                    "confirmed": confirmed,
                    "contradicted": contradicted,
                }
            )

        out_dir = APPERCEPTION_SHM
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "pattern-shifts.json"
        tmp_path = out_path.with_suffix(".tmp")
        payload = json.dumps({"shifts": shifts, "timestamp": now_ts})
        tmp_path.write_text(payload)
        tmp_path.rename(out_path)
    except Exception:
        log.debug("Pattern-shifts write failed", exc_info=True)
