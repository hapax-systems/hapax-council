#!/usr/bin/env python3
"""Export live Hapax state into DarkPlaces-readable text files.

DarkPlaces QuakeC can read files below the game directory, but cannot parse
JSON or upload live RGBA ward frames as textures. This exporter collapses the
current compositor/programme state into small ASCII lines that CSQC can render
inside the engine on top of the corresponding ward anchors.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

DEFAULT_GAME_DIR = Path.home() / ".darkplaces" / "screwm" / "data"
DEFAULT_SHM_DIR = Path("/dev/shm/hapax-compositor")
DEFAULT_MODE_FILE = Path.home() / ".cache" / "hapax" / "working-mode"
DEFAULT_REVERIE_UNIFORMS_FILE = Path("/dev/shm/hapax-imagination/uniforms.json")
DEFAULT_IMAGINATION_SOURCES_DIR = Path("/dev/shm/hapax-imagination/sources")
DEFAULT_IMAGINATION_CURRENT_FILE = Path("/dev/shm/hapax-imagination/current.json")
DEFAULT_SHADER_PLAN_FILE = Path("/dev/shm/hapax-imagination/pipeline/plan.json")
DEFAULT_ENTITY_LOCAL_EFFECT_STATE_FILE = Path(
    "/dev/shm/hapax-visual/entity-local-effect-state.json"
)
DEFAULT_STIMMUNG_STATE_FILE = Path("/dev/shm/hapax-stimmung/state.json")
DEFAULT_VISUAL_CHAIN_STATE_FILE = Path("/dev/shm/hapax-visual/visual-chain-state.json")
DEFAULT_EFFECT_DRIFT_STATE_FILE = Path("/dev/shm/hapax-visual/effect-drift-state.json")

WARD_ACTIVITY_EXPORTS: tuple[tuple[str, str], ...] = (
    ("01", "token_pole"),
    ("02", "album"),
    ("03", "stream_overlay"),
    ("04", "sierpinski"),
    ("05", "reverie"),
    ("06", "activity_header"),
    ("07", "stance_indicator"),
    ("08", "gem"),
    ("09", "grounding_provenance_ticker"),
    ("10", "impingement_cascade"),
    ("11", "recruitment_candidate_panel"),
    ("12", "thinking_indicator"),
    ("13", "pressure_gauge"),
    ("14", "activity_variety_log"),
    ("15", "whos_here"),
    ("16", "durf"),
    ("17", "coding_session_reveal"),
    ("18", "m8-display"),
    ("19", "steamdeck-display"),
    ("20", "egress_footer"),
    ("21", "programme_banner"),
    ("22", "precedent_ticker"),
    ("23", "programme_history"),
    ("24", "research_instrument_dashboard"),
    ("25", "cbip_signal_density"),
    ("26", "chat_ambient"),
    ("27", "chronicle_ticker"),
    ("28", "programme_state"),
    ("29", "polyend_instrument_reveal"),
    ("30", "interactive_lore_query"),
    ("31", "constructivist_research_poster"),
    ("32", "tufte_density"),
    ("33", "ascii_schematic"),
    ("34", "segment_content"),
    ("35", "m8_oscilloscope"),
    ("36", "cbip_dual_ir_displacement"),
)

WARD_EXPORTS: dict[str, str] = dict(WARD_ACTIVITY_EXPORTS)
IN_WORLD_WARD_COUNT = 36

SOURCE_EXPORTS: tuple[tuple[str, str], ...] = (
    ("01", "brio-operator"),
    ("02", "brio-room"),
    ("03", "brio-synths"),
    ("04", "c920-desk"),
    ("05", "c920-room"),
    ("06", "c920-overhead"),
)

CONTENT_SOURCE_EXPORTS: tuple[str, ...] = ("01", "02", "03", "04", "05", "06")

AOA_PANE_EXPORTS: tuple[tuple[str, str], ...] = (
    ("01", "root"),
    ("02", "tri_texture"),
    ("03", "data_glyph"),
    ("04", "signal_glyph"),
    ("05", "edge_accent"),
    ("06", "lod_gate"),
    ("07", "privacy_gate"),
    ("08", "source_posture"),
    ("09", "composition"),
    ("10", "payload_gate"),
)

LOCAL_EFFECT_EXPORTS: tuple[tuple[str, str], ...] = (
    ("01", "mirror"),
    ("02", "kaleidoscope"),
    ("03", "warp"),
    ("04", "fisheye"),
    ("05", "transform"),
    ("06", "displacement_map"),
    ("07", "droste"),
    ("08", "tunnel"),
    ("09", "tile"),
    ("10", "drift"),
    ("11", "breathing"),
)

VISUAL_CHAIN_EXPORTS: tuple[tuple[str, str], ...] = (
    ("01", "visual_chain.intensity"),
    ("02", "visual_chain.tension"),
    ("03", "visual_chain.diffusion"),
    ("04", "visual_chain.degradation"),
    ("05", "visual_chain.depth"),
    ("06", "visual_chain.pitch_displacement"),
    ("07", "visual_chain.temporal_distortion"),
    ("08", "visual_chain.spectral_color"),
    ("09", "visual_chain.coherence"),
)

EFFECT_DRIFT_FAMILIES: tuple[str, ...] = (
    "tonal",
    "atmospheric",
    "temporal",
    "texture",
    "edge",
)

EFFECT_DRIFT_NODE_FAMILY: dict[str, str] = {
    "color": "tonal",
    "colorgrade": "tonal",
    "palette": "tonal",
    "palette_remap": "tonal",
    "thermal": "tonal",
    "posterize": "tonal",
    "drift": "atmospheric",
    "mirror": "atmospheric",
    "kaleidoscope": "atmospheric",
    "fisheye": "atmospheric",
    "transform": "atmospheric",
    "tunnel": "atmospheric",
    "fb": "temporal",
    "feedback": "temporal",
    "trail": "temporal",
    "slitscan": "temporal",
    "stutter": "temporal",
    "post": "texture",
    "vhs": "texture",
    "scanlines": "texture",
    "halftone": "texture",
    "dither": "texture",
    "emboss": "texture",
    "grain_bump": "texture",
    "edge_detect": "edge",
    "threshold": "edge",
    "rutt_etra": "edge",
}

IMAGINATION_DIMENSION_EXPORTS: tuple[tuple[str, str], ...] = (
    ("01", "intensity"),
    ("02", "tension"),
    ("03", "depth"),
    ("04", "coherence"),
    ("05", "degradation"),
    ("06", "diffusion"),
    ("07", "spectral_color"),
    ("08", "temporal_distortion"),
    ("09", "pitch_displacement"),
)

IMAGINATION_MATERIAL_VALUES: dict[str, float] = {
    "water": 0.00,
    "fire": 0.25,
    "earth": 0.50,
    "air": 0.75,
    "void": 1.00,
}

VISUAL_ZONE_EXPORTS: tuple[tuple[str, str], ...] = (
    ("01", "work_tasks"),
    ("02", "health_infra"),
    ("03", "system_state"),
    ("04", "voice_session"),
    ("05", "ambient_sensor"),
    ("06", "governance"),
    ("07", "profile_state"),
    ("08", "context_time"),
)

VISUAL_DISPLAY_STATE_VALUES: dict[str, float] = {
    "idle": 0.15,
    "ready": 0.25,
    "receptive": 0.35,
    "present": 0.40,
    "alert": 0.85,
    "critical": 1.0,
}

STIMMUNG_STANCE_VALUES: dict[str, float] = {
    "nominal": 0.20,
    "seeking": 0.55,
    "cautious": 0.68,
    "degraded": 0.86,
    "critical": 1.0,
}

WARD_PROPERTY_Z_BASE: dict[str, float] = {
    "beyond-scrim": 0.2,
    "mid-scrim": 0.5,
    "on-scrim": 0.9,
    "surface-scrim": 1.0,
}

WARD_PROPERTY_DEFAULT_PLANES: dict[str, str] = {
    "stream_overlay": "surface-scrim",
    "stance_indicator": "surface-scrim",
    "thinking_indicator": "surface-scrim",
    "whos_here": "surface-scrim",
    "pressure_gauge": "surface-scrim",
    "durf": "surface-scrim",
    "precedent_ticker": "surface-scrim",
    "programme_history": "surface-scrim",
    "research_instrument_dashboard": "surface-scrim",
    "interactive_lore_query": "surface-scrim",
    "chat_ambient": "mid-scrim",
    "impingement_cascade": "mid-scrim",
    "sierpinski": "beyond-scrim",
    "album": "beyond-scrim",
}

WARD_PROPERTY_FRONT_STATE: dict[str, float] = {
    "integrated": 0.0,
    "retiring": 0.35,
    "fronting": 0.70,
    "fronted": 1.0,
}

SHADER_PLAN_GROUPS: dict[str, tuple[str, ...]] = {
    "color": ("color", "colorgrade", "palette", "palette_remap", "thermal"),
    "motion": ("drift", "warp", "transform", "fisheye", "displacement_map"),
    "feedback": ("fb", "feedback", "echo", "trail"),
    "post": ("post", "postprocess", "vignette", "bloom", "sharpen", "scanlines"),
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _one_line(value: object, *, limit: int = 54) -> str:
    text = "" if value is None else str(value)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + ">"
    return text


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text.rstrip("\n") + "\n")
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _copy_text(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    try:
        text = src.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    _write_atomic(dst, _one_line(text, limit=80))


def _percent(value: object) -> str:
    try:
        return f"{float(value) * 100:03.0f}%"
    except (TypeError, ValueError):
        return "000%"


def _float01(payload: dict[str, Any], key: str) -> float:
    try:
        value = float(payload.get(key, 0.0))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _entry_float(payload: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(payload.get(key, default))
    except (TypeError, ValueError):
        return default


def _nested_float(payload: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = payload.get(key)
    if isinstance(value, dict):
        return _clamp01(_entry_float(value, "value", default))
    return default


def _dict_float(payload: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(payload.get(key, default))
    except (TypeError, ValueError):
        return default


def _norm_abs_param(params: dict[str, Any], key: str, scale: float) -> float:
    scale = max(scale, 0.0001)
    return _clamp01(abs(_dict_float(params, key)) / scale)


def _read_float_file(path: Path, default: float = 0.0) -> float:
    try:
        value = float(path.read_text(encoding="utf-8", errors="ignore").strip())
    except (OSError, ValueError):
        return default
    return max(0.0, min(1.0, value))


def _read_text_file(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return default


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _active_ward_count(active_wards: dict[str, Any]) -> int:
    ward_ids = active_wards.get("ward_ids")
    if isinstance(ward_ids, list):
        return len(ward_ids)
    return 0


def _ward_activity_aliases(ward_id: str) -> set[str]:
    normalized = ward_id.strip().lower().replace("-", "_")
    aliases = {normalized}
    if normalized.endswith("_overlay"):
        aliases.add(normalized[: -len("_overlay")])
    return aliases


def _ward_property_aliases(ward_id: str) -> tuple[str, ...]:
    normalized = ward_id.strip()
    underscored = normalized.replace("-", "_")
    dashed = normalized.replace("_", "-")
    aliases = [normalized, underscored, dashed]
    if underscored.endswith("_overlay"):
        aliases.append(underscored[: -len("_overlay")])
    return tuple(dict.fromkeys(alias for alias in aliases if alias))


def _screwm_ward_count(active_wards: dict[str, Any]) -> int:
    """DarkPlaces hosts all legacy Screwm wards even without Cairo assignments."""
    return max(IN_WORLD_WARD_COUNT, _active_ward_count(active_wards))


def build_ward_activity_lines(active_wards: dict[str, Any]) -> dict[str, str]:
    ward_ids = active_wards.get("ward_ids")
    active_set = (
        {
            alias
            for ward_id in ward_ids
            if isinstance(ward_id, str)
            for alias in _ward_activity_aliases(ward_id)
        }
        if isinstance(ward_ids, list)
        else set()
    )
    return {
        f"ward-active-{ordinal}.txt": (
            "1.0000" if _ward_activity_aliases(ward_id) & active_set else "0.0000"
        )
        for ordinal, ward_id in WARD_ACTIVITY_EXPORTS
    }


def _live_ward_property_entries(properties: dict[str, Any]) -> dict[str, dict[str, Any]]:
    wards = properties.get("wards")
    if not isinstance(wards, dict):
        return {}
    now = time.time()
    entries: dict[str, dict[str, Any]] = {}
    for ward_id, entry in wards.items():
        if not isinstance(ward_id, str) or not isinstance(entry, dict):
            continue
        expires_at = entry.get("expires_at")
        if isinstance(expires_at, (int, float)) and now > float(expires_at):
            continue
        entries[ward_id] = entry
    return entries


def _ward_property_entry(
    entries: dict[str, dict[str, Any]],
    ward_id: str,
) -> dict[str, Any]:
    for alias in _ward_property_aliases(ward_id):
        if alias in entries:
            return entries[alias]
    fallback = entries.get("all")
    return fallback if fallback is not None else {}


def _ward_default_z_plane(ward_id: str) -> str:
    for alias in _ward_property_aliases(ward_id):
        if alias in WARD_PROPERTY_DEFAULT_PLANES:
            return WARD_PROPERTY_DEFAULT_PLANES[alias]
    return "on-scrim"


def _ward_property_scalars(ward_id: str, entry: dict[str, Any]) -> dict[str, float]:
    z_plane = str(entry.get("z_plane") or _ward_default_z_plane(ward_id))
    z_base = WARD_PROPERTY_Z_BASE.get(z_plane, WARD_PROPERTY_Z_BASE["on-scrim"])
    z_index_float = _clamp01(_entry_float(entry, "z_index_float", 0.5))
    depth = _clamp01(z_base + (z_index_float - 0.5) * 0.2)
    alpha = _clamp01(_entry_float(entry, "alpha", 1.0))
    glow = _clamp01(
        _entry_float(entry, "glow_radius_px", 0.0) / 64.0
        + _entry_float(entry, "border_pulse_hz", 0.0) / 4.0
    )
    scale = _clamp01(
        (_entry_float(entry, "scale", 1.0) - 1.0) / 0.35
        + _entry_float(entry, "scale_bump_pct", 0.0) / 0.25
    )
    if str(entry.get("drift_type", "sine")).lower() == "none":
        drift = 0.0
    else:
        drift = _clamp01(
            _entry_float(entry, "drift_amplitude_px", 3.0) / 24.0
            + _entry_float(entry, "drift_hz", 0.1) / 2.0
        )
    front = WARD_PROPERTY_FRONT_STATE.get(str(entry.get("front_state", "integrated")), 0.0)
    presence = _clamp01(
        max(0.0, alpha - 0.7) * 0.60
        + max(0.0, depth - 0.9) * 0.30
        + glow * 0.45
        + scale * 0.25
        + drift * 0.20
        + front * 0.35
    )
    return {
        "alpha": alpha,
        "depth": depth,
        "glow": glow,
        "scale": scale,
        "front": front,
        "drift": drift,
        "presence": presence,
    }


def build_ward_property_lines(shm_dir: Path) -> dict[str, str]:
    """Export WardProperties fishbowl/depth axes into in-scroom scalars."""
    entries = _live_ward_property_entries(_read_json(shm_dir / "ward-properties.json"))
    lines: dict[str, str] = {}
    live_scalars: list[dict[str, float]] = []
    for ordinal, ward_id in WARD_ACTIVITY_EXPORTS:
        entry = _ward_property_entry(entries, ward_id)
        scalars = _ward_property_scalars(ward_id, entry)
        if entry:
            live_scalars.append(scalars)
        for name, value in scalars.items():
            lines[f"ward-{name}-{ordinal}.txt"] = f"{value:.4f}"
    specific_count = sum(1 for key in entries if key != "all")

    def max_scalar(name: str) -> float:
        return max((item[name] for item in live_scalars), default=0.0)

    depth_pressure = max_scalar("depth")
    glow_pressure = max_scalar("glow")
    front_pressure = max_scalar("front")
    drift_pressure = max_scalar("drift")
    presence_pressure = max_scalar("presence")
    fishbowl_pressure = max(
        depth_pressure,
        glow_pressure,
        front_pressure,
        drift_pressure,
        presence_pressure,
    )
    lines["ward-property-count.txt"] = f"{specific_count:.4f}"
    lines["ward-property-active-ratio.txt"] = f"{_clamp01(specific_count / 36.0):.4f}"
    lines["ward-property-depth-pressure.txt"] = f"{depth_pressure:.4f}"
    lines["ward-property-glow-pressure.txt"] = f"{glow_pressure:.4f}"
    lines["ward-property-front-pressure.txt"] = f"{front_pressure:.4f}"
    lines["ward-property-drift-pressure.txt"] = f"{drift_pressure:.4f}"
    lines["ward-property-presence-pressure.txt"] = f"{presence_pressure:.4f}"
    lines["ward-property-fishbowl-pressure.txt"] = f"{fishbowl_pressure:.4f}"
    lines["ward-property-route.txt"] = "IN_SCROOM_FISHBOWL_WARD_PROPERTIES"
    return lines


def build_ward_lines(shm_dir: Path) -> dict[str, str]:
    active_segment = _read_json(shm_dir / "active-segment.json")
    active_wards = _read_json(shm_dir / "active_wards.json")
    album = _read_json(shm_dir / "album-state.json")
    voice = _read_json(shm_dir / "voice-state.json")
    token = _read_json(shm_dir / "token-ledger.json")
    reactivity = _read_json(shm_dir / "unified-reactivity.json")

    role = _one_line(active_segment.get("role", "idle"), limit=12).upper()
    topic = _one_line(active_segment.get("topic", "waiting for programme"), limit=34)
    beat = _one_line(active_segment.get("current_beat_text", ""), limit=48)
    source_refs = active_segment.get("source_refs")
    source_line = ""
    if isinstance(source_refs, list):
        source_line = _one_line(" ".join(str(item) for item in source_refs[:3]), limit=48)

    beat_index = active_segment.get("current_beat_index", 0)
    total_beats = active_segment.get("total_beats", 0)
    progress = _percent(active_segment.get("beat_progress", 0))

    artist = _one_line(album.get("artist", ""), limit=18)
    title = _one_line(album.get("title", ""), limit=22)
    album_line = _one_line(f"{artist} / {title}", limit=44) if artist or title else "NO ALBUM"

    blended = reactivity.get("blended") if isinstance(reactivity.get("blended"), dict) else {}
    rms = _percent(blended.get("rms", 0))
    onset = _percent(blended.get("onset", 0))

    speech = "VOICE ON" if voice.get("operator_speech_active") else "VOICE QUIET"
    active_count = _screwm_ward_count(active_wards)
    ward_ids = active_wards.get("ward_ids")
    active_line = "ACTIVE WAIT"
    if isinstance(ward_ids, list) and ward_ids:
        active_line = _one_line(" ".join(str(item).upper() for item in ward_ids[:3]), limit=44)
    token_line = _one_line(
        f"{int(token.get('total_tokens', 0)) // 1000}K TOK / {int(token.get('active_viewers', 0))} VIEW",
        limit=34,
    )

    return {
        "01": token_line,
        "02": album_line,
        "03": _one_line(f"STREAM {active_count:02d} WARDS", limit=34),
        "04": f"AOA RMS {rms} ON {onset}",
        "05": _one_line(f"REVERIE {progress} {role}", limit=34),
        "06": _one_line(f"ACT {active_line}", limit=44),
        "07": role or "NOMINAL",
        "08": _one_line(f"GEM {rms} {onset}", limit=34),
        "09": source_line or "SOURCE WAIT",
        "10": _one_line(f"IMPINGE {progress} {active_count:02d}", limit=34),
        "11": _one_line(f"RECRUIT {role}", limit=34),
        "12": f"{speech} / {active_count:02d} WARDS",
        "13": f"BEAT {progress} RMS {rms} ON {onset}",
        "14": _one_line(f"VARIETY {active_count:02d} ACTIVE", limit=34),
        "15": _one_line(f"HERE {int(token.get('active_viewers', 0))} VIEW", limit=34),
        "16": _one_line(f"DURF {role}", limit=34),
        "17": _one_line(f"CODE {topic}", limit=44),
        "18": _one_line(f"M8 RMS {rms}", limit=34),
        "19": _one_line(f"DECK ONSET {onset}", limit=34),
        "20": _one_line(f"EGRESS {progress}", limit=34),
        "21": _one_line(f"{role}: {topic}", limit=48),
        "22": _one_line(f"PRECED {source_line or role}", limit=44),
        "23": _one_line(f"HIST {role} {progress}", limit=34),
        "24": _one_line(f"INSTR RMS {rms} ON {onset}", limit=34),
        "25": _one_line(f"CBIP {rms}/{onset}", limit=34),
        "26": _one_line(f"CHAT {speech}", limit=34),
        "27": _one_line(f"CHRON {int(beat_index) + 1}/{int(total_beats or 0)}", limit=34),
        "28": _one_line(f"BEAT {int(beat_index) + 1}/{int(total_beats or 0)} {progress}", limit=32),
        "29": _one_line(f"POLY {album_line}", limit=34),
        "30": _one_line(f"QUERY {topic}", limit=44),
        "31": _one_line(f"POSTER {source_line or topic}", limit=44),
        "32": _one_line(f"TUFTE {active_count:02d} WARDS", limit=34),
        "33": _one_line(f"ASCII {progress}", limit=34),
        "34": beat or "SEGMENT WAIT",
        "35": _one_line(f"SCOPE RMS {rms} ON {onset}", limit=34),
        "36": _one_line(f"IRDUAL {rms}/{onset}", limit=34),
    }


def build_reverie_lines(uniforms_file: Path) -> dict[str, str]:
    """Collapse Reverie uniforms into QuakeC-readable scalar fields."""
    uniforms = _read_json(uniforms_file)
    salience = _float01(uniforms, "content.salience")
    trace = _float01(uniforms, "fb.trace_strength")
    temporal = max(
        _float01(uniforms, "signal.ward_fx_temporal_boost"),
        _float01(uniforms, "slot2_2_stutter.freeze_chance"),
        _float01(uniforms, "slot2_3_glitch_block.intensity"),
    )
    spectral = max(
        _float01(uniforms, "signal.ward_fx_spectral_boost"),
        _float01(uniforms, "signal.ward_fx_chromatic_boost"),
        _float01(uniforms, "slot0_1_chromatic_aberration.intensity"),
    )
    material = max(
        _float01(uniforms, "slot1_3_emboss.strength"),
        _float01(uniforms, "slot3_2_grain_bump.strength"),
        _float01(uniforms, "post.sediment_strength"),
        salience * 0.25,
    )
    inversion = max(
        _float01(uniforms, "slot3_1_invert.strength"),
        _float01(uniforms, "slot2_3_glitch_block.intensity") * 0.5,
        _float01(uniforms, "slot3_0_strobe.active") * 0.35,
    )
    aperture = max(
        _float01(uniforms, "post.vignette_strength"),
        _float01(uniforms, "slot0_0_vignette.strength"),
    )
    thermal = max(
        _float01(uniforms, "signal.color_warmth"),
        _float01(uniforms, "slot4_1_colorgrade.sepia"),
        _float01(uniforms, "content.intensity") * 0.20,
        spectral * 0.40,
    )
    return {
        "reverie-salience.txt": f"{salience:.4f}",
        "reverie-trace.txt": f"{trace:.4f}",
        "reverie-temporal.txt": f"{temporal:.4f}",
        "reverie-spectral.txt": f"{spectral:.4f}",
        "reverie-material.txt": f"{material:.4f}",
        "reverie-inversion.txt": f"{inversion:.4f}",
        "reverie-aperture.txt": f"{aperture:.4f}",
        "reverie-thermal.txt": f"{thermal:.4f}",
    }


def build_audio_lines(shm_dir: Path) -> dict[str, str]:
    reactivity = _read_json(shm_dir / "unified-reactivity.json")
    blended = reactivity.get("blended") if isinstance(reactivity.get("blended"), dict) else {}
    return {
        "audio-rms.txt": f"{_float01(blended, 'rms'):.4f}",
        "audio-onset.txt": f"{_float01(blended, 'onset'):.4f}",
    }


def build_homage_lines(shm_dir: Path, uniforms_file: Path) -> dict[str, str]:
    """Collapse the active HOMAGE package into QuakeC-readable scalars."""
    active = _read_json(shm_dir / "homage-active.json")
    substrate = _read_json(shm_dir / "homage-substrate-package.json")
    uniforms = _read_json(uniforms_file)

    package = active.get("package") or substrate.get("package") or "none"
    package = _one_line(package, limit=32) or "none"
    substrate_package = _one_line(substrate.get("package", package), limit=32) or "none"
    quake_active = 1.0 if package == "quake" or substrate_package == "quake" else 0.0

    try:
        hue = float(substrate.get("palette_accent_hue_deg", 0.0))
    except (TypeError, ValueError):
        hue = 0.0
    hue_norm = max(0.0, min(1.0, hue / 360.0))

    return {
        "homage-package.txt": package,
        "homage-substrate-package.txt": substrate_package,
        "homage-quake-active.txt": f"{quake_active:.4f}",
        "homage-transition-energy.txt": f"{_float01(uniforms, 'signal.homage_custom_4_0'):.4f}",
        "homage-accent-hue.txt": f"{hue_norm:.4f}",
        "homage-signature-intensity.txt": f"{_float01(uniforms, 'signal.homage_custom_4_2'):.4f}",
        "homage-rotation-phase.txt": f"{_float01(uniforms, 'signal.homage_custom_4_3'):.4f}",
    }


def _source_frame_freshness(source_dir: Path, now: float | None = None) -> float:
    frame_path = source_dir / "frame.rgba"
    manifest = _read_json(source_dir / "manifest.json")
    if not frame_path.exists():
        return 0.0
    try:
        age = (time.time() if now is None else now) - frame_path.stat().st_mtime
    except OSError:
        return 0.0
    ttl_ms = manifest.get("ttl_ms", 3000)
    try:
        ttl_s = max(1.0, float(ttl_ms) / 1000.0)
    except (TypeError, ValueError):
        ttl_s = 3.0
    return 1.0 if age <= ttl_s * 3.0 else 0.0


def _content_source_freshness(
    source_dir: Path,
    manifest: dict[str, Any],
    now: float | None = None,
) -> float:
    frame_path = source_dir / "frame.rgba"
    if not frame_path.exists():
        return 0.0
    try:
        age = (time.time() if now is None else now) - frame_path.stat().st_mtime
    except OSError:
        return 0.0
    ttl_ms = _entry_float(manifest, "ttl_ms", 3000.0)
    if ttl_ms <= 0:
        return 1.0
    ttl_s = max(1.0, ttl_ms / 1000.0)
    return 1.0 if age <= ttl_s * 3.0 else 0.0


def _content_source_entries(
    imagination_sources_dir: Path,
    now: float | None = None,
) -> list[dict[str, float | str]]:
    entries: list[dict[str, float | str]] = []
    try:
        source_dirs = [item for item in imagination_sources_dir.iterdir() if item.is_dir()]
    except OSError:
        source_dirs = []
    for source_dir in source_dirs:
        manifest = _read_json(source_dir / "manifest.json")
        source_id = _one_line(manifest.get("source_id", source_dir.name), limit=48)
        width = max(0.0, _entry_float(manifest, "width"))
        height = max(0.0, _entry_float(manifest, "height"))
        entries.append(
            {
                "source_id": source_id,
                "fresh": _content_source_freshness(source_dir, manifest, now),
                "opacity": _float01(manifest, "opacity"),
                "layer": _clamp01(_entry_float(manifest, "layer") / 6.0),
                "area": _clamp01((width * height) / float(1920 * 1080)),
                "z_order": _entry_float(manifest, "z_order"),
            }
        )
    return sorted(
        entries,
        key=lambda item: (
            float(item["fresh"]),
            float(item["opacity"]),
            float(item["z_order"]),
            str(item["source_id"]),
        ),
        reverse=True,
    )


def build_content_source_lines(
    imagination_sources_dir: Path = DEFAULT_IMAGINATION_SOURCES_DIR,
    now: float | None = None,
) -> dict[str, str]:
    """Export live RGBA content-source manifests as in-scroom source pressure."""
    entries = _content_source_entries(imagination_sources_dir, now)
    lines: dict[str, str] = {}
    for idx, ordinal in enumerate(CONTENT_SOURCE_EXPORTS):
        entry = entries[idx] if idx < len(entries) else {}
        lines[f"content-source-fresh-{ordinal}.txt"] = f"{float(entry.get('fresh', 0.0)):.4f}"
        lines[f"content-source-opacity-{ordinal}.txt"] = f"{float(entry.get('opacity', 0.0)):.4f}"
        lines[f"content-source-layer-{ordinal}.txt"] = f"{float(entry.get('layer', 0.0)):.4f}"
        lines[f"content-source-area-{ordinal}.txt"] = f"{float(entry.get('area', 0.0)):.4f}"
    lines["content-source-count.txt"] = (
        f"{_clamp01(len(entries) / float(len(CONTENT_SOURCE_EXPORTS))):.4f}"
    )
    lines["content-source-route.txt"] = "IN_SCROOM_CONTENT_SOURCE_MANIFESTS"
    return lines


def build_source_lines(
    shm_dir: Path,
    imagination_sources_dir: Path = DEFAULT_IMAGINATION_SOURCES_DIR,
    now: float | None = None,
) -> dict[str, str]:
    classifications = _read_json(shm_dir / "camera-classifications.json")
    lines: dict[str, str] = {}

    for ordinal, role in SOURCE_EXPORTS:
        details = classifications.get(role)
        details = details if isinstance(details, dict) else {}
        try:
            priority = float(details.get("ambient_priority", 0.0)) / 10.0
        except (TypeError, ValueError):
            priority = 0.0
        source_dir = imagination_sources_dir / f"camera-{role}"
        freshness = _source_frame_freshness(source_dir, now)
        lines[f"source-priority-{ordinal}.txt"] = f"{max(0.0, min(1.0, priority)):.4f}"
        lines[f"source-fresh-{ordinal}.txt"] = f"{freshness:.4f}"

    return lines


def build_aoa_pane_lines(
    shm_dir: Path,
    uniforms_file: Path,
    imagination_sources_dir: Path = DEFAULT_IMAGINATION_SOURCES_DIR,
    now: float | None = None,
) -> dict[str, str]:
    """Export current AoA pane-binding/gate pressure as in-world scalars."""
    active_segment = _read_json(shm_dir / "active-segment.json")
    active_wards = _read_json(shm_dir / "active_wards.json")
    uniforms = _read_json(uniforms_file)
    source_lines = build_source_lines(shm_dir, imagination_sources_dir, now)

    source_priority = [
        float(value) for key, value in source_lines.items() if key.startswith("source-priority-")
    ]
    source_freshness = [
        float(value) for key, value in source_lines.items() if key.startswith("source-fresh-")
    ]
    audio = build_audio_lines(shm_dir)
    homage = build_homage_lines(shm_dir, uniforms_file)

    try:
        beat_progress = float(active_segment.get("beat_progress", 0.0))
    except (TypeError, ValueError):
        beat_progress = 0.0
    active_ratio = min(1.0, _active_ward_count(active_wards) / float(IN_WORLD_WARD_COUNT))
    consent = _read_text_file(shm_dir / "consent-state.txt").lower()
    privacy_gate = 1.0 if consent in {"allowed", "allow", "public", "ok"} else 0.0
    voice = _read_float_file(shm_dir / "voice-active.txt")
    stimmung = _read_float_file(shm_dir / "stimmung-energy.txt", 0.5)

    signals = {
        "root": max(stimmung, _float01(uniforms, "content.salience")),
        "tri_texture": max(
            _float01(uniforms, "content.salience"),
            _float01(uniforms, "fb.trace_strength"),
        ),
        "data_glyph": active_ratio,
        "signal_glyph": max(float(audio["audio-onset.txt"]), voice),
        "edge_accent": max(source_priority, default=0.0),
        "lod_gate": _mean(source_freshness),
        "privacy_gate": privacy_gate,
        "source_posture": max(_mean(source_freshness), max(source_priority, default=0.0) * 0.5),
        "composition": max(0.0, min(1.0, beat_progress)),
        "payload_gate": max(
            float(homage["homage-quake-active.txt"]),
            float(homage["homage-transition-energy.txt"]),
            float(homage["homage-signature-intensity.txt"]),
        ),
    }

    return {
        f"aoa-pane-signal-{ordinal}.txt": f"{signals[name]:.4f}"
        for ordinal, name in AOA_PANE_EXPORTS
    }


def build_entity_local_effect_lines(effect_state_file: Path) -> dict[str, str]:
    """Export scene_quad.wgsl entity-local spatial effect activity."""
    effect_state = _read_json(effect_state_file)
    active_effects = effect_state.get("active_effects")
    active_effects = active_effects if isinstance(active_effects, list) else []
    mix_by_effect = {effect: 0.0 for _ordinal, effect in LOCAL_EFFECT_EXPORTS}

    for item in active_effects:
        if not isinstance(item, dict):
            continue
        effect = str(item.get("effect", "")).strip().lower()
        if effect not in mix_by_effect:
            continue
        mix_by_effect[effect] = max(mix_by_effect[effect], _float01(item, "mix"))

    lines = {
        f"local-effect-{ordinal}.txt": f"{mix_by_effect[effect]:.4f}"
        for ordinal, effect in LOCAL_EFFECT_EXPORTS
    }
    lines["local-effect-count.txt"] = f"{sum(1 for mix in mix_by_effect.values() if mix > 0):.4f}"
    lines["local-effect-route.txt"] = "ENTITY_LOCAL_SOURCE_PLANE"
    return lines


def _shader_plan_passes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    targets = plan.get("targets")
    if not isinstance(targets, dict):
        return []
    passes: list[dict[str, Any]] = []
    for target in targets.values():
        if not isinstance(target, dict):
            continue
        target_passes = target.get("passes")
        if not isinstance(target_passes, list):
            continue
        passes.extend(item for item in target_passes if isinstance(item, dict))
    return passes


def _shader_plan_pass_pressure(pass_row: dict[str, Any]) -> float:
    uniforms = pass_row.get("uniforms")
    uniforms = uniforms if isinstance(uniforms, dict) else {}
    param_order = pass_row.get("param_order")
    param_names = [str(item) for item in param_order] if isinstance(param_order, list) else []
    values = (
        [uniforms.get(name) for name in param_names] if param_names else list(uniforms.values())
    )
    pressure = 0.20
    for value in values:
        if isinstance(value, (int, float)):
            pressure = max(pressure, _clamp01(abs(float(value)) / 2.0))
    return pressure


def build_shader_plan_lines(shader_plan_file: Path = DEFAULT_SHADER_PLAN_FILE) -> dict[str, str]:
    """Export active imagination WGSL pass plan as in-scroom effect pressure."""
    passes = _shader_plan_passes(_read_json(shader_plan_file))
    pass_count = len(passes)
    render_count = sum(1 for item in passes if str(item.get("type") or "") == "render")
    temporal_count = sum(1 for item in passes if bool(item.get("temporal")))
    group_pressure = {name: 0.0 for name in SHADER_PLAN_GROUPS}

    for pass_row in passes:
        node_id = str(pass_row.get("node_id") or "").strip().lower()
        shader = str(pass_row.get("shader") or "").strip().lower().removesuffix(".wgsl")
        pressure = _shader_plan_pass_pressure(pass_row)
        for group, keys in SHADER_PLAN_GROUPS.items():
            if node_id in keys or shader in keys:
                group_pressure[group] = max(group_pressure[group], pressure)
        if bool(pass_row.get("temporal")):
            group_pressure["feedback"] = max(group_pressure["feedback"], pressure)

    return {
        "shader-plan-pass-count.txt": f"{_clamp01(pass_count / 8.0):.4f}",
        "shader-plan-render-ratio.txt": f"{_clamp01(render_count / max(pass_count, 1)):.4f}",
        "shader-plan-temporal-ratio.txt": f"{_clamp01(temporal_count / max(pass_count, 1)):.4f}",
        "shader-plan-color.txt": f"{group_pressure['color']:.4f}",
        "shader-plan-motion.txt": f"{group_pressure['motion']:.4f}",
        "shader-plan-feedback.txt": f"{group_pressure['feedback']:.4f}",
        "shader-plan-post.txt": f"{group_pressure['post']:.4f}",
        "shader-plan-route.txt": "IN_SCROOM_SHADER_PASS_PLAN",
    }


def _signal_severity(visual_state: dict[str, Any], category: str) -> float:
    signals = visual_state.get("signals")
    if not isinstance(signals, dict):
        return 0.0
    entries = signals.get(category)
    if not isinstance(entries, list):
        return 0.0
    values = [_float01(item, "severity") for item in entries if isinstance(item, dict)]
    return max(values, default=0.0)


def _transition_progress(transition: dict[str, Any]) -> float:
    started_at = _entry_float(transition, "started_at", 0.0)
    duration = max(0.1, _entry_float(transition, "duration_s", 2.0))
    if started_at <= 0:
        return 1.0
    return _clamp01((time.time() - started_at) / duration)


def build_visual_layer_lines(
    shm_dir: Path,
    stimmung_state_file: Path = DEFAULT_STIMMUNG_STATE_FILE,
) -> dict[str, str]:
    """Export old Scroom visual-layer/stimmung state into in-world scalars."""
    visual_state = _read_json(shm_dir / "visual-layer-state.json")
    stimmung_state = _read_json(stimmung_state_file)
    zone_opacities = visual_state.get("zone_opacities")
    zone_opacities = zone_opacities if isinstance(zone_opacities, dict) else {}
    ambient = visual_state.get("ambient_params")
    ambient = ambient if isinstance(ambient, dict) else {}
    transition = visual_state.get("transition")
    transition = transition if isinstance(transition, dict) else {}

    lines = {
        f"visual-zone-{ordinal}.txt": f"{max(_float01(zone_opacities, zone), _signal_severity(visual_state, zone)):.4f}"
        for ordinal, zone in VISUAL_ZONE_EXPORTS
    }
    display_state = str(
        visual_state.get("display_state") or visual_state.get("readiness") or "idle"
    )
    stance = str(
        stimmung_state.get("overall_stance") or visual_state.get("stimmung_stance") or "nominal"
    )
    lines.update(
        {
            "visual-display-state.txt": f"{VISUAL_DISPLAY_STATE_VALUES.get(display_state, 0.25):.4f}",
            "visual-stance.txt": f"{STIMMUNG_STANCE_VALUES.get(stance, 0.20):.4f}",
            "visual-ambient-speed.txt": f"{_clamp01(_entry_float(ambient, 'speed', 0.08) / 0.5):.4f}",
            "visual-ambient-turbulence.txt": f"{_float01(ambient, 'turbulence'):.4f}",
            "visual-ambient-warmth.txt": f"{_float01(ambient, 'color_warmth'):.4f}",
            "visual-ambient-brightness.txt": f"{_float01(ambient, 'brightness'):.4f}",
            "visual-audio-energy.txt": f"{_float01(ambient, 'audio_energy'):.4f}",
            "visual-transition-progress.txt": f"{_transition_progress(transition):.4f}",
            "stimmung-health.txt": f"{_nested_float(stimmung_state, 'health'):.4f}",
            "stimmung-resource.txt": f"{_nested_float(stimmung_state, 'resource_pressure'):.4f}",
            "stimmung-error.txt": f"{_nested_float(stimmung_state, 'error_rate'):.4f}",
            "stimmung-grounding.txt": f"{_nested_float(stimmung_state, 'grounding_quality'):.4f}",
            "stimmung-exploration.txt": f"{_nested_float(stimmung_state, 'exploration_deficit'):.4f}",
            "stimmung-audience.txt": f"{_nested_float(stimmung_state, 'audience_engagement'):.4f}",
            "stimmung-operator-energy.txt": f"{_nested_float(stimmung_state, 'operator_energy'):.4f}",
            "stimmung-coherence.txt": f"{_nested_float(stimmung_state, 'physiological_coherence'):.4f}",
            "stimmung-audio-presence.txt": f"{_nested_float(stimmung_state, 'audio_signal_presence'):.4f}",
            "visual-layer-route.txt": "IN_SCROOM_VISUAL_LAYER_STATE",
        }
    )
    return lines


def _effect_drift_family(pass_row: dict[str, Any]) -> str:
    family = str(pass_row.get("effect_family") or "").strip().lower()
    if family in EFFECT_DRIFT_FAMILIES:
        return family
    node_id = str(pass_row.get("node_id") or "").strip().lower()
    return EFFECT_DRIFT_NODE_FAMILY.get(node_id, "texture")


def _effect_drift_pass_strength(pass_row: dict[str, Any]) -> float:
    if pass_row.get("non_neutral") is False:
        return 0.0
    strength = _clamp01(abs(_entry_float(pass_row, "max_delta")) / 10.0)
    params = pass_row.get("params")
    if isinstance(params, list):
        for item in params:
            if isinstance(item, dict):
                strength = max(strength, _clamp01(abs(_entry_float(item, "delta")) / 10.0))
    if pass_row.get("non_neutral") is True:
        strength = max(strength, 0.20)
    return strength


def _effect_drift_region_count(passes: list[Any]) -> int:
    count = 0
    for pass_row in passes:
        if not isinstance(pass_row, dict):
            continue
        regions = pass_row.get("parameter_regions")
        if isinstance(regions, list):
            count += len(regions)
    return count


def build_visual_chain_lines(
    visual_chain_state_file: Path = DEFAULT_VISUAL_CHAIN_STATE_FILE,
    effect_drift_state_file: Path = DEFAULT_EFFECT_DRIFT_STATE_FILE,
) -> dict[str, str]:
    """Export visual-chain and effect-drift pressure as in-scroom scalars."""
    chain_state = _read_json(visual_chain_state_file)
    levels = chain_state.get("levels")
    levels = levels if isinstance(levels, dict) else {}
    params = chain_state.get("params")
    params = params if isinstance(params, dict) else {}

    lines = {
        f"visual-chain-{ordinal}.txt": f"{_clamp01(_dict_float(levels, key)):.4f}"
        for ordinal, key in VISUAL_CHAIN_EXPORTS
    }

    noise_pressure = max(
        _norm_abs_param(params, "noise.amplitude", 1.0),
        _norm_abs_param(params, "noise.frequency_x", 2.0),
        _norm_abs_param(params, "noise.speed", 0.15),
        _norm_abs_param(params, "noise.octaves", 3.0),
    )
    drift_pressure = max(
        _norm_abs_param(params, "drift.amplitude", 0.8),
        _norm_abs_param(params, "drift.speed", 0.5),
    )
    color_pressure = max(
        _norm_abs_param(params, "color.hue_rotate", 70.0),
        _norm_abs_param(params, "fb.hue_shift", 5.0),
        _norm_abs_param(params, "color.saturation", 0.6),
        _norm_abs_param(params, "color.brightness", 0.3),
    )
    feedback_pressure = _norm_abs_param(params, "fb.decay", 0.15)
    aperture_pressure = max(
        _norm_abs_param(params, "post.vignette_strength", 1.0),
        _norm_abs_param(params, "post.sediment_strength", 0.08),
    )
    max_level = max(
        (_clamp01(_dict_float(levels, key)) for _ord, key in VISUAL_CHAIN_EXPORTS), default=0.0
    )

    effect_state = _read_json(effect_drift_state_file)
    passes = effect_state.get("passes")
    passes = passes if isinstance(passes, list) else []
    pass_count = max(0.0, _entry_float(effect_state, "pass_count", float(len(passes))))
    non_neutral = max(
        0.0,
        _entry_float(
            effect_state,
            "non_neutral_pass_count",
            float(sum(1 for item in passes if isinstance(item, dict) and item.get("non_neutral"))),
        ),
    )
    family_strengths = {family: 0.0 for family in EFFECT_DRIFT_FAMILIES}
    max_delta = 0.0
    for pass_row in passes:
        if not isinstance(pass_row, dict):
            continue
        max_delta = max(max_delta, abs(_entry_float(pass_row, "max_delta")))
        family = _effect_drift_family(pass_row)
        family_strengths[family] = max(
            family_strengths.get(family, 0.0),
            _effect_drift_pass_strength(pass_row),
        )

    lines.update(
        {
            "visual-chain-noise.txt": f"{noise_pressure:.4f}",
            "visual-chain-drift.txt": f"{drift_pressure:.4f}",
            "visual-chain-color.txt": f"{color_pressure:.4f}",
            "visual-chain-feedback.txt": f"{feedback_pressure:.4f}",
            "visual-chain-aperture.txt": f"{aperture_pressure:.4f}",
            "visual-chain-param-pressure.txt": f"{max(noise_pressure, drift_pressure, color_pressure, feedback_pressure, aperture_pressure, max_level):.4f}",
            "effect-drift-pass-count.txt": f"{_clamp01(pass_count / 5.0):.4f}",
            "effect-drift-active-ratio.txt": f"{_clamp01(non_neutral / max(pass_count, 1.0)):.4f}",
            "effect-drift-max-delta.txt": f"{_clamp01(max_delta / 10.0):.4f}",
            "effect-drift-region-count.txt": f"{_clamp01(_effect_drift_region_count(passes) / 12.0):.4f}",
            "effect-drift-route.txt": "IN_SCROOM_EFFECT_DRIFT_STATE",
        }
    )
    for family, value in family_strengths.items():
        lines[f"effect-drift-{family}.txt"] = f"{value:.4f}"
    return lines


def build_imagination_fragment_lines(
    imagination_current_file: Path = DEFAULT_IMAGINATION_CURRENT_FILE,
) -> dict[str, str]:
    """Export the current imagination fragment as in-scroom intent pressure."""
    fragment = _read_json(imagination_current_file)
    dimensions = fragment.get("dimensions")
    dimensions = dimensions if isinstance(dimensions, dict) else {}
    material = str(fragment.get("material") or "water").strip().lower()
    continuation = 1.0 if bool(fragment.get("continuation")) else 0.0

    lines = {
        f"imagination-dim-{ordinal}.txt": f"{_clamp01(_dict_float(dimensions, key)):.4f}"
        for ordinal, key in IMAGINATION_DIMENSION_EXPORTS
    }
    lines.update(
        {
            "imagination-salience.txt": f"{_float01(fragment, 'salience'):.4f}",
            "imagination-continuation.txt": f"{continuation:.4f}",
            "imagination-material.txt": f"{IMAGINATION_MATERIAL_VALUES.get(material, 0.0):.4f}",
            "imagination-route.txt": "IN_SCROOM_IMAGINATION_FRAGMENT",
        }
    )
    return lines


def export_state(
    game_dir: Path,
    shm_dir: Path,
    mode_file: Path,
    uniforms_file: Path = DEFAULT_REVERIE_UNIFORMS_FILE,
    imagination_sources_dir: Path = DEFAULT_IMAGINATION_SOURCES_DIR,
    imagination_current_file: Path = DEFAULT_IMAGINATION_CURRENT_FILE,
    shader_plan_file: Path = DEFAULT_SHADER_PLAN_FILE,
    entity_local_effect_state_file: Path = DEFAULT_ENTITY_LOCAL_EFFECT_STATE_FILE,
    stimmung_state_file: Path = DEFAULT_STIMMUNG_STATE_FILE,
    visual_chain_state_file: Path = DEFAULT_VISUAL_CHAIN_STATE_FILE,
    effect_drift_state_file: Path = DEFAULT_EFFECT_DRIFT_STATE_FILE,
) -> None:
    game_dir.mkdir(parents=True, exist_ok=True)

    _copy_text(mode_file, game_dir / "working-mode.txt")
    _copy_text(shm_dir / "stimmung-energy.txt", game_dir / "stimmung-energy.txt")
    _copy_text(shm_dir / "voice-active.txt", game_dir / "voice-active.txt")

    ward_lines = build_ward_lines(shm_dir)
    for ordinal, ward_id in WARD_EXPORTS.items():
        line = ward_lines.get(ordinal, ward_id.upper())
        _write_atomic(game_dir / f"ward-{ordinal}.txt", line)
    active_wards = _read_json(shm_dir / "active_wards.json")
    for filename, line in build_ward_activity_lines(active_wards).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_ward_property_lines(shm_dir).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_reverie_lines(uniforms_file).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_audio_lines(shm_dir).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_homage_lines(shm_dir, uniforms_file).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_source_lines(shm_dir, imagination_sources_dir).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_content_source_lines(imagination_sources_dir).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_aoa_pane_lines(
        shm_dir, uniforms_file, imagination_sources_dir
    ).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_entity_local_effect_lines(entity_local_effect_state_file).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_shader_plan_lines(shader_plan_file).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_visual_layer_lines(shm_dir, stimmung_state_file).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_visual_chain_lines(
        visual_chain_state_file, effect_drift_state_file
    ).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_imagination_fragment_lines(imagination_current_file).items():
        _write_atomic(game_dir / filename, line)

    active_segment = _read_json(shm_dir / "active-segment.json")
    _write_atomic(
        game_dir / "programme-line.txt",
        _one_line(active_segment.get("topic", "programme waiting"), limit=64),
    )
    _write_atomic(
        game_dir / "active-wards-line.txt",
        f"{_screwm_ward_count(active_wards):02d} IN-SCROOM WARDS",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    parser.add_argument("--shm-dir", type=Path, default=DEFAULT_SHM_DIR)
    parser.add_argument("--mode-file", type=Path, default=DEFAULT_MODE_FILE)
    parser.add_argument("--uniforms-file", type=Path, default=DEFAULT_REVERIE_UNIFORMS_FILE)
    parser.add_argument(
        "--imagination-sources-dir", type=Path, default=DEFAULT_IMAGINATION_SOURCES_DIR
    )
    parser.add_argument(
        "--imagination-current-file",
        type=Path,
        default=DEFAULT_IMAGINATION_CURRENT_FILE,
    )
    parser.add_argument("--shader-plan-file", type=Path, default=DEFAULT_SHADER_PLAN_FILE)
    parser.add_argument(
        "--entity-local-effect-state-file",
        type=Path,
        default=DEFAULT_ENTITY_LOCAL_EFFECT_STATE_FILE,
    )
    parser.add_argument("--stimmung-state-file", type=Path, default=DEFAULT_STIMMUNG_STATE_FILE)
    parser.add_argument(
        "--visual-chain-state-file",
        type=Path,
        default=DEFAULT_VISUAL_CHAIN_STATE_FILE,
    )
    parser.add_argument(
        "--effect-drift-state-file",
        type=Path,
        default=DEFAULT_EFFECT_DRIFT_STATE_FILE,
    )
    parser.add_argument("--copy-self-test", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.copy_self_test is not None:
        shutil.copy2(__file__, args.copy_self_test)
        return 0

    export_state(
        args.game_dir,
        args.shm_dir,
        args.mode_file,
        args.uniforms_file,
        args.imagination_sources_dir,
        args.imagination_current_file,
        args.shader_plan_file,
        args.entity_local_effect_state_file,
        args.stimmung_state_file,
        args.visual_chain_state_file,
        args.effect_drift_state_file,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
