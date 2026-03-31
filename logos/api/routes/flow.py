"""System flow state — unified snapshot of all shm subsystems for live visualization."""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/flow", tags=["flow"])

_SHM_PATHS = {
    "stimmung": Path("/dev/shm/hapax-stimmung/state.json"),
    "temporal": Path("/dev/shm/hapax-temporal/bands.json"),
    "apperception": Path("/dev/shm/hapax-apperception/self-band.json"),
    "compositor": Path("/dev/shm/hapax-compositor/visual-layer-state.json"),
}

_PERCEPTION_PATH = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"

# Consent coverage cache (60s TTL — avoids hammering Qdrant every 3s poll)
_consent_cache: dict = {"data": None, "ts": 0.0}
_CONSENT_TTL = 60.0


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _age(raw: dict | None) -> float:
    """Compute age in seconds from a timestamp field."""
    if raw is None:
        return 999.0
    ts = raw.get("timestamp", 0)
    if not ts:
        return 999.0
    if ts < 1e9:
        return time.monotonic() - ts
    return time.time() - ts


def _status(age: float, stale_threshold: float = 10.0) -> str:
    if age < stale_threshold:
        return "active"
    if age < 30.0:
        return "stale"
    return "offline"


def _stimmung_dimensions(stimmung: dict) -> dict:
    """Extract all dimension dicts (keys with value/trend/freshness_s sub-objects)."""
    dims = {}
    skip = {"overall_stance", "timestamp", "non_nominal_dimensions"}
    for key, val in stimmung.items():
        if key in skip or not isinstance(val, dict) or "value" not in val:
            continue
        dims[key] = {
            "value": val.get("value", 0.0),
            "trend": val.get("trend", "stable"),
            "freshness_s": round(val.get("freshness_s", 0.0), 1),
        }
    return dims


def _consent_coverage() -> dict:
    """Return cached consent coverage metrics (60s TTL)."""
    now = time.time()
    if _consent_cache["data"] is not None and (now - _consent_cache["ts"]) < _CONSENT_TTL:
        return _consent_cache["data"]
    try:
        from logos.data.governance import collect_consent_coverage

        cov = collect_consent_coverage()
        result = {
            "active_contracts": cov.active_contracts,
            "coverage_pct": round(cov.coverage_pct, 1),
        }
    except Exception:
        result = {"active_contracts": 0, "coverage_pct": 0.0}
    _consent_cache["data"] = result
    _consent_cache["ts"] = now
    return result


def _engine_status(request: Request) -> dict:
    """Get engine status from in-process engine instance."""
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        return {}
    try:
        s = engine.status
        return {
            "events_processed": s.get("events_processed", 0),
            "actions_executed": s.get("actions_executed", 0),
            "error_count": s.get("errors", 0),
            "rules_evaluated": s.get("rules_evaluated", 0),
            "novelty_score": round(s.get("novelty_score", 0.0), 3),
            "shift_score": round(s.get("shift_score", 0.0), 3),
            "uptime_s": round(s.get("uptime_s", 0.0), 0),
        }
    except Exception:
        return {}


@router.get("/state")
async def get_flow_state(request: Request) -> dict:
    """Return unified system flow state for the anatomy visualization.

    Dynamically discovers pipeline nodes from agent manifests, derives edges
    from layer adjacency + gates, and composites with runtime observations.
    """
    from logos.api.flow_discovery import (
        build_declared_edges,
        composite_edges,
        discover_pipeline_nodes,
    )
    from logos.api.flow_observer import FlowObserver

    # 1. Discover pipeline nodes from manifests
    nodes = discover_pipeline_nodes()

    # 2. Enrich synthetic nodes (no state file — computed from other sources)
    _enrich_synthetic_nodes(nodes, request)

    # 3. Build declared edges from layer rules + gates
    declared = build_declared_edges(nodes)

    # 4. Runtime observation
    global _observer
    if _observer is None:
        event_bus = getattr(request.app.state, "event_bus", None)
        _observer = FlowObserver(event_bus=event_bus)
        for node in nodes:
            sp = node.get("_state_path", "")
            if sp:
                _observer.register_reader(node["id"], sp)
    try:
        _observer.scan()
    except Exception:
        pass
    observed = _observer.get_observed_edges()

    # 5. Composite edges
    edges = composite_edges(declared, observed)

    # Strip internal fields
    for n in nodes:
        n.pop("_state_path", None)

    return {"nodes": nodes, "edges": edges, "timestamp": time.time()}


_observer: FlowObserver | None = None  # type: ignore[name-defined]


def _enrich_synthetic_nodes(nodes: list[dict], request: Request) -> None:
    """Fill in metrics for nodes without state files (synthesized from other sources)."""
    node_map = {n["id"]: n for n in nodes}

    # Phenomenal context: synthesized from temporal + apperception
    if "phenomenal_context" in node_map:
        pc = node_map["phenomenal_context"]
        temp_m = node_map.get("temporal_bands", {}).get("metrics", {})
        apper_m = node_map.get("apperception", {}).get("metrics", {})
        temp_age = node_map.get("temporal_bands", {}).get("age_s", 999)
        apper_age = node_map.get("apperception", {}).get("age_s", 999)
        pc["metrics"] = {
            "bound": temp_age < 30 and apper_age < 30,
            "coherence": apper_m.get("coherence", 0),
            "surprise": temp_m.get("max_surprise", 0),
        }
        pc["age_s"] = min(temp_age, apper_age)
        pc["status"] = _status(pc["age_s"])

    # Consent: from perception + Qdrant coverage
    if "consent" in node_map:
        cn = node_map["consent"]
        perc_m = node_map.get("hapax_daimonion", {}).get("metrics", {})
        cov = _consent_coverage()
        phase = perc_m.get("consent_phase", "none") if perc_m else "none"
        cn["metrics"] = {
            "phase": phase,
            "coverage_pct": cov.get("coverage_pct", 0),
            "active_contracts": cov.get("active_contracts", 0),
        }
        perc_age = node_map.get("hapax_daimonion", {}).get("age_s", 999)
        cn["age_s"] = round(perc_age, 1)
        cn["status"] = "active" if phase != "none" else "offline"

    # Voice pipeline: from perception voice_session
    if "voice_pipeline" in node_map:
        vp = node_map["voice_pipeline"]
        perc_path = node_map.get("hapax_daimonion", {}).get("_state_path", "")
        perc_data = _read(Path(perc_path)) if perc_path else None
        voice = (perc_data or {}).get("voice_session", {})
        vp["metrics"] = {
            "state": voice.get("state", "off"),
            "routing_activation": voice.get("routing_activation", 0),
            "turn_count": voice.get("turn_count", 0),
        }
        vp["status"] = "active" if voice.get("active") else "offline"
        vp["age_s"] = node_map.get("hapax_daimonion", {}).get("age_s", 999)

    # Reactive engine: from in-process engine
    if "reactive_engine" in node_map:
        re_node = node_map["reactive_engine"]
        engine = _engine_status(request)
        re_node["metrics"] = engine
        re_node["status"] = "active" if engine.get("uptime_s", 0) > 0 else "offline"
        re_node["age_s"] = 0 if re_node["status"] == "active" else 999


# ── Legacy endpoint kept for backward compatibility ──────────────────────


@router.get("/state/legacy")
async def get_flow_state_legacy(request: Request) -> dict:
    """Legacy hardcoded flow state — kept for reference."""
    now = time.time()
    nodes = []

    perception = _read(_PERCEPTION_PATH)
    perc_age = _age(perception)
    p = perception or {}

    stimmung = _read(_SHM_PATHS["stimmung"])
    stim_age = _age(stimmung)
    st = stimmung or {}

    temporal = _read(_SHM_PATHS["temporal"])
    temp_age = _age(temporal)
    t = temporal or {}

    apperception = _read(_SHM_PATHS["apperception"])
    apper_age = _age(apperception)
    model = (apperception or {}).get("self_model", {})

    compositor = _read(_SHM_PATHS["compositor"])
    comp_age = _age(compositor)
    c = compositor or {}

    # ── Perception ────────────────────────────────────────────────
    nodes.append(
        {
            "id": "perception",
            "label": "Perception",
            "status": _status(perc_age),
            "age_s": round(perc_age, 1),
            "metrics": {
                "activity": p.get("production_activity", ""),
                "flow_score": p.get("flow_score", 0.0),
                "presence_probability": p.get("presence_probability"),
                "face_count": p.get("face_count", 0),
                "consent_phase": p.get("consent_phase", "none"),
                "aggregate_confidence": p.get("aggregate_confidence"),
                "heart_rate_bpm": p.get("heart_rate_bpm"),
                "stress_elevated": p.get("stress_elevated", False),
                "interruptibility_score": p.get("interruptibility_score"),
            }
            if perception
            else {},
        }
    )

    # ── Stimmung ──────────────────────────────────────────────────
    dims = _stimmung_dimensions(st) if stimmung else {}
    non_nominal = st.get("non_nominal_dimensions", [])
    if not non_nominal and dims:
        non_nominal = [k for k, v in dims.items() if v["value"] > 0.4]
    nodes.append(
        {
            "id": "stimmung",
            "label": "Stimmung",
            "status": _status(stim_age, 120.0),
            "age_s": round(stim_age, 1),
            "metrics": {
                "stance": st.get("overall_stance", "unknown"),
                "health": st.get("health", {}).get("value"),
                "resource_pressure": st.get("resource_pressure", {}).get("value"),
                "dimensions": dims,
                "non_nominal": non_nominal,
            }
            if stimmung
            else {},
        }
    )

    # ── Temporal Bands ────────────────────────────────────────────
    impression = t.get("impression", {})
    nodes.append(
        {
            "id": "temporal",
            "label": "Temporal Bands",
            "status": _status(temp_age),
            "age_s": round(temp_age, 1),
            "metrics": {
                "max_surprise": t.get("max_surprise", 0.0),
                "retention_count": t.get("retention_count", 0),
                "protention_count": t.get("protention_count", 0),
                "surprise_count": t.get("surprise_count", 0),
                "flow_state": impression.get("flow_state", "idle"),
                "impression": {
                    "flow_score": impression.get("flow_score"),
                    "audio_energy": impression.get("audio_energy"),
                    "heart_rate": impression.get("heart_rate"),
                    "presence": impression.get("presence"),
                },
            }
            if temporal
            else {},
        }
    )

    # ── Apperception ──────────────────────────────────────────────
    raw_dims = model.get("dimensions", {})
    apper_dims = {}
    for name, dim in raw_dims.items():
        if isinstance(dim, dict):
            apper_dims[name] = {
                "confidence": dim.get("confidence", 0.0),
                "affirming": dim.get("affirming_count", 0),
                "problematizing": dim.get("problematizing_count", 0),
            }
    nodes.append(
        {
            "id": "apperception",
            "label": "Apperception",
            "status": _status(apper_age),
            "age_s": round(apper_age, 1),
            "metrics": {
                "coherence": model.get("coherence", 0.0),
                "dimensions": apper_dims,
                "observation_count": len(model.get("recent_observations", [])),
                "reflection_count": len(model.get("recent_reflections", [])),
                "pending_action_count": len((apperception or {}).get("pending_actions", [])),
            }
            if apperception
            else {},
        }
    )

    # ── Compositor ────────────────────────────────────────────────
    zone_opacities = c.get("zone_opacities", {})
    signals = c.get("signals", {})
    signal_count = sum(len(v) if isinstance(v, list) else 0 for v in signals.values())
    max_severity = 0.0
    for cat_signals in signals.values():
        if isinstance(cat_signals, list):
            for sig in cat_signals:
                if isinstance(sig, dict):
                    max_severity = max(max_severity, sig.get("severity", 0.0))
    ambient = c.get("ambient_params", {})
    nodes.append(
        {
            "id": "compositor",
            "label": "Compositor",
            "status": _status(comp_age),
            "age_s": round(comp_age, 1),
            "metrics": {
                "display_state": c.get("display_state", "unknown"),
                "zone_opacities": zone_opacities,
                "signal_count": signal_count,
                "max_severity": round(max_severity, 2),
                "ambient_speed": ambient.get("speed"),
                "ambient_turbulence": ambient.get("turbulence"),
            }
            if compositor
            else {},
        }
    )

    # ── Voice Pipeline ────────────────────────────────────────────
    voice_data = p.get("voice_session", {})
    if not voice_data:
        voice_data = c.get("voice_session", {})
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
                "frustration_score": voice_data.get("frustration_score", 0.0),
                "acceptance_type": voice_data.get("acceptance_type", ""),
            }
            if voice_active
            else {"active": False, "state": "off"},
        }
    )

    # ── Phenomenal Context ────────────────────────────────────────
    phenom_active = temp_age < 30.0 or apper_age < 30.0
    bound = temp_age < 30.0 and apper_age < 30.0
    active_dims = 0
    for dim in raw_dims.values():
        if isinstance(dim, dict):
            shift_time = dim.get("last_shift_time")
            if shift_time and (now - shift_time) < 300:
                active_dims += 1
    nodes.append(
        {
            "id": "phenomenal",
            "label": "Phenomenal Context",
            "status": "active" if phenom_active else "offline",
            "age_s": round(min(temp_age, apper_age), 1),
            "metrics": {
                "bound": bound,
                "coherence": model.get("coherence") if apper_age < 30.0 else None,
                "surprise": t.get("max_surprise") if temp_age < 30.0 else None,
                "active_dimensions": active_dims,
            },
        }
    )

    # ── Reactive Engine ───────────────────────────────────────────
    engine_metrics = _engine_status(request)
    engine_running = bool(engine_metrics.get("uptime_s", 0))
    nodes.append(
        {
            "id": "engine",
            "label": "Reactive Engine",
            "status": "active" if engine_running else "offline",
            "age_s": 0.0 if engine_running else 999.0,
            "metrics": engine_metrics,
        }
    )

    # ── Consent ───────────────────────────────────────────────────
    consent_phase = p.get("consent_phase", "none")
    cov = _consent_coverage()
    nodes.append(
        {
            "id": "consent",
            "label": "Consent",
            "status": "active" if consent_phase != "none" else "offline",
            "age_s": round(perc_age, 1),
            "metrics": {
                "phase": consent_phase,
                "active_contracts": cov.get("active_contracts", 0),
                "coverage_pct": cov.get("coverage_pct", 0.0),
            },
        }
    )

    # ── Edges ─────────────────────────────────────────────────────
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
        {
            "source": "engine",
            "target": "compositor",
            "active": engine_running,
            "label": "engine state",
        },
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
