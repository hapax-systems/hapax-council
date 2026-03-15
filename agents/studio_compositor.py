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
import sys
import threading
import time
from pathlib import Path
from typing import Any

import gi
import yaml
from pydantic import BaseModel, Field

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------

CACHE_DIR = Path.home() / ".cache" / "hapax-compositor"
STATUS_FILE = CACHE_DIR / "status.json"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "hapax-compositor" / "config.yaml"

OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080


class CameraSpec(BaseModel):
    """A single camera source."""

    role: str  # e.g. "brio-operator", "c920-hardware", "c920-room", "c920-aux", "ir"
    device: str  # /dev/v4l/by-id/... or /dev/videoN
    width: int = 1280
    height: int = 720
    input_format: str = "mjpeg"  # "mjpeg" or "raw"
    pixel_format: str | None = None  # e.g. "gray" for IR sensor
    hero: bool = False  # hero cam gets 2x tile size


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
            log.warning("Failed to load config from %s: %s — using defaults", config_path, exc)
    return _default_config()


# ---------------------------------------------------------------------------
# Tile layout
# ---------------------------------------------------------------------------


class TileRect(BaseModel):
    x: int
    y: int
    w: int
    h: int


def compute_tile_layout(
    cameras: list[CameraSpec],
    canvas_w: int = OUTPUT_WIDTH,
    canvas_h: int = OUTPUT_HEIGHT,
) -> dict[str, TileRect]:
    """Compute tile positions for each camera on the output canvas.

    Hero camera (if any) gets a 2x tile in the top-left.
    Remaining cameras fill in a grid around it.
    """
    n = len(cameras)
    if n == 0:
        return {}

    heroes = [c for c in cameras if c.hero]
    others = [c for c in cameras if not c.hero]

    layout: dict[str, TileRect] = {}

    if heroes and len(others) >= 1:
        # Hero gets top-left 2x2 block (half canvas width, half canvas height)
        hero = heroes[0]
        hero_w = canvas_w // 2
        hero_h = canvas_h // 2

        layout[hero.role] = TileRect(x=0, y=0, w=hero_w, h=hero_h)

        # Right quadrant: 2-column grid filling same height as hero
        right_count = min(len(others), 4)
        right_cams = others[:right_count]
        remaining = others[right_count:]

        right_cols = 2
        right_rows = (right_count + right_cols - 1) // right_cols
        tile_w = (canvas_w - hero_w) // right_cols
        tile_h = hero_h // max(right_rows, 1)

        for i, cam in enumerate(right_cams):
            col = i % right_cols
            row = i // right_cols
            layout[cam.role] = TileRect(
                x=hero_w + col * tile_w,
                y=row * tile_h,
                w=tile_w,
                h=tile_h,
            )

        # Bottom row: remaining cameras (future BRIOs etc.)
        if remaining:
            bottom_w = canvas_w // len(remaining)
            for i, cam in enumerate(remaining):
                layout[cam.role] = TileRect(
                    x=i * bottom_w,
                    y=hero_h,
                    w=bottom_w,
                    h=canvas_h - hero_h,
                )
    else:
        # No hero: simple grid
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        tile_w = canvas_w // cols
        tile_h = canvas_h // rows
        for i, cam in enumerate(cameras):
            layout[cam.role] = TileRect(
                x=(i % cols) * tile_w,
                y=(i // cols) * tile_h,
                w=tile_w,
                h=tile_h,
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
        self._stale = True  # no data loaded yet

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
# GStreamer pipeline builder
# ---------------------------------------------------------------------------


class StudioCompositor:
    """Manages the GStreamer compositing pipeline."""

    def __init__(self, config: CompositorConfig) -> None:
        self.config = config
        self.pipeline: Gst.Pipeline | None = None
        self.loop: GLib.MainLoop | None = None
        self._running = False
        # Per-camera status: role -> "active" | "offline" | "error"
        self._camera_status: dict[str, str] = {}
        self._camera_status_lock = threading.Lock()
        # Map GStreamer element name prefixes back to camera roles
        self._element_to_role: dict[str, str] = {}
        self._status_timer_id: int | None = None
        # Overlay
        self._overlay_state = OverlayState()
        self._overlay_canvas_size: tuple[int, int] = (config.output_width, config.output_height)
        self._tile_layout: dict[str, TileRect] = {}
        self._state_reader_thread: threading.Thread | None = None

    def _build_pipeline(self) -> Gst.Pipeline:
        """Build the full GStreamer pipeline."""
        Gst.init(None)

        pipeline = Gst.Pipeline.new("studio-compositor")
        layout = compute_tile_layout(
            self.config.cameras, self.config.output_width, self.config.output_height
        )
        self._tile_layout = layout

        # Create compositor
        compositor = Gst.ElementFactory.make("cudacompositor", "compositor")
        if compositor is None:
            raise RuntimeError(
                "cudacompositor plugin not available -- install gst-plugins-bad with CUDA"
            )
        pipeline.add(compositor)

        fps = self.config.framerate

        # Add camera sources
        for cam in self.config.cameras:
            tile = layout.get(cam.role)
            if tile is None:
                log.warning("No tile for camera %s, skipping", cam.role)
                continue

            self._add_camera_branch(pipeline, compositor, cam, tile, fps)

        # Output chain:
        # compositor(CUDA) -> cudadownload -> videoconvert(BGRA) -> cairooverlay
        #   -> videoconvert -> capsfilter(YUY2) -> v4l2sink
        #
        # We stay in CPU space after the overlay -- the encode-then-decode
        # round trip was wasteful. v4l2loopback accepts raw YUY2 directly.
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

        elements = [download, convert_bgra, bgra_caps, overlay, convert_out, sink_caps, sink]
        for el in elements:
            if el is None:
                raise RuntimeError("Failed to create GStreamer element")
            pipeline.add(el)

        # Link chain
        prev = compositor
        for el in elements:
            if not prev.link(el):
                raise RuntimeError(f"Failed to link {prev.get_name()} -> {el.get_name()}")
            prev = el

        return pipeline

    def _add_camera_branch(
        self,
        pipeline: Gst.Pipeline,
        compositor: Gst.Element,
        cam: CameraSpec,
        tile: TileRect,
        fps: int,
    ) -> None:
        """Add a single camera source branch to the pipeline."""
        role = cam.role.replace("-", "_")

        # Track element -> role mapping for error identification
        self._element_to_role[f"src_{role}"] = cam.role

        # Source with watchdog
        src = Gst.ElementFactory.make("v4l2src", f"src_{role}")
        src.set_property("device", cam.device)

        # Skip missing devices gracefully
        if not Path(cam.device).exists():
            log.warning("Camera %s device %s not found, skipping", cam.role, cam.device)
            with self._camera_status_lock:
                self._camera_status[cam.role] = "offline"
            return

        if cam.input_format == "mjpeg":
            # MJPEG path: v4l2src -> capsfilter(mjpeg) -> jpegdec -> cudaupload -> cudaconvert
            # Note: nvjpegdec cannot decode UVC webcam Motion-JPEG, so we use
            # software jpegdec and upload the decoded frames to CUDA.
            src_caps = Gst.ElementFactory.make("capsfilter", f"srccaps_{role}")
            src_caps.set_property(
                "caps",
                Gst.Caps.from_string(
                    f"image/jpeg,width={cam.width},height={cam.height},framerate={fps}/1"
                ),
            )
            decoder = Gst.ElementFactory.make("jpegdec", f"dec_{role}")
            upload = Gst.ElementFactory.make("cudaupload", f"upload_{role}")
            convert = Gst.ElementFactory.make("cudaconvert", f"convert_{role}")
            for el in [src, src_caps, decoder, upload, convert]:
                pipeline.add(el)
            src.link(src_caps)
            src_caps.link(decoder)
            decoder.link(upload)
            upload.link(convert)
            last = convert
        else:
            # Raw path (e.g. IR gray): v4l2src -> videoconvert -> cudaupload
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
            upload = Gst.ElementFactory.make("cudaupload", f"upload_{role}")
            for el in [src, src_caps, convert, upload]:
                pipeline.add(el)
            src.link(src_caps)
            src_caps.link(convert)
            convert.link(upload)
            last = upload

        # Scale to tile size before compositor
        scale = Gst.ElementFactory.make("cudascale", f"scale_{role}")
        scale_caps = Gst.ElementFactory.make("capsfilter", f"scalecaps_{role}")
        scale_caps.set_property(
            "caps",
            Gst.Caps.from_string(f"video/x-raw(memory:CUDAMemory),width={tile.w},height={tile.h}"),
        )

        for el in [scale, scale_caps]:
            pipeline.add(el)

        last.link(scale)
        scale.link(scale_caps)

        # Request a sink pad on compositor and set position
        pad_template = compositor.get_pad_template("sink_%u")
        pad = compositor.request_pad(pad_template, None, None)
        if pad is None:
            raise RuntimeError(f"Failed to get compositor sink pad for {cam.role}")

        pad.set_property("xpos", tile.x)
        pad.set_property("ypos", tile.y)
        pad.set_property("width", tile.w)
        pad.set_property("height", tile.h)

        # Link scale_caps src pad to compositor sink pad
        src_pad = scale_caps.get_static_pad("src")
        if src_pad.link(pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Failed to link {cam.role} to compositor")

    # -- Error handling ---------------------------------------------------

    def _resolve_camera_role(self, element: Gst.Element | None) -> str | None:
        """Walk up from an element to find which camera branch it belongs to."""
        if element is None:
            return None
        name = element.get_name()
        # Direct match on src element
        if name in self._element_to_role:
            return self._element_to_role[name]
        # Check if any role suffix matches (e.g. dec_brio_operator -> brio-operator)
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
                return  # already marked
            self._camera_status[role] = "offline"
        log.warning("Camera %s marked offline", role)
        self._write_status("running")

    def _on_bus_message(self, bus: Gst.Bus, message: Gst.Message) -> bool:
        """Handle pipeline bus messages.

        Camera errors are isolated -- the failed camera's tile freezes on its
        last frame (cudacompositor holds the last buffer) while other cameras
        continue. Only non-camera errors (compositor, encoder, sink) are fatal.
        """
        t = message.type
        if t == Gst.MessageType.EOS:
            log.info("Pipeline EOS")
            self.stop()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            src_name = message.src.get_name() if message.src else "unknown"

            # Check if this error belongs to a camera branch
            role = self._resolve_camera_role(message.src)
            if role is not None:
                log.error("Camera %s error (element %s): %s", role, src_name, err.message)
                self._mark_camera_offline(role)
                # Don't stop the pipeline -- other cameras continue.
                # The compositor pad holds the last frame automatically.
            else:
                # Fatal: compositor/encoder/sink error
                log.error(
                    "Pipeline error from %s: %s (debug: %s)",
                    src_name,
                    err.message,
                    debug,
                )
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
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with self._camera_status_lock:
            cameras = dict(self._camera_status)
        active_count = sum(1 for s in cameras.values() if s == "active")
        status = {
            "state": state,
            "pid": os.getpid(),
            "cameras": cameras,
            "active_cameras": active_count,
            "total_cameras": len(cameras),
            "output_device": self.config.output_device,
            "resolution": f"{self.config.output_width}x{self.config.output_height}",
            "timestamp": time.time(),
        }
        tmp = STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(status, indent=2))
        tmp.rename(STATUS_FILE)

    def _status_tick(self) -> bool:
        """GLib timeout callback: periodically refresh the status file."""
        if self._running:
            self._write_status("running")
        return self._running  # return False to stop the timer

    # -- Overlay ----------------------------------------------------------

    def _on_overlay_caps_changed(self, overlay: Gst.Element, caps: Gst.Caps) -> None:
        """Called when cairooverlay negotiates caps -- cache canvas size."""
        s = caps.get_structure(0)
        w = s.get_int("width")
        h = s.get_int("height")
        if w[0] and h[0]:
            self._overlay_canvas_size = (w[1], h[1])
            log.debug("Overlay canvas: %dx%d", w[1], h[1])

    def _on_draw(self, overlay: Gst.Element, cr: Any, timestamp: int, duration: int) -> None:
        """Cairo draw callback -- renders text overlays on the composited frame.

        Called on the streaming thread for every frame. Must be fast (<5ms).
        Reads from the thread-safe OverlayState cache.
        """
        if not self.config.overlay_enabled:
            return

        import cairo  # type: ignore[import-untyped]

        canvas_w, canvas_h = self._overlay_canvas_size
        state = self._overlay_state.data

        cr.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        pad = 4

        # Per-camera labels
        for role, tile in self._tile_layout.items():
            # Role label (top-left of tile)
            cr.set_font_size(14)
            text = role
            extents = cr.text_extents(text)
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.6)
            cr.rectangle(
                tile.x + pad,
                tile.y + pad,
                extents.width + pad * 2,
                extents.height + pad * 2,
            )
            cr.fill()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.9)
            cr.move_to(tile.x + pad * 2, tile.y + pad + extents.height + pad)
            cr.show_text(text)

            # Consent badge (top-right of tile)
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

            # Offline indicator
            with self._camera_status_lock:
                cam_status = self._camera_status.get(role, "unknown")
            if cam_status == "offline":
                cr.set_font_size(24)
                cr.set_source_rgba(1.0, 0.3, 0.3, 0.8)
                ot = "OFFLINE"
                oe = cr.text_extents(ot)
                cr.move_to(
                    tile.x + (tile.w - oe.width) / 2,
                    tile.y + (tile.h + oe.height) / 2,
                )
                cr.show_text(ot)

        # Global: flow state banner (top center)
        if state.flow_state:
            cr.set_font_size(20)
            flow_text = f"FLOW: {state.flow_state.upper()} ({state.flow_score:.0%})"
            fe = cr.text_extents(flow_text)
            fx = (canvas_w - fe.width) / 2
            fy = 8
            cr.set_source_rgba(0.0, 0.0, 0.0, 0.6)
            cr.rectangle(fx - 6, fy, fe.width + 12, fe.height + 12)
            cr.fill()
            # Color: green for active, yellow for warming, gray otherwise
            if state.flow_state == "active":
                cr.set_source_rgba(0.2, 1.0, 0.4, 0.95)
            elif state.flow_state == "warming":
                cr.set_source_rgba(1.0, 0.9, 0.2, 0.95)
            else:
                cr.set_source_rgba(0.8, 0.8, 0.8, 0.95)
            cr.move_to(fx, fy + fe.height + 4)
            cr.show_text(flow_text)

        # Global: classification tags (bottom-left)
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

        # Global: audio energy meter (bottom bar)
        if state.audio_energy_rms > 0:
            bar_h = 4
            bar_w = int(canvas_w * min(state.audio_energy_rms * 10, 1.0))
            cr.set_source_rgba(0.3, 0.8, 0.3, 0.7)
            cr.rectangle(0, canvas_h - bar_h, bar_w, bar_h)
            cr.fill()

    # -- State reader -----------------------------------------------------

    def _state_reader_loop(self) -> None:
        """Daemon thread: read perception-state.json every 1s."""
        while self._running:
            try:
                if PERCEPTION_STATE_PATH.exists():
                    raw = PERCEPTION_STATE_PATH.read_text()
                    data = OverlayData(**json.loads(raw))
                    # Check staleness: if timestamp is >10s old, mark stale
                    if time.time() - data.timestamp > 10:
                        self._overlay_state.mark_stale()
                    else:
                        self._overlay_state.update(data)
                else:
                    self._overlay_state.mark_stale()
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                log.debug("Failed to read perception state: %s", exc)
                self._overlay_state.mark_stale()
            time.sleep(1.0)

    # -- Lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Build and start the pipeline."""
        log.info("Building compositor pipeline with %d cameras", len(self.config.cameras))

        # Initialize camera status -- _build_pipeline may mark some as offline
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

        # Mark all cameras that weren't already offline as active
        with self._camera_status_lock:
            for role, status in self._camera_status.items():
                if status == "starting":
                    self._camera_status[role] = "active"

        self._running = True
        self._write_status("running")

        self.loop = GLib.MainLoop()

        # Periodic status refresh
        interval_ms = int(self.config.status_interval_s * 1000)
        self._status_timer_id = GLib.timeout_add(interval_ms, self._status_tick)

        # Start state reader thread for overlay data
        if self.config.overlay_enabled:
            self._state_reader_thread = threading.Thread(
                target=self._state_reader_loop, daemon=True, name="state-reader"
            )
            self._state_reader_thread.start()

        # Handle signals
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

        if self._status_timer_id is not None:
            GLib.source_remove(self._status_timer_id)
            self._status_timer_id = None

        if self.pipeline:
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

    log.info(
        "Config: %d cameras, output=%s, %dx%d@%dfps, overlay=%s",
        len(cfg.cameras),
        cfg.output_device,
        cfg.output_width,
        cfg.output_height,
        cfg.framerate,
        cfg.overlay_enabled,
    )

    compositor = StudioCompositor(cfg)
    compositor.start()


if __name__ == "__main__":
    main()
