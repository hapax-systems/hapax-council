#!/usr/bin/env python3
"""Render the AoA face-control atlas for DarkPlaces live model-skin upload."""

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

DEFAULT_OUTPUT = Path("/dev/shm/hapax-compositor/quake-live-aoa-atlas.bgra")
DEFAULT_META = Path("/dev/shm/hapax-compositor/quake-live-aoa-atlas.json")
DEFAULT_GAME_DATA = Path.home() / ".darkplaces/screwm/data"
DEFAULT_CONTROLS = Path("/dev/shm/hapax-compositor/aoa-face-controls.json")
DEFAULT_WIDTH = 2048
DEFAULT_HEIGHT = 2048
DEFAULT_COLUMNS = 32
DEFAULT_CELL_SIZE = 64
DEFAULT_FPS = 4.0
FACE_COUNT = 1024
GEOMETRY_REVISION = "aoa-regular-tetrix-v6-expanded-iteration-perfect-fit-oarb"
LEAF_FACE_EDGE_UNITS = 81.12
FACE_OPERABILITY_CONTRACT = "stable-independent-control-per-rendered-fractal-face"


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _gpu_drift_default() -> bool:
    value = os.environ.get(
        "HAPAX_QUAKE_AOA_ATLAS_GPU_DRIFT",
        os.environ.get("HAPAX_QUAKE_GPU_DRIFT", "1"),
    )
    return _truthy(value)


def _gpu_drift_paths(output: Path) -> tuple[Path, Path]:
    raw_output = output.with_name(f"{output.stem}.raw.bgra")
    return raw_output, raw_output.with_suffix(".json")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _short_hash(data: bytes) -> str:
    return hashlib.blake2s(data, digest_size=8).hexdigest()


def _face_cell_map(columns: int, cell_size: int) -> list[dict[str, int]]:
    return [
        {
            "face_index": face_index,
            "row": face_index // columns,
            "column": face_index % columns,
            "x": (face_index % columns) * cell_size,
            "y": (face_index // columns) * cell_size,
            "w": cell_size,
            "h": cell_size,
        }
        for face_index in range(FACE_COUNT)
    ]


def _face_cell_map_hash(columns: int, cell_size: int) -> str:
    mapping = json.dumps(_face_cell_map(columns, cell_size), sort_keys=True).encode("utf-8")
    return _short_hash(mapping)


def _clamp_byte(value: object) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(number):
        return 0
    return max(0, min(255, int(round(number))))


def _clamp_gain(value: object, fallback: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):
        return fallback
    return max(0.0, min(4.0, number))


def _parse_color(value: object) -> tuple[int, int, int] | None:
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("#"):
            raw = raw[1:]
        if len(raw) == 6:
            try:
                return (
                    int(raw[0:2], 16),
                    int(raw[2:4], 16),
                    int(raw[4:6], 16),
                )
            except ValueError:
                return None
        return None
    if isinstance(value, list | tuple) and len(value) >= 3:
        return (_clamp_byte(value[0]), _clamp_byte(value[1]), _clamp_byte(value[2]))
    return None


def _parse_face_control(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    control: dict[str, object] = {}
    color = _parse_color(value.get("rgb", value.get("color")))
    if color is not None:
        control["rgb"] = color
    for key in ("intensity", "edge_gain", "stripe_gain", "stipple_gain"):
        if key in value:
            control[key] = _clamp_gain(value[key])
    return control


def load_face_controls(path: Path | None) -> dict[int, dict[str, object]]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    faces = payload.get("faces", payload) if isinstance(payload, dict) else payload
    controls: dict[int, dict[str, object]] = {}
    if isinstance(faces, list):
        iterable = enumerate(faces)
    elif isinstance(faces, dict):
        iterable = faces.items()
    else:
        return controls
    for key, value in iterable:
        try:
            face_index = int(key)
        except (TypeError, ValueError):
            continue
        if face_index < 0 or face_index >= FACE_COUNT:
            continue
        parsed = _parse_face_control(value)
        if parsed is not None:
            controls[face_index] = parsed
    return controls


def _read_scalar(game_data: Path, name: str, fallback: float = 0.0) -> float:
    try:
        value = float((game_data / name).read_text(encoding="utf-8").strip())
    except Exception:
        return fallback
    if not math.isfinite(value):
        return fallback
    return max(0.0, min(1.0, value))


def _drift_scalars(game_data: Path) -> dict[str, float]:
    return {
        "real_source": _read_scalar(game_data, "effect-drift-real-source.txt"),
        "active_ratio": _read_scalar(game_data, "effect-drift-active-ratio.txt"),
        "fast_ratio": _read_scalar(game_data, "effect-drift-fast-ratio.txt"),
        "slow_ratio": _read_scalar(game_data, "effect-drift-slow-ratio.txt"),
        "kind_variance": _read_scalar(game_data, "effect-drift-kind-variance.txt"),
        "max_delta": _read_scalar(game_data, "effect-drift-max-delta.txt"),
        "tonal": _read_scalar(game_data, "effect-drift-tonal.txt"),
        "texture": _read_scalar(game_data, "effect-drift-texture.txt"),
        "edge": _read_scalar(game_data, "effect-drift-edge.txt"),
        "compositing": _read_scalar(game_data, "effect-drift-compositing.txt"),
        "visual_drift": _read_scalar(game_data, "visual-chain-drift.txt"),
        "visual_color": _read_scalar(game_data, "visual-chain-color.txt"),
        "visual_feedback": _read_scalar(game_data, "visual-chain-feedback.txt"),
    }


def _face_color(face_index: int, now: float, scalars: dict[str, float]) -> tuple[int, int, int]:
    phase = (
        now * (0.22 + scalars["fast_ratio"] * 0.42)
        + face_index * 0.03125
        + scalars["kind_variance"] * 4.7
        + scalars["max_delta"] * 2.1
    )
    family = face_index % 4
    pressure = max(
        scalars["tonal"],
        scalars["texture"],
        scalars["edge"],
        scalars["compositing"],
        scalars["visual_drift"],
        scalars["visual_color"],
        scalars["visual_feedback"],
    )
    gain = 0.48 + pressure * 0.34 + scalars["active_ratio"] * 0.12
    wave_a = 0.5 + 0.5 * math.sin(phase + family * 1.71)
    wave_b = 0.5 + 0.5 * math.sin(phase * 1.37 + family * 2.03)
    wave_c = 0.5 + 0.5 * math.sin(phase * 0.73 + family * 2.77)
    if family == 0:
        rgb = (wave_a, 0.32 + wave_b * 0.50, 0.68 + wave_c * 0.28)
    elif family == 1:
        rgb = (0.48 + wave_c * 0.44, 0.78 + wave_a * 0.20, 0.28 + wave_b * 0.44)
    elif family == 2:
        rgb = (0.76 + wave_b * 0.20, 0.36 + wave_c * 0.36, 0.72 + wave_a * 0.24)
    else:
        rgb = (0.92 + wave_c * 0.08, 0.58 + wave_b * 0.32, 0.24 + wave_a * 0.44)
    # Desaturated baseline (Moksha law): pull the facet FILL toward luminance with
    # a faint cool tint, keeping only subtle per-facet hue. The bright facet edges
    # (edge_gain, painted separately in _paint_face_cell) survive this, giving the
    # required "desaturated body, luminous edges" read instead of rainbow fill.
    lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    desat = 0.80
    cool = (0.93, 0.99, 1.07)
    rgb = tuple((c * (1.0 - desat) + lum * desat) * cool[i] for i, c in enumerate(rgb))
    return tuple(max(18, min(255, int(channel * 255 * gain))) for channel in rgb)


def _paint_face_cell(
    data: bytearray,
    *,
    width: int,
    cell_size: int,
    col: int,
    row: int,
    face_index: int,
    now: float,
    scalars: dict[str, float],
    control: dict[str, object] | None = None,
) -> None:
    face_control = control or {}
    rgb = face_control.get("rgb")
    if isinstance(rgb, tuple) and len(rgb) >= 3:
        base_r, base_g, base_b = rgb
    else:
        base_r, base_g, base_b = _face_color(face_index, now, scalars)
    intensity = float(face_control.get("intensity", 1.0))
    edge_gain = float(face_control.get("edge_gain", 1.0))
    stripe_gain = float(face_control.get("stripe_gain", 1.0))
    stipple_gain = float(face_control.get("stipple_gain", 1.0))
    cell_x = col * cell_size
    cell_y = row * cell_size
    top_y = cell_size * 0.18
    bottom_y = cell_size * 0.82
    center_x = cell_size * 0.50
    left_x = cell_size * 0.18
    right_x = cell_size * 0.82
    edge_width = (1.8 + scalars["edge"] * 2.4) * max(0.4, min(2.5, edge_gain))
    stripe_period = 7 + (face_index % 5)
    pulse = 0.5 + 0.5 * math.sin(now * 0.9 + face_index * 0.19)
    # Distinct per-facet CONTENT (the locked "distinct per-facet AoA" fork): each
    # facet draws one of 6 pattern regimes (combined with its period/color/phase the
    # 1024 facets read as independent breathing cells, not one repeated motif).
    regime = face_index % 6

    for ly in range(cell_size):
        if ly < top_y or ly > bottom_y:
            continue
        t = (ly - top_y) / max(1.0, bottom_y - top_y)
        lx0 = center_x + (left_x - center_x) * t
        lx1 = center_x + (right_x - center_x) * t
        x0 = max(0, int(math.floor(lx0)))
        x1 = min(cell_size - 1, int(math.ceil(lx1)))
        row_offset = ((cell_y + ly) * width + cell_x) * 4
        for lx in range(x0, x1 + 1):
            edge_distance = min(abs(lx - lx0), abs(lx - lx1), abs(ly - bottom_y))
            edge = edge_distance <= edge_width
            anim = int(now * 9.0)
            if regime == 0:
                stripe = ((lx + ly + anim) % stripe_period) == 0  # diagonal
            elif regime == 1:
                stripe = ((ly + anim) % stripe_period) == 0  # horizontal bands
            elif regime == 2:
                stripe = ((lx - anim) % stripe_period) == 0  # vertical bands
            elif regime == 3:
                stripe = ((lx + anim) % stripe_period == 0) or (
                    (ly + anim) % stripe_period == 0
                )  # grid / cross-hatch
            elif regime == 4:
                stripe = ((lx - ly + anim) % stripe_period) == 0  # anti-diagonal
            else:
                dxc = abs(lx - center_x)
                dyc = abs(ly - cell_size * 0.5)
                stripe = ((int(dxc + dyc) + anim) % stripe_period) == 0  # concentric diamonds
            stipple = (
                (lx * 3 + ly * 5 + face_index * 7 + int(now * 11.0)) % (29 + regime * 4)
            ) == 0
            if not (edge or stripe or stipple):
                scale = (0.16 + pulse * 0.08) * intensity
            elif edge:
                scale = (0.88 + pulse * 0.18) * intensity * edge_gain
            elif stripe:
                scale = (0.46 + pulse * 0.20) * intensity * stripe_gain
            else:
                scale = (0.72 + pulse * 0.16) * intensity * stipple_gain
            idx = row_offset + lx * 4
            data[idx] = max(8, min(255, int(base_b * scale)))
            data[idx + 1] = max(8, min(255, int(base_g * scale)))
            data[idx + 2] = max(8, min(255, int(base_r * scale)))
            data[idx + 3] = 255


def render_atlas(
    *,
    width: int,
    height: int,
    columns: int,
    cell_size: int,
    frame_id: int,
    now: float,
    game_data: Path,
    controls: Path | None = DEFAULT_CONTROLS,
) -> tuple[bytes, dict[str, object]]:
    if width != columns * cell_size or height != columns * cell_size:
        raise ValueError("AoA atlas dimensions must be columns * cell_size square")
    if columns * columns != FACE_COUNT:
        raise ValueError("AoA face atlas must expose exactly 1024 cells at depth 4")

    scalars = _drift_scalars(game_data)
    face_controls = load_face_controls(controls)
    data = bytearray(width * height * 4)
    for face_index in range(FACE_COUNT):
        col = face_index % columns
        row = face_index // columns
        _paint_face_cell(
            data,
            width=width,
            cell_size=cell_size,
            col=col,
            row=row,
            face_index=face_index,
            now=now,
            scalars=scalars,
            control=face_controls.get(face_index),
        )
    meta = {
        "source": "quake-live-aoa-atlas-source",
        "renderer": "aoa-face-atlas-v1",
        "geometry_revision": GEOMETRY_REVISION,
        "frame_id": frame_id,
        "observed_at": time.time(),
        "updated_at": time.time(),
        "w": width,
        "h": height,
        "stride": width * 4,
        "columns": columns,
        "cell_size": cell_size,
        "face_count": FACE_COUNT,
        "fractal_depth": 4,
        "leaf_face_edge_units": LEAF_FACE_EDGE_UNITS,
        "atlas_contract": "one-live-control-cell-per-rendered-fractal-face",
        "face_operability_contract": FACE_OPERABILITY_CONTRACT,
        "face_control_input": str(controls) if controls else "",
        "face_control_input_exists": bool(controls and controls.exists()),
        "face_control_schema": (
            "Optional JSON object or list keyed by face_index; each entry may set "
            "rgb/color, intensity, edge_gain, stripe_gain, and stipple_gain for that face only"
        ),
        "face_control_scope": (
            "Each face_index maps to exactly one rendered AoA fractal face and one atlas cell; "
            "controls do not aggregate, group-address, bleed, or target screen-space overlays"
        ),
        "active_face_control_count": len(face_controls),
        "controlled_face_indices": sorted(face_controls)[:64],
        "face_cell_indexing": (
            "face_index == row * columns + column; row=floor(face_index/columns); "
            "column=face_index%columns; origin=top-left"
        ),
        "face_cell_count": FACE_COUNT,
        "face_cell_map_hash": _face_cell_map_hash(columns, cell_size),
        "face_cell_map_sample": _face_cell_map(columns, cell_size)[:8],
        "drift_scalars": scalars,
    }
    return bytes(data), meta


def write_frame(
    *,
    output: Path,
    meta: Path,
    width: int,
    height: int,
    columns: int,
    cell_size: int,
    frame_id: int,
    game_data: Path,
    gpu_drift: bool,
    controls: Path | None = DEFAULT_CONTROLS,
) -> dict[str, object]:
    data, payload = render_atlas(
        width=width,
        height=height,
        columns=columns,
        cell_size=cell_size,
        frame_id=frame_id,
        now=time.monotonic(),
        game_data=game_data,
        controls=controls,
    )
    input_hash = _short_hash(data)
    if gpu_drift:
        raw_output, raw_meta = _gpu_drift_paths(output)
        _atomic_write(raw_output, data)
        payload.update(
            {
                "gpu_drift": True,
                "gpu_drift_raw_output": str(raw_output),
                "gpu_drift_final_output": str(output),
                "gpu_drift_output_owner": "screwm_media_drift",
                "drift_renderer": "screwm-media-drift-wgpu",
                "drift_enabled": False,
                "drift_receiver": "aoa-atlas",
                "drift_input_hash": input_hash,
                "drift_output_hash": "",
                "drift_changed": False,
            }
        )
        _atomic_write(raw_meta, json.dumps(payload, sort_keys=True).encode("utf-8"))
        return payload

    _atomic_write(output, data)
    payload.update(
        {
            "gpu_drift": False,
            "gpu_drift_raw_output": "",
            "gpu_drift_final_output": str(output),
            "gpu_drift_output_owner": "producer",
            "drift_renderer": "none",
            "drift_enabled": False,
            "drift_receiver": "aoa-atlas",
            "drift_input_hash": input_hash,
            "drift_output_hash": input_hash,
            "drift_changed": False,
        }
    )
    _atomic_write(meta, json.dumps(payload, sort_keys=True).encode("utf-8"))
    return payload


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--columns", type=int, default=DEFAULT_COLUMNS)
    parser.add_argument("--cell-size", type=int, default=DEFAULT_CELL_SIZE)
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS)
    parser.add_argument("--game-data", type=Path, default=DEFAULT_GAME_DATA)
    parser.add_argument("--controls", type=Path, default=DEFAULT_CONTROLS)
    parser.add_argument("--gpu-drift", action="store_true", default=_gpu_drift_default())
    parser.add_argument("--once", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.width > 4096 or args.height > 4096:
        raise SystemExit("AoA atlas dimensions must stay within DarkPlaces live-texture cap")
    if args.fps <= 0:
        raise SystemExit("fps must be positive")

    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    frame_id = 0
    period = 1.0 / args.fps
    while running:
        frame_id += 1
        started = time.monotonic()
        write_frame(
            output=args.output,
            meta=args.meta,
            width=args.width,
            height=args.height,
            columns=args.columns,
            cell_size=args.cell_size,
            frame_id=frame_id,
            game_data=args.game_data,
            gpu_drift=bool(args.gpu_drift),
            controls=args.controls,
        )
        if args.once:
            break
        elapsed = time.monotonic() - started
        time.sleep(max(0.01, period - elapsed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
