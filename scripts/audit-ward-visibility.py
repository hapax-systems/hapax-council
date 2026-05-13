#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow>=11.0.0"]
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

from PIL import Image, ImageStat

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LAYOUT = REPO_ROOT / "config" / "compositor-layouts" / "default.json"
DEFAULT_RTMP = "rtmp://127.0.0.1:1935/live"
DEFAULT_DEVICE = "/dev/video42"
DEFAULT_ACTIVE_WARDS_FILE = Path("/dev/shm/hapax-compositor/current-layout-state.json")

# Audit thresholds. Match the 2026-04-19 visual-sweep classification:
# "visible" = mean luminance ≥ 0.20 with std ≥ 0.05 (real chrome content
# has both brightness and edges); "overdriven" = frame crop is too bright
# to trust even when it still has edge contrast.
THRESHOLD_FAINT_LUM = 0.20
THRESHOLD_FAINT_STD = 0.05
THRESHOLD_OVERDRIVEN_LUM = 0.92


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
    """Return (width, height) of the captured frame."""
    try:
        with Image.open(image_path) as image:
            return image.size
    except OSError:
        pass
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

    Returns None if the rect is outside the canvas or the image cannot be read.
    """
    try:
        with Image.open(image_path) as image:
            width, height = image.size
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
                return None
            gray = image.convert("L").crop((x, y, x + w, y + h))
            stat = ImageStat.Stat(gray)
            return stat.mean[0] / 255.0, stat.stddev[0] / 255.0
    except OSError:
        pass

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
    if mean_lum >= THRESHOLD_OVERDRIVEN_LUM:
        return "overdriven"
    if mean_lum < THRESHOLD_FAINT_LUM and std < THRESHOLD_FAINT_STD:
        return "absent"
    if mean_lum < THRESHOLD_FAINT_LUM or std < THRESHOLD_FAINT_STD:
        return "faint"
    return "visible"


def _load_active_wards(path: Path) -> tuple[set[str] | None, str | None]:
    """Read the active rendered ward set from current-layout-state/active_wards JSON."""
    if not path.exists():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "active_wards_unreadable"
    if not isinstance(payload, dict):
        return None, "active_wards_unreadable"

    raw_wards = (
        payload.get("active_ward_ids")
        or payload.get("ward_ids")
        or payload.get("active_wards")
        or payload.get("rendered_wards")
    )
    if raw_wards is None:
        return None, "active_wards_missing"
    if not isinstance(raw_wards, list):
        return None, "active_wards_unreadable"

    wards: set[str] = set()
    for item in raw_wards:
        if isinstance(item, str) and item.strip():
            wards.add(item)
        elif isinstance(item, dict):
            ward_id = item.get("ward") or item.get("ward_id") or item.get("id")
            if isinstance(ward_id, str) and ward_id.strip():
                wards.add(ward_id)
    return wards, None


def _load_active_assignment_rects(path: Path) -> tuple[list[dict[str, object]], str | None]:
    """Read rendered assignment geometry from current-layout-state, if present."""
    if not path.exists():
        return [], None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], "active_assignments_unreadable"
    if not isinstance(payload, dict):
        return [], "active_assignments_unreadable"
    raw_assignments = payload.get("assignments")
    if raw_assignments is None:
        return [], None
    if not isinstance(raw_assignments, list):
        return [], "active_assignments_unreadable"

    assignments: list[dict[str, object]] = []
    for item in raw_assignments:
        if not isinstance(item, dict):
            continue
        ward = item.get("ward") or item.get("source") or item.get("ward_id")
        surface = item.get("surface") or item.get("surface_id")
        geometry = item.get("geometry") if isinstance(item.get("geometry"), dict) else item
        if not isinstance(ward, str) or not ward.strip():
            continue
        if not isinstance(surface, str) or not surface.strip():
            surface = ward
        try:
            x = int(geometry.get("x", 0))  # type: ignore[union-attr]
            y = int(geometry.get("y", 0))  # type: ignore[union-attr]
            w = int(geometry.get("w", geometry.get("width", 0)))  # type: ignore[union-attr]
            h = int(geometry.get("h", geometry.get("height", 0)))  # type: ignore[union-attr]
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        try:
            opacity = float(item.get("opacity", 1.0))
        except (TypeError, ValueError):
            opacity = 1.0
        assignments.append(
            {
                "ward": ward,
                "surface": surface,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "opacity": opacity,
                "non_destructive": bool(item.get("non_destructive", False)),
            }
        )
    return assignments, None


def _visibility_failures(
    *,
    visible_count: int,
    considered_count: int,
    min_visible_wards: int | None,
    min_visible_fraction: float | None,
    missing_active_wards: set[str],
    active_wards_error: str | None,
) -> list[str]:
    failures: list[str] = []
    if active_wards_error is not None:
        failures.append(active_wards_error)
    for ward in sorted(missing_active_wards):
        failures.append(f"active_ward_missing:{ward}")
    if min_visible_wards is not None and visible_count < min_visible_wards:
        failures.append(f"visible_ward_count_below_min:{visible_count}<{min_visible_wards}")
    visible_fraction = visible_count / considered_count if considered_count else 0.0
    if min_visible_fraction is not None and visible_fraction < min_visible_fraction:
        failures.append(
            f"visible_ward_fraction_below_min:{visible_fraction:.3f}<{min_visible_fraction:.3f}"
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--rtmp", default=DEFAULT_RTMP)
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--layout", default=str(DEFAULT_LAYOUT))
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON only.")
    parser.add_argument(
        "--active-wards-file",
        default=str(DEFAULT_ACTIVE_WARDS_FILE),
        help=(
            "Optional current-layout-state/active_wards JSON. When present, "
            "only active rendered wards are audited."
        ),
    )
    parser.add_argument(
        "--min-visible-wards",
        type=int,
        default=None,
        help="Fail when fewer than this many considered wards are visible.",
    )
    parser.add_argument(
        "--min-visible-fraction",
        type=float,
        default=None,
        help="Fail when visible/considered ward fraction is below this value.",
    )
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

    active_wards, active_wards_error = _load_active_wards(Path(args.active_wards_file))
    active_assignment_rects, active_assignments_error = _load_active_assignment_rects(
        Path(args.active_wards_file)
    )
    rect_assignments = []
    for assignment in active_assignment_rects:
        ward_id = str(assignment["ward"])
        if active_wards is not None and ward_id not in active_wards:
            continue
        rect_assignments.append(
            {
                "ward": ward_id,
                "surface": assignment["surface"],
                "x": int(assignment["x"]),
                "y": int(assignment["y"]),
                "w": int(assignment["w"]),
                "h": int(assignment["h"]),
                "opacity": float(assignment.get("opacity", 1.0)),
                "non_destructive": bool(assignment.get("non_destructive", False)),
            }
        )
    if not rect_assignments:
        layout = json.loads(Path(args.layout).read_text())
        surfaces_by_id = {s["id"]: s for s in layout.get("surfaces", [])}
        for assignment in layout.get("assignments", []):
            surf = surfaces_by_id.get(assignment["surface"])
            if surf is None or surf.get("geometry", {}).get("kind") != "rect":
                continue
            ward_id = assignment["source"]
            if active_wards is not None and ward_id not in active_wards:
                continue
            geom = surf["geometry"]
            rect_assignments.append(
                {
                    "ward": ward_id,
                    "surface": assignment["surface"],
                    "x": int(geom.get("x", 0)),
                    "y": int(geom.get("y", 0)),
                    "w": int(geom.get("w", 0)),
                    "h": int(geom.get("h", 0)),
                    "opacity": float(assignment.get("opacity", 1.0)),
                    "non_destructive": bool(assignment.get("non_destructive", False)),
                }
            )
    if active_assignments_error is not None and active_wards_error is None:
        active_wards_error = active_assignments_error

    with tempfile.TemporaryDirectory() as td:
        if args.snapshot:
            snapshot_path = Path(args.snapshot)
            if not snapshot_path.exists():
                payload = {
                    "ok": False,
                    "reasons": [f"snapshot_not_found:{snapshot_path}"],
                    "wards": [],
                }
                if args.json:
                    print(json.dumps(payload, sort_keys=True))
                else:
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
            payload = {
                "ok": False,
                "reasons": ["frame_dimensions_unavailable"],
                "wards": [],
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("ERROR: could not read frame dimensions", file=sys.stderr)
            return 2
        frame_w, frame_h = frame_dims
        scale_x = frame_w / args.canvas_w
        scale_y = frame_h / args.canvas_h
        if not args.json and (abs(scale_x - 1.0) > 0.01 or abs(scale_y - 1.0) > 0.01):
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

        if not args.json:
            print(f"Captured frame: {frame_path} ({frame_path.stat().st_size} bytes)")
            print()
            header = (
                f"{'ward':30s} {'rect':24s} {'op':>5s} {'nd':>3s} {'mean':>5s} {'std':>5s}  verdict"
            )
            print(header)
            print("-" * len(header))

        verdict_counts: dict[str, int] = {}
        ward_payloads: list[dict[str, object]] = []
        for asn in rect_assignments:
            stats = _crop_stats(frame_path, asn["x"], asn["y"], asn["w"], asn["h"])
            rect_str = f"({asn['x']},{asn['y']},{asn['w']},{asn['h']})"
            if stats is None:
                if not args.json:
                    print(
                        f"{asn['ward']:30s} {rect_str:24s} "
                        f"{asn['opacity']:>5.2f} "
                        f"{('Y' if asn['non_destructive'] else 'N'):>3s} "
                        f"  N/A   N/A   crop-failed"
                    )
                ward_payloads.append(
                    {
                        **asn,
                        "mean_luminance": None,
                        "std": None,
                        "verdict": "crop-failed",
                    }
                )
                continue
            mean_lum, std = stats
            verdict = _verdict(mean_lum, std)
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
            ward_payloads.append(
                {
                    **asn,
                    "mean_luminance": round(mean_lum, 6),
                    "std": round(std, 6),
                    "verdict": verdict,
                }
            )
            if not args.json:
                print(
                    f"{asn['ward']:30s} {rect_str:24s} "
                    f"{asn['opacity']:>5.2f} "
                    f"{('Y' if asn['non_destructive'] else 'N'):>3s} "
                    f"{mean_lum:>5.2f} {std:>5.2f}  {verdict}"
                )

        visible_count = verdict_counts.get("visible", 0)
        considered_count = len(rect_assignments)
        missing_active_wards = (
            (active_wards or set()) - {str(asn["ward"]) for asn in rect_assignments}
            if active_wards is not None
            else set()
        )
        reasons = _visibility_failures(
            visible_count=visible_count,
            considered_count=considered_count,
            min_visible_wards=args.min_visible_wards,
            min_visible_fraction=args.min_visible_fraction,
            missing_active_wards=missing_active_wards,
            active_wards_error=active_wards_error,
        )
        payload = {
            "ok": not reasons,
            "reasons": reasons,
            "captured_frame": str(frame_path),
            "frame_size_bytes": frame_path.stat().st_size,
            "frame_width": frame_w,
            "frame_height": frame_h,
            "active_wards_file": str(args.active_wards_file),
            "assignment_source": "current-layout-state"
            if active_assignment_rects
            else "layout-json",
            "active_ward_ids": sorted(active_wards) if active_wards is not None else None,
            "considered_wards": considered_count,
            "visible_wards": visible_count,
            "visible_fraction": round(visible_count / considered_count, 6)
            if considered_count
            else 0.0,
            "verdict_counts": verdict_counts,
            "min_visible_wards": args.min_visible_wards,
            "min_visible_fraction": args.min_visible_fraction,
            "wards": ward_payloads,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print()
            for verdict, count in sorted(verdict_counts.items()):
                print(f"  {verdict}: {count}")
            for reason in reasons:
                print(f"FAIL: {reason}", file=sys.stderr)

    return 0 if payload["ok"] else 10


if __name__ == "__main__":
    sys.exit(main())
