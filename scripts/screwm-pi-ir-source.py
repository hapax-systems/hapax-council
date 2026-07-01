#!/usr/bin/env python3
"""Poll a Pi-NoIR HTTP frame server and feed it to a DarkPlaces live texture.

Each Pi exposes an MJPEG-style still endpoint at ``http://<host>:8090/frame.jpg``.
This poller fetches that JPEG, decodes it, converts to the DarkPlaces BGRA ABI,
and atomically writes the EXISTING brio-IR ward slot buffer (the Brio IR cameras
are stopped, freeing their three 17-slot live-texture wards) plus a ``.json``
meta sidecar at a modest fps. The Pi feeds therefore render through the existing
w18/w19/w35 IR ward panes with no new live-texture slots or BSP mounts:

    pi-desk     (Pi-1, .78) -> quake-live-ir-brio-operator.bgra  (w18, slot 15)
    pi-room     (Pi-2, .52) -> quake-live-ir-brio-room.bgra      (w19, slot 16)
    pi-overhead (Pi-6, .74) -> quake-live-ir-brio-synths.bgra    (w35, slot 17)

Those slots are wired at 340x340 BGRA8888, so the poller fits each Pi frame to
the existing IR ward dimensions.

It models the atomic-write + fallback-frame patterns of
``scripts/quake-live-media-source.py`` and ``scripts/screwm-meet-camera.sh``:
when the Pi is unreachable or returns garbage, the poller writes a quiet
procedural placeholder frame instead of crashing, so an offline Pi (e.g. the
Pi-6 overhead unit) degrades softly rather than wedging the renderer.

The overhead role also writes a ``.raw.bgra`` + ``.raw.json`` sidecar (the
contract the CBIP dual-IR displacement source reads) so the CBIP ward (w35) can
use the overhead Pi pair as its dual-IR input.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

SHM_DIR = Path("/dev/shm/hapax-compositor")
DEFAULT_PORT = 8090
DEFAULT_FRAME_PATH = "/frame.jpg"
DEFAULT_FPS = 6.0
DEFAULT_TIMEOUT_S = 1.5
DEFAULT_WIDTH = 340
DEFAULT_HEIGHT = 340
PLACEHOLDER_BACKGROUND = (13, 11, 12)  # matches the camera fallback void colour

# Role table maps each Pi onto an EXISTING brio-IR ward slot buffer (the Brio IR
# cameras are stopped, so their three 17-slot live-texture wards w18/w19/w35 are
# reused for the Pi feeds). Output paths + dims match the existing IR slot wiring
# in config/screwm-quake-media-mounts.json and assets/quake/darkplaces/
# hapax-live-texture.patch (slots 15/16/17, 340x340 BGRA8888). No new slots or
# BSP mounts are introduced. Overhead also feeds the CBIP raw sidecar (w35).
ROLE_TABLE: dict[str, dict[str, object]] = {
    "pi-desk": {
        "host": "192.168.68.78",
        # w18 / slot 15 (was brio-operator-ir)
        "output": SHM_DIR / "quake-live-ir-brio-operator.bgra",
        "width": 360,
        "height": 640,
        "write_raw_sidecar": True,
    },
    "pi-room": {
        "host": "192.168.68.52",
        # w19 / slot 16 (was brio-room-ir)
        "output": SHM_DIR / "quake-live-ir-brio-room.bgra",
        "width": 360,
        "height": 640,
        "write_raw_sidecar": True,
    },
    "pi-overhead": {
        "host": "192.168.68.81",
        # w35 / slot 17 (was brio-synths-ir / CBIP)
        "output": SHM_DIR / "quake-live-ir-brio-synths.bgra",
        "width": 640,
        "height": 360,
        # CBIP dual-IR displacement reads the .raw.bgra sidecar.
        "write_raw_sidecar": True,
    },
}

_running = True


def _handle_signal(_signum: int, _frame: object) -> None:
    global _running
    _running = False


def _frame_url(host: str, port: int, frame_path: str) -> str:
    path = frame_path if frame_path.startswith("/") else f"/{frame_path}"
    return f"http://{host}:{port}{path}"


def _fetch_jpeg(url: str, timeout_s: float) -> bytes | None:
    """Fetch the Pi frame JPEG; return None on any network/HTTP failure."""
    request = urllib.request.Request(url, headers={"User-Agent": "hapax-pi-ir-source"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            data = response.read()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    return data or None


def _decode_to_bgra(data: bytes, width: int, height: int) -> bytes | None:
    """Decode a JPEG into a width*height*4 BGRA buffer (None on decode error)."""
    try:
        with Image.open(_BytesReader(data)) as image:
            image.load()
            fitted = ImageOps.fit(
                image.convert("RGB"),
                (width, height),
                method=Image.Resampling.BILINEAR,
                centering=(0.5, 0.5),
            )
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    rgb = np.asarray(fitted, dtype=np.uint8)
    if rgb.shape != (height, width, 3):
        return None
    return _rgb_to_bgra(rgb)


def _rgb_to_bgra(rgb: np.ndarray) -> bytes:
    height, width, _ = rgb.shape
    bgra = np.empty((height, width, 4), dtype=np.uint8)
    bgra[:, :, 0] = rgb[:, :, 2]
    bgra[:, :, 1] = rgb[:, :, 1]
    bgra[:, :, 2] = rgb[:, :, 0]
    bgra[:, :, 3] = 255
    return bgra.tobytes()


def _placeholder_bgra(width: int, height: int, role: str, frames: int) -> bytes:
    """Quiet procedural placeholder so an offline Pi never crashes the poller."""
    br, bg, bb = PLACEHOLDER_BACKGROUND
    bgra = np.empty((height, width, 4), dtype=np.uint8)
    bgra[:, :, 0] = bb
    bgra[:, :, 1] = bg
    bgra[:, :, 2] = br
    bgra[:, :, 3] = 255
    # A slow, low-contrast scan line marks "waiting for live frame" without a
    # bright fourth-wall panel.
    row = int((frames * 2) % height)
    lo = max(0, row - 1)
    hi = min(height, row + 2)
    bgra[lo:hi, :, 0] = min(255, bb + 26)
    bgra[lo:hi, :, 1] = min(255, bg + 40)
    bgra[lo:hi, :, 2] = min(255, br + 18)
    del role
    return bgra.tobytes()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _write_meta(path: Path, payload: dict[str, object]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


class _BytesReader:
    """Minimal file-like wrapper so PIL can open an in-memory JPEG buffer."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk = self._data[self._pos :]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self._pos = offset
        elif whence == 1:
            self._pos += offset
        else:
            self._pos = len(self._data) + offset
        return self._pos

    def tell(self) -> int:
        return self._pos


def run(args: argparse.Namespace) -> int:
    role = args.role
    config = ROLE_TABLE.get(role)
    host = args.host or (str(config["host"]) if config else None)
    if host is None:
        print(f"unknown pi-ir role {role!r}; pass --host explicitly", file=sys.stderr)
        return 2
    width = args.width or (int(config["width"]) if config else DEFAULT_WIDTH)
    height = args.height or (int(config["height"]) if config else DEFAULT_HEIGHT)
    output = (
        Path(args.output)
        if args.output
        else (Path(str(config["output"])) if config else SHM_DIR / f"quake-live-cam-{role}.bgra")
    )
    meta_path = Path(args.meta) if args.meta else output.with_suffix(".json")
    write_raw_sidecar = (
        args.write_raw_sidecar
        if args.write_raw_sidecar is not None
        else bool(config["write_raw_sidecar"])
        if config
        else False
    )
    raw_output = output.with_suffix(".raw.bgra")
    raw_meta = output.with_suffix(".raw.json")
    url = _frame_url(host, args.port, args.frame_path)
    interval = 1.0 / max(0.5, args.fps)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    frames = 0
    while _running:
        loop_start = time.monotonic()
        raw_jpeg = _fetch_jpeg(url, args.timeout_s)
        bgra: bytes | None = None
        live = False
        if raw_jpeg is not None:
            bgra = _decode_to_bgra(raw_jpeg, width, height)
            live = bgra is not None
        if bgra is None:
            bgra = _placeholder_bgra(width, height, role, frames)
        _write_atomic(output, bgra)
        meta = {
            "source": "pi-ir",
            "role": role,
            "host": host,
            "url": url,
            "width": width,
            "height": height,
            "live": live,
            "frame": frames,
            "timestamp": time.time(),
        }
        _write_meta(meta_path, meta)
        if write_raw_sidecar:
            _write_atomic(raw_output, bgra)
            _write_meta(raw_meta, meta)
        frames += 1
        elapsed = time.monotonic() - loop_start
        sleep_s = interval - elapsed
        if sleep_s > 0 and _running:
            time.sleep(sleep_s)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Poll a Pi-NoIR HTTP frame server into DarkPlaces")
    parser.add_argument(
        "--role",
        required=True,
        help="Pi role (pi-desk / pi-room / pi-overhead); resolves host + output",
    )
    parser.add_argument("--host", default=None, help="Override the Pi host/IP")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--frame-path", default=DEFAULT_FRAME_PATH)
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS)
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--meta", default=None)
    parser.add_argument(
        "--write-raw-sidecar",
        dest="write_raw_sidecar",
        action="store_true",
        default=None,
        help="Also write .raw.bgra/.raw.json (CBIP dual-IR input). Default: per role.",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if math.isnan(args.fps) or args.fps <= 0:
        args.fps = DEFAULT_FPS
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
