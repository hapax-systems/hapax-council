"""Shared-memory output pipeline via shmsink.

Drop-in replacement for V4l2OutputPipeline that writes compositor frames
to a Unix socket via GStreamer's shmsink. A separate sidecar process
(hapax-v4l2-bridge) reads from shmsrc and pushes to /dev/video42.

This fully isolates the compositor process from v4l2loopback kernel
state. The sidecar can crash, restart, or be upgraded without touching
the compositor pipeline.

Controlled by HAPAX_V4L2_BRIDGE_ENABLED=1. When disabled, the legacy
V4l2OutputPipeline path is used.

Graph::

    interpipesrc(listen-to="compositor_v4l2_out")
      → queue(leaky=downstream, max-size-buffers=5)
      → videoconvert
      → capsfilter(video/x-raw,format=NV12,width×height,fps)
      → shmsink(socket-path=..., shm-size=..., wait-for-connection=False)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

INTERPIPE_CHANNEL = "compositor_v4l2_out"
DEFAULT_SOCKET = "/dev/shm/hapax-compositor/v4l2-bridge.sock"
BRIDGE_ENABLED_ENV = "HAPAX_V4L2_BRIDGE_ENABLED"


def is_bridge_enabled() -> bool:
    return os.environ.get(BRIDGE_ENABLED_ENV, "") == "1"


class ShmsinkOutputPipeline:
    def __init__(
        self,
        *,
        gst: Any,
        width: int,
        height: int,
        fps: int,
        socket_path: str | None = None,
        on_frame: Any | None = None,
    ) -> None:
        self._Gst = gst
        self._width = width
        self._height = height
        self._fps = fps
        self._socket_path = socket_path or os.environ.get(
            "HAPAX_V4L2_BRIDGE_SOCKET", DEFAULT_SOCKET
        )
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
            pipeline = Gst.Pipeline.new("shmsink_output_pipeline")

            src = Gst.ElementFactory.make("interpipesrc", "shm_out_src")
            if src is None:
                raise RuntimeError("interpipesrc factory failed")
            src.set_property("listen-to", INTERPIPE_CHANNEL)
            src.set_property("do-timestamp", True)
            src.set_property("allow-renegotiation", True)

            queue = Gst.ElementFactory.make("queue", "shm_out_queue")
            queue.set_property("leaky", 2)
            queue.set_property("max-size-buffers", 5)
            queue.set_property("max-size-bytes", 0)
            queue.set_property("max-size-time", 0)

            convert = Gst.ElementFactory.make("videoconvert", "shm_out_convert")
            convert.set_property("dither", 0)

            caps = Gst.ElementFactory.make("capsfilter", "shm_out_caps")
            caps.set_property(
                "caps",
                Gst.Caps.from_string(
                    f"video/x-raw,format=NV12,"
                    f"width={self._width},height={self._height},"
                    f"framerate={self._fps}/1"
                ),
            )

            frame_bytes = self._width * self._height * 3 // 2
            shm_size = frame_bytes * 8

            sink = Gst.ElementFactory.make("shmsink", "shm_output")
            if sink is None:
                raise RuntimeError("shmsink factory failed")
            sink.set_property("socket-path", self._socket_path)
            sink.set_property("shm-size", shm_size)
            sink.set_property("wait-for-connection", False)
            sink.set_property("sync", False)

            for el in (src, queue, convert, caps, sink):
                pipeline.add(el)
            src.link(queue)
            queue.link(convert)
            convert.link(caps)
            caps.link(sink)

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
            log.info(
                "ShmsinkOutputPipeline built: %s → shmsink(%s)",
                INTERPIPE_CHANNEL,
                self._socket_path,
            )

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
        log.error("ShmsinkOutputPipeline bus error: %s (%s)", err.message, debug)

    def start(self) -> bool:
        with self._state_lock:
            if self._pipeline is None:
                log.error("ShmsinkOutputPipeline: start called without build")
                return False
            Gst = self._Gst
            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                log.error("ShmsinkOutputPipeline: set_state(PLAYING) FAILURE")
                return False
            self._started = True
            nick = getattr(ret, "value_nick", str(ret))
            log.info("ShmsinkOutputPipeline started (state change=%s)", nick)
            return True

    def stop(self) -> None:
        with self._state_lock:
            if self._pipeline is None:
                return
            self._pipeline.set_state(self._Gst.State.NULL)
            self._started = False
            log.info("ShmsinkOutputPipeline stopped")

    def cycle(self) -> bool:
        self.stop()
        time.sleep(0.2)
        return self.start()
