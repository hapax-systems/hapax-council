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
    "m8-display",
    "steamdeck-display",
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
    "m8_oscilloscope",
    "cbip_dual_ir_displacement",
]

DIRECT_TEXTURE_WARDS = {
    # Reverie is bound to DarkPlaces live-texture slot 12 as w05. Keeping a
    # separate atlas proxy made stale substrate failures look like working
    # in-world reverie. The atlas reserves the cell but never renders content.
    "reverie",
}

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
    "m8-display": "M8 DISPLAY",
    "steamdeck-display": "STEAM DECK",
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
    "m8_oscilloscope": "M8 SCOPE",
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


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


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
                "texture": "w05",
                "reason": "direct live texture owns this ward",
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
            observed[ward_id] = {"status": "fallback", "reason": errors.get(ward_id)}
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
            observed[ward_id] = {"status": "fallback", "reason": errors.get(ward_id)}
            continue

        _blit_surface_into_cell(cr, src, x=x, y=y, w=cell_width, h=cell_height)
        observed[ward_id] = {
            "status": "rendered",
            "source_width": int(src.get_width()),
            "source_height": int(src.get_height()),
            "atlas_style": "borderless-no-grid",
        }

    data = _surface_bgra_bytes(surface, width, height)
    drift_input_hash = _short_hash(data)
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
        )
        if args.once:
            break
        elapsed = time.monotonic() - started
        time.sleep(max(0.01, period - elapsed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
