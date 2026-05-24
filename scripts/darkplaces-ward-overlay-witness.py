#!/usr/bin/env python3
"""Offline DarkPlaces + compositor ward overlay witness.

This script captures one frame from the dedicated DarkPlaces loopback
(`/dev/video52` by default), renders the repo's actual compositor layout Cairo
sources over that frame, and writes private evidence files. It deliberately does
not write to `/dev/video42` and redirects active-ward readbacks away from the
live compositor's `/dev/shm/hapax-compositor` files.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cairo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LOG = logging.getLogger("darkplaces-ward-overlay-witness")


@dataclass
class RegistryBuild:
    constructed: list[str] = field(default_factory=list)
    ticked: list[str] = field(default_factory=list)
    construct_errors: dict[str, str] = field(default_factory=dict)
    tick_errors: dict[str, str] = field(default_factory=dict)


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _default_out_dir() -> Path:
    return (
        Path.home()
        / "hapax-state"
        / "hardware-validation"
        / f"darkplaces-ward-overlay-{_now_stamp()}-{os.getpid()}"
    )


def _run_capture(cmd: list[str], path: Path, *, timeout_s: float = 10.0) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
    payload = {
        "cmd": cmd,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def capture_darkplaces_frame(
    *,
    device: str,
    width: int,
    height: int,
    fps: int,
    out_dir: Path,
) -> Path:
    frame_path = out_dir / "darkplaces-background.png"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "v4l2",
        "-video_size",
        f"{width}x{height}",
        "-framerate",
        str(fps),
        "-i",
        device,
        "-frames:v",
        "1",
        "-y",
        str(frame_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=12, check=False)
    (out_dir / "ffmpeg-capture.json").write_text(
        json.dumps(
            {
                "cmd": cmd,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if result.returncode != 0 or not frame_path.exists():
        raise RuntimeError(
            f"failed to capture {device} frame; rc={result.returncode}; see ffmpeg-capture.json"
        )
    return frame_path


def _patch_active_ward_paths(out_dir: Path) -> None:
    from agents.studio_compositor import active_wards

    active_wards.ACTIVE_WARDS_FILE = out_dir / "active_wards.json"
    active_wards.CURRENT_LAYOUT_STATE_FILE = out_dir / "current-layout-state.json"
    active_wards.WARD_PROPERTIES_FILE = out_dir / "ward-properties.json"


def _layout_stage_source_ids(layout: Any) -> set[str]:
    try:
        from agents.studio_compositor.compositor import _layout_source_ids_for_enabled_stages

        return set(_layout_source_ids_for_enabled_stages(layout))
    except Exception:
        LOG.debug("falling back to all assigned sources for witness", exc_info=True)
        return {assignment.source for assignment in layout.assignments}


def build_source_registry(layout: Any) -> tuple[Any, RegistryBuild]:
    from agents.studio_compositor.source_registry import SourceRegistry

    registry = SourceRegistry()
    report = RegistryBuild()
    stage_source_ids = _layout_stage_source_ids(layout)

    for source in layout.sources:
        if source.id not in stage_source_ids:
            continue
        try:
            backend = registry.construct_backend(source, budget_tracker=None)
            registry.register(source.id, backend)
            report.constructed.append(source.id)
        except Exception as exc:  # noqa: BLE001 - witness records and continues.
            report.construct_errors[source.id] = f"{type(exc).__name__}: {exc}"

    for source_id in list(registry.ids()):
        try:
            backend = registry._backends[source_id]  # noqa: SLF001 - bounded witness utility.
            tick_once = getattr(backend, "tick_once", None)
            if tick_once is None:
                continue
            tick_once()
            report.ticked.append(source_id)
        except Exception as exc:  # noqa: BLE001 - witness records and continues.
            report.tick_errors[source_id] = f"{type(exc).__name__}: {exc}"

    return registry, report


def _paint_png_background(cr: cairo.Context, png_path: Path, width: int, height: int) -> None:
    bg = cairo.ImageSurface.create_from_png(str(png_path))
    cr.save()
    if bg.get_width() != width or bg.get_height() != height:
        cr.scale(width / bg.get_width(), height / bg.get_height())
    cr.set_source_surface(bg, 0, 0)
    cr.paint()
    cr.restore()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def render_overlay_witness(
    *,
    layout_path: Path,
    background_png: Path,
    out_dir: Path,
    width: int,
    height: int,
) -> dict[str, Any]:
    _patch_active_ward_paths(out_dir)

    from agents.studio_compositor.compositor import load_layout_or_fallback
    from agents.studio_compositor.fx_chain import pip_draw_from_layout
    from agents.studio_compositor.layout_state import LayoutState

    layout = load_layout_or_fallback(layout_path)
    layout_state = LayoutState(layout)
    registry, registry_report = build_source_registry(layout)

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    _paint_png_background(cr, background_png, width, height)
    pip_draw_from_layout(
        cr,
        layout_state,
        registry,
        stage="pre_fx",
        use_composite_cache=False,
    )
    pip_draw_from_layout(
        cr,
        layout_state,
        registry,
        stage="post_fx",
        use_composite_cache=False,
    )
    surface.flush()

    composite_png = out_dir / "darkplaces-with-layout-wards.png"
    surface.write_to_png(str(composite_png))

    active_wards = _read_json(out_dir / "active_wards.json")
    current_layout = _read_json(out_dir / "current-layout-state.json")
    return {
        "layout": layout.name,
        "layout_path": str(layout_path),
        "layout_sources": len(layout.sources),
        "layout_assignments": len(layout.assignments),
        "constructed_sources": registry_report.constructed,
        "ticked_sources": registry_report.ticked,
        "construct_errors": registry_report.construct_errors,
        "tick_errors": registry_report.tick_errors,
        "active_wards": active_wards.get("ward_ids", []),
        "current_layout_state": current_layout,
        "background_png": str(background_png),
        "composite_png": str(composite_png),
    }


def write_image_stats(path: Path, out_path: Path) -> None:
    cmd = [
        "magick",
        "identify",
        "-format",
        (
            '{"width":%w,"height":%h,"mean":"%[mean]",'
            '"standard_deviation":"%[standard-deviation]","min":"%[min]",'
            '"max":"%[max]"}\n'
        ),
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    payload: dict[str, Any] = {
        "cmd": cmd,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.returncode == 0:
        try:
            payload["stats"] = json.loads(result.stdout)
        except ValueError:
            pass
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device", default=os.environ.get("HAPAX_DARKPLACES_V4L2_DEVICE", "/dev/video52")
    )
    parser.add_argument(
        "--width", type=int, default=int(os.environ.get("DARKPLACES_WIDTH", "1280"))
    )
    parser.add_argument(
        "--height", type=int, default=int(os.environ.get("DARKPLACES_HEIGHT", "720"))
    )
    parser.add_argument("--fps", type=int, default=int(os.environ.get("DARKPLACES_FPS", "30")))
    parser.add_argument(
        "--layout",
        type=Path,
        default=REPO_ROOT / "config" / "compositor-layouts" / "default.json",
    )
    parser.add_argument("--out-dir", type=Path, default=_default_out_dir())
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    out_dir = args.out_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    start = time.time()
    _run_capture(["v4l2-ctl", "-d", args.device, "--get-fmt-video"], out_dir / "video-format.json")
    _run_capture(["fuser", args.device], out_dir / "video-fuser.json")

    try:
        background = capture_darkplaces_frame(
            device=args.device,
            width=args.width,
            height=args.height,
            fps=args.fps,
            out_dir=out_dir,
        )
        report = render_overlay_witness(
            layout_path=args.layout,
            background_png=background,
            out_dir=out_dir,
            width=args.width,
            height=args.height,
        )
        write_image_stats(background, out_dir / "background-image-stats.json")
        write_image_stats(Path(report["composite_png"]), out_dir / "composite-image-stats.json")
        report["duration_s"] = round(time.time() - start, 3)
        report["ok"] = True
        (out_dir / "witness-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(json.dumps({"ok": True, "out_dir": str(out_dir), **report}, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 - witness must preserve failure evidence.
        report = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "duration_s": round(time.time() - start, 3),
        }
        (out_dir / "witness-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        LOG.exception("darkplaces ward overlay witness failed; evidence=%s", out_dir)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
