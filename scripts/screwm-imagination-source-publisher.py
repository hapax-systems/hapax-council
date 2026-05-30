#!/usr/bin/env python3
"""Publish Quake live textures into the imagination source-presence protocol.

The Quake migration disables the full studio compositor route, but
hapax-imagination still uses `/dev/shm/hapax-imagination/sources` as the
source-presence gate for expressive drift. This sidecar publishes small,
low-rate RGBA proxies from the already-active DarkPlaces live textures so the
effect pipeline has real sources without competing for the OBS output route.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
from pathlib import Path
from typing import Any

DEFAULT_INPUT_DIR = Path("/dev/shm/hapax-compositor")
DEFAULT_OUTPUT_DIR = Path("/dev/shm/hapax-imagination/sources")
DEFAULT_ROLES: tuple[str, ...] = (
    "brio-operator",
    "brio-room",
    "brio-synths",
    "c920-desk",
    "c920-room",
    "c920-overhead",
)

_STOP = False


def _signal_stop(_signum: int, _frame: object) -> None:
    global _STOP
    _STOP = True


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write(path, text.encode("utf-8"))


def _file_fresh(path: Path, max_age_s: float, now: float | None = None) -> bool:
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except OSError:
        return False
    return age <= max_age_s


def _downsample_bgra_to_rgba(
    bgra: bytes,
    src_width: int,
    src_height: int,
    dst_width: int,
    dst_height: int,
) -> bytes:
    """Nearest-neighbor downsample from BGRA8888 to RGBA8888."""
    if src_width <= 0 or src_height <= 0 or dst_width <= 0 or dst_height <= 0:
        raise ValueError("frame dimensions must be positive")
    expected = src_width * src_height * 4
    if len(bgra) != expected:
        raise ValueError(f"BGRA size mismatch: expected {expected}, got {len(bgra)}")

    out = bytearray(dst_width * dst_height * 4)
    for y in range(dst_height):
        sy = min(src_height - 1, (y * src_height) // dst_height)
        src_row = sy * src_width * 4
        dst_row = y * dst_width * 4
        for x in range(dst_width):
            sx = min(src_width - 1, (x * src_width) // dst_width)
            src = src_row + sx * 4
            dst = dst_row + x * 4
            out[dst] = bgra[src + 2]
            out[dst + 1] = bgra[src + 1]
            out[dst + 2] = bgra[src]
            out[dst + 3] = bgra[src + 3]
    return bytes(out)


def _manifest(
    *,
    source_id: str,
    width: int,
    height: int,
    opacity: float,
    z_order: int,
    ttl_ms: int,
    sequence: int,
    role: str,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "content_type": "rgba",
        "width": width,
        "height": height,
        "text": "",
        "font_weight": 400,
        "layer": 1,
        "blend_mode": "screen",
        "opacity": opacity,
        "z_order": z_order,
        "ttl_ms": ttl_ms,
        "tags": [
            "screwm-quake",
            "source-presence",
            "camera-snapshot",
            f"role:{role}",
        ],
        "frame_sequence": sequence,
        "published_at_monotonic": time.monotonic(),
        "published_at_unix": time.time(),
    }


def publish_once(
    *,
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    roles: tuple[str, ...] = DEFAULT_ROLES,
    width: int = 320,
    height: int = 180,
    max_age_s: float = 6.0,
    ttl_ms: int = 3000,
    opacity: float = 0.46,
    sequence: int = 0,
) -> int:
    published = 0
    now = time.time()
    for role in roles:
        base = f"quake-live-cam-{role}"
        frame_path = input_dir / f"{base}.bgra"
        meta_path = input_dir / f"{base}.json"
        meta = _read_json(meta_path)
        src_width = int(meta.get("width") or 0)
        src_height = int(meta.get("height") or 0)
        if src_width <= 0 or src_height <= 0:
            continue
        if not _file_fresh(frame_path, max_age_s, now=now):
            continue
        try:
            bgra = frame_path.read_bytes()
            rgba = _downsample_bgra_to_rgba(bgra, src_width, src_height, width, height)
        except (OSError, ValueError):
            continue

        source_id = f"screwm-quake-camera-{role}"
        source_dir = output_dir / source_id
        _atomic_write(source_dir / "frame.rgba", rgba)
        manifest = _manifest(
            source_id=source_id,
            width=width,
            height=height,
            opacity=opacity,
            z_order=40 + published,
            ttl_ms=ttl_ms,
            sequence=sequence,
            role=role,
        )
        _atomic_write_text(
            source_dir / "manifest.json",
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        )
        published += 1
    return published


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=180)
    parser.add_argument("--max-age-s", type=float, default=6.0)
    parser.add_argument("--ttl-ms", type=int, default=3000)
    parser.add_argument("--opacity", type=float, default=0.46)
    parser.add_argument("--role", action="append", dest="roles")
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    roles = tuple(args.roles or DEFAULT_ROLES)
    interval = 1.0 / max(args.fps, 0.1)
    sequence = 0
    signal.signal(signal.SIGINT, _signal_stop)
    signal.signal(signal.SIGTERM, _signal_stop)
    while not _STOP:
        published = publish_once(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            roles=roles,
            width=args.width,
            height=args.height,
            max_age_s=args.max_age_s,
            ttl_ms=args.ttl_ms,
            opacity=args.opacity,
            sequence=sequence,
        )
        print(f"screwm imagination source publish: {published} sources", flush=True)
        sequence += 1
        if args.once:
            return 0 if published > 0 else 1
        time.sleep(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
