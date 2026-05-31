#!/usr/bin/env python3
"""Wrap the live Reverie substrate with receiver-local drift for DarkPlaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from quake_media_drift import DEFAULT_GAME_DATA, MediaDriftRenderer  # noqa: E402

DEFAULT_INPUT = Path("/dev/shm/hapax-sources/reverie.rgba")
DEFAULT_OUTPUT = Path("/dev/shm/hapax-compositor/quake-live-reverie.bgra")
DEFAULT_META = Path("/dev/shm/hapax-compositor/quake-live-reverie.json")
DEFAULT_WIDTH = 960
DEFAULT_HEIGHT = 540
DEFAULT_FPS = 15
DEFAULT_STALE_SOURCE_SECONDS = 4.0


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _gpu_drift_default() -> bool:
    value = os.environ.get(
        "HAPAX_QUAKE_REVERIE_GPU_DRIFT",
        os.environ.get("HAPAX_QUAKE_GPU_DRIFT", ""),
    )
    return _truthy(value)


def _short_hash(data: bytes) -> str:
    return hashlib.blake2s(data, digest_size=8).hexdigest()


def _gpu_drift_paths(output: Path) -> tuple[Path, Path]:
    raw_output = output.with_name(f"{output.stem}.raw.bgra")
    return raw_output, raw_output.with_suffix(".json")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _read_source_frame(path: Path, expected_size: int, now: float) -> tuple[bytes, dict[str, Any]]:
    meta: dict[str, Any] = {
        "source_path": str(path),
        "source_exists": False,
        "source_fresh": False,
        "source_age_s": None,
        "fallback_reason": "",
    }
    try:
        stat = path.stat()
        age_s = max(0.0, now - stat.st_mtime)
        meta.update(
            {
                "source_exists": True,
                "source_fresh": True,
                "source_age_s": round(age_s, 3),
            }
        )
        data = path.read_bytes()
    except OSError as exc:
        meta["fallback_reason"] = f"source-unavailable:{type(exc).__name__}"
        return bytes((0, 0, 0, 255)) * (expected_size // 4), meta

    if len(data) != expected_size:
        meta["source_fresh"] = False
        meta["fallback_reason"] = f"source-size:{len(data)}!={expected_size}"
        return bytes((0, 0, 0, 255)) * (expected_size // 4), meta
    return data, meta


def _write_meta(
    path: Path,
    *,
    args: argparse.Namespace,
    frames: int,
    source_meta: dict[str, Any],
    input_hash: str,
    output_hash: str,
) -> None:
    gpu_drift = bool(getattr(args, "gpu_drift", False))
    payload = {
        "source": "reverie",
        "renderer": "quake-live-reverie-source",
        "pixel_format": "BGRA8888-compatible",
        "width": args.width,
        "height": args.height,
        "fps": args.fps,
        "frames": frames,
        "updated_at": time.time(),
        "gpu_drift": gpu_drift,
        "gpu_drift_raw_output": str(getattr(args, "gpu_drift_raw_output", "")),
        "gpu_drift_final_output": str(getattr(args, "output", "")),
        "gpu_drift_output_owner": "screwm_media_drift" if gpu_drift else "producer",
        "drift_renderer": "quake-media-drift-v1",
        "drift_enabled": _truthy(args.drift) and not gpu_drift,
        "drift_receiver": args.drift_receiver,
        "drift_game_data": str(args.drift_game_data),
        "drift_intensity": float(args.drift_intensity),
        "drift_input_hash": input_hash,
        "drift_output_hash": output_hash,
        "drift_changed": input_hash != output_hash if not gpu_drift else False,
        **source_meta,
    }
    _atomic_write(path, json.dumps(payload, sort_keys=True).encode("utf-8") + b"\n")


def stream_frames(args: argparse.Namespace) -> int:
    expected_size = args.width * args.height * 4
    raw_output, raw_meta = _gpu_drift_paths(args.output) if args.gpu_drift else (None, None)
    args.gpu_drift_raw_output = raw_output or ""
    drift_renderer = MediaDriftRenderer(
        game_data=args.drift_game_data,
        enabled=_truthy(args.drift),
        intensity=float(args.drift_intensity),
    )
    running = True
    frames = 0
    last_meta: dict[str, Any] = {}
    last_input_hash = ""
    last_output_hash = ""

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    period = 1.0 / max(1, args.fps)

    while running:
        started = time.monotonic()
        now = time.time()
        data, source_meta = _read_source_frame(args.input, expected_size, now)
        age_s = source_meta.get("source_age_s")
        if isinstance(age_s, (int, float)) and age_s > args.stale_source_seconds:
            source_meta["source_fresh"] = False
            source_meta["fallback_reason"] = (
                f"source-stale:{float(age_s):.1f}s>{args.stale_source_seconds:.1f}s"
            )
        frames += 1
        should_write_meta = frames == 1 or frames % max(1, args.fps * 5) == 0
        if raw_output is not None:
            input_hash = _short_hash(data) if should_write_meta else last_input_hash
            output_hash = ""
            _atomic_write(raw_output, data)
            last_meta = source_meta
            if should_write_meta:
                last_input_hash = input_hash
                last_output_hash = output_hash
                if raw_meta is not None:
                    _write_meta(
                        raw_meta,
                        args=args,
                        frames=frames,
                        source_meta=source_meta,
                        input_hash=input_hash,
                        output_hash=output_hash,
                    )
            if args.once:
                break
            elapsed = time.monotonic() - started
            time.sleep(max(0.01, period - elapsed))
            continue
        input_hash = _short_hash(data) if should_write_meta else last_input_hash
        data = drift_renderer.apply(
            data,
            width=args.width,
            height=args.height,
            receiver=args.drift_receiver,
            frame=frames,
            now=now,
        )
        output_hash = _short_hash(data) if should_write_meta else last_output_hash
        _atomic_write(args.output, data)
        last_meta = source_meta
        if should_write_meta:
            last_input_hash = input_hash
            last_output_hash = output_hash
            _write_meta(
                args.meta,
                args=args,
                frames=frames,
                source_meta=source_meta,
                input_hash=input_hash,
                output_hash=output_hash,
            )
        if args.once:
            break
        elapsed = time.monotonic() - started
        time.sleep(max(0.01, period - elapsed))

    _write_meta(
        raw_meta if raw_meta is not None else args.meta,
        args=args,
        frames=frames,
        source_meta=last_meta,
        input_hash=last_input_hash,
        output_hash=last_output_hash,
    )
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--stale-source-seconds", type=float, default=DEFAULT_STALE_SOURCE_SECONDS)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--drift",
        choices=("on", "off", "enabled", "disabled"),
        default=os.environ.get("HAPAX_QUAKE_REVERIE_DRIFT", "on"),
    )
    parser.add_argument(
        "--drift-receiver",
        default=os.environ.get("HAPAX_QUAKE_REVERIE_DRIFT_RECEIVER", "reverie:w05"),
    )
    parser.add_argument(
        "--drift-game-data",
        type=Path,
        default=Path(os.environ.get("HAPAX_QUAKE_REVERIE_DRIFT_GAME_DATA", str(DEFAULT_GAME_DATA))),
    )
    parser.add_argument(
        "--drift-intensity",
        type=float,
        default=float(os.environ.get("HAPAX_QUAKE_REVERIE_DRIFT_INTENSITY", "1.35")),
    )
    parser.add_argument(
        "--gpu-drift",
        action="store_true",
        default=_gpu_drift_default(),
        help=(
            "GPU media-drift cutover: write the undrifted reverie frame to "
            "<output>.raw.bgra and leave final output/metadata ownership to "
            "screwm_media_drift."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return stream_frames(parse_args(argv or sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
