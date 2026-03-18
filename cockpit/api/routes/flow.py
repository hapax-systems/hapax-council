"""System flow state — unified snapshot of all shm subsystems for live visualization."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api/flow", tags=["flow"])

_SHM_PATHS = {
    "stimmung": Path("/dev/shm/hapax-stimmung/state.json"),
    "temporal": Path("/dev/shm/hapax-temporal/bands.json"),
    "apperception": Path("/dev/shm/hapax-apperception/self-band.json"),
    "compositor": Path("/dev/shm/hapax-compositor/visual-layer-state.json"),
}

_PERCEPTION_PATH = Path.home() / ".cache" / "hapax-voice" / "perception-state.json"


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _age(raw: dict | None) -> float:
    if raw is None:
        return 999.0
    ts = raw.get("timestamp", 0)
    return time.time() - ts if ts else 999.0


def _status(age: float, stale_threshold: float = 10.0) -> str:
    if age < stale_threshold:
        return "active"
    if age < 30.0:
        return "stale"
    return "offline"


@router.get("/state")
def get_flow_state() -> dict:
    """Return unified system flow state for the anatomy visualization."""
    now = time.time()
    nodes = []
    edges = []

    # Perception
    perception = _read(_PERCEPTION_PATH)
    perc_age = _age(perception)
    nodes.append(
        {
            "id": "perception",
            "label": "Perception",
            "status": _status(perc_age),
            "age_s": round(perc_age, 1),
            "metrics": {
                "activity": (perception or {}).get("production_activity", ""),
                "flow_score": (perception or {}).get("flow_score", 0.0),
                "presence_probability": (perception or {}).get("presence_probability"),
                "face_count": (perception or {}).get("face_count", 0),
                "consent_phase": (perception or {}).get("consent_phase", "none"),
            }
            if perception
            else {},
        }
    )

    # Stimmung
    stimmung = _read(_SHM_PATHS["stimmung"])
    stim_age = _age(stimmung)
    nodes.append(
        {
            "id": "stimmung",
            "label": "Stimmung",
            "status": _status(stim_age, 120.0),
            "age_s": round(stim_age, 1),
            "metrics": {
                "stance": (stimmung or {}).get("overall_stance", "unknown"),
                "health": (stimmung or {}).get("health", {}).get("value"),
                "resource_pressure": (stimmung or {}).get("resource_pressure", {}).get("value"),
            }
            if stimmung
            else {},
        }
    )

    # Temporal Bands
    temporal = _read(_SHM_PATHS["temporal"])
    temp_age = _age(temporal)
    nodes.append(
        {
            "id": "temporal",
            "label": "Temporal Bands",
            "status": _status(temp_age),
            "age_s": round(temp_age, 1),
            "metrics": {
                "max_surprise": (temporal or {}).get("max_surprise", 0.0),
                "retention_count": (temporal or {}).get("retention_count", 0),
                "protention_count": (temporal or {}).get("protention_count", 0),
            }
            if temporal
            else {},
        }
    )

    # Apperception
    apperception = _read(_SHM_PATHS["apperception"])
    apper_age = _age(apperception)
    model = (apperception or {}).get("self_model", {})
    nodes.append(
        {
            "id": "apperception",
            "label": "Apperception",
            "status": _status(apper_age),
            "age_s": round(apper_age, 1),
            "metrics": {
                "coherence": model.get("coherence", 0.0),
                "dimensions": len(model.get("dimensions", {})),
                "observations": len(model.get("recent_observations", [])),
            }
            if apperception
            else {},
        }
    )

    # Compositor
    compositor = _read(_SHM_PATHS["compositor"])
    comp_age = _age(compositor)
    nodes.append(
        {
            "id": "compositor",
            "label": "Compositor",
            "status": _status(comp_age),
            "age_s": round(comp_age, 1),
            "metrics": {
                "display_state": (compositor or {}).get("display_state", "unknown"),
            }
            if compositor
            else {},
        }
    )

    # Voice Pipeline — pull from perception state (richer, updated every tick)
    voice_data = (perception or {}).get("voice_session", {})
    if not voice_data:
        voice_data = (compositor or {}).get("voice_session", {})
    voice_active = voice_data.get("active", False)
    nodes.append(
        {
            "id": "voice",
            "label": "Voice Pipeline",
            "status": "active" if voice_active else "offline",
            "age_s": round(perc_age, 1),
            "metrics": {
                "active": voice_active,
                "state": voice_data.get("state", "off"),
                "turn_count": voice_data.get("turn_count", 0),
                "last_utterance": voice_data.get("last_utterance", ""),
                "last_response": voice_data.get("last_response", ""),
                "routing_tier": voice_data.get("routing_tier", ""),
                "routing_reason": voice_data.get("routing_reason", ""),
                "routing_activation": voice_data.get("routing_activation", 0.0),
                "barge_in": voice_data.get("barge_in", False),
            }
            if voice_active
            else {"active": False, "state": "off"},
        }
    )

    # Phenomenal Context
    phenom_active = temp_age < 30.0 or apper_age < 30.0
    nodes.append(
        {
            "id": "phenomenal",
            "label": "Phenomenal Context",
            "status": "active" if phenom_active else "offline",
            "age_s": round(min(temp_age, apper_age), 1),
            "metrics": {},
        }
    )

    # Reactive Engine
    nodes.append(
        {
            "id": "engine",
            "label": "Reactive Engine",
            "status": "active",
            "age_s": 0.0,
            "metrics": {},
        }
    )

    # Consent
    consent_phase = (perception or {}).get("consent_phase", "none")
    nodes.append(
        {
            "id": "consent",
            "label": "Consent",
            "status": "active" if consent_phase != "none" else "offline",
            "age_s": round(perc_age, 1),
            "metrics": {"phase": consent_phase},
        }
    )

    # Edges
    edges = [
        {
            "source": "perception",
            "target": "stimmung",
            "active": perc_age < 10,
            "label": "perception confidence",
        },
        {
            "source": "perception",
            "target": "temporal",
            "active": perc_age < 10,
            "label": "perception ring",
        },
        {
            "source": "perception",
            "target": "consent",
            "active": perc_age < 10,
            "label": "faces + speaker",
        },
        {
            "source": "stimmung",
            "target": "apperception",
            "active": stim_age < 120,
            "label": "stance",
        },
        {
            "source": "temporal",
            "target": "apperception",
            "active": temp_age < 10,
            "label": "surprise",
        },
        {"source": "temporal", "target": "phenomenal", "active": temp_age < 30, "label": "bands"},
        {
            "source": "apperception",
            "target": "phenomenal",
            "active": apper_age < 30,
            "label": "self-band",
        },
        {
            "source": "stimmung",
            "target": "phenomenal",
            "active": stim_age < 120,
            "label": "attunement",
        },
        {"source": "phenomenal", "target": "voice", "active": voice_active, "label": "orientation"},
        {"source": "perception", "target": "voice", "active": voice_active, "label": "salience"},
        {"source": "voice", "target": "compositor", "active": voice_active, "label": "voice state"},
        {
            "source": "stimmung",
            "target": "compositor",
            "active": stim_age < 120,
            "label": "visual mood",
        },
        {
            "source": "perception",
            "target": "compositor",
            "active": perc_age < 10,
            "label": "signals",
        },
        {"source": "engine", "target": "compositor", "active": True, "label": "engine state"},
        {
            "source": "stimmung",
            "target": "engine",
            "active": stim_age < 120,
            "label": "phase gating",
        },
        {
            "source": "consent",
            "target": "voice",
            "active": consent_phase != "none",
            "label": "consent gate",
        },
    ]

    return {"nodes": nodes, "edges": edges, "timestamp": now}
