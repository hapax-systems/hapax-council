#!/usr/bin/env python3
"""HARDM signal publisher — writes cell values to SHM.

Reads each primary HARDM signal's canonical source (perception-state,
narrative-state, stimmung, consent, active homage package, etc.) and
emits a single JSON payload at
``/dev/shm/hapax-compositor/hardm-cell-signals.json`` for the HARDM
consumer (``HardmDotMatrix``) to read on each Cairo tick.

This is a stub — not every canonical source is yet plumbed. Missing
values are written as ``null`` so the consumer renders them idle
(except ``consent_gate`` which fails closed to stress, per spec §3).

Run as one-shot via systemd timer or cron. Fast, stateless, atomic
tmp+rename write.

Spec: ``docs/superpowers/specs/2026-04-18-hardm-dot-matrix-design.md``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("hardm-publish-signals")

OUT_FILE = Path("/dev/shm/hapax-compositor/hardm-cell-signals.json")

# Canonical input paths. These were previously wrong in several places;
# verified against the live filesystem 2026-04-20:
#   * perception-state publishes to ``~/.cache/hapax-daimonion/`` (the
#     daimonion does NOT use /dev/shm for this file).
#   * stimmung writes ``/dev/shm/hapax-stimmung/state.json`` (no
#     ``stimmung-state.json`` lives under hapax-daimonion).
#   * the homage rotator publishes ``homage-active-artefact.json``; the
#     old ``homage-active.json`` was stale and never populated.
_PERCEPTION_STATE = Path.home() / ".cache/hapax-daimonion/perception-state.json"
_NARRATIVE_STATE = Path("/dev/shm/hapax-director/narrative-state.json")
_STIMMUNG_STATE = Path("/dev/shm/hapax-stimmung/state.json")
_DEGRADED_FLAG = Path("/dev/shm/hapax-compositor/degraded.flag")
_UNIFORMS_JSON = Path("/dev/shm/hapax-imagination/uniforms.json")
_HOMAGE_ACTIVE = Path("/dev/shm/hapax-compositor/homage-active-artefact.json")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        log.debug("failed to read %s", path, exc_info=True)
        return {}


def _read_flag(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size >= 0
    except Exception:
        return False


def _watch_hr_bucket(bpm: float | None) -> float | None:
    """Bucket watch HR into 0.33/0.66/1.0 bands (rest → elevated).

    Returns ``None`` for missing or zero readings — the perception engine
    emits 0 when no watch sample is available, which should render as
    idle not as a spurious "rest" signal.
    """
    if bpm is None or bpm <= 0:
        return None
    if bpm < 55:
        return 0.33
    if bpm < 75:
        return 0.66
    if bpm < 95:
        return 0.33
    return 1.0


def _stimmung_value(entry: object) -> float | None:
    """Extract the numeric ``value`` field from a stimmung dimension entry.

    Stimmung writes each dimension as ``{"value": <float>, "trend": str,
    "freshness_s": float}``. Older / partial payloads may ship bare
    floats. Tolerate both shapes.
    """
    if isinstance(entry, dict):
        value = entry.get("value")
        if isinstance(value, (int, float)):
            return float(value)
        return None
    if isinstance(entry, (int, float)):
        return float(entry)
    return None


def _collect_signals() -> dict[str, Any]:
    """Collect the 16 primary HARDM signals from their canonical sources."""
    perception = _read_json(_PERCEPTION_STATE)
    narrative = _read_json(_NARRATIVE_STATE)
    stimmung = _read_json(_STIMMUNG_STATE)
    uniforms = _read_json(_UNIFORMS_JSON)
    homage_active = _read_json(_HOMAGE_ACTIVE)

    signals: dict[str, Any] = {}

    # timing family — perception schema key is `mixer_active`, not
    # `midi_active`. The signal name on the ward side stays `midi_active`
    # for back-compat with spec §3; the publisher bridges to the real
    # schema key here.
    signals["midi_active"] = bool(perception.get("mixer_active"))

    # operator family. VAD is published as a continuous confidence float
    # (`vad_confidence`); treat > 0.4 as speech-active. bt_phone is not
    # emitted by the perception engine, so we derive a best-effort proxy
    # from `operator_present` for now (a dedicated BT connection signal
    # is a separate follow-up). `heart_rate_bpm` replaces the old
    # `watch_hr_bpm`; `screen_focus` maps to `desktop_active` on the
    # perception side (`screen_focus` on the ward side).
    vad_conf = perception.get("vad_confidence")
    if isinstance(vad_conf, (int, float)):
        signals["vad_speech"] = bool(vad_conf > 0.4)
    else:
        signals["vad_speech"] = False
    signals["watch_hr"] = _watch_hr_bucket(perception.get("heart_rate_bpm"))
    signals["bt_phone"] = bool(perception.get("operator_present"))
    signals["kde_connect"] = bool(perception.get("phone_kde_connected"))
    signals["screen_focus"] = bool(perception.get("desktop_active"))

    # perception family. The perception engine emits `person_count` and
    # `face_count`; `room_occupancy_count` never existed. Use the max of
    # the two as the best proxy for "how many bodies are in the room".
    person_count = perception.get("person_count")
    face_count = perception.get("face_count")
    room_count: int | None = None
    if isinstance(person_count, (int, float)) or isinstance(face_count, (int, float)):
        room_count = int(max(person_count or 0, face_count or 0))
    if room_count is not None:
        # Level-3 bucketing: 0 → idle, 1 → 0.5, 2+ → 1.0.
        if room_count <= 0:
            signals["room_occupancy"] = 0.0
        elif room_count == 1:
            signals["room_occupancy"] = 0.5
        else:
            signals["room_occupancy"] = 1.0
    else:
        signals["room_occupancy"] = None

    signals["ir_person_detected"] = bool(perception.get("ir_person_detected"))

    # Ambient-sound schema key is `audio_energy_rms` (continuous). The
    # previous `ambient_sound_level` never existed. Normalise an RMS
    # energy in the 0..1 range.
    ambient = perception.get("audio_energy_rms")
    if isinstance(ambient, (int, float)):
        signals["ambient_sound"] = float(max(0.0, min(1.0, ambient)))
    else:
        signals["ambient_sound"] = None

    # cognition family. The stimmung publisher writes `overall_stance`
    # (the single source of truth) and `operator_energy` as the closest
    # analogue to the old `stimmung_energy` concept. Narrative state
    # does not exist as a separate file on the running system — stance
    # is always sourced from stimmung.
    stance = stimmung.get("overall_stance") or narrative.get("stance")
    signals["director_stance"] = str(stance).lower() if stance else None
    # Stimmung wraps each dimension as ``{"value": float, ...}``; extract
    # the value. Prefer operator_energy; audience_engagement as fallback
    # when operator_energy is missing.
    stim_energy = _stimmung_value(stimmung.get("operator_energy"))
    if stim_energy is None:
        stim_energy = _stimmung_value(stimmung.get("audience_engagement"))
    if stim_energy is not None:
        signals["stimmung_energy"] = float(max(0.0, min(1.0, stim_energy)))
    else:
        signals["stimmung_energy"] = None

    shader_energy = uniforms.get("signal.homage_custom_4_0")
    if isinstance(shader_energy, (int, float)):
        signals["shader_energy"] = float(max(0.0, min(1.0, shader_energy)))
    else:
        signals["shader_energy"] = None

    reverie_pass = uniforms.get("signal.reverie_pass")
    if isinstance(reverie_pass, (int, float)):
        # Normalise: 8 passes → 0..1.
        signals["reverie_pass"] = float(max(0.0, min(1.0, reverie_pass / 8.0)))
    else:
        signals["reverie_pass"] = None

    # governance family
    consent_state = _consent_state()
    signals["consent_gate"] = consent_state

    signals["degraded_stream"] = _read_flag(_DEGRADED_FLAG)

    # The homage publisher file is `homage-active-artefact.json` on the
    # running system; the top-level key is `package` per its schema.
    pkg_name = homage_active.get("package")
    if not isinstance(pkg_name, str):
        # Fallback: the artefact file nests package info under `substrate`.
        substrate = homage_active.get("substrate")
        if isinstance(substrate, dict):
            pkg_name = substrate.get("package")
    signals["homage_package"] = pkg_name if isinstance(pkg_name, str) else None

    return signals


def _consent_state() -> str | None:
    """Return consent state string or ``None``. Best-effort import."""
    try:
        from shared.consent import ConsentRegistry

        registry = ConsentRegistry()
        # ConsentRegistry API varies; we just test for any active contract.
        has_active = bool(getattr(registry, "list_active", lambda: [])())
        return "ok" if has_active else "blocked"
    except Exception:
        return None


def publish(signals: dict[str, Any]) -> None:
    """Atomic tmp+rename write."""
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.time(),
        "signals": signals,
    }
    tmp = OUT_FILE.with_suffix(OUT_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
    os.replace(tmp, OUT_FILE)


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("HARDM_PUBLISH_LOG_LEVEL", "WARNING"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signals = _collect_signals()
    publish(signals)
    return 0


if __name__ == "__main__":
    sys.exit(main())
