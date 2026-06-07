#!/usr/bin/env python3
"""Render compositor ward sources into one DarkPlaces live texture atlas."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

import cairo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from quake_media_drift import DEFAULT_GAME_DATA, MediaDriftRenderer  # noqa: E402

DEFAULT_OUTPUT = Path("/dev/shm/hapax-compositor/quake-live-ward-atlas.bgra")
DEFAULT_META = Path("/dev/shm/hapax-compositor/quake-live-ward-atlas.json")
DEFAULT_LAYOUT = REPO_ROOT / "config" / "compositor-layouts" / "default.json"
DEFAULT_WIDTH = 2048
DEFAULT_HEIGHT = 2304
DEFAULT_COLUMNS = 4
DEFAULT_CELL_WIDTH = 512
DEFAULT_CELL_HEIGHT = 256
DEFAULT_FPS = 2.0
DEFAULT_STALE_SOURCE_SECONDS = 6.0
DEFAULT_REVERIE_UNIFORMS = Path("/dev/shm/hapax-imagination/uniforms.json")
DEFAULT_REVERIE_VISUAL_CHAIN = Path("/dev/shm/hapax-visual/screwm-visual-chain-state.json")
VISIBILITY_SAMPLE_GRID = 96
VISIBILITY_ALPHA_NONZERO_FLOOR = 0.01
VISIBILITY_MEAN_LUMA_FLOOR = 0.08
VISIBILITY_DETAIL_STD_FLOOR = 0.025
VISIBILITY_DETAIL_EDGE_FLOOR = 0.006
VISIBILITY_NEAR_BLACK_LUMA = 0.06
VISIBILITY_BLACK_LUMA = 0.02
VISIBILITY_WHITE_LUMA = 0.95
VISIBILITY_NEAR_BLACK_RATIO_CEILING = 0.70
VISIBILITY_BLACK_RATIO_CEILING = 0.90
VISIBILITY_WHITE_RATIO_CEILING = 0.90
READABILITY_LIFT_ALPHA_FLOOR = VISIBILITY_ALPHA_NONZERO_FLOOR

WARD_IDS = [
    "token_pole",
    "album",
    "stream_overlay",
    "aoa_oarb_state",
    "reverie",
    "activity_header",
    "stance_indicator",
    "gem",
    "grounding_provenance_ticker",
    "impingement_cascade",
    "recruitment_candidate_panel",
    "thinking_indicator",
    "pressure_gauge",
    "activity_variety_log",
    "whos_here",
    "durf",
    "coding_session_reveal",
    "brio-operator-ir",
    "brio-room-ir",
    "egress_footer",
    "programme_banner",
    "precedent_ticker",
    "programme_history",
    "research_instrument_dashboard",
    "cbip_signal_density",
    "chat_ambient",
    "chronicle_ticker",
    "programme_state",
    "polyend_instrument_reveal",
    "interactive_lore_query",
    "constructivist_research_poster",
    "tufte_density",
    "ascii_schematic",
    "segment_content",
    "brio-synths-ir",
    "cbip_dual_ir_displacement",
]

DIRECT_TEXTURE_WARDS = {
    # These wards are bound to DarkPlaces live-texture slots directly. Keeping
    # separate atlas proxies made stale/dim substrate failures look like working
    # in-world live wards. The atlas reserves each cell but never renders content.
    "reverie",
    "brio-operator-ir",
    "brio-room-ir",
    "brio-synths-ir",
}
DIRECT_TEXTURE_WARD_TEXTURES = {
    "reverie": "w05",
    "brio-operator-ir": "w18",
    "brio-room-ir": "w19",
    "brio-synths-ir": "w35",
}

GENERIC_ATLAS_IDLE_SCAFFOLD_WARDS = frozenset(
    {
        "precedent_ticker",
        "programme_history",
        "research_instrument_dashboard",
        "chronicle_ticker",
        "programme_state",
        "constructivist_research_poster",
        "tufte_density",
        "ascii_schematic",
    }
)
SOURCE_PROVIDED_ATLAS_IDLE_SCAFFOLD_WARDS = frozenset(
    {
        "durf",
        "coding_session_reveal",
    }
)
ATLAS_IDLE_SCAFFOLD_WARDS = (
    GENERIC_ATLAS_IDLE_SCAFFOLD_WARDS | SOURCE_PROVIDED_ATLAS_IDLE_SCAFFOLD_WARDS
)

WARD_LABELS = {
    "token_pole": "TOKEN POLE",
    "album": "ALBUM",
    "stream_overlay": "STREAM",
    "aoa_oarb_state": "AOA OARB",
    "reverie": "REVERIE",
    "activity_header": "ACTIVITY",
    "stance_indicator": "STANCE",
    "gem": "GEM",
    "grounding_provenance_ticker": "GROUNDING",
    "impingement_cascade": "IMPINGEMENT",
    "recruitment_candidate_panel": "RECRUITMENT",
    "thinking_indicator": "THINKING",
    "pressure_gauge": "PRESSURE",
    "activity_variety_log": "VARIETY",
    "whos_here": "WHO'S HERE",
    "durf": "DURF",
    "coding_session_reveal": "CODING",
    "brio-operator-ir": "BRIO OP IR",
    "brio-room-ir": "BRIO ROOM IR",
    "egress_footer": "EGRESS",
    "programme_banner": "PROGRAMME",
    "precedent_ticker": "PRECEDENT",
    "programme_history": "HISTORY",
    "research_instrument_dashboard": "RESEARCH",
    "cbip_signal_density": "CBIP",
    "chat_ambient": "CHAT",
    "chronicle_ticker": "CHRONICLE",
    "programme_state": "STATE",
    "polyend_instrument_reveal": "POLYEND",
    "interactive_lore_query": "LORE QUERY",
    "constructivist_research_poster": "POSTER",
    "tufte_density": "TUFTE",
    "ascii_schematic": "ASCII",
    "segment_content": "SEGMENT",
    "brio-synths-ir": "BRIO SYN IR",
    "cbip_dual_ir_displacement": "IR DUAL",
}

PALETTE = {
    "bg": (0.015, 0.020, 0.030),
    "panel": (0.020, 0.032, 0.045),
    "cyan": (0.27, 0.90, 1.0),
    "magenta": (1.0, 0.25, 0.66),
    "amber": (1.0, 0.68, 0.05),
    "green": (0.46, 1.0, 0.70),
    "dim": (0.12, 0.17, 0.23),
}


def _load_layout(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    sources = data.get("sources") or []
    return {str(source["id"]): source for source in sources if isinstance(source, dict)}


def _construct_backends(layout_path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    from agents.studio_compositor.source_registry import SourceRegistry
    from shared.compositor_model import SourceSchema

    sources = _load_layout(layout_path)
    registry = SourceRegistry()
    errors: dict[str, str] = {}
    for ward_id in WARD_IDS:
        source_data = sources.get(ward_id)
        if source_data is None:
            errors[ward_id] = "missing layout source"
            continue
        try:
            schema = SourceSchema.model_validate(source_data)
            registry.register(ward_id, registry.construct_backend(schema))
        except Exception as exc:  # noqa: BLE001 - visible fallback per cell
            errors[ward_id] = f"{type(exc).__name__}: {exc}"
    return {ward_id: registry for ward_id in WARD_IDS if ward_id not in errors}, errors


def _surface_bgra_bytes(surface: cairo.ImageSurface, width: int, height: int) -> bytes:
    surface.flush()
    stride = int(surface.get_stride())
    row_bytes = width * 4
    data = bytes(surface.get_data())
    if stride == row_bytes:
        return data[: row_bytes * height]
    return b"".join(data[y * stride : y * stride + row_bytes] for y in range(height))


def _luma_from_bgra(data: bytes, offset: int) -> float:
    b = data[offset]
    g = data[offset + 1]
    r = data[offset + 2]
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _surface_visibility_stats(surface: cairo.ImageSurface) -> dict[str, float | int]:
    """Return bounded pixel metrics for classifying weak live ward frames."""
    surface.flush()
    width = max(0, int(surface.get_width()))
    height = max(0, int(surface.get_height()))
    if width <= 0 or height <= 0:
        return {
            "sample_count": 0,
            "mean_luma": 0.0,
            "luma_std": 0.0,
            "edge_energy": 0.0,
            "near_black_ratio": 1.0,
            "black_ratio": 1.0,
            "white_ratio": 0.0,
            "alpha_nonzero_ratio": 0.0,
        }

    stride = int(surface.get_stride())
    data = bytes(surface.get_data())
    x_step = max(1, width // VISIBILITY_SAMPLE_GRID)
    y_step = max(1, height // VISIBILITY_SAMPLE_GRID)
    sample_count = 0
    alpha_nonzero = 0
    near_black = 0
    black = 0
    white = 0
    luma_sum = 0.0
    luma_sq_sum = 0.0
    edge_sum = 0.0
    edge_count = 0

    for y in range(0, height, y_step):
        row = y * stride
        for x in range(0, width, x_step):
            offset = row + x * 4
            luma = _luma_from_bgra(data, offset)
            sample_count += 1
            luma_sum += luma
            luma_sq_sum += luma * luma
            if data[offset + 3] > 2:
                alpha_nonzero += 1
            if luma <= VISIBILITY_NEAR_BLACK_LUMA:
                near_black += 1
            if luma <= VISIBILITY_BLACK_LUMA:
                black += 1
            if luma >= VISIBILITY_WHITE_LUMA:
                white += 1

            next_x = x + x_step
            if next_x < width:
                edge_sum += abs(luma - _luma_from_bgra(data, row + next_x * 4))
                edge_count += 1
            next_y = y + y_step
            if next_y < height:
                edge_sum += abs(luma - _luma_from_bgra(data, next_y * stride + x * 4))
                edge_count += 1

    if sample_count <= 0:
        return {
            "sample_count": 0,
            "mean_luma": 0.0,
            "luma_std": 0.0,
            "edge_energy": 0.0,
            "near_black_ratio": 1.0,
            "black_ratio": 1.0,
            "white_ratio": 0.0,
            "alpha_nonzero_ratio": 0.0,
        }

    mean = luma_sum / sample_count
    variance = max(0.0, (luma_sq_sum / sample_count) - (mean * mean))
    return {
        "sample_count": sample_count,
        "mean_luma": round(mean, 6),
        "luma_std": round(math.sqrt(variance), 6),
        "edge_energy": round(edge_sum / max(1, edge_count), 6),
        "near_black_ratio": round(near_black / sample_count, 6),
        "black_ratio": round(black / sample_count, 6),
        "white_ratio": round(white / sample_count, 6),
        "alpha_nonzero_ratio": round(alpha_nonzero / sample_count, 6),
    }


def _visibility_thresholds() -> dict[str, float | int]:
    return {
        "sample_grid": VISIBILITY_SAMPLE_GRID,
        "alpha_nonzero_floor": VISIBILITY_ALPHA_NONZERO_FLOOR,
        "mean_luma_floor": VISIBILITY_MEAN_LUMA_FLOOR,
        "detail_std_floor": VISIBILITY_DETAIL_STD_FLOOR,
        "detail_edge_floor": VISIBILITY_DETAIL_EDGE_FLOOR,
        "near_black_luma": VISIBILITY_NEAR_BLACK_LUMA,
        "black_luma": VISIBILITY_BLACK_LUMA,
        "white_luma": VISIBILITY_WHITE_LUMA,
        "near_black_ratio_ceiling": VISIBILITY_NEAR_BLACK_RATIO_CEILING,
        "black_ratio_ceiling": VISIBILITY_BLACK_RATIO_CEILING,
        "white_ratio_ceiling": VISIBILITY_WHITE_RATIO_CEILING,
    }


def _visibility_classification(
    *,
    status: str,
    stats: dict[str, float | int],
) -> tuple[str, list[str]]:
    if status not in {"rendered", "atlas-idle-scaffold"}:
        return status, []

    sample_count = int(stats.get("sample_count", 0))
    mean_luma = float(stats.get("mean_luma", 0.0))
    luma_std = float(stats.get("luma_std", 0.0))
    edge_energy = float(stats.get("edge_energy", 0.0))
    near_black_ratio = float(stats.get("near_black_ratio", 1.0))
    black_ratio = float(stats.get("black_ratio", 1.0))
    white_ratio = float(stats.get("white_ratio", 0.0))
    alpha_nonzero_ratio = float(stats.get("alpha_nonzero_ratio", 0.0))
    reasons: list[str] = []

    if sample_count <= 0:
        reasons.append("sample_count_empty")
    if alpha_nonzero_ratio < VISIBILITY_ALPHA_NONZERO_FLOOR:
        reasons.append("alpha_nonzero_ratio_below_floor")
    if black_ratio > VISIBILITY_BLACK_RATIO_CEILING:
        reasons.append("black_ratio_above_ceiling")
    if near_black_ratio > VISIBILITY_NEAR_BLACK_RATIO_CEILING:
        reasons.append("near_black_ratio_above_ceiling")
    if white_ratio > VISIBILITY_WHITE_RATIO_CEILING:
        reasons.append("white_ratio_above_ceiling")
    if mean_luma < VISIBILITY_MEAN_LUMA_FLOOR:
        reasons.append("mean_luma_below_floor")
    if luma_std < VISIBILITY_DETAIL_STD_FLOOR and edge_energy < VISIBILITY_DETAIL_EDGE_FLOOR:
        reasons.append("detail_below_floor")

    if not reasons:
        return "visible", []
    if status == "atlas-idle-scaffold":
        return "weak-idle-scaffold", reasons
    return "weak-rendered", reasons


def _needs_readability_lift(
    *,
    status: str,
    classification: str,
    stats: dict[str, float | int],
) -> bool:
    if status not in {"rendered", "atlas-idle-scaffold"}:
        return False
    if classification not in {"weak-rendered", "weak-idle-scaffold"}:
        return False
    if int(stats.get("sample_count", 0)) <= 0:
        return False
    if float(stats.get("alpha_nonzero_ratio", 0.0)) < READABILITY_LIFT_ALPHA_FLOOR:
        return False
    return (
        float(stats.get("mean_luma", 0.0)) < VISIBILITY_MEAN_LUMA_FLOOR
        or float(stats.get("near_black_ratio", 1.0)) > VISIBILITY_NEAR_BLACK_RATIO_CEILING
        or float(stats.get("black_ratio", 1.0)) > VISIBILITY_BLACK_RATIO_CEILING
    )


def _readability_lift_surface(
    source: cairo.ImageSurface,
    *,
    ward_id: str,
    t: float,
) -> cairo.ImageSurface:
    """Lift a fresh but too-dark source without faking missing content."""
    source.flush()
    width = max(1, int(source.get_width()))
    height = max(1, int(source.get_height()))
    src_stride = int(source.get_stride())
    src_data = bytes(source.get_data())
    lifted = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    lifted.flush()
    dst_stride = int(lifted.get_stride())
    dst_data = lifted.get_data()
    seed = (sum(ord(ch) for ch in ward_id) % 37) * 0.17
    denom_x = max(1, width - 1)
    denom_y = max(1, height - 1)

    for y in range(height):
        y_norm = y / denom_y
        for x in range(width):
            src = y * src_stride + x * 4
            dst = y * dst_stride + x * 4
            b = src_data[src]
            g = src_data[src + 1]
            r = src_data[src + 2]
            a = src_data[src + 3]
            wave = 0.5 + 0.5 * math.sin(t * 0.61 + x * 0.031 + y * 0.019 + seed)
            shimmer = 0.5 + 0.5 * math.sin(x * 0.37 + y * 0.23 + seed * 1.7)
            tile = 1.0 if ((x // 5) + (y // 4)) % 2 == 0 else 0.0
            x_norm = x / denom_x
            micro = 22 * shimmer + 18 * tile
            base_r = 20 + 28 * y_norm + 22 * wave + micro * 0.62
            base_g = 24 + 24 * (1.0 - y_norm) + 16 * wave + micro * 0.50
            base_b = 34 + 30 * (1.0 - x_norm) + 24 * (1.0 - wave) + micro * 0.72

            if a > 2:
                luma = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
                gain = 2.65 if luma < 0.12 else 1.75 if luma < 0.28 else 1.20
                floor = 30 + 24 * wave + micro * 0.88
                dst_data[dst] = min(255, int(max(base_b, b * gain + floor * 0.78)))
                dst_data[dst + 1] = min(255, int(max(base_g, g * gain + floor * 0.92)))
                dst_data[dst + 2] = min(255, int(max(base_r, r * gain + floor)))
                dst_data[dst + 3] = 255
            else:
                dst_data[dst] = min(255, int(base_b))
                dst_data[dst + 1] = min(255, int(base_g))
                dst_data[dst + 2] = min(255, int(base_r))
                dst_data[dst + 3] = 255

    lifted.mark_dirty()
    cr = cairo.Context(lifted)
    cr.set_operator(cairo.OPERATOR_SCREEN)
    cr.set_line_width(max(1.0, min(width, height) * 0.006))
    for i in range(6):
        phase = t * 0.37 + i * 0.83 + seed
        y0 = height * ((i + 0.5) / 6.0)
        cr.set_source_rgba(0.22, 0.86, 1.0, 0.08 + 0.04 * math.sin(phase))
        cr.move_to(0, y0)
        cr.curve_to(
            width * 0.28,
            y0 + math.sin(phase) * height * 0.08,
            width * 0.72,
            y0 + math.cos(phase * 1.31) * height * 0.08,
            width,
            y0 + math.sin(phase * 0.71) * height * 0.05,
        )
        cr.stroke()
    cr.set_operator(cairo.OPERATOR_OVER)
    lifted.flush()
    return lifted


def _visibility_summary(observed: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    suspect_wards: list[dict[str, Any]] = []
    readability_lift_count = 0
    suspect_classifications = {"fallback", "weak-rendered", "weak-idle-scaffold"}
    for index, ward_id in enumerate(WARD_IDS, start=1):
        ward = observed.get(ward_id)
        if not isinstance(ward, dict):
            continue
        post_classification = str(
            ward.get("visibility_classification") or ward.get("status") or "unknown"
        )
        # A readability lift decorates a dim/empty source so the cell renders legibly,
        # but its POST-lift classification must not mask a genuinely weak/dead source
        # from the audit. Report the PRE-lift classification and keep lifted wards in
        # the suspect list so the weak-frame signal survives the lift (#3985 neutralized
        # the #3979 detector; this restores it without changing the rendered pixels).
        lifted = bool(ward.get("readability_lift"))
        pre = ward.get("pre_readability_visibility") or {}
        if lifted:
            readability_lift_count += 1
            classification = str(pre.get("classification") or post_classification)
            reasons = pre.get("reasons") or ward.get("visibility_reasons", [])
        else:
            classification = post_classification
            reasons = ward.get("visibility_reasons", [])
        counts[classification] = counts.get(classification, 0) + 1
        if lifted or classification in suspect_classifications:
            suspect_wards.append(
                {
                    "index": index,
                    "ward_id": ward_id,
                    "status": ward.get("status"),
                    "visibility_classification": classification,
                    "post_lift_classification": post_classification if lifted else None,
                    "readability_lift": lifted,
                    "visibility_reasons": reasons,
                    "mean_luma": ward.get("mean_luma"),
                    "luma_std": ward.get("luma_std"),
                    "edge_energy": ward.get("edge_energy"),
                    "near_black_ratio": ward.get("near_black_ratio"),
                }
            )
    return {
        "counts": counts,
        "suspect_wards": suspect_wards,
        "readability_lift_count": readability_lift_count,
    }


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _gpu_drift_default() -> bool:
    value = os.environ.get(
        "HAPAX_QUAKE_WARD_ATLAS_GPU_DRIFT",
        os.environ.get("HAPAX_QUAKE_GPU_DRIFT", ""),
    )
    return _truthy(value)


def _gpu_drift_paths(output: Path) -> tuple[Path, Path]:
    raw_output = output.with_name(f"{output.stem}.raw.bgra")
    return raw_output, raw_output.with_suffix(".json")


def _short_hash(data: bytes) -> str:
    return hashlib.blake2s(data, digest_size=8).hexdigest()


def _draw_text(cr: cairo.Context, text: str, x: float, y: float, size: int, color: str) -> None:
    cr.save()
    cr.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(size)
    cr.set_source_rgb(*PALETTE[color])
    cr.move_to(x, y)
    cr.show_text(text)
    cr.restore()


def _paint_cell_frame(
    cr: cairo.Context,
    *,
    ward_id: str,
    index: int,
    x: int,
    y: int,
    w: int,
    h: int,
    t: float,
) -> None:
    """Paint only a fail-closed cell substrate.

    Successful wards must not receive an atlas-level border, title band, grid,
    or arbitrary frame. Their shape and visual language come from the source
    ward and its declared in-world receiver contract.
    """
    cr.save()
    cr.rectangle(x, y, w, h)
    cr.set_source_rgb(*PALETTE["bg"])
    cr.fill()
    cr.restore()


def _paint_fallback(
    cr: cairo.Context,
    *,
    ward_id: str,
    index: int,
    x: int,
    y: int,
    w: int,
    h: int,
    reason: str,
) -> None:
    """Fail closed without inventing a visible ward.

    A missing/stale source is not a content surface. It should be represented
    by absence in the Scroom and by metadata for operators, not by a fake label
    or diagnostic panel inside the DarkPlaces environment.
    """
    _paint_cell_frame(cr, ward_id=ward_id, index=index, x=x, y=y, w=w, h=h, t=time.monotonic())


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _float_field(payload: dict[str, Any], key: str, fallback: float = 0.0) -> float:
    try:
        value = float(payload.get(key, fallback))
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(1.0, value))


def _nested_float(payload: dict[str, Any], *keys: str, fallback: float = 0.0) -> float:
    for key in keys:
        current: Any = payload
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if current is None:
            current = payload.get(key)
        try:
            return max(0.0, min(1.0, float(current)))
        except (TypeError, ValueError):
            continue
    return fallback


def _paint_reverie_state_proxy(
    cr: cairo.Context,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    t: float,
    uniforms_path: Path = DEFAULT_REVERIE_UNIFORMS,
    visual_chain_path: Path = DEFAULT_REVERIE_VISUAL_CHAIN,
) -> dict[str, Any]:
    """Render a live reverie-state ward when the RGBA substrate is stale.

    This is intentionally not a diagnostic label. It is a live abstract
    material field derived from reverie uniforms so the ward remains an
    in-world reverie entity without pretending stale pixels are fresh.
    """
    uniforms = _read_json(uniforms_path)
    visual_chain = _read_json(visual_chain_path)
    hue = float(uniforms.get("color.hue_rotate", 0.0) or 0.0) % 360.0
    hue = (
        hue + _nested_float(visual_chain, "params.color.hue_rotate", "color.hue_rotate") * 160.0
    ) % 360.0
    warmth = _float_field(uniforms, "signal.color_warmth", 0.25)
    spectral = _nested_float(visual_chain, "levels.visual_chain.spectral_color", fallback=0.45)
    temporal = _nested_float(visual_chain, "levels.visual_chain.temporal_distortion", fallback=0.45)
    depth = _nested_float(visual_chain, "levels.visual_chain.depth", fallback=0.45)
    tension = _nested_float(visual_chain, "levels.visual_chain.tension", fallback=0.55)
    coherence = _nested_float(visual_chain, "levels.visual_chain.coherence", fallback=0.50)
    drift = _nested_float(visual_chain, "params.drift.amplitude", fallback=0.42)
    noise_amp = _nested_float(visual_chain, "params.noise.amplitude", fallback=0.56)
    opacity = max(0.72, _float_field(uniforms, "post.master_opacity", 0.88))
    anonymize = _float_field(uniforms, "post.anonymize", 0.25)
    sediment = max(
        _float_field(uniforms, "post.sediment_strength", 0.0),
        _nested_float(visual_chain, "params.post.sediment_strength", fallback=0.12),
    )
    decay = max(
        _float_field(uniforms, "fb.decay", 0.0),
        _nested_float(visual_chain, "params.fb.decay", fallback=0.12),
    )
    pulse = 0.5 + 0.5 * math.sin(t * (0.72 + temporal * 0.62) + hue * 0.017)
    slow = 0.5 + 0.5 * math.sin(t * (0.18 + drift * 0.22) + depth * 4.0)
    cr.save()
    cr.rectangle(x, y, w, h)
    cr.clip()
    grad = cairo.LinearGradient(x, y, x + w, y + h)
    grad.add_color_stop_rgba(
        0.00, 0.02 + warmth * 0.10, 0.02, 0.12 + anonymize * 0.30, 0.78 * opacity
    )
    grad.add_color_stop_rgba(
        0.36, 0.36 + warmth * 0.42, 0.06 + pulse * 0.26, 0.36 + spectral * 0.40, 0.82 * opacity
    )
    grad.add_color_stop_rgba(0.72, 0.03, 0.32 + pulse * 0.28, 0.42 + decay * 0.32, 0.68 * opacity)
    grad.add_color_stop_rgba(1.00, 0.02, 0.07 + slow * 0.16, 0.18 + warmth * 0.34, 0.58 * opacity)
    cr.set_source(grad)
    cr.paint()

    for i in range(14):
        phase = t * (0.35 + temporal * 0.24 + i * 0.028) + i * 0.78 + hue * 0.011
        cx = x + w * (0.12 + 0.78 * ((math.sin(phase) + 1.0) * 0.5))
        cy = y + h * (0.18 + 0.64 * ((math.cos(phase * 0.73) + 1.0) * 0.5))
        radius = max(w, h) * (0.10 + depth * 0.05 + 0.06 * math.sin(phase * 1.7))
        aura = cairo.RadialGradient(cx, cy, 0, cx, cy, radius)
        aura.add_color_stop_rgba(
            0, 1.0, 0.32 + warmth * 0.40, 0.78 + spectral * 0.22, 0.24 + pulse * 0.24
        )
        aura.add_color_stop_rgba(1, 0.05, 0.70, 0.86, 0.0)
        cr.set_source(aura)
        cr.arc(cx, cy, radius, 0, math.tau)
        cr.fill()

    cr.set_line_width(max(1.0, min(w, h) * (0.010 + tension * 0.010)))
    for i in range(18):
        phase = t * (0.40 + drift * 0.25) + i * 0.51
        y0 = y + h * ((i + 0.35 + slow * 0.18) / 18.0)
        cr.set_source_rgba(0.30, 0.94, 1.0, 0.12 + pulse * 0.12)
        cr.move_to(x, y0)
        cr.curve_to(
            x + w * 0.25,
            y0 + math.sin(phase) * h * (0.12 + drift * 0.16),
            x + w * 0.74,
            y0 + math.cos(phase * 1.2) * h * (0.12 + temporal * 0.16),
            x + w * (0.92 + depth * 0.22),
            y0 + math.sin(phase * 0.6) * h * 0.12,
        )
        cr.stroke()

    cr.set_line_width(max(1.0, min(w, h) * 0.006))
    for i in range(11):
        phase = t * (0.55 + noise_amp * 0.20) + i * 1.37
        cx = x + w * (0.50 + math.sin(phase) * (0.20 + depth * 0.13))
        cy = y + h * (0.50 + math.cos(phase * 0.81) * (0.18 + temporal * 0.14))
        r = min(w, h) * (0.10 + i * 0.018 + coherence * 0.04)
        cr.set_source_rgba(1.0, 0.55 + warmth * 0.24, 0.10, 0.055 + pulse * 0.055)
        cr.arc(cx, cy, r, 0, math.tau)
        cr.stroke()

    cr.set_operator(cairo.OPERATOR_SCREEN)
    cr.set_source_rgba(0.96, 0.12 + spectral * 0.36, 0.76, min(0.34, 0.10 + tension * 0.22))
    for i in range(10):
        phase = t * 0.23 + i * 0.43
        x0 = x + w * ((i - 2.0) / 8.0)
        cr.move_to(x0, y + h * (0.05 + 0.05 * math.sin(phase)))
        cr.line_to(
            x0 + w * (0.55 + 0.20 * math.sin(phase)), y + h * (0.96 + 0.04 * math.cos(phase))
        )
        cr.stroke()
    cr.set_operator(cairo.OPERATOR_OVER)

    cr.set_source_rgba(1.0, 0.78, 0.18, min(0.30, 0.08 + sediment * 1.8 + noise_amp * 0.08))
    for i in range(42):
        phase = i * 12.9898 + int(t * (7 + temporal * 12)) * 78.233
        px = x + (math.sin(phase) * 43758.5453 % 1.0) * w
        py = y + (math.sin(phase * 1.31) * 24634.6345 % 1.0) * h
        size = max(1.0, min(w, h) * (0.004 + (i % 5) * 0.0015))
        cr.rectangle(px, py, size * (1.5 + drift), size)
        cr.fill()
    cr.restore()
    return {
        "status": "state-proxy",
        "source": "reverie-uniforms",
        "uniforms_path": str(uniforms_path),
        "visual_chain_path": str(visual_chain_path),
        "hue_rotate": round(hue, 3),
        "drift": round(drift, 3),
        "temporal": round(temporal, 3),
        "spectral": round(spectral, 3),
        "freshness": "live-uniform-field",
        "proxy": "material-reverie-field",
    }


def _stale_source_reason(backend: Any, *, now: float, max_age_s: float) -> str | None:
    """Return a stale-source reason for shm-backed live wards.

    Source-registry substrate readers intentionally allow unlimited age so the
    compositor can keep topology stable. Inside the Quake atlas, stale pixels
    are worse than absence: they masquerade as a functioning in-world ward.
    """
    path_value = getattr(backend, "_path", None)
    if path_value is None:
        return None
    payload_path = Path(path_value)
    sidecar_path = Path(
        getattr(backend, "_sidecar_path", payload_path.with_suffix(payload_path.suffix + ".json"))
    )
    try:
        payload_mtime = payload_path.stat().st_mtime
        sidecar_mtime = sidecar_path.stat().st_mtime
    except OSError as exc:
        return f"shm source unavailable:{type(exc).__name__}"
    age = now - min(payload_mtime, sidecar_mtime)
    if age > max_age_s:
        return f"stale shm source:{age:.1f}s>{max_age_s:.1f}s"
    return None


def _blit_surface_into_cell(
    cr: cairo.Context,
    source: cairo.ImageSurface,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
) -> None:
    src_w = max(1, int(source.get_width()))
    src_h = max(1, int(source.get_height()))
    content_x = x
    content_y = y
    content_w = w
    content_h = h
    cr.save()
    cr.rectangle(content_x, content_y, content_w, content_h)
    cr.clip()
    cr.translate(content_x, content_y)
    cr.scale(content_w / src_w, content_h / src_h)
    cr.set_source_surface(source, 0, 0)
    cr.paint()
    cr.restore()


def _surface_has_visible_alpha(surface: cairo.ImageSurface, *, min_alpha: int = 3) -> bool:
    surface.flush()
    width = max(0, int(surface.get_width()))
    height = max(0, int(surface.get_height()))
    stride = int(surface.get_stride())
    data = bytes(surface.get_data())
    row_bytes = width * 4
    for row in range(height):
        start = row * stride + 3
        end = row * stride + row_bytes
        if any(data[offset] > min_alpha for offset in range(start, end, 4)):
            return True
    return False


def _generic_atlas_idle_surface(
    *,
    ward_id: str,
    width: int,
    height: int,
    t: float,
) -> cairo.ImageSurface:
    width = max(1, int(width))
    height = max(1, int(height))
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    cr.set_source_rgb(0.075, 0.090, 0.105)
    cr.paint()
    cr.rectangle(0, 0, width, height)
    cr.set_source_rgba(0.17, 0.23, 0.30, 0.70)
    cr.fill()

    cr.set_line_width(max(1.0, min(width, height) * 0.006))
    grid = max(18, min(width, height) // 5)
    for x in range(0, width + grid, grid):
        cr.set_source_rgba(0.27, 0.90, 1.0, 0.20)
        cr.move_to(x, 0)
        cr.line_to(max(0, x - width * 0.20), height)
        cr.stroke()
    for y in range(0, height + grid, grid):
        cr.set_source_rgba(1.0, 0.25, 0.66, 0.18)
        cr.move_to(0, y)
        cr.line_to(width, max(0, y - height * 0.16))
        cr.stroke()

    pulse = 0.5 + 0.5 * math.sin(t * 1.37 + len(ward_id))
    cr.set_line_width(max(2.0, min(width, height) * 0.012))
    cr.set_source_rgba(0.46, 1.0, 0.70, 0.45 + pulse * 0.22)
    cr.rectangle(width * 0.055, height * 0.14, width * 0.89, height * 0.72)
    cr.stroke()
    cr.set_source_rgba(1.0, 0.68, 0.05, 0.28 + pulse * 0.16)
    cr.rectangle(width * 0.075, height * 0.20, width * 0.85, height * 0.20)
    cr.fill()

    label = WARD_LABELS.get(ward_id, ward_id.replace("_", " ").upper())
    title_size = max(13, min(30, width // max(8, len(label))))
    status_size = max(12, min(24, height // 6))
    _draw_text(cr, label[:34], width * 0.10, height * 0.35, title_size, "cyan")
    _draw_text(cr, "IDLE", width * 0.10, height * 0.63, status_size, "amber")
    surface.flush()
    return surface


def _atlas_idle_surface_from_backend(
    backend: Any,
    *,
    ward_id: str,
    width: int,
    height: int,
    t: float,
) -> cairo.ImageSurface | None:
    if ward_id not in ATLAS_IDLE_SCAFFOLD_WARDS:
        return None
    source = getattr(backend, "_source", None)
    render_idle = getattr(source, "render_atlas_idle_surface", None)
    if ward_id in SOURCE_PROVIDED_ATLAS_IDLE_SCAFFOLD_WARDS and callable(render_idle):
        return render_idle(width, height, t)
    if ward_id in GENERIC_ATLAS_IDLE_SCAFFOLD_WARDS:
        return _generic_atlas_idle_surface(ward_id=ward_id, width=width, height=height, t=t)
    return None


def render_atlas(
    *,
    output: Path,
    meta: Path,
    layout_path: Path,
    width: int,
    height: int,
    columns: int,
    cell_width: int,
    cell_height: int,
    frame_id: int,
    backends: dict[str, Any] | None = None,
    errors: dict[str, str] | None = None,
    stale_source_seconds: float = DEFAULT_STALE_SOURCE_SECONDS,
    drift_renderer: MediaDriftRenderer | None = None,
    drift_receiver: str = "ward-atlas",
    gpu_drift_raw_output: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if backends is None or errors is None:
        backends, errors = _construct_backends(layout_path)

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    cr.set_source_rgb(*PALETTE["bg"])
    cr.paint()
    cr.set_antialias(cairo.ANTIALIAS_DEFAULT)
    now = time.monotonic()
    observed: dict[str, Any] = {}

    for index, ward_id in enumerate(WARD_IDS, start=1):
        col = (index - 1) % columns
        row = (index - 1) // columns
        x = col * cell_width
        y = row * cell_height
        if x + cell_width > width or y + cell_height > height:
            continue

        if ward_id in DIRECT_TEXTURE_WARDS:
            _paint_fallback(
                cr,
                ward_id=ward_id,
                index=index,
                x=x,
                y=y,
                w=cell_width,
                h=cell_height,
                reason="direct live texture owns this ward",
            )
            observed[ward_id] = {
                "status": "direct-texture-owned",
                "texture": DIRECT_TEXTURE_WARD_TEXTURES[ward_id],
                "reason": "direct live texture owns this ward",
                "visibility_classification": "direct-texture-owned",
                "visibility_reasons": ["owned_by_direct_live_texture"],
            }
            continue

        registry = backends.get(ward_id)
        if registry is None:
            _paint_fallback(
                cr,
                ward_id=ward_id,
                index=index,
                x=x,
                y=y,
                w=cell_width,
                h=cell_height,
                reason=errors.get(ward_id, "backend unavailable"),
            )
            observed[ward_id] = {
                "status": "fallback",
                "reason": errors.get(ward_id),
                "visibility_classification": "fallback",
                "visibility_reasons": [str(errors.get(ward_id) or "backend unavailable")],
            }
            continue

        try:
            backend = registry._backends[ward_id]  # noqa: SLF001 - bounded producer bridge
            stale_reason = _stale_source_reason(
                backend, now=time.time(), max_age_s=stale_source_seconds
            )
            if stale_reason is not None:
                src = None
                errors[ward_id] = stale_reason
                raise RuntimeError(stale_reason)
            tick_once = getattr(backend, "tick_once", None)
            if tick_once is not None:
                tick_once()
            src = registry.get_current_surface(ward_id)
        except Exception as exc:  # noqa: BLE001 - one ward must not kill atlas
            src = None
            errors[ward_id] = f"{type(exc).__name__}: {exc}"

        if src is None:
            _paint_fallback(
                cr,
                ward_id=ward_id,
                index=index,
                x=x,
                y=y,
                w=cell_width,
                h=cell_height,
                reason=errors.get(ward_id, "surface not fresh"),
            )
            observed[ward_id] = {
                "status": "fallback",
                "reason": errors.get(ward_id),
                "visibility_classification": "fallback",
                "visibility_reasons": [str(errors.get(ward_id) or "surface not fresh")],
            }
            continue

        status = "rendered"
        if ward_id in ATLAS_IDLE_SCAFFOLD_WARDS and not _surface_has_visible_alpha(src):
            idle_src = _atlas_idle_surface_from_backend(
                backend,
                ward_id=ward_id,
                width=int(src.get_width()),
                height=int(src.get_height()),
                t=now,
            )
            if idle_src is not None:
                src = idle_src
                status = "atlas-idle-scaffold"

        visibility_stats = _surface_visibility_stats(src)
        visibility_classification, visibility_reasons = _visibility_classification(
            status=status,
            stats=visibility_stats,
        )
        readability_lift = False
        pre_readability: dict[str, Any] = {}
        if _needs_readability_lift(
            status=status,
            classification=visibility_classification,
            stats=visibility_stats,
        ):
            pre_readability = {
                "classification": visibility_classification,
                "reasons": visibility_reasons,
                "stats": dict(visibility_stats),
            }
            src = _readability_lift_surface(src, ward_id=ward_id, t=now)
            visibility_stats = _surface_visibility_stats(src)
            visibility_classification, visibility_reasons = _visibility_classification(
                status=status,
                stats=visibility_stats,
            )
            readability_lift = True

        _blit_surface_into_cell(cr, src, x=x, y=y, w=cell_width, h=cell_height)
        observed[ward_id] = {
            "status": status,
            "source_width": int(src.get_width()),
            "source_height": int(src.get_height()),
            "atlas_style": "borderless-no-grid",
            "visibility_classification": visibility_classification,
            "visibility_reasons": visibility_reasons,
            "readability_lift": readability_lift,
            **visibility_stats,
        }
        if pre_readability:
            observed[ward_id]["pre_readability_visibility"] = pre_readability

    data = _surface_bgra_bytes(surface, width, height)
    drift_input_hash = _short_hash(data)
    visibility_summary = _visibility_summary(observed)
    if gpu_drift_raw_output is not None:
        _atomic_write(gpu_drift_raw_output, data)
        payload = {
            "w": width,
            "h": height,
            "stride": width * 4,
            "frame_id": frame_id,
            "observed_at": time.time(),
            "cell_width": cell_width,
            "cell_height": cell_height,
            "columns": columns,
            "ward_count": len(WARD_IDS),
            "wards": observed,
            "visibility_thresholds": _visibility_thresholds(),
            "visibility_summary": visibility_summary,
            "gpu_drift": True,
            "gpu_drift_raw_output": str(gpu_drift_raw_output),
            "gpu_drift_final_output": str(output),
            "gpu_drift_output_owner": "screwm_media_drift",
            "drift_renderer": "quake-media-drift-v1",
            "drift_enabled": False,
            "drift_receiver": drift_receiver,
            "drift_game_data": str(getattr(drift_renderer, "game_data", ""))
            if drift_renderer is not None
            else "",
            "drift_intensity": float(getattr(drift_renderer, "intensity", 0.0))
            if drift_renderer is not None
            else 0.0,
            "drift_input_hash": drift_input_hash,
            "drift_output_hash": "",
            "drift_changed": False,
        }
        _atomic_write(
            gpu_drift_raw_output.with_suffix(".json"),
            json.dumps(payload, sort_keys=True).encode("utf-8"),
        )
        return observed, errors
    if drift_renderer is not None:
        data = drift_renderer.apply(
            data,
            width=width,
            height=height,
            receiver=drift_receiver,
            frame=frame_id,
            now=now,
        )
    drift_output_hash = _short_hash(data)
    _atomic_write(output, data)
    payload = {
        "w": width,
        "h": height,
        "stride": width * 4,
        "frame_id": frame_id,
        "observed_at": time.time(),
        "cell_width": cell_width,
        "cell_height": cell_height,
        "columns": columns,
        "ward_count": len(WARD_IDS),
        "wards": observed,
        "visibility_thresholds": _visibility_thresholds(),
        "visibility_summary": visibility_summary,
        "drift_renderer": "quake-media-drift-v1",
        "drift_enabled": bool(getattr(drift_renderer, "enabled", False))
        if drift_renderer is not None
        else False,
        "drift_receiver": drift_receiver,
        "drift_game_data": str(getattr(drift_renderer, "game_data", "")) if drift_renderer else "",
        "drift_intensity": float(getattr(drift_renderer, "intensity", 0.0))
        if drift_renderer is not None
        else 0.0,
        "drift_input_hash": drift_input_hash,
        "drift_output_hash": drift_output_hash,
        "drift_changed": drift_input_hash != drift_output_hash,
    }
    _atomic_write(meta, json.dumps(payload, sort_keys=True).encode("utf-8"))
    return observed, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Screwm ward atlas BGRA frames")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--layout", type=Path, default=DEFAULT_LAYOUT)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--columns", type=int, default=DEFAULT_COLUMNS)
    parser.add_argument("--cell-width", type=int, default=DEFAULT_CELL_WIDTH)
    parser.add_argument("--cell-height", type=int, default=DEFAULT_CELL_HEIGHT)
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--drift",
        choices=("on", "off", "enabled", "disabled"),
        default=os.environ.get("HAPAX_QUAKE_WARD_ATLAS_DRIFT", "on"),
        help="Apply receiver-local Scroom drift before DarkPlaces texture upload.",
    )
    parser.add_argument(
        "--drift-receiver",
        default=os.environ.get("HAPAX_QUAKE_WARD_ATLAS_DRIFT_RECEIVER", "ward-atlas"),
        help="Receiver identity used for deterministic ward-atlas drift.",
    )
    parser.add_argument(
        "--drift-game-data",
        type=Path,
        default=Path(
            os.environ.get("HAPAX_QUAKE_WARD_ATLAS_DRIFT_GAME_DATA", str(DEFAULT_GAME_DATA))
        ),
        help="DarkPlaces-exported drift scalar directory.",
    )
    parser.add_argument(
        "--drift-intensity",
        type=float,
        default=float(os.environ.get("HAPAX_QUAKE_WARD_ATLAS_DRIFT_INTENSITY", "1.2")),
        help="Receiver-local drift intensity multiplier.",
    )
    parser.add_argument(
        "--gpu-drift",
        action="store_true",
        default=_gpu_drift_default(),
        help=(
            "GPU media-drift cutover: write the undrifted atlas frame to "
            "<output>.raw.bgra and leave final output/metadata ownership to "
            "screwm_media_drift."
        ),
    )
    args = parser.parse_args()

    if args.width > 4096 or args.height > 4096:
        raise SystemExit("atlas dimensions must stay within DarkPlaces live-texture cap")
    if args.columns <= 0 or args.cell_width <= 0 or args.cell_height <= 0:
        raise SystemExit("columns/cell dimensions must be positive")

    running = True

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    backends, errors = _construct_backends(args.layout)
    drift_renderer = MediaDriftRenderer(
        game_data=args.drift_game_data,
        enabled=_truthy(args.drift),
        intensity=args.drift_intensity,
    )
    raw_output, _raw_meta = _gpu_drift_paths(args.output) if args.gpu_drift else (None, None)
    frame_id = 0
    period = 1.0 / max(0.1, args.fps)
    while running:
        frame_id += 1
        started = time.monotonic()
        render_atlas(
            output=args.output,
            meta=args.meta,
            layout_path=args.layout,
            width=args.width,
            height=args.height,
            columns=args.columns,
            cell_width=args.cell_width,
            cell_height=args.cell_height,
            frame_id=frame_id,
            backends=backends,
            errors=errors,
            drift_renderer=drift_renderer,
            drift_receiver=args.drift_receiver,
            gpu_drift_raw_output=raw_output,
        )
        if args.once:
            break
        elapsed = time.monotonic() - started
        time.sleep(max(0.01, period - elapsed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
