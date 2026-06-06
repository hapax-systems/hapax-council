#!/usr/bin/env python3
"""Feed live media frames to the DarkPlaces texture hook.

DarkPlaces reads an atomic raw BGRA frame from /dev/shm and uploads it into a
configured in-world BSP texture. Separate service instances can feed YouTube,
camera, or test frames into different live texture slots.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from quake_media_drift import DEFAULT_GAME_DATA, MediaDriftRenderer  # noqa: E402

DEFAULT_OUTPUT = Path("/dev/shm/hapax-compositor/quake-live-yt.bgra")
DEFAULT_META = Path("/dev/shm/hapax-compositor/quake-live-yt.json")
DEFAULT_YOUTUBE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
DEFAULT_YOUTUBE_VIDEO_ID_PATH = Path("/dev/shm/hapax-compositor/youtube-video-id.txt")
DEFAULT_YOUTUBE_PLAYER_ATTR_FILES = (
    Path("/dev/shm/hapax-compositor/yt-attribution-0.txt"),
    Path("/dev/shm/hapax-compositor/yt-attribution.txt"),
)
DEFAULT_MASK_BACKGROUND = "0c0b0d"
DEFAULT_SPHERE_MEDIA_ASPECT = 16 / 9
SPHERE_FRONT_HEIGHT_RATIO = 1.0
CAMERA_FALLBACK_BACKGROUND = "0c0b0d"
CAMERA_ROLE_DEFAULTS = {
    "brio-operator": {
        "device": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_5342C819-video-index0",
        "size": "1280x720",
        "fps": 10,
        "format": "mjpeg",
    },
    "brio-room": {
        "device": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_43B0576A-video-index0",
        "size": "1280x720",
        "fps": 10,
        "format": "mjpeg",
    },
    "brio-synths": {
        "device": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_9726C031-video-index0",
        "size": "1280x720",
        "fps": 10,
        "format": "mjpeg",
    },
    "brio-operator-ir": {
        "device": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_5342C819-video-index2",
        "size": "340x340",
        "fps": 10,
        "format": "gray",
    },
    "brio-room-ir": {
        "device": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_43B0576A-video-index2",
        "size": "340x340",
        "fps": 10,
        "format": "gray",
    },
    "brio-synths-ir": {
        "device": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_9726C031-video-index2",
        "size": "340x340",
        "fps": 10,
        "format": "gray",
    },
    "c920-desk": {
        "device": "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_2657DFCF-video-index0",
        "size": "1280x720",
        "fps": 10,
        "format": "mjpeg",
    },
    "c920-room": {
        "device": "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_86B6B75F-video-index0",
        "size": "1280x720",
        "fps": 10,
        "format": "mjpeg",
    },
    "c920-overhead": {
        "device": "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_7B88C71F-video-index0",
        "size": "1280x720",
        "fps": 10,
        "format": "mjpeg",
    },
}


def _run_checked(args: list[str]) -> str:
    completed = subprocess.run(args, text=True, capture_output=True, check=True)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return completed.stdout


def _youtube_video_url(page_url: str, *, height: int) -> str:
    target_height = min(max(height, 360), 1080)
    format_selector = (
        f"bv*[height<={target_height}][vcodec^=avc1][ext=mp4]/"
        f"bv*[height<={target_height}][ext=mp4]/"
        f"bv*[height<={target_height}]/b[ext=mp4]/b"
    )
    try:
        output = _run_checked(["yt-dlp", "-f", format_selector, "-g", page_url])
    except subprocess.CalledProcessError as exc:
        if exc.stderr:
            sys.stderr.write(exc.stderr)
        if exc.stdout:
            sys.stderr.write(exc.stdout)
        raise
    urls = [line.strip() for line in output.splitlines() if line.strip()]
    if not urls:
        raise RuntimeError("yt-dlp did not return a video URL")
    return urls[0]


def _youtube_video_url_with_fallback(args: argparse.Namespace, *, height: int) -> str | None:
    try:
        return _youtube_video_url(args.resolved_url, height=height)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        if getattr(args, "youtube_fallback", "canary") != "canary":
            raise
        failed_url = args.resolved_url
        if failed_url == DEFAULT_YOUTUBE_URL:
            args.fallback_reason = f"youtube_url_resolve_failed:{type(exc).__name__}"
            return None
        args.fallback_reason = f"youtube_url_resolve_failed:canary:{type(exc).__name__}"
        args.resolved_url = DEFAULT_YOUTUBE_URL
        args.url_source = "fallback-canary"
        try:
            return _youtube_video_url(args.resolved_url, height=height)
        except (RuntimeError, subprocess.CalledProcessError) as fallback_exc:
            args.fallback_reason = f"youtube_canary_resolve_failed:{type(fallback_exc).__name__}"
            return None


def _youtube_page_url_from_text(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    return f"https://www.youtube.com/watch?v={text}"


def _resolve_youtube_page_url(args: argparse.Namespace) -> str:
    args.url_source = "configured"
    url_file = getattr(args, "url_file", None)
    if url_file is not None and url_file.exists():
        file_value = url_file.read_text(encoding="utf-8").strip()
        if file_value:
            args.url_source = f"file:{url_file}"
            return _youtube_page_url_from_text(file_value)

    for attr_file in getattr(args, "youtube_player_attr_files", ()):
        try:
            lines = attr_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        if len(lines) >= 3 and lines[2].strip():
            args.url_source = f"youtube-player:{attr_file}"
            return _youtube_page_url_from_text(lines[2].strip())

    configured_url = getattr(args, "configured_url", args.url)
    if (
        configured_url == DEFAULT_YOUTUBE_URL
        and getattr(args, "youtube_fallback", "canary") == "offline"
    ):
        args.url_source = "unbound"
        return ""
    if configured_url == DEFAULT_YOUTUBE_URL:
        args.url_source = "default-canary"
    return _youtube_page_url_from_text(configured_url)


def _decode_dimensions(args: argparse.Namespace) -> tuple[int, int]:
    if args.projection != "sphere-front":
        return args.width, args.height
    # The OARB is a spherical attention object, not a flat 2:1 screen. Preserve
    # the declared live-media aspect inside the sphere skin; the remaining
    # equirectangular field carries procedural spherical backing.
    front_height = int(args.height * SPHERE_FRONT_HEIGHT_RATIO)
    media_aspect = float(args.sphere_front_aspect or DEFAULT_SPHERE_MEDIA_ASPECT)
    frame_width = min(args.width, int(round(front_height * media_aspect)))
    frame_height = min(front_height, int(round(frame_width / media_aspect)))
    return frame_width - (frame_width % 2), frame_height - (frame_height % 2)


def _parse_size(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    text = value.lower().strip()
    if "x" not in text:
        return None
    w_text, _, h_text = text.partition("x")
    try:
        width = int(w_text)
        height = int(h_text)
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _ffmpeg_command(args: argparse.Namespace, frame_width: int, frame_height: int) -> list[str]:
    args.fallback_reason = ""
    args.youtube_gpu_decode_active = False
    if args.projection == "sphere-front":
        filters = [
            f"fps={args.fps}",
            f"scale=w={frame_width}:h={frame_height}:force_original_aspect_ratio=increase:flags=lanczos",
            f"crop={frame_width}:{frame_height}",
        ]
        # The historical CPU projection path mirrors before seam wrapping. When
        # GPU projection owns sphere-front, the shader mirrors during projection
        # so FFmpeg does not spend CPU on a separate full-frame hflip.
        if not _gpu_owns_projection(args):
            filters.append("hflip")
        filters.append("format=bgra")
        vf = ",".join(filters)
    elif args.source == "camera" and _parse_size(args.camera_size) == (frame_width, frame_height):
        vf = f"fps={args.fps},format=bgra"
    else:
        vf = (
            f"fps={args.fps},"
            f"scale=w={frame_width}:h={frame_height}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={frame_width}:{frame_height}:(ow-iw)/2:(oh-ih)/2,"
            "format=bgra"
        )
    base = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-nostdin",
        "-threads",
        "1",
        "-filter_threads",
        "1",
    ]
    if args.source == "youtube":
        args.resolved_url = _resolve_youtube_page_url(args)
        if not args.resolved_url:
            args.fallback_reason = "youtube_source_unbound"
            return _youtube_offline_command(args, frame_width, frame_height)
        video_url = _youtube_video_url_with_fallback(args, height=args.height)
        if not video_url:
            return _youtube_offline_command(args, frame_width, frame_height)
        cuda_vf = _youtube_cuda_filter(args, frame_width, frame_height)
        if cuda_vf:
            args.youtube_gpu_decode_active = True
            return base + [
                "-hwaccel",
                "cuda",
                "-hwaccel_output_format",
                "cuda",
                "-re",
                "-i",
                video_url,
                "-an",
                "-vf",
                cuda_vf,
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgra",
                "-",
            ]
        return base + [
            "-re",
            "-i",
            video_url,
            "-an",
            "-vf",
            vf,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgra",
            "-",
        ]
    if args.source == "camera":
        if args.camera_device and not Path(args.camera_device).exists():
            args.fallback_reason = f"camera_device_missing:{args.camera_device}"
            return _camera_fallback_command(args, frame_width, frame_height)
        return base + [
            "-f",
            "v4l2",
            "-input_format",
            args.camera_format,
            "-video_size",
            args.camera_size,
            "-framerate",
            str(args.camera_fps),
            "-i",
            args.camera_device,
            "-an",
            "-vf",
            vf,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgra",
            "-",
        ]
    return base + [
        "-f",
        "lavfi",
        "-re",
        "-i",
        f"testsrc2=size={args.width}x{args.height}:rate={args.fps}",
        "-vf",
        vf,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgra",
        "-",
    ]


def _youtube_offline_command(
    args: argparse.Namespace,
    frame_width: int,
    frame_height: int,
) -> list[str]:
    lavfi = f"color=c={args.mask_background}:s={frame_width}x{frame_height}:r=1,format=bgra"
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-nostdin",
        "-f",
        "lavfi",
        "-re",
        "-i",
        lavfi,
        "-t",
        str(max(10.0, float(args.restart_delay))),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgra",
        "-",
    ]


def _camera_fallback_command(
    args: argparse.Namespace,
    frame_width: int,
    frame_height: int,
) -> list[str]:
    role = (args.camera_role or "camera").replace("-", " ").upper()
    font_size = max(24, min(frame_width, frame_height) // 14)
    sub_font_size = max(16, font_size // 2)
    grid_w = max(80, frame_width // 8)
    grid_h = max(45, frame_height // 8)
    lavfi = (
        f"color=c={CAMERA_FALLBACK_BACKGROUND}:s={frame_width}x{frame_height}:r={args.fps},"
        f"drawgrid=width={grid_w}:height={grid_h}:thickness=2:color=0x44e7ff44,"
        f"drawtext=text='{role} OFFLINE':fontcolor=0xffb000:fontsize={font_size}:"
        "x=(w-text_w)/2:y=(h-text_h)/2-36,"
        f"drawtext=text='WAITING FOR LIVE CAMERA':fontcolor=0x44e7ff:fontsize={sub_font_size}:"
        "x=(w-text_w)/2:y=(h-text_h)/2+36,"
        "format=bgra"
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-nostdin",
        "-f",
        "lavfi",
        "-re",
        "-i",
        lavfi,
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgra",
        "-",
    ]


def _parse_hex_color(value: str) -> tuple[int, int, int]:
    text = value.strip().removeprefix("#")
    if len(text) != 6:
        raise ValueError(f"expected 6-digit RGB color, got {value!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _apply_mask(data: bytes, width: int, height: int, mask: str, background: str) -> bytes:
    if mask == "none":
        return data
    if mask != "circle":
        raise ValueError(f"unsupported mask {mask!r}")

    pixels = bytearray(data)
    bg_r, bg_g, bg_b = _parse_hex_color(background)
    cx = (width - 1) * 0.5
    cy = (height - 1) * 0.5
    radius = min(width, height) * 0.47
    feather = max(1.0, min(width, height) * 0.055)
    outer = radius
    inner = radius - feather

    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 4
            dx = x - cx
            dy = y - cy
            distance = (dx * dx + dy * dy) ** 0.5
            if distance <= inner:
                continue
            if distance >= outer:
                pixels[idx : idx + 4] = bytes((bg_b, bg_g, bg_r, 255))
                continue
            alpha = (outer - distance) / feather
            pixels[idx] = int(pixels[idx] * alpha + bg_b * (1.0 - alpha))
            pixels[idx + 1] = int(pixels[idx + 1] * alpha + bg_g * (1.0 - alpha))
            pixels[idx + 2] = int(pixels[idx + 2] * alpha + bg_r * (1.0 - alpha))
            pixels[idx + 3] = 255
    return bytes(pixels)


def _apply_freshness_overlay(data: bytes, width: int, height: int, mode: str, frames: int) -> bytes:
    if mode == "none":
        return data
    if mode != "seam-pulse":
        raise ValueError(f"unsupported freshness overlay {mode!r}")

    pixels = bytearray(data)
    pulse = int(112 + 112 * (0.5 + 0.5 * math.sin(frames * 0.31)))
    color = bytes((pulse, 224, 64, 255))
    bar_w = max(24, width // 48)
    bar_h = max(4, height // 128)
    y0 = height - bar_h - max(2, height // 180)

    for y in range(y0, min(height, y0 + bar_h)):
        row = y * width * 4
        for x in range(bar_w):
            pixels[row + x * 4 : row + x * 4 + 4] = color
        for x in range(width - bar_w, width):
            pixels[row + x * 4 : row + x * 4 + 4] = color

    return bytes(pixels)


@functools.lru_cache(maxsize=8)
def _sphere_background(out_width: int, out_height: int, background: str) -> bytes:
    bg_r, bg_g, bg_b = _parse_hex_color(background)
    pixels = bytearray(bytes((bg_b, bg_g, bg_r, 255)) * (out_width * out_height))

    for y in range(out_height):
        # Latitude shading makes the non-media back/sides read as a sphere, not
        # a flat pad. The live media itself remains unmodified.
        shade = 0.54 + 0.30 * (1.0 - abs((y + 0.5) / out_height - 0.5) * 2.0)
        for x in range(out_width):
            idx = (y * out_width + x) * 4
            # Subtle equirectangular guide lines preserve the sphere/mount
            # contract when the live source is dark.
            guide = x % max(8, out_width // 16) < 1 or abs(y - out_height // 2) <= 1
            boost = 1.26 if guide else 1.0
            pixels[idx] = min(255, int(bg_b * shade * boost))
            pixels[idx + 1] = min(255, int(bg_g * shade * boost))
            pixels[idx + 2] = min(255, int(bg_r * shade * boost))
            pixels[idx + 3] = 255

    return bytes(pixels)


def _compose_sphere_front(
    data: bytes,
    frame_width: int,
    frame_height: int,
    out_width: int,
    out_height: int,
    background: str,
) -> bytes:
    pixels = bytearray(_sphere_background(out_width, out_height, background))
    offset_y = (out_height - frame_height) // 2
    seam_left_width = frame_width // 2
    seam_right_width = frame_width - seam_left_width
    # The generated MDL presents the negative-Y inspection face at the texture
    # seam. Center the source on that seam: media left-of-center wraps to the
    # right edge, media right-of-center wraps to the left edge.
    right_edge_x = out_width - seam_left_width

    for y in range(frame_height):
        src = y * frame_width * 4
        dst_row = (offset_y + y) * out_width * 4
        # The MDL sphere's front-facing UVs have opposite handedness from the
        # flat media source. The ffmpeg filter performs the hflip so this hot
        # path only performs seam wrapping.
        row = data[src : src + frame_width * 4]
        left_half = row[: seam_left_width * 4]
        right_half = row[seam_left_width * 4 : frame_width * 4]
        pixels[dst_row : dst_row + seam_right_width * 4] = right_half
        dst = dst_row + right_edge_x * 4
        pixels[dst : dst + seam_left_width * 4] = left_half

    return bytes(pixels)


def _project_frame(
    data: bytes,
    args: argparse.Namespace,
    frame_width: int,
    frame_height: int,
    frames: int = 0,
) -> bytes:
    if args.projection == "flat":
        masked = _apply_mask(data, args.width, args.height, args.mask, args.mask_background)
        return _apply_freshness_overlay(
            masked, args.width, args.height, getattr(args, "freshness_overlay", "none"), frames
        )
    if args.projection == "sphere-front":
        projected = _compose_sphere_front(
            data,
            frame_width,
            frame_height,
            args.width,
            args.height,
            args.mask_background,
        )
        masked = _apply_mask(projected, args.width, args.height, args.mask, args.mask_background)
        return _apply_freshness_overlay(
            masked, args.width, args.height, getattr(args, "freshness_overlay", "none"), frames
        )
    raise ValueError(f"unsupported projection {args.projection!r}")


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _write_meta(path: Path, args: argparse.Namespace, frames: int) -> None:
    gpu_drift = bool(getattr(args, "gpu_drift", False))
    gpu_projection_kind = str(getattr(args, "gpu_projection_kind", "") or "")
    payload = {
        "source": args.source,
        "url": getattr(args, "resolved_url", args.url) if args.source == "youtube" else "",
        "configured_url": getattr(args, "configured_url", args.url)
        if args.source == "youtube"
        else "",
        "url_source": getattr(args, "url_source", "") if args.source == "youtube" else "",
        "url_file": str(getattr(args, "url_file", "")) if args.source == "youtube" else "",
        "camera_role": args.camera_role if args.source == "camera" else "",
        "camera_device": args.camera_device if args.source == "camera" else "",
        "width": args.width,
        "height": args.height,
        "source_frame_width": getattr(args, "source_frame_width", args.width),
        "source_frame_height": getattr(args, "source_frame_height", args.height),
        "fps": args.fps,
        "mask": args.mask,
        "mask_background": args.mask_background,
        "projection": args.projection,
        "freshness_overlay": getattr(args, "freshness_overlay", "none"),
        "projection_front_height_ratio": (
            SPHERE_FRONT_HEIGHT_RATIO if args.projection == "sphere-front" else None
        ),
        "gpu_drift": gpu_drift,
        "gpu_drift_raw_output": str(getattr(args, "gpu_drift_raw_output", "")),
        "gpu_drift_final_output": str(getattr(args, "output", "")),
        "gpu_drift_output_owner": "screwm_media_drift" if gpu_drift else "producer",
        "gpu_projection": bool(gpu_projection_kind),
        "gpu_projection_kind": gpu_projection_kind,
        "gpu_projection_output_owner": "screwm_media_drift" if gpu_projection_kind else "producer",
        "youtube_gpu_decode_requested": bool(getattr(args, "youtube_gpu_decode", False)),
        "youtube_gpu_decode_active": bool(getattr(args, "youtube_gpu_decode_active", False)),
        "youtube_gpu_decode_runtime_disabled": bool(
            getattr(args, "youtube_gpu_decode_runtime_disabled", False)
        ),
        "drift_renderer": "quake-media-drift-v1",
        "drift_enabled": _truthy(getattr(args, "drift", "on")) and not gpu_drift,
        "drift_receiver": _drift_receiver(args),
        "drift_game_data": str(getattr(args, "drift_game_data", DEFAULT_GAME_DATA)),
        "drift_intensity": float(getattr(args, "drift_intensity", 1.0)),
        "drift_input_hash": getattr(args, "drift_input_hash", ""),
        "drift_output_hash": getattr(args, "drift_output_hash", ""),
        "drift_changed": bool(getattr(args, "drift_changed", False)),
        "fallback_reason": getattr(args, "fallback_reason", ""),
        "frames": frames,
        "updated_at": time.time(),
    }
    _write_atomic(path, json.dumps(payload, sort_keys=True).encode("utf-8") + b"\n")


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _gpu_projection_default() -> bool:
    return _truthy(os.environ.get("HAPAX_QUAKE_GPU_PROJECTION", ""))


def _gpu_projection_kind(args: argparse.Namespace) -> str:
    if not bool(getattr(args, "gpu_projection", False)):
        return ""
    if not bool(getattr(args, "gpu_drift", False)):
        return ""
    if args.projection != "sphere-front":
        return ""
    if args.mask != "none":
        raise ValueError("GPU sphere-front projection requires --mask none")
    if getattr(args, "freshness_overlay", "none") != "none":
        raise ValueError("GPU sphere-front projection requires --freshness-overlay none")
    return "sphere-front"


def _gpu_owns_projection(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "gpu_projection_kind", ""))


def _youtube_gpu_decode_default() -> bool:
    return _truthy(os.environ.get("HAPAX_QUAKE_YOUTUBE_GPU_DECODE", ""))


def _youtube_cuda_filter(
    args: argparse.Namespace, frame_width: int, frame_height: int
) -> str | None:
    if args.source != "youtube" or not bool(getattr(args, "youtube_gpu_decode", False)):
        return None
    if bool(getattr(args, "youtube_gpu_decode_runtime_disabled", False)):
        return None
    if args.projection == "sphere-front" and not _gpu_owns_projection(args):
        # CPU-owned sphere-front still needs the CPU hflip/projection path.
        return None
    return ",".join(
        [
            f"fps={args.fps}",
            (f"scale_cuda=w={frame_width}:h={frame_height}:interp_algo=lanczos:format=yuv420p"),
            "hwdownload",
            "format=yuv420p",
            "format=bgra",
        ]
    )


def _drift_receiver(args: argparse.Namespace) -> str:
    configured = str(getattr(args, "drift_receiver", "") or "").strip()
    if configured:
        return configured
    if args.source == "youtube":
        return "oarb-youtube"
    if args.source == "camera":
        role = str(getattr(args, "camera_role", "") or "camera")
        return f"camera:{role}"
    return f"media:{args.source}"


def _short_hash(data: bytes) -> str:
    return hashlib.blake2s(data, digest_size=8).hexdigest()


def _gpu_drift_paths(output: Path) -> tuple[Path, Path]:
    raw_output = output.with_name(f"{output.stem}.raw.bgra")
    return raw_output, raw_output.with_suffix(".json")


def stream_frames(args: argparse.Namespace) -> int:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw_output, raw_meta = _gpu_drift_paths(args.output) if args.gpu_drift else (None, None)
    args.gpu_drift_raw_output = raw_output or ""
    args.gpu_projection_kind = ""
    frame_width, frame_height = _decode_dimensions(args)
    args.source_frame_width = frame_width
    args.source_frame_height = frame_height
    frame_size = frame_width * frame_height * 4
    if raw_output is not None:
        args.gpu_projection_kind = _gpu_projection_kind(args)
    drift_renderer = MediaDriftRenderer(
        game_data=getattr(args, "drift_game_data", DEFAULT_GAME_DATA),
        enabled=_truthy(getattr(args, "drift", "on")),
        intensity=float(getattr(args, "drift_intensity", 1.0)),
    )
    drift_receiver = _drift_receiver(args)
    frames = 0
    stop = False

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while not stop:
        command = _ffmpeg_command(args, frame_width, frame_height)
        loop_frames = 0
        with subprocess.Popen(command, stdout=subprocess.PIPE) as proc:
            assert proc.stdout is not None
            while not stop:
                data = proc.stdout.read(frame_size)
                if len(data) != frame_size:
                    break
                loop_frames += 1
                frames += 1
                should_write_meta = frames == 1 or frames % max(1, args.fps * 5) == 0
                if raw_output is not None:
                    if not args.gpu_projection_kind:
                        data = _project_frame(data, args, frame_width, frame_height, frames)
                    # GPU media-drift cutover: emit the undrifted frame for the
                    # screwm_media_drift service (it writes the drifted args.output).
                    if should_write_meta:
                        args.drift_input_hash = _short_hash(data)
                        args.drift_output_hash = ""
                        args.drift_changed = False
                    _write_atomic(raw_output, data)
                    if should_write_meta and raw_meta is not None:
                        _write_meta(raw_meta, args, frames)
                    continue
                data = _project_frame(data, args, frame_width, frame_height, frames)
                drift_input_hash = _short_hash(data) if should_write_meta else ""
                data = drift_renderer.apply(
                    data,
                    width=args.width,
                    height=args.height,
                    receiver=drift_receiver,
                    frame=frames,
                )
                if should_write_meta:
                    drift_output_hash = _short_hash(data)
                    args.drift_input_hash = drift_input_hash
                    args.drift_output_hash = drift_output_hash
                    args.drift_changed = drift_input_hash != drift_output_hash
                _write_atomic(args.output, data)
                if should_write_meta:
                    _write_meta(args.meta, args, frames)
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        if (
            args.source == "youtube"
            and bool(getattr(args, "youtube_gpu_decode_active", False))
            and loop_frames == 0
            and not stop
        ):
            args.youtube_gpu_decode_runtime_disabled = True
            args.youtube_gpu_decode_active = False
            args.fallback_reason = "youtube_gpu_decode_failed"
        if not stop:
            time.sleep(args.restart_delay)
    _write_meta(raw_meta if raw_meta is not None else args.meta, args, frames)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("youtube", "camera", "test"), default="youtube")
    parser.add_argument(
        "--url", default=os.environ.get("HAPAX_QUAKE_YOUTUBE_URL", DEFAULT_YOUTUBE_URL)
    )
    parser.add_argument(
        "--url-file",
        type=Path,
        default=(
            Path(os.environ["HAPAX_QUAKE_YOUTUBE_URL_FILE"])
            if os.environ.get("HAPAX_QUAKE_YOUTUBE_URL_FILE")
            else None
        ),
        help=(
            "Optional file containing a YouTube watch URL or video id. "
            "When omitted, the configured URL is used unchanged."
        ),
    )
    parser.add_argument(
        "--youtube-fallback",
        choices=("canary", "offline"),
        default=os.environ.get("HAPAX_QUAKE_YOUTUBE_FALLBACK", "canary"),
        help="Behavior when no explicit URL or non-empty URL file is available.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--width", type=int, default=64)
    parser.add_argument("--height", type=int, default=64)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument(
        "--projection",
        choices=("flat", "sphere-front"),
        default=os.environ.get("HAPAX_QUAKE_MEDIA_PROJECTION", "flat"),
        help="Projection contract for the output texture. sphere-front fills the AoA sphere skin.",
    )
    parser.add_argument(
        "--sphere-front-aspect",
        type=float,
        default=float(
            os.environ.get("HAPAX_QUAKE_SPHERE_FRONT_ASPECT", DEFAULT_SPHERE_MEDIA_ASPECT)
        ),
        help="source aspect ratio used before filling the OARB sphere texture",
    )
    parser.add_argument(
        "--mask",
        choices=("none", "circle"),
        default=os.environ.get("HAPAX_QUAKE_MEDIA_MASK", "none"),
        help="Optional output mask. circle is used for the AoA/YT sphere feed.",
    )
    parser.add_argument(
        "--mask-background",
        default=os.environ.get("HAPAX_QUAKE_MEDIA_MASK_BACKGROUND", DEFAULT_MASK_BACKGROUND),
        help="6-digit RGB fill used outside a non-alpha BSP mask.",
    )
    parser.add_argument(
        "--freshness-overlay",
        choices=("none", "seam-pulse"),
        default=os.environ.get("HAPAX_QUAKE_MEDIA_FRESHNESS_OVERLAY", "none"),
        help="Diagnostic heartbeat written into the texture itself for OBS-side liveness checks.",
    )
    parser.add_argument(
        "--drift",
        choices=("on", "off", "enabled", "disabled"),
        default=os.environ.get("HAPAX_QUAKE_MEDIA_DRIFT", "on"),
        help="Apply receiver-local Scroom drift before DarkPlaces texture upload.",
    )
    parser.add_argument(
        "--drift-receiver",
        default=os.environ.get("HAPAX_QUAKE_MEDIA_DRIFT_RECEIVER", ""),
        help="Receiver identity used for deterministic texture-local drift.",
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
        default=float(os.environ.get("HAPAX_QUAKE_MEDIA_DRIFT_INTENSITY", "1.0")),
        help="Multiplier for texture-local drift intensity.",
    )
    parser.add_argument(
        "--gpu-drift",
        action="store_true",
        default=os.environ.get("HAPAX_QUAKE_GPU_DRIFT", "").strip().lower()
        in ("1", "on", "true", "yes", "enabled"),
        help="GPU media-drift cutover: write the undrifted frame to "
        "<output>.raw.bgra and skip the Python drift; the screwm_media_drift "
        "GPU service applies drift and writes <output> (which the engine blits).",
    )
    parser.add_argument(
        "--gpu-projection",
        action="store_true",
        default=_gpu_projection_default(),
        help=(
            "With --gpu-drift and --projection sphere-front, write the raw media frame "
            "and leave OARB seam projection/background composition to screwm_media_drift."
        ),
    )
    parser.add_argument(
        "--youtube-gpu-decode",
        action="store_true",
        default=_youtube_gpu_decode_default(),
        help=(
            "For YouTube sources, request CUDA hardware frames and scale on GPU before "
            "the unavoidable BGRA download for the DarkPlaces live-texture ABI."
        ),
    )
    parser.add_argument("--restart-delay", type=float, default=2.0)
    parser.add_argument("--camera-role", default=os.environ.get("HAPAX_QUAKE_CAMERA_ROLE", ""))
    parser.add_argument("--camera-device", default=os.environ.get("HAPAX_QUAKE_CAMERA_DEVICE"))
    parser.add_argument("--camera-format", default=os.environ.get("HAPAX_QUAKE_CAMERA_FORMAT"))
    parser.add_argument("--camera-size", default=os.environ.get("HAPAX_QUAKE_CAMERA_SIZE"))
    parser.add_argument("--camera-fps", type=int, default=_int_env("HAPAX_QUAKE_CAMERA_FPS"))
    args = parser.parse_args(argv)
    args.configured_url = args.url
    args.resolved_url = args.url
    args.url_source = "configured"
    args.fallback_reason = ""
    args.youtube_player_attr_files = DEFAULT_YOUTUBE_PLAYER_ATTR_FILES
    _resolve_camera_defaults(args)
    return args


def _int_env(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return int(value)


def _resolve_camera_defaults(args: argparse.Namespace) -> None:
    if args.source != "camera":
        return

    defaults = CAMERA_ROLE_DEFAULTS.get(args.camera_role) if args.camera_role else None
    if args.camera_role and defaults is None:
        known = ", ".join(sorted(CAMERA_ROLE_DEFAULTS))
        raise SystemExit(f"unknown camera role {args.camera_role!r}; known roles: {known}")

    args.camera_device = args.camera_device or (defaults or {}).get("device") or "/dev/video0"
    args.camera_format = args.camera_format or (defaults or {}).get("format") or "mjpeg"
    args.camera_size = args.camera_size or (defaults or {}).get("size") or "1280x720"
    args.camera_fps = args.camera_fps or int((defaults or {}).get("fps") or 30)


def main(argv: list[str]) -> int:
    return stream_frames(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
