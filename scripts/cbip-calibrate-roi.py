#!/usr/bin/env python3
"""Write a one-time CBIP ROI/capture calibration for a fixed Pi camera.

Interactive mode opens an image and records four clicks. Non-interactive mode
accepts ``--corners x,y x,y x,y x,y`` and is suitable for tests or SSH use.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PI_EDGE = REPO_ROOT / "pi-edge"
if str(PI_EDGE) not in sys.path:
    sys.path.insert(0, str(PI_EDGE))

from cbip_calibration import (  # noqa: E402
    DEFAULT_FRAME_SIZE,
    RoiRect,
    local_calibration_path,
    write_local_calibration,
)


def _parse_frame_size(value: str) -> tuple[int, int]:
    cleaned = value.lower().replace(",", "x")
    parts = cleaned.split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("frame size must look like 1920x1080")
    try:
        width, height = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("frame size must contain integers") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("frame size must be positive")
    return width, height


def _parse_corner(value: str) -> tuple[int, int]:
    parts = value.replace(":", ",").split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("corner must look like x,y")
    try:
        x, y = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("corner coordinates must be integers") from exc
    return x, y


def _interactive_corners(image_path: Path) -> tuple[list[tuple[int, int]], tuple[int, int]]:
    import cv2

    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise SystemExit(f"could not read image: {image_path}")
    frame_size = (int(image.shape[1]), int(image.shape[0]))
    points: list[tuple[int, int]] = []
    window = "CBIP ROI calibration: click four platter corners, q to abort"
    display = image.copy()

    def on_mouse(event, x, y, flags, param):  # noqa: ANN001
        del flags, param
        if event != cv2.EVENT_LBUTTONDOWN or len(points) >= 4:
            return
        points.append((int(x), int(y)))
        cv2.circle(display, (int(x), int(y)), 8, (0, 255, 255), -1)
        if len(points) > 1:
            cv2.line(display, points[-2], points[-1], (0, 255, 255), 2)
        if len(points) == 4:
            cv2.line(display, points[-1], points[0], (0, 255, 255), 2)

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)
    while len(points) < 4:
        cv2.imshow(window, display)
        key = cv2.waitKey(50) & 0xFF
        if key in {ord("q"), 27}:
            cv2.destroyWindow(window)
            raise SystemExit("ROI calibration aborted")
    cv2.imshow(window, display)
    cv2.waitKey(250)
    cv2.destroyWindow(window)
    return points, frame_size


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cam-id", required=True, help="camera key, e.g. overhead, overhead-left")
    parser.add_argument("--image", type=Path, help="upright calibration frame for interactive mode")
    parser.add_argument(
        "--corners",
        nargs=4,
        type=_parse_corner,
        metavar=("TL", "TR", "BR", "BL"),
        help="four ROI corners as x,y; skips the interactive picker",
    )
    parser.add_argument(
        "--frame-size",
        type=_parse_frame_size,
        default=DEFAULT_FRAME_SIZE,
        help="upright frame size for non-interactive mode, default 1920x1080",
    )
    parser.add_argument("--output", type=Path, help="override output JSON path")
    parser.add_argument("--exposure-time-us", type=int, help="locked rpicam shutter/exposure time")
    parser.add_argument("--analogue-gain", type=float, help="locked rpicam analogue gain")
    parser.add_argument("--red-gain", type=float, help="locked rpicam AWB red gain")
    parser.add_argument("--blue-gain", type=float, help="locked rpicam AWB blue gain")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if (args.red_gain is None) ^ (args.blue_gain is None):
        parser.error("--red-gain and --blue-gain must be provided together")

    if args.corners is not None:
        corners = list(args.corners)
        frame_size = args.frame_size
    else:
        if args.image is None:
            parser.error(
                "provide --image for interactive mode or --corners for non-interactive mode"
            )
        corners, frame_size = _interactive_corners(args.image)

    roi = RoiRect.from_corners(corners, frame_size=frame_size)
    output = args.output or local_calibration_path(args.cam_id)
    colour_gains = (
        (float(args.red_gain), float(args.blue_gain))
        if args.red_gain is not None and args.blue_gain is not None
        else None
    )
    write_local_calibration(
        output,
        camera_id=args.cam_id,
        roi=roi,
        frame_size=frame_size,
        corners=corners,
        exposure_time_us=args.exposure_time_us,
        analogue_gain=args.analogue_gain,
        colour_gains=colour_gains,
    )
    print(output)


if __name__ == "__main__":
    main()
