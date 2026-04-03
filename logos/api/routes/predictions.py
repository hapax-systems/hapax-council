"""Reverie prediction monitor + live operational metrics.

Prediction summaries from /dev/shm/hapax-reverie/predictions.json (5-min timer).
Live operational metrics from uniforms, perception state, and chronicle (real-time).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Response

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/predictions", tags=["predictions"])

PREDICTIONS_SHM = Path("/dev/shm/hapax-reverie/predictions.json")
UNIFORMS_FILE = Path("/dev/shm/hapax-imagination/uniforms.json")
PERCEPTION_STATE = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
CHRONICLE_DIR = Path("/dev/shm/hapax-chronicle")


def _read_predictions() -> dict:
    try:
        return json.loads(PREDICTIONS_SHM.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@router.get("")
async def get_predictions() -> dict:
    """Return latest prediction monitor sample as JSON."""
    return _read_predictions()


@router.get("/metrics")
async def predictions_metrics() -> Response:
    """Expose prediction metrics in Prometheus text format."""
    data = _read_predictions()
    if not data:
        return Response("# no prediction data available\n", media_type="text/plain")

    lines: list[str] = []
    lines.append("# HELP reverie_prediction_actual Current actual value of each prediction metric")
    lines.append("# TYPE reverie_prediction_actual gauge")
    lines.append(
        "# HELP reverie_prediction_healthy Whether prediction is within expected range (1=yes)"
    )
    lines.append("# TYPE reverie_prediction_healthy gauge")
    lines.append("# HELP reverie_hours_since_deploy Hours elapsed since PR #570 deployment")
    lines.append("# TYPE reverie_hours_since_deploy gauge")
    lines.append("# HELP reverie_alert_count Number of active prediction alerts")
    lines.append("# TYPE reverie_alert_count gauge")

    hours = data.get("hours_since_deploy", 0)
    lines.append(f"reverie_hours_since_deploy {hours}")
    lines.append(f"reverie_alert_count {data.get('alert_count', 0)}")

    for p in data.get("predictions", []):
        name = p.get("name", "unknown")
        actual = p.get("actual", 0)
        healthy = 1 if p.get("healthy", False) else 0
        lines.append(f'reverie_prediction_actual{{prediction="{name}"}} {actual}')
        lines.append(f'reverie_prediction_healthy{{prediction="{name}"}} {healthy}')

    # --- Live operational metrics (real-time, not from timer) ---

    # Shader uniforms: per-parameter deviation from vocabulary defaults
    _VOCAB_DEFAULTS = {
        "color.brightness": 1.0,
        "color.saturation": 1.0,
        "color.hue_rotate": 0.0,
        "noise.amplitude": 0.7,
        "noise.frequency_x": 1.5,
        "fb.hue_shift": 0.0,
        "post.vignette_strength": 0.35,
    }
    lines.append("# HELP reverie_uniform_value Current shader uniform value")
    lines.append("# TYPE reverie_uniform_value gauge")
    lines.append("# HELP reverie_uniform_deviation Deviation from vocabulary default")
    lines.append("# TYPE reverie_uniform_deviation gauge")
    try:
        uniforms = json.loads(UNIFORMS_FILE.read_text())
        for param, default in _VOCAB_DEFAULTS.items():
            val = uniforms.get(param)
            if val is not None and isinstance(val, (int, float)):
                lines.append(f'reverie_uniform_value{{param="{param}"}} {val}')
                lines.append(
                    f'reverie_uniform_deviation{{param="{param}"}} {abs(val - default):.6f}'
                )
    except Exception:
        pass

    # Presence signals: individual signal states
    lines.append(
        "# HELP reverie_presence_signal Individual presence signal value (1=active, 0=inactive)"
    )
    lines.append("# TYPE reverie_presence_signal gauge")
    lines.append("# HELP reverie_presence_posterior Bayesian presence posterior")
    lines.append("# TYPE reverie_presence_posterior gauge")
    _PRESENCE_SIGNALS = [
        "presence_probability",
        "presence_state",
        "desk_activity",
        "desk_energy",
        "ir_hand_activity",
        "ir_motion_delta",
        "ir_person_detected",
        "ir_person_count",
    ]
    try:
        perception = json.loads(PERCEPTION_STATE.read_text())
        pp = perception.get("presence_probability", 0)
        lines.append(f"reverie_presence_posterior {pp}")
        # Desk energy (continuous 0-1)
        de = perception.get("desk_energy", 0)
        lines.append(f'reverie_presence_signal{{signal="desk_energy"}} {de}')
        # IR motion (continuous)
        motion = perception.get("ir_motion_delta", 0)
        lines.append(f'reverie_presence_signal{{signal="ir_motion_delta"}} {motion}')
        # Binary signals
        for sig in ["ir_hand_activity", "desk_activity"]:
            val = perception.get(sig, "idle")
            active = 1 if isinstance(val, str) and val not in ("idle", "none", "unknown", "") else 0
            lines.append(f'reverie_presence_signal{{signal="{sig}"}} {active}')
        ir_persons = perception.get("ir_person_count", 0)
        lines.append(f'reverie_presence_signal{{signal="ir_person_count"}} {ir_persons}')
    except Exception:
        pass

    # Chronicle technique confidence: last 60s of activations
    lines.append("# HELP reverie_technique_confidence Last recruitment confidence per technique")
    lines.append("# TYPE reverie_technique_confidence gauge")
    lines.append("# HELP reverie_technique_rate Activations per minute per technique")
    lines.append("# TYPE reverie_technique_rate gauge")
    try:
        events_file = CHRONICLE_DIR / "events.jsonl"
        if events_file.exists():
            now = time.time()
            cutoff = now - 60.0
            technique_last: dict[str, float] = {}
            technique_count: dict[str, int] = {}
            with open(events_file) as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if e.get("source") != "visual" or e.get("event_type") != "technique.activated":
                        continue
                    ts = e.get("ts", 0)
                    if ts < cutoff:
                        continue
                    name = e.get("payload", {}).get("technique_name", "")
                    conf = e.get("payload", {}).get("confidence", 0)
                    if name:
                        technique_last[name] = conf
                        technique_count[name] = technique_count.get(name, 0) + 1
            for name, conf in technique_last.items():
                lines.append(f'reverie_technique_confidence{{technique="{name}"}} {conf}')
            elapsed = min(60.0, now - cutoff)
            for name, count in technique_count.items():
                rate = count / elapsed * 60 if elapsed > 0 else 0
                lines.append(f'reverie_technique_rate{{technique="{name}"}} {rate:.2f}')
    except Exception:
        pass

    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
