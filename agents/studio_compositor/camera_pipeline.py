"""Isolated per-camera GstPipeline producing a named interpipesink.

See docs/superpowers/specs/2026-04-12-compositor-hot-swap-architecture-design.md

Each camera lives in its own GstPipeline instance rather than as a branch of
the composite pipeline. Errors are bounded to the producer pipeline and do
not propagate to the composite bus. The composite pipeline consumes via
`interpipesrc listen-to=cam_<role>` — hot-swappable at runtime to the
paired fallback producer via a thread-safe GObject property write.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import CameraSpec

log = logging.getLogger(__name__)


class CameraPipeline:
    """Single v4l2 camera as an isolated producer GstPipeline.

    Graph:
        v4l2src device=/dev/v4l/by-id/...
          ! capsfilter (image/jpeg or raw, native dimensions)
          ! watchdog timeout=2000
          ! jpegdec              (if mjpeg)
          ! videoconvert
          ! capsfilter (video/x-raw, format=NV12, native dimensions)
          ! interpipesink name=cam_<role> sync=false async=false forward-events=false
    """

    def __init__(
        self,
        spec: CameraSpec,
        *,
        gst: Any,
        fps: int,
        on_error: Callable[[str, str], None] | None = None,
        on_frame: Callable[[], None] | None = None,
    ) -> None:
        self._spec = spec
        self._Gst = gst
        self._fps = fps
        self._on_error = on_error
        self._on_frame = on_frame

        self._role_safe = spec.role.replace("-", "_")
        self._sink_name = f"cam_{self._role_safe}"
        self._pipeline_name = f"camera_pipeline_{self._role_safe}"

        self._pipeline: Any = None
        self._bus: Any = None
        self._bus_signal_id: int = 0
        self._state_lock = threading.RLock()
        self._last_frame_monotonic: float = 0.0
        self._rebuild_count = 0
        self._started = False

    @property
    def role(self) -> str:
        return self._spec.role

    @property
    def sink_name(self) -> str:
        return self._sink_name

    @property
    def rebuild_count(self) -> int:
        return self._rebuild_count

    @property
    def last_frame_age_seconds(self) -> float:
        if self._last_frame_monotonic <= 0.0:
            return float("inf")
        return time.monotonic() - self._last_frame_monotonic

    def build(self) -> None:
        """Construct the GstPipeline graph. Idempotent (no-op if already built)."""
        with self._state_lock:
            if self._pipeline is not None:
                return

            Gst = self._Gst
            pipeline = Gst.Pipeline.new(self._pipeline_name)

            src = Gst.ElementFactory.make("v4l2src", f"src_{self._role_safe}")
            if src is None:
                raise RuntimeError(f"{self._spec.role}: v4l2src factory failed")
            src.set_property("device", self._spec.device)
            src.set_property("do-timestamp", True)

            src_caps = Gst.ElementFactory.make("capsfilter", f"srccaps_{self._role_safe}")
            if self._spec.input_format == "mjpeg":
                src_caps.set_property(
                    "caps",
                    Gst.Caps.from_string(
                        f"image/jpeg,width={self._spec.width},"
                        f"height={self._spec.height},framerate={self._fps}/1"
                    ),
                )
            else:
                pix_fmt = self._spec.pixel_format or "YUY2"
                src_caps.set_property(
                    "caps",
                    Gst.Caps.from_string(
                        f"video/x-raw,format={pix_fmt},width={self._spec.width},"
                        f"height={self._spec.height},framerate={self._fps}/1"
                    ),
                )

            watchdog = Gst.ElementFactory.make("watchdog", f"watchdog_{self._role_safe}")
            if watchdog is None:
                raise RuntimeError(f"{self._spec.role}: watchdog element missing")
            watchdog.set_property("timeout", 2000)  # ms

            decoder: Any = None
            if self._spec.input_format == "mjpeg":
                decoder = Gst.ElementFactory.make("jpegdec", f"dec_{self._role_safe}")
                if decoder is None:
                    raise RuntimeError(f"{self._spec.role}: jpegdec factory failed")

            convert = Gst.ElementFactory.make("videoconvert", f"vc_{self._role_safe}")
            convert.set_property("dither", 0)

            out_caps = Gst.ElementFactory.make("capsfilter", f"outcaps_{self._role_safe}")
            out_caps.set_property(
                "caps",
                Gst.Caps.from_string(
                    f"video/x-raw,format=NV12,width={self._spec.width},"
                    f"height={self._spec.height},framerate={self._fps}/1"
                ),
            )

            sink = Gst.ElementFactory.make("interpipesink", self._sink_name)
            if sink is None:
                raise RuntimeError(
                    f"{self._spec.role}: interpipesink factory failed — "
                    "install gst-plugin-interpipe"
                )
            sink.set_property("sync", False)
            sink.set_property("async", False)
            sink.set_property("forward-events", False)
            sink.set_property("forward-eos", False)

            elements = [src, src_caps, watchdog]
            if decoder is not None:
                elements.append(decoder)
            elements.extend([convert, out_caps, sink])

            for el in elements:
                pipeline.add(el)

            for i in range(len(elements) - 1):
                if not elements[i].link(elements[i + 1]):
                    raise RuntimeError(
                        f"{self._spec.role}: failed to link "
                        f"{elements[i].get_name()} -> {elements[i + 1].get_name()}"
                    )

            # Frame-flow observation: a pad probe on the interpipesink sink pad
            # updates the monotonic timestamp on every buffer. Used by Phase 4
            # metrics exporter and by the Type=notify watchdog.
            sink_pad = sink.get_static_pad("sink")
            if sink_pad is not None:
                sink_pad.add_probe(Gst.PadProbeType.BUFFER, self._on_buffer_probe)

            self._pipeline = pipeline
            self._bus = pipeline.get_bus()
            self._bus.add_signal_watch()
            self._bus_signal_id = self._bus.connect("message", self._on_bus_message)

            log.info(
                "camera_pipeline %s built (device=%s, %dx%d@%dfps, format=%s)",
                self._spec.role,
                self._spec.device,
                self._spec.width,
                self._spec.height,
                self._fps,
                self._spec.input_format,
            )

    def start(self) -> bool:
        """Transition to PLAYING. Returns False on failure."""
        with self._state_lock:
            if self._pipeline is None:
                log.error("camera_pipeline %s: start called without build", self._spec.role)
                return False

            if not Path(self._spec.device).exists():
                log.warning(
                    "camera_pipeline %s: device %s not present, deferring start",
                    self._spec.role,
                    self._spec.device,
                )
                return False

            Gst = self._Gst
            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                log.error("camera_pipeline %s: set_state(PLAYING) FAILURE", self._spec.role)
                return False
            self._started = True
            log.info(
                "camera_pipeline %s started (state change=%s)", self._spec.role, ret.value_nick
            )
            return True

    def stop(self) -> None:
        """Transition to NULL. Idempotent."""
        with self._state_lock:
            if self._pipeline is None:
                return
            Gst = self._Gst
            self._pipeline.set_state(Gst.State.NULL)
            self._started = False

    def teardown(self) -> None:
        """Full teardown: NULL + bus disconnect + element release. Idempotent."""
        with self._state_lock:
            if self._pipeline is None:
                return
            self.stop()
            if self._bus is not None and self._bus_signal_id:
                try:
                    self._bus.disconnect(self._bus_signal_id)
                except (TypeError, ValueError):
                    pass
                self._bus_signal_id = 0
                try:
                    self._bus.remove_signal_watch()
                except (TypeError, ValueError):
                    pass
            self._bus = None
            self._pipeline = None

    def rebuild(self) -> bool:
        """Teardown and rebuild from scratch. Returns True on successful restart."""
        with self._state_lock:
            self._rebuild_count += 1
            self.teardown()
            try:
                self.build()
            except Exception:
                log.exception("camera_pipeline %s: rebuild build() failed", self._spec.role)
                return False
            return self.start()

    def is_playing(self) -> bool:
        with self._state_lock:
            if self._pipeline is None:
                return False
            Gst = self._Gst
            _, current, _ = self._pipeline.get_state(timeout=0)
            return current == Gst.State.PLAYING

    def _on_buffer_probe(self, pad: Any, info: Any) -> Any:
        """GStreamer pad probe: note frame arrival, passthrough."""
        self._last_frame_monotonic = time.monotonic()
        if self._on_frame is not None:
            try:
                self._on_frame()
            except Exception:
                log.exception("camera_pipeline %s: on_frame callback raised", self._spec.role)
        return self._Gst.PadProbeReturn.OK

    def _on_bus_message(self, bus: Any, message: Any) -> bool:
        """Handle bus messages scoped to this producer pipeline only."""
        Gst = self._Gst
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            src = message.src.get_name() if message.src else "unknown"
            log.error(
                "camera_pipeline %s error (element=%s): %s (debug=%s)",
                self._spec.role,
                src,
                err.message,
                debug,
            )
            if self._on_error is not None:
                try:
                    self._on_error(self._spec.role, err.message)
                except Exception:
                    log.exception("camera_pipeline %s: on_error callback raised", self._spec.role)
        elif t == Gst.MessageType.WARNING:
            err, debug = message.parse_warning()
            log.warning(
                "camera_pipeline %s warning: %s (debug=%s)",
                self._spec.role,
                err.message,
                debug,
            )
        return True
