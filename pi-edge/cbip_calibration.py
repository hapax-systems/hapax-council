"""CBIP static camera calibration helpers for the Pi IR edge daemon.

The operator's CBIP/platter frame is physically fixed, so the Pi side should
load a one-time ROI and locked capture settings instead of rediscovering the
platter boundary every frame.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_FRAME_SIZE = (1920, 1080)
DEFAULT_LOCAL_DIR = Path.home() / ".config" / "hapax"
ENV_CONFIG_PATH = "HAPAX_CBIP_CALIBRATION_CONFIG"
ENV_LOCAL_DIR = "HAPAX_CBIP_CALIBRATION_DIR"


@dataclass(frozen=True)
class RoiRect:
    """Axis-aligned ROI in upright frame coordinates."""

    x: int
    y: int
    width: int
    height: int

    @classmethod
    def from_corners(
        cls,
        corners: list[tuple[int, int]],
        *,
        frame_size: tuple[int, int] | None = None,
    ) -> RoiRect:
        if len(corners) != 4:
            raise ValueError("ROI calibration requires exactly four corners")
        xs = [int(x) for x, _ in corners]
        ys = [int(y) for _, y in corners]
        roi = cls(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        if frame_size is None:
            return roi
        return roi.clamped(*frame_size)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> RoiRect | None:
        try:
            x = int(data["x"])
            y = int(data["y"])
            width = int(data["width"])
            height = int(data["height"])
        except (KeyError, TypeError, ValueError):
            return None
        if width <= 0 or height <= 0:
            return None
        return cls(x, y, width, height)

    def clamped(self, frame_width: int, frame_height: int) -> RoiRect:
        x = min(max(0, int(self.x)), max(0, frame_width - 1))
        y = min(max(0, int(self.y)), max(0, frame_height - 1))
        width = min(max(1, int(self.width)), max(1, frame_width - x))
        height = min(max(1, int(self.height)), max(1, frame_height - y))
        return RoiRect(x, y, width, height)

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class CbipCameraCalibration:
    """Per-camera ROI and capture controls."""

    camera_id: str
    frame_size: tuple[int, int] = DEFAULT_FRAME_SIZE
    roi: RoiRect | None = None
    exposure_locked: bool = False
    exposure_time_us: int | None = None
    analogue_gain: float | None = None
    white_balance_locked: bool = False
    colour_gains: tuple[float, float] | None = None
    source_paths: tuple[str, ...] = ()

    @property
    def has_roi(self) -> bool:
        return self.roi is not None

    def rpicam_still_args(self) -> list[str]:
        """Return rpicam-still args for locked exposure and white balance."""
        args: list[str] = []
        if self.exposure_locked:
            if self.exposure_time_us is not None and self.exposure_time_us > 0:
                args.extend(["--shutter", str(int(self.exposure_time_us))])
            if self.analogue_gain is not None and self.analogue_gain > 0:
                args.extend(["--gain", _format_float(self.analogue_gain)])
        if self.white_balance_locked and self.colour_gains is not None:
            red, blue = self.colour_gains
            if red > 0 and blue > 0:
                args.extend(["--awbgains", f"{_format_float(red)},{_format_float(blue)}"])
        return args


def _format_float(value: float) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def default_config_paths() -> list[Path]:
    paths: list[Path] = []
    env = os.environ.get(ENV_CONFIG_PATH)
    if env:
        paths.append(Path(env).expanduser())
    here = Path(__file__).resolve()
    paths.extend(
        [
            here.parents[1] / "config" / "cbip-calibration.yaml",
            Path.cwd() / "config" / "cbip-calibration.yaml",
            Path.home() / "hapax-edge" / "config" / "cbip-calibration.yaml",
            Path.home() / "hapax-edge" / "cbip-calibration.yaml",
        ]
    )
    return _dedupe_paths(paths)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path)
        if key not in seen:
            out.append(path)
            seen.add(key)
    return out


def default_local_dir() -> Path:
    env = os.environ.get(ENV_LOCAL_DIR)
    if env:
        return Path(env).expanduser()
    return DEFAULT_LOCAL_DIR


def local_calibration_path(camera_id: str, local_dir: Path | None = None) -> Path:
    root = local_dir or default_local_dir()
    return root / f"cbip-roi-{camera_id}.json"


def load_camera_calibration(
    camera_id: str,
    *,
    hostname: str | None = None,
    config_path: Path | None = None,
    local_dir: Path | None = None,
) -> CbipCameraCalibration:
    """Load versioned config plus local ROI/capture override for one camera."""
    base = CbipCameraCalibration(camera_id=camera_id)
    sources: list[str] = []

    config_paths = [config_path] if config_path is not None else default_config_paths()
    for path in config_paths:
        if path is None or not path.exists():
            continue
        data = _load_yaml_or_json(path)
        entry = _select_camera_entry(data, camera_id=camera_id, hostname=hostname)
        if entry:
            base = _calibration_from_mapping(camera_id, entry, source_paths=(str(path),))
            sources.extend(base.source_paths)
            break

    for key in [hostname, camera_id]:
        if not key:
            continue
        path = local_calibration_path(key, local_dir=local_dir)
        if path.exists():
            override = _load_json(path)
            base = _merge_calibration(base, override, source_path=str(path))
            sources = [*sources, str(path)]
            break

    return CbipCameraCalibration(
        camera_id=base.camera_id,
        frame_size=base.frame_size,
        roi=base.roi,
        exposure_locked=base.exposure_locked,
        exposure_time_us=base.exposure_time_us,
        analogue_gain=base.analogue_gain,
        white_balance_locked=base.white_balance_locked,
        colour_gains=base.colour_gains,
        source_paths=tuple(dict.fromkeys(sources or base.source_paths)),
    )


def crop_to_roi(frame: Any, calibration: CbipCameraCalibration) -> Any:
    """Crop an OpenCV/Numpy frame to the configured ROI, if present."""
    if calibration.roi is None:
        return frame
    frame_height, frame_width = frame.shape[:2]
    roi = calibration.roi.clamped(frame_width, frame_height)
    return frame[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width].copy()


def write_local_calibration(
    path: Path,
    *,
    camera_id: str,
    roi: RoiRect,
    frame_size: tuple[int, int],
    corners: list[tuple[int, int]] | None = None,
    exposure_time_us: int | None = None,
    analogue_gain: float | None = None,
    colour_gains: tuple[float, float] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body: dict[str, Any] = {
        "version": 1,
        "camera_id": camera_id,
        "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frame_size": [int(frame_size[0]), int(frame_size[1])],
        "roi": roi.to_dict(),
    }
    if corners is not None:
        body["corners"] = [[int(x), int(y)] for x, y in corners]
    if exposure_time_us is not None:
        body["exposure_locked"] = True
        body["exposure_time_us"] = int(exposure_time_us)
    if analogue_gain is not None:
        body["analogue_gain"] = float(analogue_gain)
    if colour_gains is not None:
        body["white_balance_locked"] = True
        body["colour_gains"] = [float(colour_gains[0]), float(colour_gains[1])]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_yaml_or_json(path: Path) -> dict[str, Any]:
    text = path.read_text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = _load_yaml(text)
    return data if isinstance(data, dict) else {}


def _load_yaml(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return _parse_simple_yaml(text)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the small config/cbip-calibration.yaml shape without PyYAML."""
    root: dict[str, Any] = {}
    cameras: dict[str, dict[str, Any]] = {}
    current_camera: str | None = None
    in_cameras = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0 and stripped == "cameras:":
            root["cameras"] = cameras
            in_cameras = True
            current_camera = None
            continue
        if indent == 0 and ":" in stripped:
            key, value = stripped.split(":", 1)
            root[key] = _parse_scalar(value.strip())
            in_cameras = False
            continue
        if in_cameras and indent == 2 and stripped.endswith(":"):
            current_camera = stripped[:-1]
            cameras[current_camera] = {}
            continue
        if in_cameras and indent >= 4 and current_camera and ":" in stripped:
            key, value = stripped.split(":", 1)
            cameras[current_camera][key.strip()] = _parse_scalar(value.strip())
    return root


def _parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", ""}:
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip('"').strip("'")


def _select_camera_entry(
    data: dict[str, Any], *, camera_id: str, hostname: str | None
) -> dict[str, Any]:
    cameras = data.get("cameras")
    if not isinstance(cameras, dict):
        return {}
    for key in [hostname, camera_id]:
        if key and isinstance(cameras.get(key), dict):
            return dict(cameras[key])
    return {}


def _calibration_from_mapping(
    camera_id: str,
    data: dict[str, Any],
    *,
    source_paths: tuple[str, ...] = (),
) -> CbipCameraCalibration:
    frame_size = _frame_size_from_mapping(data)
    roi = _roi_from_mapping(data, frame_size=frame_size)
    return CbipCameraCalibration(
        camera_id=str(data.get("camera_id") or camera_id),
        frame_size=frame_size,
        roi=roi,
        exposure_locked=bool(data.get("exposure_locked", False)),
        exposure_time_us=_optional_int(data.get("exposure_time_us")),
        analogue_gain=_optional_float(data.get("analogue_gain")),
        white_balance_locked=bool(data.get("white_balance_locked", False)),
        colour_gains=_colour_gains_from_mapping(data),
        source_paths=source_paths,
    )


def _merge_calibration(
    base: CbipCameraCalibration, data: dict[str, Any], *, source_path: str
) -> CbipCameraCalibration:
    override = _calibration_from_mapping(base.camera_id, data, source_paths=(source_path,))
    return CbipCameraCalibration(
        camera_id=override.camera_id or base.camera_id,
        frame_size=override.frame_size or base.frame_size,
        roi=override.roi or base.roi,
        exposure_locked=override.exposure_locked or base.exposure_locked,
        exposure_time_us=override.exposure_time_us
        if override.exposure_time_us is not None
        else base.exposure_time_us,
        analogue_gain=override.analogue_gain
        if override.analogue_gain is not None
        else base.analogue_gain,
        white_balance_locked=override.white_balance_locked or base.white_balance_locked,
        colour_gains=override.colour_gains or base.colour_gains,
        source_paths=(*base.source_paths, source_path),
    )


def _frame_size_from_mapping(data: dict[str, Any]) -> tuple[int, int]:
    raw = data.get("frame_size")
    if isinstance(raw, list | tuple) and len(raw) == 2:
        try:
            return int(raw[0]), int(raw[1])
        except (TypeError, ValueError):
            return DEFAULT_FRAME_SIZE
    width = _optional_int(data.get("frame_width")) or DEFAULT_FRAME_SIZE[0]
    height = _optional_int(data.get("frame_height")) or DEFAULT_FRAME_SIZE[1]
    return width, height


def _roi_from_mapping(data: dict[str, Any], *, frame_size: tuple[int, int]) -> RoiRect | None:
    raw = data.get("roi")
    roi = RoiRect.from_mapping(raw) if isinstance(raw, dict) else None
    if roi is None:
        roi = RoiRect.from_mapping(
            {
                "x": data.get("roi_x"),
                "y": data.get("roi_y"),
                "width": data.get("roi_width"),
                "height": data.get("roi_height"),
            }
        )
    return roi.clamped(*frame_size) if roi is not None else None


def _colour_gains_from_mapping(data: dict[str, Any]) -> tuple[float, float] | None:
    raw = data.get("colour_gains")
    if isinstance(raw, list | tuple) and len(raw) == 2:
        red = _optional_float(raw[0])
        blue = _optional_float(raw[1])
    else:
        red = _optional_float(data.get("colour_gain_red"))
        blue = _optional_float(data.get("colour_gain_blue"))
    if red is None or blue is None:
        return None
    return red, blue


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
