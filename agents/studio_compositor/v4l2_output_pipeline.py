"""Isolated v4l2sink output pipeline via interpipesrc.

Decouples the v4l2sink from the main compositor pipeline so state
transitions (PLAYING→NULL→PLAYING for stall recovery) complete in <1s
instead of requiring a 15-30s flush of the upstream GL chain.

Graph::

    interpipesrc(listen-to="compositor_v4l2_out")
      → queue(leaky=downstream, max-size-buffers=5)
      → videoconvert
      → capsfilter(video/x-raw,format=NV12,width×height,fps)
      → v4l2sink(sync=False)

The main pipeline ends at an ``interpipesink`` named
``compositor_v4l2_out`` on ``output_tee``. This class consumes from
that channel — same pattern as ``CameraPipeline`` but inverted
(camera = producer → interpipesink; this = interpipesrc → consumer).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

INTERPIPE_CHANNEL = "compositor_v4l2_out"


class V4l2OutputPipeline:
    def __init__(
        self,
        *,
        gst: Any,
        device: str,
        width: int,
        height: int,
        fps: int,
        on_frame: Callable[[], None] | None = None,
    ) -> None:
        self._Gst = gst
        self._device = device
        self._width = width
        self._height = height
        self._fps = fps
        self._on_frame = on_frame

        self._pipeline: Any = None
        self._bus: Any = None
        self._bus_signal_id: int = 0
        self._state_lock = threading.RLock()
        self._started = False
        self._last_frame_monotonic: float = 0.0

    @property
    def last_frame_age_seconds(self) -> float:
        if self._last_frame_monotonic <= 0.0:
            return float("inf")
        return time.monotonic() - self._last_frame_monotonic

    def build(self) -> None:
        with self._state_lock:
            if self._pipeline is not None:
                return

            Gst = self._Gst
            pipeline = Gst.Pipeline.new("v4l2_output_pipeline")

            src = Gst.ElementFactory.make("interpipesrc", "v4l2_out_src")
            if src is None:
                raise RuntimeError("interpipesrc factory failed")
            src.set_property("listen-to", INTERPIPE_CHANNEL)
            src.set_property("do-timestamp", True)
            src.set_property("allow-renegotiation", True)

            queue = Gst.ElementFactory.make("queue", "v4l2_out_queue")
            queue.set_property("leaky", 2)  # downstream
            queue.set_property("max-size-buffers", 5)
            queue.set_property("max-size-bytes", 0)
            queue.set_property("max-size-time", 0)

            convert = Gst.ElementFactory.make("videoconvert", "v4l2_out_convert")
            convert.set_property("dither", 0)

            caps = Gst.ElementFactory.make("capsfilter", "v4l2_out_caps")
            caps.set_property(
                "caps",
                Gst.Caps.from_string(
                    f"video/x-raw,format=NV12,"
                    f"width={self._width},height={self._height},"
                    f"framerate={self._fps}/1"
                ),
            )

            sink = Gst.ElementFactory.make("v4l2sink", "output")
            if sink is None:
                raise RuntimeError("v4l2sink factory failed")
            sink.set_property("device", self._device)
            sink.set_property("sync", False)
            sink.set_property("qos", False)
            try:
                sink.set_property("enable-last-sample", False)
            except TypeError:
                pass

            for el in (src, queue, convert, caps, sink):
                pipeline.add(el)
            src.link(queue)
            queue.link(convert)
            convert.link(caps)
            caps.link(sink)

            # Frame-flow probe on sink pad
            sink_pad = sink.get_static_pad("sink")
            if sink_pad is not None:
                sink_pad.add_probe(
                    Gst.PadProbeType.BUFFER,
                    self._buffer_probe,
                    None,
                )

            bus = pipeline.get_bus()
            bus.add_signal_watch()
            sig_id = bus.connect("message::error", self._on_bus_error)

            self._pipeline = pipeline
            self._bus = bus
            self._bus_signal_id = sig_id
            log.info("V4l2OutputPipeline built: %s → %s", INTERPIPE_CHANNEL, self._device)

    def _buffer_probe(self, pad: Any, info: Any, _user_data: Any) -> Any:
        self._last_frame_monotonic = time.monotonic()
        if self._on_frame is not None:
            try:
                self._on_frame()
            except Exception:
                pass
        return self._Gst.PadProbeReturn.OK

    def _on_bus_error(self, _bus: Any, message: Any) -> None:
        err, debug = message.parse_error()
        log.error("V4l2OutputPipeline bus error: %s (%s)", err.message, debug)

    def start(self) -> bool:
        with self._state_lock:
            if self._pipeline is None:
                log.error("V4l2OutputPipeline: start called without build")
                return False
            Gst = self._Gst
            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                log.error("V4l2OutputPipeline: set_state(PLAYING) FAILURE")
                return False
            self._started = True
            log.info("V4l2OutputPipeline started (state change=%s)", ret.value_nick)
            return True

    def stop(self) -> None:
        with self._state_lock:
            if self._pipeline is None:
                return
            Gst = self._Gst
            self._pipeline.set_state(Gst.State.NULL)
            t0 = time.monotonic()
            ret, state, _pending = self._pipeline.get_state(timeout=3 * Gst.SECOND)
            dt_ms = (time.monotonic() - t0) * 1000.0
            try:
                from . import metrics as _m

                if _m.COMP_PIPELINE_TEARDOWN_DURATION_MS is not None:
                    _m.COMP_PIPELINE_TEARDOWN_DURATION_MS.labels(role="v4l2_output").observe(dt_ms)
            except Exception:
                pass
            if ret != Gst.StateChangeReturn.SUCCESS:
                log.warning("V4l2OutputPipeline: NULL transition incomplete (%.0fms)", dt_ms)
            else:
                log.info("V4l2OutputPipeline stopped (%.0fms)", dt_ms)
            self._started = False

    def teardown(self) -> None:
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
            self._pipeline = None
            self._bus = None

    def rebuild(self) -> bool:
        self.teardown()
        self.build()
        return self.start()

    def is_alive(self, threshold_s: float = 45.0) -> bool:
        return self.last_frame_age_seconds < threshold_s
