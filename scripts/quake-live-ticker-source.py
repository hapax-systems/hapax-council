#!/usr/bin/env python3
"""Render live ticker ward mounts into DarkPlaces BGRA texture files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path

import cairo
import gi

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from quake_media_drift import DEFAULT_GAME_DATA, MediaDriftRenderer  # noqa: E402

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402


DEFAULT_OUTPUT = Path("/dev/shm/hapax-compositor/quake-live-ticker-grounding.bgra")
DEFAULT_META = Path("/dev/shm/hapax-compositor/quake-live-ticker-grounding.json")
DEFAULT_INTENT_PATH = Path(
    os.path.expanduser("~/hapax-state/stream-experiment/director-intent.jsonl")
)
DEFAULT_WIDTH = 1344
DEFAULT_HEIGHT = 176
DEFAULT_FPS = 8
FONT_FAMILY = os.environ.get("HAPAX_QUAKE_TICKER_FONT", "Px437 IBM VGA 8x16")

PALETTE = {
    "bg": (4, 6, 12, 255),
    "cyan": (68, 231, 255, 255),
    "magenta": (255, 70, 170, 255),
    "amber": (255, 176, 0, 255),
    "green": (118, 255, 178, 255),
    "muted": (106, 124, 148, 255),
    "dim": (32, 43, 58, 255),
}


def _read_latest_intent(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - 16384))
            tail = fh.read().decode("utf-8", errors="ignore")
        lines = [line for line in tail.splitlines() if line.strip()]
        if not lines:
            return {}
        data = json.loads(lines[-1])
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _is_synthetic_grounding_marker(value: str) -> bool:
    lowered = value.strip().lower()
    return (
        not lowered
        or lowered.startswith(".")
        or lowered.startswith("fallback.")
        or lowered.startswith("inferred.")
        or lowered in {"parser-error", "silence-hold"}
    )


def _grounding_rows(intent: dict, *, max_rows: int = 3) -> list[str]:
    rows: list[str] = []
    for raw in intent.get("grounding_provenance") or []:
        for part in str(raw).replace(" , ", ",").split(","):
            clean = part.strip()
            if clean and not _is_synthetic_grounding_marker(clean) and clean not in rows:
                rows.append(clean)
            if len(rows) >= max_rows:
                return rows
    return rows


def _precedent_rows(intent: dict, *, max_rows: int = 3) -> list[str]:
    rows: list[str] = []
    structural = intent.get("structural_intent") or {}
    if isinstance(structural, dict):
        emphasis = [str(item) for item in structural.get("ward_emphasis") or [] if item]
        if emphasis:
            rows.append("ward emphasis: " + " / ".join(emphasis[:4]))
        rotation = str(structural.get("homage_rotation_mode") or "").strip()
        if rotation:
            rows.append("homage rotation: " + rotation)
        dispatch = [str(item) for item in structural.get("ward_dispatch") or [] if item]
        if dispatch:
            rows.append("dispatch: " + " / ".join(dispatch[:3]))
    condition = str(intent.get("condition_id") or "").strip()
    if condition and condition != "none":
        rows.append("condition: " + condition)
    if not rows:
        rows.append("no active precedent route; holding director posture")
    return rows[:max_rows]


def _chronicle_rows(intent: dict, *, max_rows: int = 3) -> list[str]:
    rows: list[str] = []
    activity = str(intent.get("activity") or "").strip()
    stance = str(intent.get("stance") or "").strip()
    if activity or stance:
        rows.append(f"activity: {activity or 'unknown'} / stance: {stance or 'unknown'}")
    for impingement in intent.get("compositional_impingements") or []:
        if not isinstance(impingement, dict):
            continue
        family = str(impingement.get("intent_family") or "intent").strip()
        material = str(impingement.get("material") or "void").strip()
        salience = impingement.get("salience")
        try:
            salience_text = f"{float(salience):.2f}"
        except (TypeError, ValueError):
            salience_text = "--"
        rows.append(f"{material}: {family} salience {salience_text}")
        if len(rows) >= max_rows:
            break
    narrative = str(intent.get("narrative_text") or "").strip()
    if narrative and len(rows) < max_rows:
        rows.append(narrative)
    if not rows:
        rows.append("chronicle quiet; waiting for current director event")
    return rows[:max_rows]


def _ticker_rows(intent: dict, role: str, *, max_rows: int = 3) -> list[str]:
    if role == "precedent":
        return _precedent_rows(intent, max_rows=max_rows)
    if role == "chronicle":
        return _chronicle_rows(intent, max_rows=max_rows)
    return _grounding_rows(intent, max_rows=max_rows)


def _set_rgba(cr: cairo.Context, color: tuple[int, int, int, int], alpha: float = 1.0) -> None:
    cr.set_source_rgba(
        color[0] / 255.0,
        color[1] / 255.0,
        color[2] / 255.0,
        (color[3] / 255.0) * alpha,
    )


def _layout(
    cr: cairo.Context,
    text: str,
    size: int,
    *,
    max_width: int | None = None,
    ellipsize: bool = True,
) -> Pango.Layout:
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(Pango.FontDescription(f"{FONT_FAMILY} {size}"))
    layout.set_text(text, -1)
    if max_width is not None:
        layout.set_width(max_width * Pango.SCALE)
        if ellipsize:
            layout.set_ellipsize(Pango.EllipsizeMode.END)
    return layout


def _text_width(cr: cairo.Context, text: str, size: int) -> int:
    layout = _layout(cr, text, size, ellipsize=False)
    width, _height = layout.get_pixel_size()
    return width


def _draw_text(
    cr: cairo.Context,
    text: str,
    x: int,
    y: int,
    size: int,
    color: tuple[int, int, int, int],
    *,
    max_width: int | None = None,
) -> None:
    _set_rgba(cr, color)
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, _layout(cr, text, size, max_width=max_width))


def _draw_scanlines(cr: cairo.Context, width: int, height: int, t: float) -> None:
    """Legacy diagnostic grid painter.

    The in-world ticker mount is borderless. This helper remains available for
    explicit diagnostic rendering, but the production ticker does not call it.
    """
    drift = int(t * 18) % 8
    _set_rgba(cr, (38, 52, 74, 255), 0.38)
    cr.set_line_width(1)
    for y in range(drift, height, 8):
        cr.move_to(0, y + 0.5)
        cr.line_to(width, y + 0.5)
    cr.stroke()

    for x in range(0, width, 64):
        _set_rgba(cr, (41, 72, 86, 255) if x % 128 == 0 else PALETTE["dim"], 0.65)
        cr.move_to(x + 0.5, 0)
        cr.line_to(x + 0.5, height)
        cr.stroke()


def _surface_bgra_bytes(surface: cairo.ImageSurface, width: int, height: int) -> bytes:
    surface.flush()
    stride = surface.get_stride()
    data = bytes(surface.get_data())
    row_bytes = width * 4
    if stride == row_bytes:
        return data[: row_bytes * height]
    return b"".join(data[y * stride : y * stride + row_bytes] for y in range(height))


def _flip_bgra_y(data: bytes, width: int, height: int) -> bytes:
    row_bytes = width * 4
    return b"".join(
        data[y * row_bytes : (y + 1) * row_bytes] for y in range(height - 1, -1, -1)
    )


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def render_ticker_frame(
    *,
    width: int,
    height: int,
    role: str,
    rows: list[str],
    now: float,
) -> bytes:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)

    _set_rgba(cr, PALETTE["bg"])
    cr.paint()
    cr.set_antialias(cairo.ANTIALIAS_NONE)

    header_size = max(18, height // 5)
    row_size = max(17, height // 7)
    tiny_size = max(13, height // 10)
    phase = (now * 0.18) % 1.0
    hot = tuple(
        int(PALETTE["cyan"][idx] * (1.0 - phase) + PALETTE["magenta"][idx] * phase)
        for idx in range(3)
    ) + (255,)

    _draw_text(cr, ">>>", 22, 15, header_size, hot)
    role_label = {
        "grounding": "[grounding provenance]",
        "precedent": "[precedent]",
        "chronicle": "[chronicle]",
    }.get(role, f"[{role}]")
    _draw_text(cr, role_label, 132, 15, header_size, PALETTE["muted"])
    _draw_text(
        cr,
        time.strftime("%H:%M:%S", time.localtime(now)),
        width - 198,
        20,
        tiny_size,
        PALETTE["amber"],
    )

    if not rows:
        breath = 0.55 + 0.35 * abs(((now * 0.6) % 2.0) - 1.0)
        color = tuple(int(c * breath) for c in PALETTE["muted"][:3]) + (255,)
        rows = ["(ungrounded) waiting for director-intent grounding_provenance"]
    else:
        rows = rows[:3]
        color = PALETTE["green"]

    y = 64
    for idx, row in enumerate(rows):
        color = (PALETTE["green"], PALETTE["cyan"], PALETTE["amber"])[idx % 3]
        cr.arc(27, y + 13, 5, 0, 6.28318530718)
        _set_rgba(cr, color)
        cr.fill()

        text = "* " + row
        text_w = _text_width(cr, text, row_size)
        if text_w > width - 96:
            span = text_w + 160
            x = 42 - int((now * 42) % span)
            while x < width:
                _draw_text(cr, text, x, y, row_size, color)
                x += span
        else:
            _draw_text(cr, text, 42, y, row_size, color, max_width=width - 72)
        y += 36

    return _surface_bgra_bytes(surface, width, height)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _write_meta(path: Path, args: argparse.Namespace, frames: int, row_count: int) -> None:
    payload = {
        "source": "ticker",
        "renderer": "cairo-pango",
        "pixel_format": "BGRA8888",
        "ticker_role": args.ticker_role,
        "input": str(args.intent_path),
        "width": args.width,
        "height": args.height,
        "fps": args.fps,
        "preflip_y": _truthy(args.preflip_y),
        "drift_renderer": "quake-media-drift-v1",
        "drift_enabled": _truthy(getattr(args, "drift", "on")),
        "drift_receiver": _drift_receiver(args),
        "drift_game_data": str(getattr(args, "drift_game_data", DEFAULT_GAME_DATA)),
        "drift_intensity": float(getattr(args, "drift_intensity", 1.0)),
        "drift_input_hash": getattr(args, "drift_input_hash", ""),
        "drift_output_hash": getattr(args, "drift_output_hash", ""),
        "drift_changed": bool(getattr(args, "drift_changed", False)),
        "frames": frames,
        "row_count": row_count,
        "updated_at": time.time(),
    }
    _write_atomic(path, json.dumps(payload, sort_keys=True).encode("utf-8") + b"\n")


def stream_frames(args: argparse.Namespace) -> int:
    frames = 0
    rows: list[str] = []
    stop = False
    drift_renderer = MediaDriftRenderer(
        game_data=getattr(args, "drift_game_data", DEFAULT_GAME_DATA),
        enabled=_truthy(getattr(args, "drift", "on")),
        intensity=float(getattr(args, "drift_intensity", 1.0)),
    )
    drift_receiver = _drift_receiver(args)

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    frame_interval = 1.0 / max(1, args.fps)

    while not stop:
        now = time.time()
        intent = _read_latest_intent(args.intent_path)
        rows = _ticker_rows(intent, args.ticker_role)
        data = render_ticker_frame(
            width=args.width,
            height=args.height,
            role=args.ticker_role,
            rows=rows,
            now=now,
        )
        next_frame = frames + 1
        should_write_meta = next_frame == 1 or next_frame % max(1, args.fps * 5) == 0
        drift_input_hash = (
            hashlib.blake2s(data, digest_size=8).hexdigest()
            if should_write_meta
            else getattr(args, "drift_input_hash", "")
        )
        data = drift_renderer.apply(
            data,
            width=args.width,
            height=args.height,
            receiver=drift_receiver,
            frame=next_frame,
            now=now,
        )
        drift_output_hash = (
            hashlib.blake2s(data, digest_size=8).hexdigest()
            if should_write_meta
            else getattr(args, "drift_output_hash", "")
        )
        if should_write_meta:
            args.drift_input_hash = drift_input_hash
            args.drift_output_hash = drift_output_hash
            args.drift_changed = drift_input_hash != drift_output_hash
        if _truthy(args.preflip_y):
            data = _flip_bgra_y(data, args.width, args.height)
        _write_atomic(args.output, data)
        frames += 1
        if should_write_meta:
            _write_meta(args.meta, args, frames, len(rows))
        if args.once:
            break
        time.sleep(frame_interval)

    _write_meta(args.meta, args, frames, len(rows))
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker-role", default=os.environ.get("HAPAX_QUAKE_TICKER_ROLE", "grounding"))
    parser.add_argument("--intent-path", type=Path, default=DEFAULT_INTENT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--preflip-y", default=os.environ.get("HAPAX_QUAKE_TICKER_PREFLIP_Y", "0"))
    parser.add_argument(
        "--drift",
        choices=("on", "off", "enabled", "disabled"),
        default=os.environ.get("HAPAX_QUAKE_TICKER_DRIFT", "on"),
        help="Apply receiver-local Scroom drift before DarkPlaces texture upload.",
    )
    parser.add_argument(
        "--drift-receiver",
        default=os.environ.get("HAPAX_QUAKE_TICKER_DRIFT_RECEIVER", ""),
        help="Receiver identity used for deterministic ticker drift.",
    )
    parser.add_argument(
        "--drift-game-data",
        type=Path,
        default=Path(os.environ.get("HAPAX_QUAKE_DRIFT_GAME_DATA", str(DEFAULT_GAME_DATA))),
        help="DarkPlaces game data directory containing exported drift scalars.",
    )
    parser.add_argument(
        "--drift-intensity",
        type=float,
        default=float(os.environ.get("HAPAX_QUAKE_TICKER_DRIFT_INTENSITY", "1.0")),
        help="Multiplier for texture-local ticker drift intensity.",
    )
    parser.add_argument("--once", action="store_true")
    return parser.parse_args(argv)


def _drift_receiver(args: argparse.Namespace) -> str:
    configured = str(getattr(args, "drift_receiver", "") or "").strip()
    if configured:
        return configured
    return f"ticker:{args.ticker_role}"


def main(argv: list[str]) -> int:
    return stream_frames(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
