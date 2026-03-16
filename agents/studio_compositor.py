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
CONSENT_AUDIT_PATH = CACHE_DIR / "consent-audit.jsonl"
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
    x_off = 0
    y_off = 0
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
VISUAL_LAYER_STATE_PATH = Path("/dev/shm/hapax-compositor/visual-layer-state.json")


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
    persistence_allowed: bool = True
    guest_present: bool = False
    consent_phase: str = "no_guest"
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
        # Consent enforcement — valve elements gate recording/HLS persistence
        self._recording_valves: dict[str, Any] = {}
        self._recording_muxes: dict[str, Any] = {}
        self._hls_valve: Any = None
        self._consent_recording_allowed: bool = True
        # Overlay surface cache -- avoids full Cairo redraw when state unchanged
        self._overlay_cache_surface: Any = None
        self._overlay_cache_timestamp: float = 0.0
        self._overlay_cache_cam_hash: str = ""
        # Visual layer state (read from aggregator JSON)
        self._vl_state: dict | None = None
        self._vl_state_lock = threading.Lock()
        self._vl_state_timestamp: float = 0.0
        # Visual layer zone opacity interpolation (current values, lerped per frame)
        self._vl_zone_opacities: dict[str, float] = {}
        self._vl_cache_surface: Any = None
        self._vl_cache_timestamp: float = 0.0

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

        # GPU effects branch
        self._add_effects_branch(pipeline, output_tee)

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
            Gst.Caps.from_string("video/x-raw,width=1920,height=1080"),
        )
        rate = Gst.ElementFactory.make("videorate", "snapshot-rate")
        rate_caps = Gst.ElementFactory.make("capsfilter", "snapshot-rate-caps")
        rate_caps.set_property(
            "caps",
            Gst.Caps.from_string("video/x-raw,framerate=15/1"),
        )
        encoder = Gst.ElementFactory.make("jpegenc", "snapshot-jpeg")
        encoder.set_property("quality", 85)
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
                    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
                    try:
                        os.write(fd, mapinfo.data)
                    finally:
                        os.close(fd)
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

    def _add_effects_branch(self, pipeline: Any, tee: Any) -> None:
        """Add GPU-accelerated visual effects branch.

        Pipeline: tee → queue → videoconvert(RGBA) → glupload → glcolorconvert →
                  glshader(color_grade) → [gleffects] → glshader(post_process) →
                  glcolorconvert → gldownload → videoconvert → videoscale → videorate →
                  jpegenc → appsink (fx snapshot to /dev/shm)
        """
        Gst = self._Gst

        from agents.studio_effects import PRESETS, load_shader

        # Start with a default preset
        initial_preset = PRESETS.get("clean", list(PRESETS.values())[0])

        # --- Build the chain ---
        queue = Gst.ElementFactory.make("queue", "queue-fx")
        queue.set_property("leaky", 2)
        queue.set_property("max-size-buffers", 2)

        # Stutter element (freeze/replay) — before GL upload
        from agents.studio_stutter import StutterElement

        stutter_el = StutterElement()
        stutter_el.set_property("check-interval", 999)  # disabled by default
        stutter_el.set_property("freeze-chance", 0.0)

        # Convert to RGBA for GL upload
        convert_rgba = Gst.ElementFactory.make("videoconvert", "fx-convert-rgba")
        rgba_caps = Gst.ElementFactory.make("capsfilter", "fx-rgba-caps")
        rgba_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,format=RGBA"))

        # GL upload + color convert
        glupload = Gst.ElementFactory.make("glupload", "fx-glupload")
        glcolorconvert_in = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-in")

        # Color grade shader
        color_grade = Gst.ElementFactory.make("glshader", "fx-color-grade")
        color_frag = load_shader("color_grade.frag")
        if color_frag:
            color_grade.set_property("fragment", color_frag)
            cg = initial_preset.color_grade
            uniforms = Gst.Structure.from_string(
                f"uniforms, u_saturation=(float){cg.saturation}, "
                f"u_brightness=(float){cg.brightness}, "
                f"u_contrast=(float){cg.contrast}, "
                f"u_sepia=(float){cg.sepia}, "
                f"u_hue_rotate=(float){cg.hue_rotate}"
            )
            color_grade.set_property("uniforms", uniforms[0])

        # VHS shader (RGB split, head-switch, noise band, scanlines)
        vhs_shader = Gst.ElementFactory.make("glshader", "fx-vhs")
        vhs_frag = load_shader("vhs.frag")
        if vhs_frag:
            vhs_shader.set_property("fragment", vhs_frag)
            vhs_uniforms = Gst.Structure.from_string(
                "uniforms, u_time=(float)0.0, u_chroma_shift=(float)0.0, "
                "u_head_switch_y=(float)0.92, u_noise_band_y=(float)0.0, "
                "u_width=(float)1920.0, u_height=(float)1080.0"
            )
            vhs_shader.set_property("uniforms", vhs_uniforms[0])

        # Slice warp shader (pan, rotate, zoom, horizontal slice displacement)
        warp_shader = Gst.ElementFactory.make("glshader", "fx-warp")
        warp_frag = load_shader("slice_warp.frag")
        if warp_frag:
            warp_shader.set_property("fragment", warp_frag)
            warp_uniforms = Gst.Structure.from_string(
                "uniforms, u_time=(float)0.0, u_slice_count=(float)0.0, "
                "u_slice_amplitude=(float)0.0, u_pan_x=(float)0.0, u_pan_y=(float)0.0, "
                "u_rotation=(float)0.0, u_zoom=(float)1.0, u_zoom_breath=(float)0.0, "
                "u_width=(float)1920.0, u_height=(float)1080.0"
            )
            warp_shader.set_property("uniforms", warp_uniforms[0])

        # GL effects (glow for Neon, sobel for Ghost)
        glow_effect = Gst.ElementFactory.make("gleffects", "fx-glow")
        glow_effect.set_property("effect", 0)  # identity (passthrough)

        # Post-process shader (vignette, scanlines, band displacement)
        post_proc = Gst.ElementFactory.make("glshader", "fx-post-process")
        post_frag = load_shader("post_process.frag")
        if post_frag:
            post_proc.set_property("fragment", post_frag)
            pp = initial_preset.post_process
            pp_uniforms = Gst.Structure.from_string(
                f"uniforms, u_vignette_strength=(float){pp.vignette_strength}, "
                f"u_scanline_alpha=(float){pp.scanline_alpha}, "
                f"u_time=(float)0.0, "
                f"u_band_active=(float)0.0, "
                f"u_band_y=(float)0.0, u_band_height=(float)0.0, u_band_shift=(float)0.0, "
                f"u_syrup_active=(float){1.0 if pp.syrup_gradient else 0.0}, "
                f"u_syrup_color_r=(float){pp.syrup_color[0]}, "
                f"u_syrup_color_g=(float){pp.syrup_color[1]}, "
                f"u_syrup_color_b=(float){pp.syrup_color[2]}"
            )
            post_proc.set_property("uniforms", pp_uniforms[0])

        # GL download back to CPU
        glcolorconvert_out = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-out")
        gldownload = Gst.ElementFactory.make("gldownload", "fx-gldownload")

        # Scale + rate + JPEG encode for snapshot output
        fx_convert = Gst.ElementFactory.make("videoconvert", "fx-out-convert")
        fx_scale = Gst.ElementFactory.make("videoscale", "fx-scale")
        fx_scale_caps = Gst.ElementFactory.make("capsfilter", "fx-scale-caps")
        fx_scale_caps.set_property(
            "caps", Gst.Caps.from_string("video/x-raw,width=1920,height=1080")
        )

        fx_rate = Gst.ElementFactory.make("videorate", "fx-rate")
        fx_rate_caps = Gst.ElementFactory.make("capsfilter", "fx-rate-caps")
        fx_rate_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,framerate=15/1"))

        fx_jpeg = Gst.ElementFactory.make("jpegenc", "fx-jpeg")
        fx_jpeg.set_property("quality", 80)

        fx_sink = Gst.ElementFactory.make("appsink", "fx-snapshot-sink")
        fx_sink.set_property("sync", False)
        fx_sink.set_property("async", False)
        fx_sink.set_property("drop", True)
        fx_sink.set_property("max-buffers", 1)

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

        def _on_fx_sample(sink: Any) -> int:
            sample = sink.emit("pull-sample")
            if sample is None:
                return 1
            buf = sample.get_buffer()
            ok, mapinfo = buf.map(self._Gst.MapFlags.READ)
            if ok:
                try:
                    tmp = SNAPSHOT_DIR / "fx-snapshot.jpg.tmp"
                    final = SNAPSHOT_DIR / "fx-snapshot.jpg"
                    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
                    try:
                        os.write(fd, mapinfo.data)
                    finally:
                        os.close(fd)
                    tmp.rename(final)
                except OSError:
                    pass
                finally:
                    buf.unmap(mapinfo)
            return 0

        fx_sink.set_property("emit-signals", True)
        fx_sink.connect("new-sample", _on_fx_sample)

        # Add all elements to pipeline
        elements = [
            queue,
            stutter_el,
            convert_rgba,
            rgba_caps,
            glupload,
            glcolorconvert_in,
            color_grade,
            vhs_shader,
            warp_shader,
            glow_effect,
            post_proc,
            glcolorconvert_out,
            gldownload,
            fx_convert,
            fx_scale,
            fx_scale_caps,
            fx_rate,
            fx_rate_caps,
            fx_jpeg,
            fx_sink,
        ]
        for el in elements:
            if el is None:
                log.error("Failed to create FX pipeline element")
                return
            pipeline.add(el)

        # Link chain
        convert_rgba.link(rgba_caps)
        rgba_caps.link(glupload)
        glupload.link(glcolorconvert_in)
        glcolorconvert_in.link(color_grade)
        color_grade.link(vhs_shader)
        vhs_shader.link(warp_shader)
        warp_shader.link(glow_effect)
        # Temporal feedback via custom Rust GstGLFilter plugin (FBO ping-pong)
        #
        # Single element replaces the entire multi-tap trail system.
        # Maintains a persistent accumulation texture — each frame blends
        # with the decayed previous output, creating true compounding trails.
        temporal_fx = Gst.ElementFactory.make("temporalfx", "fx-temporal")
        if temporal_fx is None:
            log.error("temporalfx plugin not found! Install libgsttemporalfx.so")
            # Fallback: direct passthrough
            glow_effect.link(post_proc)
        else:
            pipeline.add(temporal_fx)
            # Default: no feedback (clean preset)
            temporal_fx.set_property("feedback-amount", 0.0)
            glow_effect.link(temporal_fx)
            temporal_fx.link(post_proc)
        post_proc.link(glcolorconvert_out)
        glcolorconvert_out.link(gldownload)
        gldownload.link(fx_convert)
        fx_convert.link(fx_scale)
        fx_scale.link(fx_scale_caps)
        fx_scale_caps.link(fx_rate)
        fx_rate.link(fx_rate_caps)
        fx_rate_caps.link(fx_jpeg)
        fx_jpeg.link(fx_sink)

        # Link queue to convert (first in chain after queue)
        queue.link(stutter_el)
        stutter_el.link(convert_rgba)

        # Explicit tee → queue pad link
        tee_pad = tee.request_pad(tee.get_pad_template("src_%u"), None, None)
        queue_sink = queue.get_static_pad("sink")
        tee_pad.link(queue_sink)

        # Store references for runtime preset switching
        self._fx_temporal = temporal_fx
        self._fx_stutter = stutter_el
        self._fx_color_grade = color_grade
        self._fx_vhs_shader = vhs_shader
        self._fx_warp_shader = warp_shader
        self._fx_glow_effect = glow_effect
        self._fx_post_proc = post_proc
        self._fx_active_preset = initial_preset.name
        self._fx_tick = 0

        log.info("FX branch: glshader pipeline → /dev/shm/hapax-compositor/fx-snapshot.jpg")

    def _switch_fx_preset(self, preset_name: str) -> None:
        """Switch the active visual effect preset at runtime."""
        from agents.studio_effects import PRESETS

        preset = PRESETS.get(preset_name)
        if preset is None:
            log.warning("Unknown FX preset: %s", preset_name)
            return
        if preset_name == self._fx_active_preset:
            return

        Gst = self._Gst

        # Update color grade uniforms
        cg = preset.color_grade
        uniforms = Gst.Structure.from_string(
            f"uniforms, u_saturation=(float){cg.saturation}, "
            f"u_brightness=(float){cg.brightness}, "
            f"u_contrast=(float){cg.contrast}, "
            f"u_sepia=(float){cg.sepia}, "
            f"u_hue_rotate=(float){cg.hue_rotate}"
        )
        self._fx_color_grade.set_property("uniforms", uniforms[0])

        # Update VHS shader — active only for VHS preset
        chroma_shift = 4.0 if preset.use_vhs_shader else 0.0
        vhs_uniforms = Gst.Structure.from_string(
            f"uniforms, u_time=(float)0.0, u_chroma_shift=(float){chroma_shift}, "
            f"u_head_switch_y=(float)0.92, u_noise_band_y=(float)0.0, "
            f"u_width=(float)1920.0, u_height=(float)1080.0"
        )
        self._fx_vhs_shader.set_property("uniforms", vhs_uniforms[0])

        # Update warp shader
        warp = preset.warp
        if warp:
            warp_uniforms = Gst.Structure.from_string(
                f"uniforms, u_time=(float)0.0, "
                f"u_slice_count=(float){warp.slice_count}, "
                f"u_slice_amplitude=(float){warp.slice_amplitude}, "
                f"u_pan_x=(float){warp.pan_x}, u_pan_y=(float){warp.pan_y}, "
                f"u_rotation=(float){warp.rotation}, u_zoom=(float){warp.zoom}, "
                f"u_zoom_breath=(float){warp.zoom_breath}, "
                f"u_width=(float)1920.0, u_height=(float)1080.0"
            )
        else:
            warp_uniforms = Gst.Structure.from_string(
                "uniforms, u_time=(float)0.0, u_slice_count=(float)0.0, "
                "u_slice_amplitude=(float)0.0, u_pan_x=(float)0.0, u_pan_y=(float)0.0, "
                "u_rotation=(float)0.0, u_zoom=(float)1.0, u_zoom_breath=(float)0.0, "
                "u_width=(float)1920.0, u_height=(float)1080.0"
            )
        self._fx_warp_shader.set_property("uniforms", warp_uniforms[0])

        # Update gleffects — glow for Neon, sobel for Ghost, identity otherwise
        if preset.use_glow:
            self._fx_glow_effect.set_property("effect", 15)  # glow
        elif preset.use_sobel:
            self._fx_glow_effect.set_property("effect", 16)  # sobel
        else:
            self._fx_glow_effect.set_property("effect", 0)  # identity

        # Update post-process uniforms
        pp = preset.post_process
        pp_uniforms = Gst.Structure.from_string(
            f"uniforms, u_vignette_strength=(float){pp.vignette_strength}, "
            f"u_scanline_alpha=(float){pp.scanline_alpha}, "
            f"u_time=(float)0.0, "
            f"u_band_active=(float)0.0, "
            f"u_band_y=(float)0.0, u_band_height=(float)0.0, u_band_shift=(float)0.0, "
            f"u_syrup_active=(float){1.0 if pp.syrup_gradient else 0.0}, "
            f"u_syrup_color_r=(float){pp.syrup_color[0]}, "
            f"u_syrup_color_g=(float){pp.syrup_color[1]}, "
            f"u_syrup_color_b=(float){pp.syrup_color[2]}"
        )
        self._fx_post_proc.set_property("uniforms", pp_uniforms[0])

        # Update temporal feedback (Rust FBO ping-pong plugin)
        trail = preset.trail
        if self._fx_temporal is not None:
            if trail.count > 0 and trail.opacity > 0:
                self._fx_temporal.set_property("feedback-amount", trail.opacity)

                # Decay from filter_params brightness (lower = faster fade)
                fp = trail.filter_params
                decay_base = fp.get("brightness", 0.7)
                # Per-channel decay for color shift effects
                self._fx_temporal.set_property("decay-r", min(decay_base * 1.0, 0.99))
                self._fx_temporal.set_property("decay-g", min(decay_base * 0.98, 0.99))
                self._fx_temporal.set_property("decay-b", min(decay_base * 0.96, 0.99))

                # Hue shift from filter_params
                self._fx_temporal.set_property("hue-shift", fp.get("hue_rotate", 0.0))

                # Blend mode
                blend_map = {
                    "add": 0,
                    "multiply": 1,
                    "difference": 2,
                    "source-over": 3,
                }
                self._fx_temporal.set_property(
                    "blend-mode", blend_map.get(trail.blend_mode, 0)
                )
            else:
                self._fx_temporal.set_property("feedback-amount", 0.0)

        # Update stutter element
        st = preset.stutter
        if st:
            self._fx_stutter.set_property("check-interval", st.check_interval)
            self._fx_stutter.set_property("freeze-chance", st.freeze_chance)
            self._fx_stutter.set_property("freeze-min", st.freeze_min)
            self._fx_stutter.set_property("freeze-max", st.freeze_max)
            self._fx_stutter.set_property("replay-frames", st.replay_frames)
        else:
            self._fx_stutter.set_property("freeze-chance", 0.0)
            self._fx_stutter.set_property("check-interval", 999)

        self._fx_active_preset = preset_name
        self._fx_tick = 0
        log.info("FX preset switched to: %s", preset_name)

    def _add_camera_snapshot_branch(self, pipeline: Any, camera_tee: Any, cam: CameraSpec) -> None:
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
            Gst.Caps.from_string("video/x-raw,framerate=15/1"),
        )
        scale = Gst.ElementFactory.make("videoscale", f"camsnap-scale-{role}")
        # Use native resolution
        scale_caps = Gst.ElementFactory.make("capsfilter", f"camsnap-scalecaps-{role}")
        scale_caps.set_property(
            "caps",
            Gst.Caps.from_string(f"video/x-raw,width={cam.width},height={cam.height}"),
        )
        encoder = Gst.ElementFactory.make("jpegenc", f"camsnap-jpeg-{role}")
        encoder.set_property("quality", 80)
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
                    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
                    try:
                        os.write(fd, mapinfo.data)
                    finally:
                        os.close(fd)
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
        tee_pad = camera_tee.request_pad(camera_tee.get_pad_template("src_%u"), None, None)
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
            Gst.Caps.from_string(f"video/x-raw(memory:CUDAMemory),width={tile.w},height={tile.h}"),
        )

        for el in [queue_comp, upload, cuda_convert, scale, scale_caps]:
            pipeline.add(el)

        queue_comp.link(upload)
        upload.link(cuda_convert)
        cuda_convert.link(scale)
        scale.link(scale_caps)

        # Explicit tee -> queue pad link
        tee_pad = camera_tee.request_pad(camera_tee.get_pad_template("src_%u"), None, None)
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

        # Track elements for auto-reconnect
        if not hasattr(self, "_camera_elements"):
            self._camera_elements: dict[str, dict[str, Any]] = {}
            self._camera_specs: dict[str, CameraSpec] = {}
        self._camera_elements[cam.role] = {
            "src": src,
            "tee": camera_tee,
        }
        self._camera_specs[cam.role] = cam

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
        valve = Gst.ElementFactory.make("valve", f"rec-valve-{role}")
        valve.set_property("drop", not self._consent_recording_allowed)
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

        elements = [queue, valve, convert, nv12_caps, encoder, parser, mux_sink]
        for el in elements:
            pipeline.add(el)

        queue.link(valve)
        valve.link(convert)
        convert.link(nv12_caps)
        nv12_caps.link(encoder)
        encoder.link(parser)
        parser.link(mux_sink)

        # Explicit tee -> queue pad link
        tee_pad = camera_tee.request_pad(camera_tee.get_pad_template("src_%u"), None, None)
        queue_sink = queue.get_static_pad("sink")
        tee_pad.link(queue_sink)

        self._recording_valves[cam.role] = valve
        self._recording_muxes[cam.role] = mux_sink

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
        valve = Gst.ElementFactory.make("valve", "hls-valve")
        valve.set_property("drop", not self._consent_recording_allowed)
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
        hls_sink.set_property("playlist-location", str(hls_dir / "stream.m3u8"))
        hls_sink.set_property("async-handling", True)

        elements = [queue, valve, convert, nv12_caps, encoder, parser, hls_sink]
        for el in elements:
            pipeline.add(el)

        self._hls_valve = valve

        queue.link(valve)
        valve.link(convert)
        convert.link(nv12_caps)
        nv12_caps.link(encoder)
        encoder.link(parser)
        parser.link(hls_sink)

        # Explicit tee -> queue pad link
        tee_pad = tee.request_pad(tee.get_pad_template("src_%u"), None, None)
        queue_sink = queue.get_static_pad("sink")
        tee_pad.link(queue_sink)

    # -- Consent enforcement ----------------------------------------------

    def _log_consent_event(self, event: str, allowed: bool) -> None:
        """Append a consent event to the JSONL audit trail."""

        with self._overlay_state._lock:
            contracts = list(self._overlay_state._data.active_contracts)

        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "consent_allowed": allowed,
            "active_contracts": contracts,
            "recording_cameras": list(self._recording_valves.keys()),
            "hls_active": self._hls_valve is not None,
        }

        try:
            CONSENT_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(CONSENT_AUDIT_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            log.debug("Failed to write consent audit log")

    def _disable_persistence(self) -> None:
        """Consent withdrawn — finalize segments then drop recording/HLS buffers."""
        log.warning("Consent persistence DENIED — stopping recording and HLS")
        # Emit split-now BEFORE closing valves so pending buffers flush cleanly
        for _role, mux in self._recording_muxes.items():
            try:
                mux.emit("split-now")
            except Exception:
                pass
        # Close valves
        for valve in self._recording_valves.values():
            valve.set_property("drop", True)
        if self._hls_valve is not None:
            self._hls_valve.set_property("drop", True)
        with self._recording_status_lock:
            for role in self._recording_status:
                self._recording_status[role] = "consent-blocked"
        self._log_consent_event("recording_paused", allowed=False)

    def _enable_persistence(self) -> None:
        """Consent restored — resume recording and HLS."""
        log.info("Consent persistence ALLOWED — resuming recording and HLS")
        for valve in self._recording_valves.values():
            valve.set_property("drop", False)
        if self._hls_valve is not None:
            self._hls_valve.set_property("drop", False)
        with self._recording_status_lock:
            for role in self._recording_status:
                if self._recording_status[role] == "consent-blocked":
                    self._recording_status[role] = "active"
        self._log_consent_event("recording_resumed", allowed=True)

        # Tag new MKV segments with consent provenance
        Gst = self._Gst
        if Gst is None:
            return
        with self._overlay_state._lock:
            contracts = list(self._overlay_state._data.active_contracts)
        contract_str = ",".join(contracts) if contracts else "operator-only"

        for role, mux in self._recording_muxes.items():
            try:
                # splitmuxsink wraps a muxer — get the internal matroskamux
                inner_mux = mux.get_property("muxer")
                if inner_mux is None:
                    inner_mux = mux
                tag_list = Gst.TagList.new_empty()
                tag_list.add_value(
                    Gst.TagMergeMode.REPLACE,
                    Gst.TAG_EXTENDED_COMMENT,
                    f"consent-contracts={contract_str}",
                )
                tag_list.add_value(
                    Gst.TagMergeMode.REPLACE,
                    Gst.TAG_COMMENT,
                    f"Consent: {'granted' if contracts else 'operator-only'}",
                )
                inner_mux.merge_tags(tag_list, Gst.TagMergeMode.REPLACE)
            except Exception:
                log.debug("Failed to set consent tags on %s", role)

    def _purge_video_recordings(self, contract_id: str) -> int:
        """Purge video recording segments associated with a revoked consent contract.

        Scans the consent audit log to find recording segments that were created
        while the revoked contract was active, then deletes those files.
        Returns the number of files purged.
        """

        purged = 0
        rec_dir = Path(self.config.recording.output_dir)

        # Find time ranges when this contract was active from the audit log
        active_ranges: list[tuple[str, str | None]] = []
        current_start: str | None = None

        try:
            if CONSENT_AUDIT_PATH.exists():
                for line in CONSENT_AUDIT_PATH.read_text().splitlines():
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    if contract_id in entry.get("active_contracts", []):
                        if entry["event"] == "recording_resumed" and current_start is None:
                            current_start = entry["timestamp"]
                        elif entry["event"] == "recording_paused" and current_start:
                            active_ranges.append((current_start, entry["timestamp"]))
                            current_start = None
                if current_start:
                    active_ranges.append((current_start, None))  # still active
        except Exception:
            log.warning("Failed to read consent audit for purge")
            return 0

        if not active_ranges:
            return 0

        # Scan MKV recording files and delete those within active ranges
        if rec_dir.exists():
            for role_dir in rec_dir.iterdir():
                if not role_dir.is_dir():
                    continue
                for mkv_file in role_dir.glob("*.mkv"):
                    try:
                        name_parts = mkv_file.stem.split("_")
                        ts_str = name_parts[-2]  # YYYYMMDD-HHMMSS
                        file_time = datetime.strptime(ts_str, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
                        file_iso = file_time.isoformat()

                        for start, end in active_ranges:
                            if file_iso >= start and (end is None or file_iso <= end):
                                mkv_file.unlink()
                                purged += 1
                                log.info(
                                    "Purged recording: %s (contract %s revoked)",
                                    mkv_file,
                                    contract_id,
                                )
                                break
                    except (ValueError, IndexError):
                        continue

        # Purge HLS segments written during the contract period
        hls_dir = Path(self.config.hls.output_dir)
        if hls_dir.exists():
            for ts_file in hls_dir.glob("*.ts"):
                try:
                    mtime = datetime.fromtimestamp(ts_file.stat().st_mtime, tz=UTC)
                    mtime_iso = mtime.isoformat()
                    for start, end in active_ranges:
                        if mtime_iso >= start and (end is None or mtime_iso <= end):
                            ts_file.unlink()
                            purged += 1
                            log.info("Purged HLS segment: %s", ts_file)
                            break
                except OSError:
                    continue

        return purged

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
            elif src_name.startswith("fx-v4l2"):
                # FX v4l2sink errors are non-fatal — device may be busy or unavailable
                log.warning("FX v4l2sink error (non-fatal): %s", err.message)
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
        with self._overlay_state._lock:
            guest_present = self._overlay_state._data.guest_present
            consent_phase = self._overlay_state._data.consent_phase
        active_count = sum(1 for s in cameras.values() if s == "active")
        hls_url = ""
        if self.config.hls.enabled:
            hls_url = str(Path(self.config.hls.output_dir) / "stream.m3u8")
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
            "consent_recording_allowed": self._consent_recording_allowed,
            "guest_present": guest_present,
            "consent_phase": consent_phase,
            "timestamp": time.time(),
        }
        tmp = STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(status, indent=2))
        tmp.rename(STATUS_FILE)

        # Write consent sidecar for snapshot consumers (ephemeral, in /dev/shm)
        try:
            consent_file = SNAPSHOT_DIR / "consent-state.txt"
            consent_file.write_text("allowed" if self._consent_recording_allowed else "blocked")
        except OSError:
            pass  # SNAPSHOT_DIR may not exist yet during early startup

    def _fx_tick_callback(self) -> bool:
        """GLib timeout: update time-varying FX shader uniforms at ~30fps.

        Reads audio_energy_rms from the perception state to modulate
        shader parameters in sync with audio — beat-reactive effects.
        """
        if not self._running:
            return False
        if not hasattr(self, "_fx_warp_shader"):
            return False

        import random

        from agents.studio_effects import PRESETS

        self._fx_tick += 1
        t = self._fx_tick * 0.04
        Gst = self._Gst

        preset = PRESETS.get(self._fx_active_preset)
        if not preset:
            return True

        # --- Beat reactivity: read audio energy ---
        with self._overlay_state._lock:
            energy = self._overlay_state._data.audio_energy_rms
        # Normalize: energy is typically 0.0-0.3, clamp to 0-1
        beat = min(energy * 4.0, 1.0)
        # Smooth with exponential decay for punchier response
        if not hasattr(self, "_fx_beat_smooth"):
            self._fx_beat_smooth = 0.0
        self._fx_beat_smooth = max(beat, self._fx_beat_smooth * 0.85)
        b = self._fx_beat_smooth  # 0.0 = silent, 1.0 = loud

        # --- Color grade: pulse brightness/contrast on beats ---
        cg = preset.color_grade
        beat_brightness = cg.brightness + b * 0.15  # up to +15% brightness on beat
        beat_contrast = cg.contrast + b * 0.1  # up to +10% contrast on beat
        beat_saturation = cg.saturation + b * 0.2  # slightly more saturated on beat

        cg_u = Gst.Structure.from_string(
            f"uniforms, u_saturation=(float){beat_saturation}, "
            f"u_brightness=(float){beat_brightness}, "
            f"u_contrast=(float){beat_contrast}, "
            f"u_sepia=(float){cg.sepia}, "
            f"u_hue_rotate=(float){cg.hue_rotate}"
        )
        self._fx_color_grade.set_property("uniforms", cg_u[0])

        # --- Warp: amplify displacement on beats ---
        if preset.warp and (preset.warp.pan_x > 0 or preset.warp.slice_count > 0):
            w = preset.warp
            beat_slice_amp = w.slice_amplitude * (1.0 + b * 0.5)  # up to +50% on beat
            beat_pan_x = w.pan_x * (1.0 + b * 0.3)
            beat_pan_y = w.pan_y * (1.0 + b * 0.3)
            beat_zoom_breath = w.zoom_breath * (1.0 + b * 0.4)

            warp_u = Gst.Structure.from_string(
                f"uniforms, u_time=(float){t}, "
                f"u_slice_count=(float){w.slice_count}, "
                f"u_slice_amplitude=(float){beat_slice_amp}, "
                f"u_pan_x=(float){beat_pan_x}, u_pan_y=(float){beat_pan_y}, "
                f"u_rotation=(float){w.rotation}, u_zoom=(float){w.zoom}, "
                f"u_zoom_breath=(float){beat_zoom_breath}, "
                f"u_width=(float)1920.0, u_height=(float)1080.0"
            )
            self._fx_warp_shader.set_property("uniforms", warp_u[0])

        # --- VHS: increase chroma shift + noise band speed on beats ---
        if preset.use_vhs_shader:
            beat_chroma = 4.0 + b * 6.0  # 4-10px chroma shift, more on beat
            noise_speed = 0.003 + b * 0.008  # faster noise scrolling on beat
            noise_y = (self._fx_tick * noise_speed) % 1.0
            vhs_u = Gst.Structure.from_string(
                f"uniforms, u_time=(float){t}, u_chroma_shift=(float){beat_chroma}, "
                f"u_head_switch_y=(float)0.92, u_noise_band_y=(float){noise_y}, "
                f"u_width=(float)1920.0, u_height=(float)1080.0"
            )
            self._fx_vhs_shader.set_property("uniforms", vhs_u[0])

        # --- Post-process: beat-triggered band displacement ---
        pp = preset.post_process
        # Increase band displacement probability and intensity on beats
        beat_band_chance = pp.band_chance + b * 0.3  # more frequent bands on beat
        beat_band_shift = pp.band_max_shift * (1.0 + b * 1.0)  # up to 2x shift on beat

        band_active = 1.0 if beat_band_chance > 0 and random.random() < beat_band_chance else 0.0
        band_y = random.random() * 0.6 + 0.2 if band_active else 0.0
        band_h = random.random() * 0.03 + 0.005 if band_active else 0.0
        band_shift = (random.random() - 0.5) * 2 * beat_band_shift / 1920.0 if band_active else 0.0

        # Beat flash: brief vignette pulse (open up on beat, close in on silence)
        beat_vignette = pp.vignette_strength * (1.0 - b * 0.3)  # vignette opens on beat

        pp_u = Gst.Structure.from_string(
            f"uniforms, u_vignette_strength=(float){beat_vignette}, "
            f"u_scanline_alpha=(float){pp.scanline_alpha}, "
            f"u_time=(float){t}, "
            f"u_band_active=(float){band_active}, "
            f"u_band_y=(float){band_y}, u_band_height=(float){band_h}, u_band_shift=(float){band_shift}, "
            f"u_syrup_active=(float){1.0 if pp.syrup_gradient else 0.0}, "
            f"u_syrup_color_r=(float){pp.syrup_color[0]}, "
            f"u_syrup_color_g=(float){pp.syrup_color[1]}, "
            f"u_syrup_color_b=(float){pp.syrup_color[2]}"
        )
        self._fx_post_proc.set_property("uniforms", pp_u[0])

        return True  # keep timer running

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
        self._overlay_cache_surface = None  # force re-render on caps change

    def _on_draw(self, overlay: Any, cr: Any, timestamp: int, duration: int) -> None:
        """Cairo draw callback -- renders text overlays on the composited frame.

        Uses a cached ImageSurface to avoid full redraw every frame.  The cache
        is invalidated when the overlay state timestamp or camera status hash
        changes.
        """
        if not self.config.overlay_enabled:
            return

        import cairo  # type: ignore[import-untyped]

        canvas_w, canvas_h = self._overlay_canvas_size

        # Read overlay data directly under lock instead of model_copy() every frame
        with self._overlay_state._lock:
            state = self._overlay_state._data

        # Build a cheap hash of camera status for cache invalidation
        with self._camera_status_lock:
            cam_hash = "|".join(f"{r}:{s}" for r, s in sorted(self._camera_status.items()))

        cur_ts = state.timestamp
        cache_valid = (
            self._overlay_cache_surface is not None
            and cur_ts == self._overlay_cache_timestamp
            and cam_hash == self._overlay_cache_cam_hash
        )

        if not cache_valid:
            # Create / clear the cached surface and redraw everything onto it
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, canvas_w, canvas_h)
            ctx = cairo.Context(surf)
            ctx.set_operator(cairo.OPERATOR_CLEAR)
            ctx.paint()
            ctx.set_operator(cairo.OPERATOR_OVER)

            ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            pad = 4

            for role, tile in self._tile_layout.items():
                ctx.set_font_size(14)
                text = role
                extents = ctx.text_extents(text)
                ctx.set_source_rgba(0.0, 0.0, 0.0, 0.6)
                ctx.rectangle(
                    tile.x + pad,
                    tile.y + pad,
                    extents.width + pad * 2,
                    extents.height + pad * 2,
                )
                ctx.fill()
                ctx.set_source_rgba(1.0, 1.0, 1.0, 0.9)
                ctx.move_to(tile.x + pad * 2, tile.y + pad + extents.height + pad)
                ctx.show_text(text)

                if not self.config.recording.enabled:
                    badge_color = (0.5, 0.5, 0.5, 0.7)  # gray — recording disabled
                    badge_text = "NO-REC"
                elif state.consent_phase == "guest_detected":
                    badge_color = (1.0, 0.9, 0.2, 0.9)  # yellow — debouncing
                    badge_text = "DETECTING"
                elif state.consent_phase == "consent_pending":
                    badge_color = (1.0, 0.6, 0.1, 0.9)  # orange — awaiting consent
                    badge_text = "PENDING"
                elif state.consent_phase == "consent_refused":
                    badge_color = (0.9, 0.2, 0.1, 0.9)  # red — guest refused
                    badge_text = "PAUSED"
                elif state.persistence_allowed:
                    badge_color = (0.2, 0.8, 0.2, 0.9)  # green — all clear
                    badge_text = "REC"
                else:
                    badge_color = (0.9, 0.3, 0.1, 0.9)  # orange/red — consent-blocked
                    badge_text = "PAUSED"
                ctx.set_font_size(12)
                be = ctx.text_extents(badge_text)
                bx = tile.x + tile.w - be.width - pad * 3
                by = tile.y + pad
                ctx.set_source_rgba(0.0, 0.0, 0.0, 0.6)
                ctx.rectangle(bx, by, be.width + pad * 2, be.height + pad * 2)
                ctx.fill()
                ctx.set_source_rgba(*badge_color)
                ctx.move_to(bx + pad, by + be.height + pad)
                ctx.show_text(badge_text)

                with self._camera_status_lock:
                    cam_status = self._camera_status.get(role, "unknown")
                if cam_status == "offline":
                    ctx.set_font_size(24)
                    ctx.set_source_rgba(1.0, 0.3, 0.3, 0.8)
                    ot = "OFFLINE"
                    oe = ctx.text_extents(ot)
                    ctx.move_to(
                        tile.x + (tile.w - oe.width) / 2,
                        tile.y + (tile.h + oe.height) / 2,
                    )
                    ctx.show_text(ot)

            if state.flow_state:
                ctx.set_font_size(20)
                flow_text = f"FLOW: {state.flow_state.upper()} ({state.flow_score:.0%})"
                fe = ctx.text_extents(flow_text)
                fx = (canvas_w - fe.width) / 2
                fy = 8
                ctx.set_source_rgba(0.0, 0.0, 0.0, 0.6)
                ctx.rectangle(fx - 6, fy, fe.width + 12, fe.height + 12)
                ctx.fill()
                if state.flow_state == "active":
                    ctx.set_source_rgba(0.2, 1.0, 0.4, 0.95)
                elif state.flow_state == "warming":
                    ctx.set_source_rgba(1.0, 0.9, 0.2, 0.95)
                else:
                    ctx.set_source_rgba(0.8, 0.8, 0.8, 0.95)
                ctx.move_to(fx, fy + fe.height + 4)
                ctx.show_text(flow_text)

            if state.production_activity or state.music_genre:
                ctx.set_font_size(14)
                tags = " | ".join(filter(None, [state.production_activity, state.music_genre]))
                te = ctx.text_extents(tags)
                tx = 8
                ty = canvas_h - 28
                ctx.set_source_rgba(0.0, 0.0, 0.0, 0.5)
                ctx.rectangle(tx - 4, ty - te.height - 4, te.width + 8, te.height + 8)
                ctx.fill()
                ctx.set_source_rgba(0.9, 0.9, 0.9, 0.85)
                ctx.move_to(tx, ty)
                ctx.show_text(tags)

            if state.audio_energy_rms > 0:
                bar_h = 4
                bar_w = int(canvas_w * min(state.audio_energy_rms * 10, 1.0))
                ctx.set_source_rgba(0.3, 0.8, 0.3, 0.7)
                ctx.rectangle(0, canvas_h - bar_h, bar_w, bar_h)
                ctx.fill()

            # Consent-blocked banner — prominent center notice when recording is paused
            if not state.persistence_allowed and self.config.recording.enabled:
                ctx.set_font_size(18)
                banner = "RECORDING PAUSED \u2014 CONSENT REQUIRED"
                be = ctx.text_extents(banner)
                bx = (canvas_w - be.width) / 2
                by = canvas_h - 50
                ctx.set_source_rgba(0.0, 0.0, 0.0, 0.7)
                ctx.rectangle(bx - 8, by - be.height - 6, be.width + 16, be.height + 12)
                ctx.fill()
                ctx.set_source_rgba(1.0, 0.3, 0.1, 0.95)
                ctx.move_to(bx, by)
                ctx.show_text(banner)

            self._overlay_cache_surface = surf
            self._overlay_cache_timestamp = cur_ts
            self._overlay_cache_cam_hash = cam_hash

        # Blit cached surface onto the cairooverlay context
        cr.set_source_surface(self._overlay_cache_surface, 0, 0)
        cr.paint()

        # Visual layer zones — render on top of existing overlay
        self._render_visual_layer(cr, canvas_w, canvas_h)

    # -- Visual layer zone rendering ----------------------------------------

    # Zone color palettes (RGBA, desaturated 30% for neurodivergent-safe display)
    _VL_ZONE_COLORS: dict[str, tuple[float, float, float]] = {
        "context_time": (0.4, 0.6, 0.85),  # soft blue
        "governance": (0.3, 0.7, 0.7),  # teal
        "work_tasks": (0.85, 0.65, 0.3),  # amber
        "health_infra": (0.3, 0.8, 0.3),  # green (shifts to red at high severity)
        "profile_state": (0.9, 0.9, 0.9),  # white/neutral
        "ambient_sensor": (0.6, 0.6, 0.7),  # muted lavender
    }

    # Zone layout as fractions of canvas (matching visual_layer_state.py ZONE_LAYOUT)
    _VL_ZONES: dict[str, tuple[float, float, float, float]] = {
        "context_time": (0.01, 0.03, 0.25, 0.12),
        "governance": (0.74, 0.03, 0.25, 0.12),
        "work_tasks": (0.01, 0.20, 0.18, 0.45),
        "health_infra": (0.78, 0.78, 0.21, 0.18),
        "profile_state": (0.35, 0.01, 0.30, 0.06),
        "ambient_sensor": (0.01, 0.92, 0.75, 0.06),
    }

    _VL_LERP_RATE = 3.0  # opacity units per second (full 0→1 in ~333ms)
    _VL_LAST_FRAME_TIME: float = 0.0

    _VL_TOGGLE_PATH = Path("/dev/shm/hapax-compositor/visual-layer-enabled.txt")

    def _render_visual_layer(self, cr: Any, canvas_w: int, canvas_h: int) -> None:
        """Render visual layer zones with per-zone opacity interpolation."""
        import cairo  # type: ignore[import-untyped]

        # Check toggle — defaults to enabled
        try:
            if self._VL_TOGGLE_PATH.exists():
                if self._VL_TOGGLE_PATH.read_text().strip() == "false":
                    return
        except OSError:
            pass

        with self._vl_state_lock:
            vl = self._vl_state

        if vl is None:
            return

        zone_opacities = vl.get("zone_opacities", {})
        signals = vl.get("signals", {})

        if not zone_opacities and not signals:
            return

        # Time-based opacity interpolation
        now = time.monotonic()
        dt = min(now - self._VL_LAST_FRAME_TIME, 0.1) if self._VL_LAST_FRAME_TIME > 0 else 0.016
        self._VL_LAST_FRAME_TIME = now

        # Lerp current opacities toward targets
        for zone_name, target in zone_opacities.items():
            current = self._vl_zone_opacities.get(zone_name, 0.0)
            if abs(current - target) < 0.01:
                self._vl_zone_opacities[zone_name] = target
            else:
                step = self._VL_LERP_RATE * dt
                if target > current:
                    self._vl_zone_opacities[zone_name] = min(target, current + step)
                else:
                    self._vl_zone_opacities[zone_name] = max(target, current - step)

        # Render each zone
        pad = 6
        cr.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)

        for zone_name, (zx, zy, zw, zh) in self._VL_ZONES.items():
            opacity = self._vl_zone_opacities.get(zone_name, 0.0)
            if opacity < 0.02:
                continue

            zone_signals = signals.get(zone_name, [])
            if not zone_signals:
                continue

            # Zone pixel coordinates
            x = int(zx * canvas_w)
            y = int(zy * canvas_h)
            w = int(zw * canvas_w)
            h = int(zh * canvas_h)

            # Zone background pill
            r, g, b = self._VL_ZONE_COLORS.get(zone_name, (0.5, 0.5, 0.5))

            # Severity-based color shift for health_infra
            if zone_name == "health_infra" and zone_signals:
                max_sev = max(s.get("severity", 0) for s in zone_signals)
                if max_sev > 0.7:
                    r, g, b = (0.9, 0.2, 0.1)  # red
                elif max_sev > 0.4:
                    r, g, b = (0.85, 0.65, 0.2)  # amber

            cr.set_source_rgba(0.0, 0.0, 0.0, 0.45 * opacity)
            self._rounded_rect(cr, x, y, w, h, 8)
            cr.fill()

            # Render signal titles
            cr.set_font_size(13)
            text_y = y + pad + 13
            for sig in zone_signals[:3]:  # Max 3 per zone
                title = sig.get("title", "")[:40]
                if not title:
                    continue

                cr.set_source_rgba(r, g, b, 0.9 * opacity)
                cr.move_to(x + pad, text_y)
                cr.show_text(title)

                detail = sig.get("detail", "")[:50]
                if detail:
                    text_y += 14
                    cr.set_font_size(11)
                    cr.set_source_rgba(0.79, 0.82, 0.85, 0.7 * opacity)
                    cr.move_to(x + pad, text_y)
                    cr.show_text(detail)
                    cr.set_font_size(13)

                text_y += 18

    @staticmethod
    def _rounded_rect(cr: Any, x: float, y: float, w: float, h: float, radius: float) -> None:
        """Draw a rounded rectangle path."""
        import math

        cr.new_sub_path()
        cr.arc(x + w - radius, y + radius, radius, -math.pi / 2, 0)
        cr.arc(x + w - radius, y + h - radius, radius, 0, math.pi / 2)
        cr.arc(x + radius, y + h - radius, radius, math.pi / 2, math.pi)
        cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()

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

    def _try_reconnect_camera(self, role: str) -> bool:
        """Attempt to reconnect an offline camera."""
        spec = self._camera_specs.get(role) if hasattr(self, "_camera_specs") else None
        if not spec or not Path(spec.device).exists():
            return False

        elements = self._camera_elements.get(role, {}) if hasattr(self, "_camera_elements") else {}
        src = elements.get("src")
        if src is None:
            return False

        # Reset the source element: NULL -> PLAYING
        src.set_state(self._Gst.State.NULL)
        time.sleep(0.5)
        ret = src.set_state(self._Gst.State.PLAYING)

        if ret == self._Gst.StateChangeReturn.FAILURE:
            log.warning("Failed to reconnect camera %s", role)
            return False

        with self._camera_status_lock:
            self._camera_status[role] = "active"
        log.info("Camera %s reconnected", role)
        self._write_status("running")
        return True

    def _state_reader_loop(self) -> None:
        """Daemon thread: read perception-state.json every 1s."""
        profile_check_counter = 0
        reconnect_counter = 0
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

            # Read visual layer state (from aggregator)
            try:
                if VISUAL_LAYER_STATE_PATH.exists():
                    vl_raw = VISUAL_LAYER_STATE_PATH.read_text()
                    vl_data = json.loads(vl_raw)
                    with self._vl_state_lock:
                        self._vl_state = vl_data
                        self._vl_state_timestamp = vl_data.get("timestamp", 0.0)
            except (json.JSONDecodeError, OSError):
                pass  # Aggregator may not be running

            # Consent enforcement: toggle recording/HLS valves
            with self._overlay_state._lock:
                consent_ok = self._overlay_state._data.persistence_allowed
            if consent_ok != self._consent_recording_allowed:
                self._consent_recording_allowed = consent_ok
                GLib = self._GLib
                if GLib:
                    if consent_ok:
                        GLib.idle_add(self._enable_persistence)
                    else:
                        GLib.idle_add(self._disable_persistence)

            # Evaluate camera profiles every 10 iterations (~10s)
            profile_check_counter += 1
            if profile_check_counter >= 10:
                profile_check_counter = 0
                try:
                    self._evaluate_camera_profile()
                except Exception as exc:
                    log.debug("Failed to evaluate camera profile: %s", exc)

                # Attempt reconnection of offline cameras every 30s (3 x 10s)
                reconnect_counter += 1
                if reconnect_counter >= 3:
                    reconnect_counter = 0
                    with self._camera_status_lock:
                        offline = [r for r, s in self._camera_status.items() if s == "offline"]
                    for role in offline:
                        try:
                            self._try_reconnect_camera(role)
                        except Exception as exc:
                            log.debug("Camera reconnect failed for %s: %s", role, exc)

            # Check for FX preset switch requests
            fx_request_path = SNAPSHOT_DIR / "fx-request.txt"
            if fx_request_path.exists():
                try:
                    preset_name = fx_request_path.read_text().strip()
                    if preset_name and hasattr(self, "_fx_color_grade"):
                        self._switch_fx_preset(preset_name)
                    fx_request_path.unlink()
                except Exception as exc:
                    log.debug("Failed to process FX request: %s", exc)
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

        # Read initial consent state — close valves before PLAYING if needed
        try:
            if PERCEPTION_STATE_PATH.exists():
                raw = PERCEPTION_STATE_PATH.read_text()
                initial = json.loads(raw)
                if time.time() - initial.get("timestamp", 0) < 10:
                    if not initial.get("persistence_allowed", True):
                        self._consent_recording_allowed = False
                        for valve in self._recording_valves.values():
                            valve.set_property("drop", True)
                        if self._hls_valve is not None:
                            self._hls_valve.set_property("drop", True)
                        log.warning("Starting with recording BLOCKED (consent not available)")
        except Exception:
            log.debug("Failed to read initial consent state", exc_info=True)

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
        self._log_consent_event("pipeline_start", allowed=self._consent_recording_allowed)

        # Register video recording purge handler with RevocationPropagator
        try:
            import shared.governance.revocation as _rev_mod
            from shared.governance.revocation import RevocationPropagator  # noqa: F811

            for attr in dir(_rev_mod):
                obj = getattr(_rev_mod, attr, None)
                if isinstance(obj, RevocationPropagator):
                    obj.register_handler("video_recordings", self._purge_video_recordings)
                    log.info("Registered video recording purge handler")
                    break
        except Exception:
            log.debug("RevocationPropagator not available — video purge disabled")

        self.loop = GLib.MainLoop()

        interval_ms = int(self.config.status_interval_s * 1000)
        self._status_timer_id = GLib.timeout_add(interval_ms, self._status_tick)

        # FX uniform update timer (~30fps) for time-varying effects
        if hasattr(self, "_fx_warp_shader"):
            GLib.timeout_add(33, self._fx_tick_callback)

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
        self._log_consent_event("pipeline_stop", allowed=self._consent_recording_allowed)
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
