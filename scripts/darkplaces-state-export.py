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
DEFAULT_GEM_RECRUITMENT_FILE = Path("/dev/shm/hapax-gem/recruitment.json")
DEFAULT_GEM_FRAMES_FILE = Path("/dev/shm/hapax-gem/gem-frames.json")
DEFAULT_LEGACY_GEM_FRAMES_FILE = Path("/dev/shm/hapax-compositor/gem-frames.json")
DEFAULT_RECENT_IMPINGEMENTS_FILE = Path("/dev/shm/hapax-compositor/recent-impingements.json")
DEFAULT_RECENT_RECRUITMENT_FILE = Path("/dev/shm/hapax-compositor/recent-recruitment.json")
DEFAULT_DAIMONION_CONSENT_FILE = Path("/dev/shm/hapax-daimonion/consent-state.json")
DEFAULT_ENTITY_LOCAL_EFFECT_STATE_FILE = Path(
    "/dev/shm/hapax-visual/entity-local-effect-state.json"
)
DEFAULT_STIMMUNG_STATE_FILE = Path("/dev/shm/hapax-stimmung/state.json")
DEFAULT_VISUAL_CHAIN_STATE_FILE = Path(
    os.environ.get(
        "HAPAX_DARKPLACES_VISUAL_CHAIN_STATE_FILE",
        "/dev/shm/hapax-visual/visual-chain-state.json",
    )
)
DEFAULT_VISUAL_CHAIN_FALLBACK_STATE_FILE = Path(
    os.environ.get(
        "HAPAX_DARKPLACES_VISUAL_CHAIN_FALLBACK_STATE_FILE",
        "/dev/shm/hapax-visual/screwm-visual-chain-state.json",
    )
)
DEFAULT_EFFECT_DRIFT_STATE_FILE = Path("/dev/shm/hapax-visual/effect-drift-state.json")
DEFAULT_EFFECT_DRIFT_FALLBACK_STATE_FILE = Path(
    os.environ.get(
        "HAPAX_DARKPLACES_EFFECT_DRIFT_FALLBACK_STATE_FILE",
        "/dev/shm/hapax-visual/screwm-effect-drift-fallback-state.json",
    )
)

WARD_ACTIVITY_EXPORTS: tuple[tuple[str, str], ...] = (
    ("01", "token_pole"),
    ("02", "album"),
    ("03", "stream_overlay"),
    ("04", "aoa_oarb_state"),
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
    "compositing",
)

EFFECT_DRIFT_NODE_FAMILY: dict[str, str] = {
    "color": "tonal",
    "colorgrade": "tonal",
    "bloom": "tonal",
    "invert": "tonal",
    "vignette": "tonal",
    "palette": "tonal",
    "palette_remap": "tonal",
    "thermal": "tonal",
    "posterize": "tonal",
    "color_map": "tonal",
    "nightvision_tint": "tonal",
    "drift": "atmospheric",
    "chromatic_aberration": "atmospheric",
    "mirror": "atmospheric",
    "kaleidoscope": "atmospheric",
    "fisheye": "atmospheric",
    "transform": "atmospheric",
    "warp": "atmospheric",
    "displacement_map": "atmospheric",
    "pixsort": "atmospheric",
    "droste": "atmospheric",
    "tile": "atmospheric",
    "tunnel": "atmospheric",
    "breathing": "atmospheric",
    "fb": "temporal",
    "feedback": "temporal",
    "trail": "temporal",
    "echo": "temporal",
    "slitscan": "temporal",
    "stutter": "temporal",
    "diff": "temporal",
    "fluid_sim": "temporal",
    "reaction_diffusion": "temporal",
    "post": "texture",
    "postprocess": "texture",
    "ascii": "texture",
    "vhs": "texture",
    "glitch_block": "texture",
    "scanlines": "texture",
    "halftone": "texture",
    "sharpen": "texture",
    "kuwahara": "texture",
    "noise_overlay": "texture",
    "noise_gen": "texture",
    "particle_system": "texture",
    "strobe": "texture",
    "dither": "texture",
    "emboss": "texture",
    "grain_bump": "texture",
    "edge_detect": "edge",
    "threshold": "edge",
    "rutt_etra": "edge",
    "voronoi_overlay": "edge",
    "waveform_render": "edge",
    "blend": "compositing",
    "chroma_key": "compositing",
    "crossfade": "compositing",
    "luma_key": "compositing",
}

EFFECT_DRIFT_MODE_VALUES: dict[str, dict[str, float]] = {
    "tonal": {
        "color": 0.10,
        "colorgrade": 0.10,
        "bloom": 0.22,
        "invert": 0.36,
        "vignette": 0.48,
        "thermal": 0.62,
        "posterize": 0.74,
        "palette": 0.86,
        "palette_remap": 0.96,
    },
    "atmospheric": {
        "drift": 0.10,
        "chromatic_aberration": 0.22,
        "kaleidoscope": 0.34,
        "fisheye": 0.48,
        "mirror": 0.60,
        "transform": 0.70,
        "slitscan": 0.80,
        "warp": 0.86,
        "displacement_map": 0.92,
        "droste": 0.96,
        "tile": 0.98,
        "tunnel": 1.00,
        "breathing": 0.42,
    },
    "temporal": {
        "fb": 0.98,
        "trail": 0.15,
        "echo": 0.30,
        "stutter": 0.45,
        "diff": 0.60,
        "fluid_sim": 0.75,
        "reaction_diffusion": 0.88,
        "feedback": 0.98,
    },
    "texture": {
        "ascii": 0.10,
        "vhs": 0.20,
        "glitch_block": 0.32,
        "scanlines": 0.44,
        "emboss": 0.55,
        "halftone": 0.66,
        "sharpen": 0.76,
        "kuwahara": 0.82,
        "noise_overlay": 0.88,
        "grain_bump": 0.90,
        "dither": 0.92,
        "noise_gen": 0.94,
        "particle_system": 0.96,
        "strobe": 0.99,
    },
    "edge": {
        "edge_detect": 0.20,
        "rutt_etra": 0.40,
        "voronoi_overlay": 0.60,
        "threshold": 0.80,
        "waveform_render": 0.95,
    },
    "compositing": {
        "blend": 0.20,
        "chroma_key": 0.45,
        "crossfade": 0.70,
        "luma_key": 0.90,
    },
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
    "aoa_oarb_state": "beyond-scrim",
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

PROGRAMME_ROLE_VALUES: dict[str, float] = {
    "idle": 0.05,
    "ambient": 0.12,
    "listening": 0.18,
    "rant": 0.28,
    "tier_list": 0.42,
    "top_10": 0.54,
    "react": 0.62,
    "iceberg": 0.72,
    "interview": 0.82,
    "lecture": 0.92,
}

ALBUM_RISK_VALUES: dict[str, float] = {
    "safe": 0.05,
    "tier_1": 0.15,
    "tier_2": 0.35,
    "tier_3": 0.60,
    "tier_4": 0.85,
    "tier_4_risky": 0.92,
    "unknown": 0.30,
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
    if not isinstance(ward_ids, list):
        ward_ids = active_wards.get("active_ward_ids")
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
    if not isinstance(ward_ids, list):
        ward_ids = active_wards.get("active_ward_ids")
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


def _active_wards_with_layout_fallback(shm_dir: Path) -> dict[str, Any]:
    active_wards = _read_json(shm_dir / "active_wards.json")
    ward_ids = active_wards.get("ward_ids")
    if isinstance(ward_ids, list) and ward_ids:
        return active_wards

    layout_state = _read_json(shm_dir / "current-layout-state.json")
    layout_ids = layout_state.get("active_ward_ids")
    if not isinstance(layout_ids, list) or not layout_ids:
        layout_ids = layout_state.get("ward_ids")
    if isinstance(layout_ids, list) and layout_ids:
        merged = dict(active_wards)
        merged["ward_ids"] = layout_ids
        return merged
    return active_wards


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
    active_wards = _active_wards_with_layout_fallback(shm_dir)
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


def _quake_live_camera_freshness(shm_dir: Path, role: str, now: float | None = None) -> float:
    meta_path = shm_dir / f"quake-live-cam-{role}.json"
    meta = _read_json(meta_path)
    timestamp = _entry_float(meta, "updated_at")
    if timestamp <= 0:
        try:
            timestamp = meta_path.stat().st_mtime
        except OSError:
            return 0.0
    age = (time.time() if now is None else now) - timestamp
    fps = max(1.0, _entry_float(meta, "fps", 10.0))
    ttl_s = max(12.0, 30.0 / fps)
    return 1.0 if age <= ttl_s else 0.0


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
        freshness = max(
            _source_frame_freshness(source_dir, now),
            _quake_live_camera_freshness(shm_dir, role, now),
        )
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
    active_wards = _active_wards_with_layout_fallback(shm_dir)
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


def _gem_frames(frames_file: Path, legacy_frames_file: Path) -> list[dict[str, Any]]:
    payload = _read_json(frames_file)
    frames = payload.get("frames")
    if not isinstance(frames, list):
        payload = _read_json(legacy_frames_file)
        frames = payload.get("frames")
    if not isinstance(frames, list):
        return []
    return [item for item in frames if isinstance(item, dict)]


def _gem_written_ts(frames_file: Path, legacy_frames_file: Path) -> float:
    payload = _read_json(frames_file)
    if "written_ts" not in payload:
        payload = _read_json(legacy_frames_file)
    return _entry_float(payload, "written_ts", 0.0)


def build_gem_mural_lines(
    recruitment_file: Path = DEFAULT_GEM_RECRUITMENT_FILE,
    frames_file: Path = DEFAULT_GEM_FRAMES_FILE,
    legacy_frames_file: Path = DEFAULT_LEGACY_GEM_FRAMES_FILE,
    now: float | None = None,
) -> dict[str, str]:
    """Export GEM recruitment/mural state as in-scroom expression pressure."""
    now = time.time() if now is None else now
    recruitment = _read_json(recruitment_file)
    frames = _gem_frames(frames_file, legacy_frames_file)
    score = _float01(recruitment, "score")
    ttl = max(1.0, _entry_float(recruitment, "ttl_s", 30.0))
    updated_at = _entry_float(recruitment, "updated_at", 0.0)
    written_ts = _gem_written_ts(frames_file, legacy_frames_file)
    recruitment_fresh = _clamp01(1.0 - max(0.0, now - updated_at) / ttl) if updated_at else 0.0
    frame_fresh = (
        _clamp01(1.0 - max(0.0, now - written_ts) / max(ttl * 4.0, 1.0)) if written_ts else 0.0
    )

    layer_count = 0
    opacity_sum = 0.0
    hold_pressure = 0.0
    for frame in frames:
        layers = frame.get("layers")
        if isinstance(layers, list):
            layer_count += sum(1 for item in layers if isinstance(item, dict))
            for layer in layers:
                if isinstance(layer, dict):
                    opacity_sum += _float01(layer, "opacity")
        hold_pressure = max(hold_pressure, _clamp01(_entry_float(frame, "hold_ms", 0.0) / 6000.0))

    frame_count = len(frames)
    max_layers = max(frame_count * 6, 1)
    layer_density = _clamp01(layer_count / float(max_layers))
    layer_opacity = _clamp01(opacity_sum / float(max(layer_count, 1)))
    narrative = str(recruitment.get("narrative") or "")
    narrative_pressure = _clamp01(len(_one_line(narrative, limit=240)) / 240.0)

    return {
        "gem-recruitment-score.txt": f"{score:.4f}",
        "gem-recruitment-fresh.txt": f"{recruitment_fresh:.4f}",
        "gem-frame-fresh.txt": f"{frame_fresh:.4f}",
        "gem-frame-count.txt": f"{_clamp01(frame_count / 12.0):.4f}",
        "gem-layer-density.txt": f"{layer_density:.4f}",
        "gem-layer-opacity.txt": f"{layer_opacity:.4f}",
        "gem-hold-pressure.txt": f"{hold_pressure:.4f}",
        "gem-narrative-pressure.txt": f"{narrative_pressure:.4f}",
        "gem-route.txt": "IN_SCROOM_GEM_RECRUITMENT_MURAL",
    }


def _recent_impingement_entries(path: Path) -> list[dict[str, Any]]:
    entries = _read_json(path).get("entries")
    if not isinstance(entries, list):
        return []
    return [item for item in entries if isinstance(item, dict)]


def _recent_recruitment_entries(path: Path) -> list[tuple[str, dict[str, Any]]]:
    families = _read_json(path).get("families")
    if not isinstance(families, dict):
        return []
    return [(str(name), details) for name, details in families.items() if isinstance(details, dict)]


def build_impingement_recruitment_lines(
    recent_impingements_file: Path = DEFAULT_RECENT_IMPINGEMENTS_FILE,
    recent_recruitment_file: Path = DEFAULT_RECENT_RECRUITMENT_FILE,
    now: float | None = None,
) -> dict[str, str]:
    """Export recent impingement/recruitment pressure as in-scroom fields."""
    now = time.time() if now is None else now
    impingements = _recent_impingement_entries(recent_impingements_file)
    strengths = [_float01(item, "value") for item in impingements]
    freshness = [
        _clamp01(1.0 - max(0.0, now - _entry_float(item, "ts", 0.0)) / 60.0)
        for item in impingements
    ]
    curiosity = [
        _float01(item, "value")
        for item in impingements
        if str(item.get("source") or "").startswith("exploration.")
    ]
    reverie_alert = [
        _float01(item, "value")
        for item in impingements
        if str(item.get("source") or "") == "reverie_prediction"
    ]

    recruitment = _recent_recruitment_entries(recent_recruitment_file)
    fresh_count = 0
    transition_pressure = 0.0
    studio_pressure = 0.0
    max_score = 0.0
    for family, details in recruitment:
        last_ts = _entry_float(details, "last_recruited_ts", 0.0)
        ttl = max(1.0, _entry_float(details, "ttl_s", 180.0))
        fresh = _clamp01(1.0 - max(0.0, now - last_ts) / ttl) if last_ts else 0.0
        if fresh > 0:
            fresh_count += 1
        score = _float01(details, "score")
        max_score = max(max_score, score)
        if family.startswith("transition."):
            transition_pressure = max(transition_pressure, fresh)
        if (
            family.startswith("overlay.")
            or family.startswith("preset.")
            or family.startswith("gem.")
        ):
            studio_pressure = max(studio_pressure, fresh, score)

    return {
        "impingement-count.txt": f"{_clamp01(len(impingements) / 15.0):.4f}",
        "impingement-strength.txt": f"{max(strengths, default=0.0):.4f}",
        "impingement-fresh.txt": f"{max(freshness, default=0.0):.4f}",
        "impingement-curiosity.txt": f"{max(curiosity, default=0.0):.4f}",
        "impingement-reverie-alert.txt": f"{max(reverie_alert, default=0.0):.4f}",
        "recruitment-family-count.txt": f"{_clamp01(len(recruitment) / 12.0):.4f}",
        "recruitment-fresh-ratio.txt": f"{_clamp01(fresh_count / max(len(recruitment), 1)):.4f}",
        "recruitment-score.txt": f"{max_score:.4f}",
        "recruitment-transition-pressure.txt": f"{transition_pressure:.4f}",
        "recruitment-studio-pressure.txt": f"{studio_pressure:.4f}",
        "impingement-recruitment-route.txt": "IN_SCROOM_IMPINGEMENT_RECRUITMENT_FIELD",
    }


def _list_ratio(value: object, scale: float) -> float:
    if not isinstance(value, list):
        return 0.0
    return _clamp01(len(value) / max(scale, 1.0))


def build_programme_segment_lines(shm_dir: Path, now: float | None = None) -> dict[str, str]:
    """Export active programme/segment state as in-scroom field pressure."""
    now = time.time() if now is None else now
    segment = _read_json(shm_dir / "active-segment.json")
    cue_hold = _read_json(shm_dir / "segment-cue-hold.json")
    role = str(segment.get("role") or "idle").strip().lower()
    beat_progress = _clamp01(_entry_float(segment, "beat_progress", 0.0))
    current_beat = max(0.0, _entry_float(segment, "current_beat_index", 0.0) + 1.0)
    total_beats = max(1.0, _entry_float(segment, "total_beats", 1.0))
    elapsed = max(0.0, _entry_float(segment, "beat_elapsed_s", 0.0))
    planned = max(1.0, _entry_float(segment, "planned_duration_s", 3600.0))
    cue_set_at = _entry_float(cue_hold, "set_at", 0.0)
    cue_ttl = max(1.0, _entry_float(cue_hold, "ttl_s", 1.0))
    cue_fresh = _clamp01(1.0 - max(0.0, now - cue_set_at) / cue_ttl) if cue_set_at else 0.0

    source_pressure = _list_ratio(segment.get("source_refs"), 6.0)
    asset_pressure = max(
        _list_ratio(segment.get("asset_attributions"), 4.0),
        _list_ratio(segment.get("asset_requirements"), 6.0),
    )
    affordance_pressure = _list_ratio(segment.get("source_affordance_kinds"), 6.0)

    return {
        "programme-role.txt": f"{PROGRAMME_ROLE_VALUES.get(role, 0.24):.4f}",
        "programme-beat-progress.txt": f"{beat_progress:.4f}",
        "programme-beat-index.txt": f"{_clamp01(current_beat / total_beats):.4f}",
        "programme-duration-pressure.txt": f"{_clamp01(elapsed / planned):.4f}",
        "programme-source-pressure.txt": f"{source_pressure:.4f}",
        "programme-asset-pressure.txt": f"{asset_pressure:.4f}",
        "programme-affordance-pressure.txt": f"{affordance_pressure:.4f}",
        "programme-cue-hold.txt": f"{cue_fresh:.4f}",
        "programme-segment-route.txt": "IN_SCROOM_PROGRAMME_SEGMENT_FIELD",
    }


def build_live_context_lines(shm_dir: Path, now: float | None = None) -> dict[str, str]:
    """Export token, album, viewer, and voice context as scroom pressure."""
    now = time.time() if now is None else now
    token_ledger = _read_json(shm_dir / "token-ledger.json")
    album_state = _read_json(shm_dir / "album-state.json")
    voice_state = _read_json(shm_dir / "voice-state.json")

    total_tokens = max(0.0, _entry_float(token_ledger, "total_tokens", 0.0))
    active_viewers = max(0.0, _entry_float(token_ledger, "active_viewers", 0.0))
    explosions = max(0.0, _entry_float(token_ledger, "explosions", 0.0))
    album_ts = _entry_float(album_state, "timestamp", 0.0)
    album_fresh = _clamp01(1.0 - max(0.0, now - album_ts) / 3600.0) if album_ts else 0.0
    album_playing = 1.0 if bool(album_state.get("playing")) else 0.0
    risk = str(album_state.get("content_risk") or "unknown").strip().lower()

    return {
        "live-token-pressure.txt": f"{_clamp01(total_tokens / 1_000_000.0):.4f}",
        "live-viewer-pressure.txt": f"{_clamp01(active_viewers / 10.0):.4f}",
        "live-token-burst.txt": f"{_clamp01(explosions / 200.0):.4f}",
        "live-album-confidence.txt": f"{_float01(album_state, 'confidence'):.4f}",
        "live-album-fresh.txt": f"{album_fresh:.4f}",
        "live-album-playing.txt": f"{album_playing:.4f}",
        "live-album-risk.txt": f"{ALBUM_RISK_VALUES.get(risk, 0.30):.4f}",
        "live-voice-active.txt": f"{1.0 if bool(voice_state.get('operator_speech_active')) else 0.0:.4f}",
        "live-context-route.txt": "IN_SCROOM_LIVE_CONTEXT_FIELD",
    }


def build_governance_health_lines(
    shm_dir: Path,
    daimonion_consent_file: Path = DEFAULT_DAIMONION_CONSENT_FILE,
    now: float | None = None,
) -> dict[str, str]:
    """Export consent, compositor health, and follow-mode pressure."""
    now = time.time() if now is None else now
    consent_text = _read_text_file(shm_dir / "consent-state.txt").strip().lower()
    consent_state = _read_json(daimonion_consent_file)
    health = _read_json(shm_dir / "health.json")
    follow = _read_json(shm_dir / "follow-mode-recommendation.json")
    health_ts = _entry_float(health, "timestamp", 0.0)
    follow_ts = _entry_float(follow, "ts", 0.0)
    follow_ttl = max(1.0, _entry_float(follow, "ttl_s", 15.0))
    consent_allowed = 1.0 if consent_text in {"allow", "allowed", "public", "ok"} else 0.0
    persistence_allowed = 1.0 if bool(consent_state.get("persistence_allowed")) else 0.0

    return {
        "governance-consent-allowed.txt": f"{consent_allowed:.4f}",
        "governance-persistence-allowed.txt": f"{persistence_allowed:.4f}",
        "governance-health-reference.txt": f"{_float01(health, 'reference'):.4f}",
        "governance-health-perception.txt": f"{_float01(health, 'perception'):.4f}",
        "governance-health-error.txt": f"{_float01(health, 'error'):.4f}",
        "governance-health-fresh.txt": f"{(_clamp01(1.0 - max(0.0, now - health_ts) / 300.0) if health_ts else 0.0):.4f}",
        "governance-follow-active.txt": f"{1.0 if bool(follow.get('active')) else 0.0:.4f}",
        "governance-follow-confidence.txt": f"{_float01(follow, 'confidence'):.4f}",
        "governance-follow-fresh.txt": f"{(_clamp01(1.0 - max(0.0, now - follow_ts) / follow_ttl) if follow_ts else 0.0):.4f}",
        "governance-health-route.txt": "IN_SCROOM_GOVERNANCE_HEALTH_FIELD",
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
    return EFFECT_DRIFT_NODE_FAMILY.get(_effect_drift_effect_name(pass_row), "texture")


def _effect_drift_effect_name(pass_row: dict[str, Any]) -> str:
    for key in ("effect", "effect_name", "node"):
        value = str(pass_row.get(key) or "").strip().lower()
        if value:
            return value
    node_id = str(pass_row.get("node_id") or "").strip().lower()
    if not node_id:
        return ""
    match = re.match(r"^slot\d+_(?:\d+_)?(.+)$", node_id)
    if match:
        return match.group(1)
    return node_id


def _effect_drift_slot_index(pass_row: dict[str, Any]) -> str:
    slot_index = pass_row.get("slot_index")
    if isinstance(slot_index, (int, float)):
        return str(int(slot_index))
    node_id = str(pass_row.get("node_id") or "").strip().lower()
    match = re.match(r"^slot(\d+)_", node_id)
    if match:
        return match.group(1)
    return _effect_drift_effect_name(pass_row)


def _effect_drift_mode_value(pass_row: dict[str, Any], family: str) -> float:
    effect = _effect_drift_effect_name(pass_row)
    mode_values = EFFECT_DRIFT_MODE_VALUES.get(family, {})
    return mode_values.get(effect, 0.0)


def _effect_drift_pass_strength(pass_row: dict[str, Any]) -> float:
    if pass_row.get("non_neutral") is False:
        return 0.0
    if "slot_intensity" in pass_row:
        strength = _clamp01(_entry_float(pass_row, "slot_intensity"))
        delta_hint = _clamp01(abs(_entry_float(pass_row, "max_delta")) / 100.0)
        strength = max(strength, min(delta_hint, 0.18))
    else:
        strength = _clamp01(abs(_entry_float(pass_row, "max_delta")) / 10.0)
        params = pass_row.get("params")
        if isinstance(params, list):
            for item in params:
                if isinstance(item, dict):
                    strength = max(strength, _clamp01(abs(_entry_float(item, "delta")) / 10.0))
    if pass_row.get("non_neutral") is True:
        strength = max(strength, 0.06)
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


def _state_file_fresh(path: Path, *, now: float | None = None, max_age_s: float = 10.0) -> bool:
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except OSError:
        return False
    return age <= max_age_s


def _visual_chain_pressure(payload: dict[str, Any]) -> float:
    levels = payload.get("levels")
    levels = levels if isinstance(levels, dict) else {}
    params = payload.get("params")
    params = params if isinstance(params, dict) else {}
    level_pressure = max(
        (_clamp01(_dict_float(levels, key)) for _ordinal, key in VISUAL_CHAIN_EXPORTS),
        default=0.0,
    )
    param_pressure = max(
        (
            abs(_dict_float(params, key))
            for key in (
                "noise.amplitude",
                "noise.frequency_x",
                "noise.speed",
                "drift.amplitude",
                "drift.speed",
                "color.hue_rotate",
                "color.saturation",
                "fb.decay",
                "post.vignette_strength",
            )
        ),
        default=0.0,
    )
    return max(level_pressure, min(param_pressure, 1.0))


def _select_visual_chain_state(
    primary_file: Path,
    fallback_file: Path,
    *,
    now: float | None = None,
) -> tuple[dict[str, Any], str]:
    primary = _read_json(primary_file)
    if primary and _state_file_fresh(primary_file, now=now) and _visual_chain_pressure(primary) > 0:
        return primary, "canonical"
    fallback = _read_json(fallback_file)
    if fallback and _state_file_fresh(fallback_file, now=now):
        return fallback, "fallback"
    if primary:
        return primary, "canonical-stale-or-neutral"
    if fallback:
        return fallback, "fallback-stale"
    return {}, "missing"


def _is_real_slotdrift_state(payload: dict[str, Any]) -> bool:
    source_presence = payload.get("source_presence")
    coverage = payload.get("slotdrift_coverage")
    if not isinstance(source_presence, dict) or not isinstance(coverage, dict):
        return False
    if source_presence.get("fail_closed") is True:
        return False
    visible = source_presence.get("visible_source_count")
    minimum = source_presence.get("minimum_effect_source_count")
    try:
        if visible is not None and minimum is not None and float(visible) < float(minimum):
            return False
    except (TypeError, ValueError):
        return False
    return True


def _select_effect_drift_state(
    primary_file: Path,
    fallback_file: Path,
    *,
    now: float | None = None,
) -> tuple[dict[str, Any], str]:
    primary = _read_json(primary_file)
    primary_fresh = bool(primary) and _state_file_fresh(primary_file, now=now, max_age_s=60.0)
    if primary_fresh and _is_real_slotdrift_state(primary):
        return primary, "slotdrift"
    fallback = _read_json(fallback_file)
    fallback_fresh = bool(fallback) and _state_file_fresh(fallback_file, now=now)
    if fallback_fresh:
        return fallback, "synthetic-fallback"
    if primary:
        return primary, "primary-stale-or-noncanonical"
    if fallback:
        return fallback, "synthetic-fallback-stale"
    return {}, "missing"


def build_visual_chain_lines(
    visual_chain_state_file: Path = DEFAULT_VISUAL_CHAIN_STATE_FILE,
    effect_drift_state_file: Path = DEFAULT_EFFECT_DRIFT_STATE_FILE,
    visual_chain_fallback_state_file: Path = DEFAULT_VISUAL_CHAIN_FALLBACK_STATE_FILE,
    effect_drift_fallback_state_file: Path = DEFAULT_EFFECT_DRIFT_FALLBACK_STATE_FILE,
    now: float | None = None,
) -> dict[str, str]:
    """Export visual-chain and effect-drift pressure as in-scroom scalars."""
    chain_state, chain_source = _select_visual_chain_state(
        visual_chain_state_file, visual_chain_fallback_state_file, now=now
    )
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

    effect_state, effect_source = _select_effect_drift_state(
        effect_drift_state_file, effect_drift_fallback_state_file, now=now
    )
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
    family_modes = {family: 0.0 for family in EFFECT_DRIFT_FAMILIES}
    family_mode_scores = {family: -1.0 for family in EFFECT_DRIFT_FAMILIES}
    active_effect_names: set[str] = set()
    active_slot_indices: set[str] = set()
    active_fast_count = 0
    active_slow_count = 0
    active_pass_count = 0
    active_strength_sum = 0.0
    max_delta = 0.0
    for pass_row in passes:
        if not isinstance(pass_row, dict):
            continue
        max_delta = max(max_delta, abs(_entry_float(pass_row, "max_delta")))
        family = _effect_drift_family(pass_row)
        pass_strength = _effect_drift_pass_strength(pass_row)
        if pass_strength > 0.0:
            active_pass_count += 1
            active_strength_sum += pass_strength
            effect_name = _effect_drift_effect_name(pass_row)
            if effect_name:
                active_effect_names.add(effect_name)
            active_slot_indices.add(_effect_drift_slot_index(pass_row))
            cadence = str(pass_row.get("eviction_cadence") or "").strip().lower()
            if cadence == "fast":
                active_fast_count += 1
            elif cadence == "slow":
                active_slow_count += 1
        family_strengths[family] = max(
            family_strengths.get(family, 0.0),
            pass_strength,
        )
        mode_score = pass_strength + _clamp01(_entry_float(pass_row, "slot_intensity")) * 0.25
        mode_value = _effect_drift_mode_value(pass_row, family)
        if mode_value > 0 and mode_score > family_mode_scores.get(family, -1.0):
            family_mode_scores[family] = mode_score
            family_modes[family] = mode_value
    effective_non_neutral = non_neutral
    active_families = [
        family for family in EFFECT_DRIFT_FAMILIES if family_strengths.get(family, 0.0) > 0.0
    ]
    if effect_source == "slotdrift" and active_families:
        # SlotDrift already performs fast/slow eviction and type rotation. Do
        # not collapse that into a small rotating family subset here; DarkPlaces
        # needs the full family vector so "kind" changes remain visible on
        # media/entity surfaces instead of becoming a single intensity pulse.
        effective_non_neutral = float(len(active_families))
    active_ratio_denominator = max(1.0, min(pass_count, 6.0))
    drift_strength_peak = max(family_strengths.values(), default=0.0)
    active_strength_mean = active_strength_sum / max(1.0, float(active_pass_count))
    if effect_source == "slotdrift" and active_pass_count > 0:
        active_ratio = _clamp01(0.36 + active_strength_mean * 0.64)
    else:
        active_ratio = _clamp01(effective_non_neutral / active_ratio_denominator)
    active_slot_ratio = _clamp01(len(active_slot_indices) / 5.0)
    active_effect_ratio = _clamp01(active_pass_count / max(1.0, pass_count))
    cadence_denominator = max(1.0, float(active_pass_count))
    fast_ratio = _clamp01(active_fast_count / cadence_denominator)
    slow_ratio = _clamp01(active_slow_count / cadence_denominator)
    kind_variance = _clamp01(len(active_effect_names) / max(1.0, pass_count))

    lines.update(
        {
            "visual-chain-noise.txt": f"{noise_pressure:.4f}",
            "visual-chain-drift.txt": f"{drift_pressure:.4f}",
            "visual-chain-color.txt": f"{color_pressure:.4f}",
            "visual-chain-feedback.txt": f"{feedback_pressure:.4f}",
            "visual-chain-aperture.txt": f"{aperture_pressure:.4f}",
            "visual-chain-param-pressure.txt": f"{max(noise_pressure, drift_pressure, color_pressure, feedback_pressure, aperture_pressure, max_level):.4f}",
            "effect-drift-pass-count.txt": f"{_clamp01(pass_count / 5.0):.4f}",
            "effect-drift-active-ratio.txt": f"{active_ratio:.4f}",
            "effect-drift-active-slot-ratio.txt": f"{active_slot_ratio:.4f}",
            "effect-drift-active-effect-ratio.txt": f"{active_effect_ratio:.4f}",
            "effect-drift-fast-ratio.txt": f"{fast_ratio:.4f}",
            "effect-drift-slow-ratio.txt": f"{slow_ratio:.4f}",
            "effect-drift-kind-variance.txt": f"{kind_variance:.4f}",
            "effect-drift-max-delta.txt": f"{_clamp01(drift_strength_peak):.4f}",
            "effect-drift-region-count.txt": f"{_clamp01(_effect_drift_region_count(passes) / 12.0):.4f}",
            "effect-drift-route.txt": "IN_SCROOM_EFFECT_DRIFT_STATE",
            "effect-drift-source.txt": effect_source,
            "effect-drift-real-source.txt": "1.0000" if effect_source == "slotdrift" else "0.0000",
            "visual-chain-source.txt": chain_source,
        }
    )
    for family, value in family_strengths.items():
        lines[f"effect-drift-{family}.txt"] = f"{value:.4f}"
    for family, value in family_modes.items():
        lines[f"effect-drift-mode-{family}.txt"] = f"{value:.4f}"
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
    gem_recruitment_file: Path = DEFAULT_GEM_RECRUITMENT_FILE,
    gem_frames_file: Path = DEFAULT_GEM_FRAMES_FILE,
    legacy_gem_frames_file: Path = DEFAULT_LEGACY_GEM_FRAMES_FILE,
    recent_impingements_file: Path = DEFAULT_RECENT_IMPINGEMENTS_FILE,
    recent_recruitment_file: Path = DEFAULT_RECENT_RECRUITMENT_FILE,
    daimonion_consent_file: Path = DEFAULT_DAIMONION_CONSENT_FILE,
    entity_local_effect_state_file: Path = DEFAULT_ENTITY_LOCAL_EFFECT_STATE_FILE,
    stimmung_state_file: Path = DEFAULT_STIMMUNG_STATE_FILE,
    visual_chain_state_file: Path = DEFAULT_VISUAL_CHAIN_STATE_FILE,
    effect_drift_state_file: Path = DEFAULT_EFFECT_DRIFT_STATE_FILE,
    visual_chain_fallback_state_file: Path = DEFAULT_VISUAL_CHAIN_FALLBACK_STATE_FILE,
    effect_drift_fallback_state_file: Path = DEFAULT_EFFECT_DRIFT_FALLBACK_STATE_FILE,
    now: float | None = None,
) -> None:
    game_dir.mkdir(parents=True, exist_ok=True)

    _copy_text(mode_file, game_dir / "working-mode.txt")
    _copy_text(shm_dir / "stimmung-energy.txt", game_dir / "stimmung-energy.txt")
    _copy_text(shm_dir / "voice-active.txt", game_dir / "voice-active.txt")

    ward_lines = build_ward_lines(shm_dir)
    for ordinal, ward_id in WARD_EXPORTS.items():
        line = ward_lines.get(ordinal, ward_id.upper())
        _write_atomic(game_dir / f"ward-{ordinal}.txt", line)
    active_wards = _active_wards_with_layout_fallback(shm_dir)
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
    for filename, line in build_source_lines(shm_dir, imagination_sources_dir, now).items():
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
    for filename, line in build_gem_mural_lines(
        gem_recruitment_file, gem_frames_file, legacy_gem_frames_file, now
    ).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_impingement_recruitment_lines(
        recent_impingements_file, recent_recruitment_file, now
    ).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_programme_segment_lines(shm_dir, now).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_live_context_lines(shm_dir, now).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_governance_health_lines(
        shm_dir, daimonion_consent_file, now
    ).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_visual_layer_lines(shm_dir, stimmung_state_file).items():
        _write_atomic(game_dir / filename, line)
    for filename, line in build_visual_chain_lines(
        visual_chain_state_file,
        effect_drift_state_file,
        visual_chain_fallback_state_file,
        effect_drift_fallback_state_file,
        now,
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
    parser.add_argument("--gem-recruitment-file", type=Path, default=DEFAULT_GEM_RECRUITMENT_FILE)
    parser.add_argument("--gem-frames-file", type=Path, default=DEFAULT_GEM_FRAMES_FILE)
    parser.add_argument(
        "--legacy-gem-frames-file",
        type=Path,
        default=DEFAULT_LEGACY_GEM_FRAMES_FILE,
    )
    parser.add_argument(
        "--recent-impingements-file",
        type=Path,
        default=DEFAULT_RECENT_IMPINGEMENTS_FILE,
    )
    parser.add_argument(
        "--recent-recruitment-file",
        type=Path,
        default=DEFAULT_RECENT_RECRUITMENT_FILE,
    )
    parser.add_argument(
        "--daimonion-consent-file",
        type=Path,
        default=DEFAULT_DAIMONION_CONSENT_FILE,
    )
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
    parser.add_argument(
        "--visual-chain-fallback-state-file",
        type=Path,
        default=DEFAULT_VISUAL_CHAIN_FALLBACK_STATE_FILE,
    )
    parser.add_argument(
        "--effect-drift-fallback-state-file",
        type=Path,
        default=DEFAULT_EFFECT_DRIFT_FALLBACK_STATE_FILE,
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
        args.gem_recruitment_file,
        args.gem_frames_file,
        args.legacy_gem_frames_file,
        args.recent_impingements_file,
        args.recent_recruitment_file,
        args.daimonion_consent_file,
        args.entity_local_effect_state_file,
        args.stimmung_state_file,
        args.visual_chain_state_file,
        args.effect_drift_state_file,
        args.visual_chain_fallback_state_file,
        args.effect_drift_fallback_state_file,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
