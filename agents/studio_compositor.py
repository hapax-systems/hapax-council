"""Studio Compositor — GStreamer pipeline that tiles camera feeds into a single 1080p output.

Reads N camera feeds via v4l2src, decodes MJPEG with jpegdec, uploads to CUDA,
composites via cudacompositor, encodes with nvh264enc, and outputs to
/dev/video42 (v4l2loopback).

Features:
- Hero camera (2x tile), automatic grid layout for remaining cameras
- Per-camera watchdog timeout (freeze last frame on disconnect)
- Bus error handling: camera failures are isolated, other cameras continue
- Cairo overlay: role labels, consent badges, flow state, audio meter
- Perception state bridge: reads ~/.cache/hapax-voice/perception-state.json
- Status file written atomically to ~/.cache/hapax-compositor/status.json
- Per-camera recording via nvh264enc + splitmuxsink
- HLS output for browser preview via hlssink2
- JPEG snapshots to /dev/shm for low-latency access
- Camera profiles with time-based and condition-based switching

Usage:
    uv run python -m agents.studio_compositor --config PATH
    uv run python -m agents.studio_compositor --default-config
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------

CACHE_DIR = Path.home() / ".cache" / "hapax-compositor"
STATUS_FILE = CACHE_DIR / "status.json"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "hapax-compositor" / "config.yaml"
SNAPSHOT_DIR = Path("/dev/shm/hapax-compositor")

OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080


class CameraV4L2(BaseModel):
    """V4L2 control values for a camera."""

    gain: int | None = None
    exposure: int | None = None
    brightness: int | None = None
    contrast: int | None = None
    saturation: int | None = None
    sharpness: int | None = None
    white_balance_temperature: int | None = None
    focus_absolute: int | None = None


class CameraProfile(BaseModel):
    """A named camera profile with optional schedule/condition gating."""

    name: str
    schedule: str | None = None  # e.g. "08:00-18:00" or "night"
    condition: str | None = None  # e.g. "flow_state=active"
    priority: int = 0
    cameras: dict[str, CameraV4L2] = Field(default_factory=dict)


class CameraSpec(BaseModel):
    """A single camera source."""

    role: str  # e.g. "brio-operator", "c920-hardware", "c920-room", "c920-aux", "ir"
    device: str  # /dev/v4l/by-id/... or /dev/videoN
    width: int = 1280
    height: int = 720
    input_format: str = "mjpeg"  # "mjpeg" or "raw"
    pixel_format: str | None = None  # e.g. "gray" for IR sensor
    hero: bool = False  # hero cam gets 2x tile size


class RecordingConfig(BaseModel):
    """Per-camera recording configuration."""

    enabled: bool = True
    output_dir: str = str(Path.home() / "video-recording")
    segment_seconds: int = 300
    qp: int = 23


class HlsConfig(BaseModel):
    """HLS output configuration."""

    enabled: bool = True
    target_duration: int = 2
    playlist_length: int = 3
    max_files: int = 6
    output_dir: str = str(CACHE_DIR / "hls")
    bitrate: int = 4000


class CompositorConfig(BaseModel):
    """Full compositor configuration."""

    cameras: list[CameraSpec] = Field(default_factory=list)
    output_device: str = "/dev/video42"
    output_width: int = OUTPUT_WIDTH
    output_height: int = OUTPUT_HEIGHT
    framerate: int = 30
    bitrate: int = 8_000_000  # nvh264enc bitrate in bits/sec
    watchdog_timeout_ms: int = 5000  # per-source watchdog timeout
    status_interval_s: float = 5.0
    overlay_enabled: bool = True
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    hls: HlsConfig = Field(default_factory=HlsConfig)
    camera_profiles: list[CameraProfile] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Default config for the current studio
# ---------------------------------------------------------------------------

_DEFAULT_CAMERAS: list[dict[str, Any]] = [
    {
        "role": "brio-operator",
        "device": "/dev/v4l/by-id/usb-046d_Logitech_BRIO_5342C819-video-index0",
        "width": 1920,
        "height": 1080,
        "input_format": "mjpeg",
        "hero": True,
    },
    {
        "role": "c920-hardware",
        "device": "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_2657DFCF-video-index0",
        "width": 1280,
        "height": 720,
        "input_format": "mjpeg",
    },
    {
        "role": "c920-room",
        "device": "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_86B6B75F-video-index0",
        "width": 1280,
        "height": 720,
        "input_format": "mjpeg",
    },
    {
        "role": "c920-aux",
        "device": "/dev/v4l/by-id/usb-046d_HD_Pro_Webcam_C920_7B88C71F-video-index0",
        "width": 1280,
        "height": 720,
        "input_format": "mjpeg",
    },
]


def _default_config() -> CompositorConfig:
    return CompositorConfig(cameras=[CameraSpec(**c) for c in _DEFAULT_CAMERAS])


def load_config(path: Path | None = None) -> CompositorConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text()) or {}
            return CompositorConfig(**data)
        except Exception as exc:
            log.warning("Failed to load config from %s: %s -- using defaults", config_path, exc)
    return _default_config()


# ---------------------------------------------------------------------------
# Tile layout
# ---------------------------------------------------------------------------


class TileRect(BaseModel):
    x: int
    y: int
    w: int
    h: int


def _fit_16x9(w: int, h: int) -> tuple[int, int, int, int]:
    """Compute largest 16:9 rect fitting in w x h, return (x_off, y_off, fit_w, fit_h)."""
    target_ratio = 16 / 9
    if w / h > target_ratio:
        # slot is wider than 16:9 — height is the constraint
        fit_h = h
        fit_w = int(h * target_ratio)
    else:
        # slot is taller than 16:9 — width is the constraint
        fit_w = w
        fit_h = int(w / target_ratio)
    x_off = (w - fit_w) // 2
    y_off = (h - fit_h) // 2
    return x_off, y_off, fit_w, fit_h


def compute_tile_layout(
    cameras: list[CameraSpec],
    canvas_w: int = OUTPUT_WIDTH,
    canvas_h: int = OUTPUT_HEIGHT,
) -> dict[str, TileRect]:
    """Compute tile positions for each camera on the output canvas.

    Hero camera (if any) gets the left portion, others stack vertically on the right.
    All tiles are 16:9 fitted and centered within their allocated slots.
    """
    n = len(cameras)
    if n == 0:
        return {}

    heroes = [c for c in cameras if c.hero]
    others = [c for c in cameras if not c.hero]

    layout: dict[str, TileRect] = {}

    if heroes and len(others) >= 1:
        hero = heroes[0]
        # Hero gets left portion: 2/3 width for <=4 others, 1/2 for more
        if len(others) <= 4:
            hero_slot_w = (canvas_w * 2) // 3
        else:
            hero_slot_w = canvas_w // 2
        hero_slot_h = canvas_h

        hx, hy, hw, hh = _fit_16x9(hero_slot_w, hero_slot_h)
        layout[hero.role] = TileRect(x=hx, y=hy, w=hw, h=hh)

        # Others stack vertically on the right
        right_x = hero_slot_w
        right_w = canvas_w - hero_slot_w
        slot_h = canvas_h // len(others)

        for i, cam in enumerate(others):
            sx, sy, sw, sh = _fit_16x9(right_w, slot_h)
            layout[cam.role] = TileRect(
                x=right_x + sx,
                y=i * slot_h + sy,
                w=sw,
                h=sh,
            )
    else:
        # No hero: equal grid with 16:9 fitted tiles
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        slot_w = canvas_w // cols
        slot_h = canvas_h // rows
        for i, cam in enumerate(cameras):
            col = i % cols
            row = i // cols
            sx, sy, sw, sh = _fit_16x9(slot_w, slot_h)
            layout[cam.role] = TileRect(
                x=col * slot_w + sx,
                y=row * slot_h + sy,
                w=sw,
                h=sh,
            )

    return layout


# ---------------------------------------------------------------------------
# Overlay state (thread-safe cache, read from perception-state.json)
# ---------------------------------------------------------------------------

PERCEPTION_STATE_PATH = Path.home() / ".cache" / "hapax-voice" / "perception-state.json"


class OverlayData(BaseModel):
    """Snapshot of perception state for rendering overlays."""

    production_activity: str = ""
    music_genre: str = ""
    flow_state: str = ""
    flow_score: float = 0.0
    emotion_valence: float = 0.0
    emotion_arousal: float = 0.0
    audio_energy_rms: float = 0.0
    active_contracts: list[str] = Field(default_factory=list)
    timestamp: float = 0.0


class OverlayState:
    """Thread-safe cache for overlay rendering data."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = OverlayData()
        self._stale = True

    @property
    def data(self) -> OverlayData:
        with self._lock:
            return self._data.model_copy()

    @property
    def stale(self) -> bool:
        with self._lock:
            return self._stale

    def update(self, data: OverlayData) -> None:
        with self._lock:
            self._data = data
            self._stale = False

    def mark_stale(self) -> None:
        with self._lock:
            self._stale = True


# ---------------------------------------------------------------------------
# Camera profile engine
# ---------------------------------------------------------------------------

PROFILES_CONFIG_PATH = Path.home() / ".config" / "hapax-compositor" / "profiles.yaml"


def _time_in_range(start_str: str, end_str: str) -> bool:
    """Check if current time is within start-end range (HH:MM format)."""
    now = datetime.now(tz=UTC).astimezone()
    current = now.hour * 60 + now.minute
    sh, sm = (int(x) for x in start_str.split(":"))
    eh, em = (int(x) for x in end_str.split(":"))
    start = sh * 60 + sm
    end = eh * 60 + em
    if start <= end:
        return start <= current < end
    # wraps midnight
    return current >= start or current < end


def _schedule_matches(schedule: str | None) -> bool:
    """Evaluate a schedule string."""
    if not schedule:
        return True
    if "-" in schedule and ":" in schedule:
        parts = schedule.split("-", 1)
        return _time_in_range(parts[0].strip(), parts[1].strip())
    if schedule == "night":
        return _time_in_range("20:00", "06:00")
    if schedule == "day":
        return _time_in_range("06:00", "20:00")
    return True


def _condition_matches(condition: str | None, overlay_data: OverlayData) -> bool:
    """Evaluate a condition string against current overlay/perception state."""
    if not condition:
        return True
    if "=" in condition:
        key, value = condition.split("=", 1)
        key = key.strip()
        value = value.strip()
        actual = getattr(overlay_data, key, None)
        if actual is None:
            return False
        return str(actual) == value
    return True


def evaluate_active_profile(
    profiles: list[CameraProfile], overlay_data: OverlayData
) -> CameraProfile | None:
    """Return the highest-priority matching profile, or None."""
    candidates = []
    for p in profiles:
        if _schedule_matches(p.schedule) and _condition_matches(p.condition, overlay_data):
            candidates.append(p)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.priority, reverse=True)
    return candidates[0]


def apply_camera_profile(profile: CameraProfile) -> None:
    """Apply V4L2 controls from a camera profile via v4l2-ctl."""
    for device_role, controls in profile.cameras.items():
        ctrl_args: list[str] = []
        for field_name, value in controls.model_dump(exclude_none=True).items():
            ctrl_args.append(f"{field_name}={value}")
        if not ctrl_args:
            continue
        ctrl_str = ",".join(ctrl_args)
        # Find device path — we use the role name from the profile
        # The caller should ensure device_role matches a known device
        cmd = ["v4l2-ctl", "-d", device_role, "--set-ctrl", ctrl_str]
        try:
            subprocess.run(cmd, capture_output=True, timeout=5, check=False)
            log.debug("Applied profile controls to %s: %s", device_role, ctrl_str)
        except Exception as exc:
            log.warning("Failed to apply v4l2 controls to %s: %s", device_role, exc)


def load_camera_profiles(config_profiles: list[CameraProfile]) -> list[CameraProfile]:
    """Load camera profiles from config or standalone file."""
    if config_profiles:
        return config_profiles
    if PROFILES_CONFIG_PATH.exists():
        try:
            data = yaml.safe_load(PROFILES_CONFIG_PATH.read_text()) or {}
            profiles_raw = data.get("profiles", [])
            return [CameraProfile(**p) for p in profiles_raw]
        except Exception as exc:
            log.warning("Failed to load camera profiles: %s", exc)
    return []


# ---------------------------------------------------------------------------
# GStreamer pipeline builder
# ---------------------------------------------------------------------------


def _init_gstreamer() -> tuple[Any, Any]:
    """Import and initialize GStreamer. Returns (GLib, Gst) modules."""
    import gi as _gi

    _gi.require_version("Gst", "1.0")
    from gi.repository import GLib as _GLib
    from gi.repository import Gst as _Gst

    _Gst.init(None)
    return _GLib, _Gst


class StudioCompositor:
    """Manages the GStreamer compositing pipeline."""

    def __init__(self, config: CompositorConfig) -> None:
        self.config = config
        self.pipeline: Gst.Pipeline | None = None  # type: ignore[name-defined]
        self.loop: GLib.MainLoop | None = None  # type: ignore[name-defined]
        self._running = False
        self._camera_status: dict[str, str] = {}
        self._camera_status_lock = threading.Lock()
        self._recording_status: dict[str, str] = {}
        self._recording_status_lock = threading.Lock()
        self._element_to_role: dict[str, str] = {}
        self._status_timer_id: int | None = None
        self._overlay_state = OverlayState()
        self._overlay_canvas_size: tuple[int, int] = (config.output_width, config.output_height)
        self._tile_layout: dict[str, TileRect] = {}
        self._state_reader_thread: threading.Thread | None = None
        self._GLib: Any = None
        self._Gst: Any = None
        self._active_profile_name: str = ""
        self._camera_profiles = load_camera_profiles(config.camera_profiles)
        self._status_dir_exists = False

    def _build_pipeline(self) -> Any:
        """Build the full GStreamer pipeline."""
        Gst = self._Gst

        pipeline = Gst.Pipeline.new("studio-compositor")
        layout = compute_tile_layout(
            self.config.cameras, self.config.output_width, self.config.output_height
        )
        self._tile_layout = layout

        compositor = Gst.ElementFactory.make("cudacompositor", "compositor")
        if compositor is None:
            raise RuntimeError(
                "cudacompositor plugin not available -- install gst-plugins-bad with CUDA"
            )
        pipeline.add(compositor)

        fps = self.config.framerate

        for cam in self.config.cameras:
            tile = layout.get(cam.role)
            if tile is None:
                log.warning("No tile for camera %s, skipping", cam.role)
                continue
            self._add_camera_branch(pipeline, compositor, cam, tile, fps)

        # Output chain: compositor -> cudadownload -> BGRA -> cairooverlay -> tee
        download = Gst.ElementFactory.make("cudadownload", "download")
        convert_bgra = Gst.ElementFactory.make("videoconvert", "convert-bgra")
        bgra_caps = Gst.ElementFactory.make("capsfilter", "bgra-caps")
        bgra_caps.set_property(
            "caps",
            Gst.Caps.from_string(
                f"video/x-raw,format=BGRA,width={self.config.output_width},"
                f"height={self.config.output_height},framerate={fps}/1"
            ),
        )

        overlay = Gst.ElementFactory.make("cairooverlay", "overlay")
        overlay.connect("draw", self._on_draw)
        overlay.connect("caps-changed", self._on_overlay_caps_changed)

        # Tee after overlay for v4l2sink + HLS + snapshot branches
        output_tee = Gst.ElementFactory.make("tee", "output-tee")

        elements_pre = [download, convert_bgra, bgra_caps, overlay, output_tee]
        for el in elements_pre:
            if el is None:
                raise RuntimeError("Failed to create GStreamer element")
            pipeline.add(el)

        # Link compositor -> download -> convert_bgra -> bgra_caps -> overlay -> tee
        prev = compositor
        for el in elements_pre:
            if not prev.link(el):
                raise RuntimeError(f"Failed to link {prev.get_name()} -> {el.get_name()}")
            prev = el

        # v4l2sink branch via tee
        queue_v4l2 = Gst.ElementFactory.make("queue", "queue-v4l2")
        queue_v4l2.set_property("leaky", 1)  # upstream
        queue_v4l2.set_property("max-size-buffers", 2)
        convert_out = Gst.ElementFactory.make("videoconvert", "convert-out")
        sink_caps = Gst.ElementFactory.make("capsfilter", "sink-caps")
        sink_caps.set_property(
            "caps",
            Gst.Caps.from_string(
                f"video/x-raw,format=YUY2,width={self.config.output_width},"
                f"height={self.config.output_height},framerate={fps}/1"
            ),
        )
        sink = Gst.ElementFactory.make("v4l2sink", "output")
        sink.set_property("device", self.config.output_device)
        sink.set_property("sync", False)

        for el in [queue_v4l2, convert_out, sink_caps, sink]:
            pipeline.add(el)

        # Link queue_v4l2 -> convert_out -> sink_caps -> sink
        queue_v4l2.link(convert_out)
        convert_out.link(sink_caps)
        sink_caps.link(sink)

        # Explicit tee -> queue pad linking
        tee_pad = output_tee.request_pad(output_tee.get_pad_template("src_%u"), None, None)
        queue_sink_pad = queue_v4l2.get_static_pad("sink")
        tee_pad.link(queue_sink_pad)

        # HLS branch
        if self.config.hls.enabled:
            self._add_hls_branch(pipeline, output_tee, fps)

        # Snapshot branch
        self._add_snapshot_branch(pipeline, output_tee)

        return pipeline

    def _add_snapshot_branch(self, pipeline: Any, tee: Any) -> None:
        """Add composited frame snapshot branch: tee -> queue -> convert -> scale -> rate -> jpeg -> appsink."""
        Gst = self._Gst

        queue = Gst.ElementFactory.make("queue", "queue-snapshot")
        queue.set_property("leaky", 2)  # downstream
        queue.set_property("max-size-buffers", 1)
        convert = Gst.ElementFactory.make("videoconvert", "snapshot-convert")
        scale = Gst.ElementFactory.make("videoscale", "snapshot-scale")
        scale_caps = Gst.ElementFactory.make("capsfilter", "snapshot-scale-caps")
        scale_caps.set_property(
            "caps",
            Gst.Caps.from_string("video/x-raw,width=960,height=540"),
        )
        rate = Gst.ElementFactory.make("videorate", "snapshot-rate")
        rate_caps = Gst.ElementFactory.make("capsfilter", "snapshot-rate-caps")
        rate_caps.set_property(
            "caps",
            Gst.Caps.from_string("video/x-raw,framerate=15/1"),
        )
        encoder = Gst.ElementFactory.make("jpegenc", "snapshot-jpeg")
        encoder.set_property("quality", 75)
        appsink = Gst.ElementFactory.make("appsink", "snapshot-sink")
        appsink.set_property("sync", False)
        appsink.set_property("async", False)
        appsink.set_property("drop", True)
        appsink.set_property("max-buffers", 1)

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

        def _on_new_sample(sink: Any) -> int:
            sample = sink.emit("pull-sample")
            if sample is None:
                return 1  # GST_FLOW_ERROR
            buf = sample.get_buffer()
            ok, mapinfo = buf.map(self._Gst.MapFlags.READ)
            if ok:
                try:
                    tmp = SNAPSHOT_DIR / "snapshot.jpg.tmp"
                    final = SNAPSHOT_DIR / "snapshot.jpg"
                    tmp.write_bytes(bytes(mapinfo.data))
                    tmp.rename(final)
                finally:
                    buf.unmap(mapinfo)
            return 0  # GST_FLOW_OK

        appsink.set_property("emit-signals", True)
        appsink.connect("new-sample", _on_new_sample)

        elements = [queue, convert, scale, scale_caps, rate, rate_caps, encoder, appsink]
        for el in elements:
            pipeline.add(el)

        # Chain link
        queue.link(convert)
        convert.link(scale)
        scale.link(scale_caps)
        scale_caps.link(rate)
        rate.link(rate_caps)
        rate_caps.link(encoder)
        encoder.link(appsink)

        # Explicit tee -> queue pad link
        tee_pad = tee.request_pad(tee.get_pad_template("src_%u"), None, None)
        queue_sink = queue.get_static_pad("sink")
        tee_pad.link(queue_sink)

    def _add_camera_snapshot_branch(
        self, pipeline: Any, camera_tee: Any, cam: CameraSpec
    ) -> None:
        """Add per-camera snapshot branch writing JPEG to /dev/shm."""
        Gst = self._Gst
        role = cam.role.replace("-", "_")

        queue = Gst.ElementFactory.make("queue", f"queue-camsnap-{role}")
        queue.set_property("leaky", 2)  # downstream
        queue.set_property("max-size-buffers", 2)
        convert = Gst.ElementFactory.make("videoconvert", f"camsnap-convert-{role}")
        rate = Gst.ElementFactory.make("videorate", f"camsnap-rate-{role}")
        rate_caps = Gst.ElementFactory.make("capsfilter", f"camsnap-ratecaps-{role}")
        rate_caps.set_property(
            "caps",
            Gst.Caps.from_string("video/x-raw,framerate=5/1"),
        )
        scale = Gst.ElementFactory.make("videoscale", f"camsnap-scale-{role}")
        # Maintain aspect ratio, target 640 wide
        aspect_h = int(640 * cam.height / cam.width)
        scale_caps = Gst.ElementFactory.make("capsfilter", f"camsnap-scalecaps-{role}")
        scale_caps.set_property(
            "caps",
            Gst.Caps.from_string(f"video/x-raw,width=640,height={aspect_h}"),
        )
        encoder = Gst.ElementFactory.make("jpegenc", f"camsnap-jpeg-{role}")
        encoder.set_property("quality", 70)
        appsink = Gst.ElementFactory.make("appsink", f"camsnap-sink-{role}")
        appsink.set_property("sync", False)
        appsink.set_property("async", False)
        appsink.set_property("drop", True)
        appsink.set_property("max-buffers", 1)

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        snap_role = cam.role  # capture for closure

        def _on_new_sample(sink: Any) -> int:
            sample = sink.emit("pull-sample")
            if sample is None:
                return 1
            buf = sample.get_buffer()
            ok, mapinfo = buf.map(self._Gst.MapFlags.READ)
            if ok:
                try:
                    tmp = SNAPSHOT_DIR / f"{snap_role}.jpg.tmp"
                    final = SNAPSHOT_DIR / f"{snap_role}.jpg"
                    tmp.write_bytes(bytes(mapinfo.data))
                    tmp.rename(final)
                finally:
                    buf.unmap(mapinfo)
            return 0

        appsink.set_property("emit-signals", True)
        appsink.connect("new-sample", _on_new_sample)

        elements = [queue, convert, rate, rate_caps, scale, scale_caps, encoder, appsink]
        for el in elements:
            pipeline.add(el)

        queue.link(convert)
        convert.link(rate)
        rate.link(rate_caps)
        rate_caps.link(scale)
        scale.link(scale_caps)
        scale_caps.link(encoder)
        encoder.link(appsink)

        # Explicit tee -> queue pad link
        tee_pad = camera_tee.request_pad(
            camera_tee.get_pad_template("src_%u"), None, None
        )
        queue_sink = queue.get_static_pad("sink")
        tee_pad.link(queue_sink)

    def _add_camera_branch(
        self, pipeline: Any, compositor: Any, cam: CameraSpec, tile: TileRect, fps: int
    ) -> None:
        """Add a single camera source branch to the pipeline."""
        Gst = self._Gst
        role = cam.role.replace("-", "_")
        self._element_to_role[f"src_{role}"] = cam.role

        src = Gst.ElementFactory.make("v4l2src", f"src_{role}")
        src.set_property("device", cam.device)

        if not Path(cam.device).exists():
            log.warning("Camera %s device %s not found, skipping", cam.role, cam.device)
            with self._camera_status_lock:
                self._camera_status[cam.role] = "offline"
            return

        if cam.input_format == "mjpeg":
            src_caps = Gst.ElementFactory.make("capsfilter", f"srccaps_{role}")
            src_caps.set_property(
                "caps",
                Gst.Caps.from_string(
                    f"image/jpeg,width={cam.width},height={cam.height},framerate={fps}/1"
                ),
            )
            decoder = Gst.ElementFactory.make("jpegdec", f"dec_{role}")
            convert = Gst.ElementFactory.make("videoconvert", f"convert_{role}")
            for el in [src, src_caps, decoder, convert]:
                pipeline.add(el)
            src.link(src_caps)
            src_caps.link(decoder)
            decoder.link(convert)
            last = convert
        else:
            src_caps = Gst.ElementFactory.make("capsfilter", f"srccaps_{role}")
            pix_fmt = cam.pixel_format or "GRAY8"
            src_caps.set_property(
                "caps",
                Gst.Caps.from_string(
                    f"video/x-raw,format={pix_fmt},width={cam.width},height={cam.height},"
                    f"framerate={fps}/1"
                ),
            )
            convert = Gst.ElementFactory.make("videoconvert", f"rawconv_{role}")
            for el in [src, src_caps, convert]:
                pipeline.add(el)
            src.link(src_caps)
            src_caps.link(convert)
            last = convert

        # Insert tee after decode/convert, before CUDA upload
        camera_tee = Gst.ElementFactory.make("tee", f"tee_{role}")
        pipeline.add(camera_tee)
        last.link(camera_tee)

        # Compositor branch: tee -> queue -> cudaupload -> cudaconvert -> cudascale -> compositor
        queue_comp = Gst.ElementFactory.make("queue", f"queue-comp-{role}")
        queue_comp.set_property("leaky", 1)  # upstream
        queue_comp.set_property("max-size-buffers", 2)
        upload = Gst.ElementFactory.make("cudaupload", f"upload_{role}")
        cuda_convert = Gst.ElementFactory.make("cudaconvert", f"cudaconv_{role}")
        scale = Gst.ElementFactory.make("cudascale", f"scale_{role}")
        scale_caps = Gst.ElementFactory.make("capsfilter", f"scalecaps_{role}")
        scale_caps.set_property(
            "caps",
            Gst.Caps.from_string(
                f"video/x-raw(memory:CUDAMemory),width={tile.w},height={tile.h}"
            ),
        )

        for el in [queue_comp, upload, cuda_convert, scale, scale_caps]:
            pipeline.add(el)

        queue_comp.link(upload)
        upload.link(cuda_convert)
        cuda_convert.link(scale)
        scale.link(scale_caps)

        # Explicit tee -> queue pad link
        tee_pad = camera_tee.request_pad(
            camera_tee.get_pad_template("src_%u"), None, None
        )
        queue_sink = queue_comp.get_static_pad("sink")
        tee_pad.link(queue_sink)

        # Link to compositor
        pad_template = compositor.get_pad_template("sink_%u")
        pad = compositor.request_pad(pad_template, None, None)
        if pad is None:
            raise RuntimeError(f"Failed to get compositor sink pad for {cam.role}")

        pad.set_property("xpos", tile.x)
        pad.set_property("ypos", tile.y)
        pad.set_property("width", tile.w)
        pad.set_property("height", tile.h)

        src_pad = scale_caps.get_static_pad("src")
        if src_pad.link(pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Failed to link {cam.role} to compositor")

        # Recording branch
        if self.config.recording.enabled:
            self._add_recording_branch(pipeline, camera_tee, cam, fps)

        # Per-camera snapshot branch
        self._add_camera_snapshot_branch(pipeline, camera_tee, cam)

    def _add_recording_branch(
        self, pipeline: Any, camera_tee: Any, cam: CameraSpec, fps: int
    ) -> None:
        """Add per-camera recording branch: tee -> queue -> convert -> nvh264enc -> splitmuxsink."""
        Gst = self._Gst
        role = cam.role.replace("-", "_")
        rec_cfg = self.config.recording

        queue = Gst.ElementFactory.make("queue", f"queue-rec-{role}")
        queue.set_property("leaky", 2)  # downstream
        queue.set_property("max-size-buffers", 30)
        queue.set_property("max-size-time", 5 * 1_000_000_000)  # 5 seconds in ns
        convert = Gst.ElementFactory.make("videoconvert", f"rec-convert-{role}")
        nv12_caps = Gst.ElementFactory.make("capsfilter", f"rec-nv12caps-{role}")
        nv12_caps.set_property(
            "caps",
            Gst.Caps.from_string("video/x-raw,format=NV12"),
        )
        encoder = Gst.ElementFactory.make("nvh264enc", f"rec-enc-{role}")
        encoder.set_property("preset", 2)  # hp
        encoder.set_property("rc-mode", 3)  # constqp
        encoder.set_property("qp-const", rec_cfg.qp)
        parser = Gst.ElementFactory.make("h264parse", f"rec-parse-{role}")

        mux_sink = Gst.ElementFactory.make("splitmuxsink", f"rec-mux-{role}")
        mux_sink.set_property("max-size-time", rec_cfg.segment_seconds * 1_000_000_000)
        mux_sink.set_property("muxer", Gst.ElementFactory.make("matroskamux", None))
        mux_sink.set_property("async-handling", True)

        # Create output directory
        rec_dir = Path(rec_cfg.output_dir) / cam.role
        rec_dir.mkdir(parents=True, exist_ok=True)

        cam_role = cam.role  # capture for closure

        def _format_location(splitmux: Any, fragment_id: int) -> str:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            return str(rec_dir / f"{cam_role}_{ts}_{fragment_id:04d}.mkv")

        mux_sink.connect("format-location-full", lambda s, fid, _sample: _format_location(s, fid))

        elements = [queue, convert, nv12_caps, encoder, parser, mux_sink]
        for el in elements:
            pipeline.add(el)

        queue.link(convert)
        convert.link(nv12_caps)
        nv12_caps.link(encoder)
        encoder.link(parser)
        parser.link(mux_sink)

        # Explicit tee -> queue pad link
        tee_pad = camera_tee.request_pad(
            camera_tee.get_pad_template("src_%u"), None, None
        )
        queue_sink = queue.get_static_pad("sink")
        tee_pad.link(queue_sink)

        with self._recording_status_lock:
            self._recording_status[cam.role] = "active"

    def _add_hls_branch(self, pipeline: Any, tee: Any, fps: int) -> None:
        """Add HLS output branch: tee -> queue -> convert -> nvh264enc -> h264parse -> hlssink2."""
        Gst = self._Gst
        hls_cfg = self.config.hls

        queue = Gst.ElementFactory.make("queue", "queue-hls")
        queue.set_property("leaky", 2)  # downstream
        queue.set_property("max-size-buffers", 60)
        queue.set_property("max-size-time", 3 * 1_000_000_000)  # 3 seconds in ns
        convert = Gst.ElementFactory.make("videoconvert", "hls-convert")
        nv12_caps = Gst.ElementFactory.make("capsfilter", "hls-nv12caps")
        nv12_caps.set_property(
            "caps",
            Gst.Caps.from_string("video/x-raw,format=NV12"),
        )
        encoder = Gst.ElementFactory.make("nvh264enc", "hls-enc")
        encoder.set_property("preset", 2)  # hp
        encoder.set_property("rc-mode", 3)  # constqp
        encoder.set_property("qp-const", 26)
        encoder.set_property("gop-size", fps * hls_cfg.target_duration)
        parser = Gst.ElementFactory.make("h264parse", "hls-parse")

        hls_dir = Path(hls_cfg.output_dir)
        hls_dir.mkdir(parents=True, exist_ok=True)

        hls_sink = Gst.ElementFactory.make("hlssink2", "hls-sink")
        hls_sink.set_property("target-duration", hls_cfg.target_duration)
        hls_sink.set_property("playlist-length", hls_cfg.playlist_length)
        hls_sink.set_property("max-files", hls_cfg.max_files)
        hls_sink.set_property("location", str(hls_dir / "segment%05d.ts"))
        hls_sink.set_property("playlist-location", str(hls_dir / "playlist.m3u8"))
        hls_sink.set_property("async-handling", True)

        elements = [queue, convert, nv12_caps, encoder, parser, hls_sink]
        for el in elements:
            pipeline.add(el)

        queue.link(convert)
        convert.link(nv12_caps)
        nv12_caps.link(encoder)
        encoder.link(parser)
        parser.link(hls_sink)

        # Explicit tee -> queue pad link
        tee_pad = tee.request_pad(tee.get_pad_template("src_%u"), None, None)
        queue_sink = queue.get_static_pad("sink")
        tee_pad.link(queue_sink)

    # -- Error handling ---------------------------------------------------

    def _resolve_camera_role(self, element: Any) -> str | None:
        """Walk up from an element to find which camera branch it belongs to."""
        if element is None:
            return None
        name = element.get_name()
        if name in self._element_to_role:
            return self._element_to_role[name]
        for _elem_prefix, role in self._element_to_role.items():
            role_suffix = role.replace("-", "_")
            if role_suffix in name:
                return role
        return None

    def _mark_camera_offline(self, role: str) -> None:
        """Mark a camera as offline and update status file."""
        with self._camera_status_lock:
            prev = self._camera_status.get(role)
            if prev == "offline":
                return
            self._camera_status[role] = "offline"
        log.warning("Camera %s marked offline", role)
        self._write_status("running")

    def _on_bus_message(self, bus: Any, message: Any) -> bool:
        """Handle pipeline bus messages."""
        Gst = self._Gst
        t = message.type
        if t == Gst.MessageType.EOS:
            log.info("Pipeline EOS")
            self.stop()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            src_name = message.src.get_name() if message.src else "unknown"
            role = self._resolve_camera_role(message.src)
            if role is not None:
                log.error("Camera %s error (element %s): %s", role, src_name, err.message)
                self._mark_camera_offline(role)
            else:
                log.error("Pipeline error from %s: %s (debug: %s)", src_name, err.message, debug)
                self.stop()
        elif t == Gst.MessageType.WARNING:
            err, debug = message.parse_warning()
            log.warning("Pipeline warning: %s (debug: %s)", err.message, debug)
        elif t == Gst.MessageType.STATE_CHANGED:
            if message.src == self.pipeline:
                old, new, _ = message.parse_state_changed()
                log.debug("Pipeline state: %s -> %s", old.value_nick, new.value_nick)
        return True

    # -- Status -----------------------------------------------------------

    def _write_status(self, state: str) -> None:
        """Write compositor status to cache file (atomic write-then-rename)."""
        if not self._status_dir_exists:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._status_dir_exists = True
        with self._camera_status_lock:
            cameras = dict(self._camera_status)
        with self._recording_status_lock:
            recording_cameras = dict(self._recording_status)
        active_count = sum(1 for s in cameras.values() if s == "active")
        hls_url = ""
        if self.config.hls.enabled:
            hls_url = str(Path(self.config.hls.output_dir) / "playlist.m3u8")
        status = {
            "state": state,
            "pid": os.getpid(),
            "cameras": cameras,
            "active_cameras": active_count,
            "total_cameras": len(cameras),
            "output_device": self.config.output_device,
            "resolution": f"{self.config.output_width}x{self.config.output_height}",
            "recording_enabled": self.config.recording.enabled,
            "recording_cameras": recording_cameras,
            "hls_enabled": self.config.hls.enabled,
            "hls_url": hls_url,
            "camera_profile": self._active_profile_name,
            "timestamp": time.time(),
        }
        tmp = STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(status, indent=2))
        tmp.rename(STATUS_FILE)

    def _status_tick(self) -> bool:
        """GLib timeout callback: periodically refresh the status file."""
        if self._running:
            self._write_status("running")
        return self._running

    # -- Overlay ----------------------------------------------------------

    def _on_overlay_caps_changed(self, overlay: Any, caps: Any) -> None:
        """Called when cairooverlay negotiates caps -- cache canvas size."""
        s = caps.get_structure(0)
        w = s.get_int("width")
        h = s.get_int("height")
        if w[0] and h[0]:
            self._overlay_canvas_size = (w[1], h[1])
            log.debug("Overlay canvas: %dx%d", w[1], h[1])

    def _on_draw(self, overlay: Any, cr: Any, timestamp: int, duration: int) -> None:
        """Cairo draw callback -- renders text overlays on the composited frame."""
        if not self.config.overlay_enabled:
            return

        import cairo  # type: ignore[import-untyped]

        canvas_w, canvas_h = self._overlay_canvas_size
        state = self._overlay_state.data
        cr.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        pad = 4

        for role, tile in self._tile_layout.items():
            cr.set_font_size(14)
            text = role
            extents = cr.text_extents(text)
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.6)
            cr.rectangle(
                tile.x + pad, tile.y + pad, extents.width + pad * 2, extents.height + pad * 2
            )
            cr.fill()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.9)
            cr.move_to(tile.x + pad * 2, tile.y + pad + extents.height + pad)
            cr.show_text(text)

            has_consent = any("consent" in c for c in state.active_contracts)
            badge_color = (0.2, 0.8, 0.2, 0.9) if has_consent else (0.8, 0.2, 0.2, 0.9)
            badge_text = "REC" if has_consent else "NO-REC"
            cr.set_font_size(12)
            be = cr.text_extents(badge_text)
            bx = tile.x + tile.w - be.width - pad * 3
            by = tile.y + pad
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.6)
            cr.rectangle(bx, by, be.width + pad * 2, be.height + pad * 2)
            cr.fill()
            cr.set_source_rgba(*badge_color)
            cr.move_to(bx + pad, by + be.height + pad)
            cr.show_text(badge_text)

            with self._camera_status_lock:
                cam_status = self._camera_status.get(role, "unknown")
            if cam_status == "offline":
                cr.set_font_size(24)
                cr.set_source_rgba(1.0, 0.3, 0.3, 0.8)
                ot = "OFFLINE"
                oe = cr.text_extents(ot)
                cr.move_to(tile.x + (tile.w - oe.width) / 2, tile.y + (tile.h + oe.height) / 2)
                cr.show_text(ot)

        if state.flow_state:
            cr.set_font_size(20)
            flow_text = f"FLOW: {state.flow_state.upper()} ({state.flow_score:.0%})"
            fe = cr.text_extents(flow_text)
            fx = (canvas_w - fe.width) / 2
            fy = 8
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.6)
            cr.rectangle(fx - 6, fy, fe.width + 12, fe.height + 12)
            cr.fill()
            if state.flow_state == "active":
                cr.set_source_rgba(0.2, 1.0, 0.4, 0.95)
            elif state.flow_state == "warming":
                cr.set_source_rgba(1.0, 0.9, 0.2, 0.95)
            else:
                cr.set_source_rgba(0.8, 0.8, 0.8, 0.95)
            cr.move_to(fx, fy + fe.height + 4)
            cr.show_text(flow_text)

        if state.production_activity or state.music_genre:
            cr.set_font_size(14)
            tags = " | ".join(filter(None, [state.production_activity, state.music_genre]))
            te = cr.text_extents(tags)
            tx = 8
            ty = canvas_h - 28
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.5)
            cr.rectangle(tx - 4, ty - te.height - 4, te.width + 8, te.height + 8)
            cr.fill()
            cr.set_source_rgba(0.9, 0.9, 0.9, 0.85)
            cr.move_to(tx, ty)
            cr.show_text(tags)

        if state.audio_energy_rms > 0:
            bar_h = 4
            bar_w = int(canvas_w * min(state.audio_energy_rms * 10, 1.0))
            cr.set_source_rgba(0.3, 0.8, 0.3, 0.7)
            cr.rectangle(0, canvas_h - bar_h, bar_w, bar_h)
            cr.fill()

    # -- State reader -----------------------------------------------------

    def _evaluate_camera_profile(self) -> None:
        """Evaluate and apply camera profiles if changed."""
        if not self._camera_profiles:
            return
        overlay_data = self._overlay_state.data
        profile = evaluate_active_profile(self._camera_profiles, overlay_data)
        if profile is None:
            if self._active_profile_name:
                log.info("No camera profile matches, clearing active profile")
                self._active_profile_name = ""
            return
        if profile.name != self._active_profile_name:
            log.info("Switching camera profile: %s -> %s", self._active_profile_name, profile.name)
            self._active_profile_name = profile.name
            apply_camera_profile(profile)

    def _state_reader_loop(self) -> None:
        """Daemon thread: read perception-state.json every 1s."""
        profile_check_counter = 0
        while self._running:
            try:
                if PERCEPTION_STATE_PATH.exists():
                    raw = PERCEPTION_STATE_PATH.read_text()
                    data = OverlayData(**json.loads(raw))
                    if time.time() - data.timestamp > 10:
                        self._overlay_state.mark_stale()
                    else:
                        self._overlay_state.update(data)
                else:
                    self._overlay_state.mark_stale()
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                log.debug("Failed to read perception state: %s", exc)
                self._overlay_state.mark_stale()

            # Evaluate camera profiles every 10 iterations (~10s)
            profile_check_counter += 1
            if profile_check_counter >= 10:
                profile_check_counter = 0
                try:
                    self._evaluate_camera_profile()
                except Exception as exc:
                    log.debug("Failed to evaluate camera profile: %s", exc)

            time.sleep(1.0)

    # -- Lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Build and start the pipeline."""
        self._GLib, self._Gst = _init_gstreamer()
        GLib = self._GLib
        Gst = self._Gst

        log.info("Building compositor pipeline with %d cameras", len(self.config.cameras))

        with self._camera_status_lock:
            for cam in self.config.cameras:
                self._camera_status[cam.role] = "starting"

        self.pipeline = self._build_pipeline()

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

        self._write_status("starting")

        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            self._write_status("error")
            raise RuntimeError("Failed to start pipeline")

        log.info("Pipeline started -- output on %s", self.config.output_device)

        with self._camera_status_lock:
            for role, status in self._camera_status.items():
                if status == "starting":
                    self._camera_status[role] = "active"

        self._running = True
        self._write_status("running")

        self.loop = GLib.MainLoop()

        interval_ms = int(self.config.status_interval_s * 1000)
        self._status_timer_id = GLib.timeout_add(interval_ms, self._status_tick)

        if self.config.overlay_enabled:
            self._state_reader_thread = threading.Thread(
                target=self._state_reader_loop, daemon=True, name="state-reader"
            )
            self._state_reader_thread.start()

        def _shutdown(signum: int, frame: Any) -> None:
            log.info("Signal %d received, shutting down", signum)
            self.stop()

        signal.signal(signal.SIGINT, _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        try:
            self.loop.run()
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        """Stop the pipeline cleanly."""
        if not self._running:
            return
        self._running = False
        log.info("Stopping compositor pipeline")

        GLib = self._GLib
        Gst = self._Gst

        if self._status_timer_id is not None and GLib is not None:
            GLib.source_remove(self._status_timer_id)
            self._status_timer_id = None

        if self.pipeline and Gst is not None:
            self.pipeline.set_state(Gst.State.NULL)

        if self.loop and self.loop.is_running():
            self.loop.quit()

        self._write_status("stopped")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Studio Compositor -- tiled camera output")
    parser.add_argument("--config", type=Path, help="Config YAML path")
    parser.add_argument(
        "--default-config", action="store_true", help="Print default config and exit"
    )
    parser.add_argument("--no-overlay", action="store_true", help="Disable overlay rendering")
    parser.add_argument("--record-dir", type=str, help="Override recording output directory")
    parser.add_argument("--no-record", action="store_true", help="Disable per-camera recording")
    parser.add_argument("--no-hls", action="store_true", help="Disable HLS output")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    from shared.log_setup import configure_logging

    configure_logging(agent="studio-compositor", level="DEBUG" if args.verbose else None)

    if args.default_config:
        cfg = _default_config()
        print(yaml.dump(json.loads(cfg.model_dump_json()), default_flow_style=False))
        sys.exit(0)

    cfg = load_config(path=args.config)
    if args.no_overlay:
        cfg.overlay_enabled = False
    if args.no_record:
        cfg.recording.enabled = False
    if args.record_dir:
        cfg.recording.output_dir = args.record_dir
    if args.no_hls:
        cfg.hls.enabled = False

    log.info(
        "Config: %d cameras, output=%s, %dx%d@%dfps, overlay=%s, recording=%s, hls=%s",
        len(cfg.cameras),
        cfg.output_device,
        cfg.output_width,
        cfg.output_height,
        cfg.framerate,
        cfg.overlay_enabled,
        cfg.recording.enabled,
        cfg.hls.enabled,
    )

    compositor = StudioCompositor(cfg)
    compositor.start()


if __name__ == "__main__":
    main()
