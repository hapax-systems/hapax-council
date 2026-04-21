#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Capture one frame from MediaMTX RTMP relay and report per-ward visibility.

The wiring audit's visual sweep flagged 9 of 16 wards as "not visible at the
expected position" while the per-ward blit metrics showed 100% blit success.
This diagnostic re-runs the audit's frame-crop method against a fresh frame
so the gap can be attributed per ward (mean luminance, std, area-fill ratio).

Usage:
    scripts/audit-ward-visibility.py [--rtmp URL] [--device PATH] [--frame OUT.jpg]

Source priority:
    1. ``--device`` (e.g. /dev/video42) — direct V4L2 capture; skipped when
       OBS holds the device.
    2. ``--rtmp`` (default rtmp://127.0.0.1:1935/live) — MediaMTX relay.
       Always available because compositor publishes here unconditionally.

Output:
    Per-ward table with: rect (x, y, w, h), mean luminance [0..1], std,
    visual verdict (visible / faint / absent / overdriven). Absent matches
    the audit's verdict pattern (uniform low-std region with no chrome).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LAYOUT = REPO_ROOT / "config" / "compositor-layouts" / "default.json"
DEFAULT_RTMP = "rtmp://127.0.0.1:1935/live"
DEFAULT_DEVICE = "/dev/video42"

# Audit thresholds. Match the 2026-04-19 visual-sweep classification:
# "visible" = mean luminance ≥ 0.20 with std ≥ 0.10 (real chrome content
# has both brightness and edges); "faint" = enough luminance but flat; etc.
THRESHOLD_FAINT_LUM = 0.20
THRESHOLD_FAINT_STD = 0.05
THRESHOLD_OVERDRIVEN_LUM = 0.92
THRESHOLD_OVERDRIVEN_STD = 0.10


def _ffmpeg_capture_rtmp(url: str, out: Path, *, timeout_s: int = 8) -> bool:
    """Pull one keyframe via ffmpeg from an RTMP URL. Returns True on success."""
    if shutil.which("ffmpeg") is None:
        print("ERROR: ffmpeg not on PATH — install ffmpeg first", file=sys.stderr)
        return False
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-rw_timeout",
        str(timeout_s * 1_000_000),
        "-i",
        url,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout_s + 5, check=False)
    except subprocess.TimeoutExpired:
        print(f"ERROR: ffmpeg RTMP capture timed out ({url})", file=sys.stderr)
        return False
    if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        print(
            f"ERROR: ffmpeg RTMP capture failed (rc={result.returncode}): "
            f"{result.stderr.decode(errors='replace')[:240]}",
            file=sys.stderr,
        )
        return False
    return True


def _ffmpeg_capture_v4l2(device: str, out: Path, *, timeout_s: int = 8) -> bool:
    """Pull one keyframe via ffmpeg from a V4L2 device. Returns True on success."""
    if shutil.which("ffmpeg") is None:
        return False
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "v4l2",
        "-i",
        device,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0 and out.exists() and out.stat().st_size > 0


def _frame_dimensions(image_path: Path) -> tuple[int, int] | None:
    """Return (width, height) of the captured frame using ImageMagick."""
    if shutil.which("identify") is None:
        return None
    try:
        result = subprocess.run(
            ["identify", "-format", "%w %h", str(image_path)],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    try:
        parts = result.stdout.decode().strip().split()
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return None


def _crop_stats(image_path: Path, x: int, y: int, w: int, h: int) -> tuple[float, float] | None:
    """Return (mean_luminance, std) for the given crop, [0..1] scale.

    Uses ImageMagick's ``identify -format`` to avoid a Pillow dependency on
    the diagnostic script. Returns None if the crop tool isn't installed
    or the rect is outside the canvas.
    """
    if shutil.which("identify") is None or shutil.which("convert") is None:
        return None
    crop_geom = f"{w}x{h}+{x}+{y}"
    # Convert crop to grayscale, then read mean + std (both in [0..1]).
    cmd = [
        "convert",
        str(image_path),
        "-crop",
        crop_geom,
        "+repage",
        "-colorspace",
        "Gray",
        "-format",
        "%[fx:mean] %[fx:standard_deviation]",
        "info:",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=5, check=False)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    try:
        parts = result.stdout.decode().strip().split()
        return float(parts[0]), float(parts[1])
    except (IndexError, ValueError):
        return None


def _verdict(mean_lum: float, std: float) -> str:
    if mean_lum >= THRESHOLD_OVERDRIVEN_LUM and std >= THRESHOLD_OVERDRIVEN_STD:
        return "overdriven"
    if mean_lum < THRESHOLD_FAINT_LUM and std < THRESHOLD_FAINT_STD:
        return "absent"
    if mean_lum < THRESHOLD_FAINT_LUM or std < THRESHOLD_FAINT_STD:
        return "faint"
    return "visible"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--rtmp", default=DEFAULT_RTMP)
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--layout", default=str(DEFAULT_LAYOUT))
    parser.add_argument(
        "--frame",
        default=None,
        help="Optional path to save the captured frame for inspection.",
    )
    parser.add_argument(
        "--no-rtmp-fallback",
        action="store_true",
        help="Fail rather than falling back to RTMP when V4L2 capture fails.",
    )
    parser.add_argument(
        "--snapshot",
        default=None,
        help=(
            "Skip live capture and read a pre-existing frame at this path "
            "(e.g. /dev/shm/hapax-compositor/fx-snapshot.jpg). Coordinates "
            "from default.json are auto-scaled if the snapshot dimensions "
            "differ from the layout canvas."
        ),
    )
    parser.add_argument(
        "--canvas-w",
        type=int,
        default=1920,
        help="Layout canvas width (default 1920) used for coord scaling.",
    )
    parser.add_argument(
        "--canvas-h",
        type=int,
        default=1080,
        help="Layout canvas height (default 1080) used for coord scaling.",
    )
    args = parser.parse_args()

    layout = json.loads(Path(args.layout).read_text())
    surfaces_by_id = {s["id"]: s for s in layout.get("surfaces", [])}
    rect_assignments = []
    for assignment in layout.get("assignments", []):
        surf = surfaces_by_id.get(assignment["surface"])
        if surf is None or surf.get("geometry", {}).get("kind") != "rect":
            continue
        geom = surf["geometry"]
        rect_assignments.append(
            {
                "ward": assignment["source"],
                "surface": assignment["surface"],
                "x": int(geom.get("x", 0)),
                "y": int(geom.get("y", 0)),
                "w": int(geom.get("w", 0)),
                "h": int(geom.get("h", 0)),
                "opacity": float(assignment.get("opacity", 1.0)),
                "non_destructive": bool(assignment.get("non_destructive", False)),
            }
        )

    with tempfile.TemporaryDirectory() as td:
        if args.snapshot:
            snapshot_path = Path(args.snapshot)
            if not snapshot_path.exists():
                print(f"ERROR: snapshot {snapshot_path} not found", file=sys.stderr)
                return 2
            frame_path = snapshot_path
            captured = True
        else:
            frame_path = Path(args.frame) if args.frame else Path(td) / "frame.jpg"
            captured = _ffmpeg_capture_v4l2(args.device, frame_path)
            if not captured and not args.no_rtmp_fallback:
                print(
                    f"V4L2 device {args.device} unavailable (likely OBS holding it); "
                    f"falling back to RTMP {args.rtmp}",
                    file=sys.stderr,
                )
                captured = _ffmpeg_capture_rtmp(args.rtmp, frame_path)
            if not captured:
                print("ERROR: failed to capture a frame from any source", file=sys.stderr)
                return 2

        # Scale layout coordinates to the actual frame dimensions.
        # Compositor canvas is 1920×1080; snapshots / V4L2 may be 1280×720.
        frame_dims = _frame_dimensions(frame_path)
        if frame_dims is None:
            print("ERROR: could not read frame dimensions", file=sys.stderr)
            return 2
        frame_w, frame_h = frame_dims
        scale_x = frame_w / args.canvas_w
        scale_y = frame_h / args.canvas_h
        if abs(scale_x - 1.0) > 0.01 or abs(scale_y - 1.0) > 0.01:
            print(
                f"Frame {frame_w}×{frame_h} differs from canvas {args.canvas_w}×{args.canvas_h}; "
                f"scaling coords by ({scale_x:.3f}, {scale_y:.3f})",
                file=sys.stderr,
            )
        for asn in rect_assignments:
            asn["x"] = int(asn["x"] * scale_x)
            asn["y"] = int(asn["y"] * scale_y)
            asn["w"] = max(1, int(asn["w"] * scale_x))
            asn["h"] = max(1, int(asn["h"] * scale_y))

        print(f"Captured frame: {frame_path} ({frame_path.stat().st_size} bytes)")
        print()
        header = (
            f"{'ward':30s} {'rect':24s} {'op':>5s} {'nd':>3s} {'mean':>5s} {'std':>5s}  verdict"
        )
        print(header)
        print("-" * len(header))

        verdict_counts: dict[str, int] = {}
        for asn in rect_assignments:
            stats = _crop_stats(frame_path, asn["x"], asn["y"], asn["w"], asn["h"])
            rect_str = f"({asn['x']},{asn['y']},{asn['w']},{asn['h']})"
            if stats is None:
                print(
                    f"{asn['ward']:30s} {rect_str:24s} "
                    f"{asn['opacity']:>5.2f} {('Y' if asn['non_destructive'] else 'N'):>3s} "
                    f"  N/A   N/A   crop-failed"
                )
                continue
            mean_lum, std = stats
            verdict = _verdict(mean_lum, std)
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
            print(
                f"{asn['ward']:30s} {rect_str:24s} "
                f"{asn['opacity']:>5.2f} {('Y' if asn['non_destructive'] else 'N'):>3s} "
                f"{mean_lum:>5.2f} {std:>5.2f}  {verdict}"
            )

        print()
        for verdict, count in sorted(verdict_counts.items()):
            print(f"  {verdict}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
