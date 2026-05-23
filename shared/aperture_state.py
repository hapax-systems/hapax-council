"""Unified aperture state snapshot for cross-aperture awareness.

Reads per-aperture health + state files from /dev/shm and writes
a unified snapshot. Any aperture can read the snapshot to know what
the rest of the system is doing — enabling self-grounding.

Zero external dependencies — stdlib only (json, time, pathlib, os).
Safe to import from any module. Follows patterns from:
- control_signal.py (publish_health atomic write)
- apperception_shm.py (read_apperception_block staleness-gated reader)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

SNAPSHOT_PATH = Path("/dev/shm/hapax-aperture-state/snapshot.json")
_STALENESS_THRESHOLD = 30  # seconds — matches apperception_shm

_STATE_SOURCES: dict[str, dict[str, Path]] = {
    "stimmung": {
        "health": Path("/dev/shm/hapax-stimmung/health.json"),
        "state": Path("/dev/shm/hapax-stimmung/state.json"),
    },
    "compositor": {
        "health": Path("/dev/shm/hapax-compositor/health.json"),
        "segment": Path("/dev/shm/hapax-compositor/active-segment.json"),
    },
    "daimonion": {
        "health": Path("/dev/shm/hapax-voice_daemon/health.json"),
        "consent": Path("/dev/shm/hapax-daimonion/consent-state.json"),
    },
    "imagination": {
        "health": Path("/dev/shm/hapax-imagination/health.json"),
        "current": Path("/dev/shm/hapax-imagination/current.json"),
    },
    "reverie": {
        "health": Path("/dev/shm/hapax-reverie/health.json"),
    },
    "dmn": {
        "health": Path("/dev/shm/hapax-dmn/health.json"),
    },
    "apperception": {
        "state": Path("/dev/shm/hapax-apperception/self-band.json"),
    },
    "broadcast": {
        "health": Path("/dev/shm/hapax-broadcast/audio-safe-for-broadcast.json"),
    },
    "logos": {
        "health": Path("/dev/shm/hapax-logos/health.json"),
    },
    "voice_pipeline": {
        "health": Path("/dev/shm/hapax-voice_pipeline/health.json"),
    },
    "reactive_engine": {
        "health": Path("/dev/shm/hapax-reactive_engine/health.json"),
    },
    "content_resolver": {
        "health": Path("/dev/shm/hapax-content_resolver/health.json"),
    },
    "consent_engine": {
        "health": Path("/dev/shm/hapax-consent_engine/health.json"),
    },
    "ir_perception": {
        "health": Path("/dev/shm/hapax-ir_perception/health.json"),
    },
    "temporal_bands": {
        "health": Path("/dev/shm/hapax-temporal_bands/health.json"),
    },
    "contact_mic": {
        "health": Path("/dev/shm/hapax-contact_mic/health.json"),
    },
}

_HEALTH_STALE_S = 120.0


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _extract_health(data: dict | None, now: float) -> dict:
    if data is None:
        return {"error": None, "stale": True}
    try:
        ts = float(data.get("timestamp", 0) or 0)
        err = float(data.get("error", 1.0))
    except (TypeError, ValueError):
        return {"error": None, "stale": True}
    return {"error": round(err, 3), "stale": (now - ts) > _HEALTH_STALE_S}


def _extract_stimmung(data: dict | None) -> dict:
    if data is None:
        return {}
    return {
        "stance": data.get("overall_stance", "unknown"),
    }


def _extract_segment(data: dict | None) -> dict:
    if data is None:
        return {}
    return {
        "role": data.get("role", "unknown"),
        "topic": data.get("topic", ""),
        "beat_progress": data.get("beat_progress"),
    }


def _extract_consent(data: dict | None) -> dict:
    if data is None:
        return {}
    return {"phase": data.get("phase", "unknown")}


def _extract_imagination(data: dict | None) -> dict:
    if data is None:
        return {}
    return {
        "narrative": (data.get("narrative") or "")[:100],
        "salience": data.get("salience"),
    }


def _extract_apperception(data: dict | None) -> dict:
    if data is None:
        return {}
    model = data.get("self_model", {})
    return {"coherence": model.get("coherence")}


def _extract_broadcast(data: dict | None) -> dict:
    if data is None:
        return {}
    return {"status": data.get("status", "unknown")}


def write_aperture_snapshot(
    *, sources: dict[str, dict[str, Path]] | None = None, path: Path = SNAPSHOT_PATH
) -> dict:
    """Read all aperture state files and write unified snapshot.

    Returns the snapshot dict for callers that need it inline.
    """
    src = sources or _STATE_SOURCES
    now = time.time()
    apertures: dict[str, dict] = {}

    for name, paths in src.items():
        entry: dict = {"component": name}

        health_data = _read_json(paths["health"]) if "health" in paths else None
        entry.update(_extract_health(health_data, now))

        if "state" in paths and name == "stimmung":
            entry.update(_extract_stimmung(_read_json(paths["state"])))
        elif "state" in paths and name == "apperception":
            entry.update(_extract_apperception(_read_json(paths["state"])))
        if "segment" in paths:
            entry.update(_extract_segment(_read_json(paths["segment"])))
        if "consent" in paths:
            entry.update(_extract_consent(_read_json(paths["consent"])))
        if "current" in paths:
            entry.update(_extract_imagination(_read_json(paths["current"])))
        if name == "broadcast" and "health" in paths:
            entry.update(_extract_broadcast(health_data))

        apertures[name] = entry

    snapshot = {"timestamp": now, "apertures": apertures}

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    tmp.write_text(json.dumps(snapshot), encoding="utf-8")
    tmp.replace(path)

    return snapshot


def read_aperture_state_block(path: Path = SNAPSHOT_PATH) -> str:
    """Read unified aperture snapshot and format for prompt injection.

    Returns natural-language orientation block. Returns empty string
    if snapshot is missing, stale (>30s), or has no aperture data.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        ts = raw.get("timestamp", 0)
        if ts > 0 and (time.time() - ts) > _STALENESS_THRESHOLD:
            return ""

        apertures = raw.get("apertures", {})
        if not apertures:
            return ""

        lines: list[str] = ["System apertures (what the rest of the system is doing right now):"]

        _state_keys = {"stance", "role", "phase", "narrative", "coherence", "status"}
        for name, entry in apertures.items():
            has_state = bool(_state_keys & entry.keys())
            if not has_state and entry.get("stale", True) and entry.get("error") is None:
                continue

            parts: list[str] = []

            err = entry.get("error")
            if err is not None:
                label = "healthy" if err < 0.3 else "degraded" if err < 0.7 else "critical"
                parts.append(label)

            if "stance" in entry:
                parts.append(f"stance {entry['stance']}")
            if "role" in entry and "topic" in entry:
                role = entry["role"]
                topic = entry["topic"]
                if topic:
                    parts.append(f'segment "{role}" on "{topic}"')
                else:
                    parts.append(f'segment "{role}"')
                prog = entry.get("beat_progress")
                if prog is not None:
                    parts.append(f"{prog:.0%} through")
            if "phase" in entry:
                parts.append(f"consent {entry['phase']}")
            if "narrative" in entry:
                narr = entry["narrative"]
                if narr:
                    parts.append(f'rendering "{narr}"')
                sal = entry.get("salience")
                if sal is not None:
                    parts.append(f"salience {sal:.2f}")
            if "coherence" in entry:
                coh = entry["coherence"]
                if coh is not None:
                    label = "coherent" if coh > 0.6 else "settling" if coh > 0.4 else "rebuilding"
                    parts.append(f"self-model {label} ({coh:.2f})")
            if "status" in entry:
                parts.append(entry["status"])

            if parts:
                lines.append(f"  {name}: {', '.join(parts)}")

        if len(lines) <= 1:
            return ""

        return "\n".join(lines)
    except Exception:
        return ""
