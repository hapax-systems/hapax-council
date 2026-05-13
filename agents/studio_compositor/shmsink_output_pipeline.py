"""Shared-memory output pipeline via shmsink.

Drop-in replacement for V4l2OutputPipeline that writes compositor frames
to a Unix socket via GStreamer's shmsink. A separate sidecar process
(hapax-v4l2-bridge) reads from shmsrc and pushes to /dev/video42.

This fully isolates the compositor process from v4l2loopback kernel
state. The sidecar can crash, restart, or be upgraded without touching
the compositor pipeline.

Controlled by HAPAX_V4L2_BRIDGE_ENABLED=1. When disabled, the legacy
V4l2OutputPipeline path is used. HAPAX_COMPOSITOR_DISABLE_V4L2_OUTPUT=1
is a stronger incident-containment gate: no v4l2/shm output branch should
be constructed at all.

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
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

INTERPIPE_CHANNEL = "compositor_v4l2_out"
DEFAULT_SOCKET = "/dev/shm/hapax-compositor/v4l2-bridge.sock"
BRIDGE_ENABLED_ENV = "HAPAX_V4L2_BRIDGE_ENABLED"
V4L2_OUTPUT_DISABLED_ENV = "HAPAX_COMPOSITOR_DISABLE_V4L2_OUTPUT"
SNAPSHOT_DIR = Path("/dev/shm/hapax-compositor")
_DEFAULT_PROOF_SNAPSHOT_INTERVAL_S = 1.0


def _set_optional_property(element: Any, name: str, value: Any) -> None:
    try:
        element.set_property(name, value)
    except Exception:
        log.debug("shmsink interpipesrc property not supported: %s", name, exc_info=True)


def is_bridge_enabled() -> bool:
    return os.environ.get(BRIDGE_ENABLED_ENV, "") == "1"


def is_v4l2_output_disabled() -> bool:
    return os.environ.get(V4L2_OUTPUT_DISABLED_ENV, "") == "1"


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
        proof_snapshot_path: str | os.PathLike[str] | None = None,
        proof_snapshot_interval_s: float | None = None,
    ) -> None:
        self._Gst = gst
        self._width = width
        self._height = height
        self._fps = fps
        self._socket_path = socket_path or os.environ.get(
            "HAPAX_V4L2_BRIDGE_SOCKET", DEFAULT_SOCKET
        )
        self._on_frame = on_frame
        self._proof_snapshot_path = (
            Path(proof_snapshot_path) if proof_snapshot_path else (SNAPSHOT_DIR / "fx-snapshot.jpg")
        )
        self._proof_snapshot_interval_s = (
            _DEFAULT_PROOF_SNAPSHOT_INTERVAL_S
            if proof_snapshot_interval_s is None
            else max(0.0, float(proof_snapshot_interval_s))
        )
        self._proof_snapshot_last_monotonic: float = 0.0
        self._proof_snapshot_inflight = False
        self._proof_snapshot_lock = threading.Lock()
        self._proof_snapshot_failure_logged = False

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
            _set_optional_property(src, "stream-sync", "restart-ts")
            _set_optional_property(src, "is-live", True)
            _set_optional_property(src, "format", Gst.Format.TIME)
            _set_optional_property(src, "automatic-eos", False)
            _set_optional_property(src, "accept-eos-event", False)

            queue = Gst.ElementFactory.make("queue", "shm_out_queue")
            queue.set_property("leaky", 2)
            queue.set_property("max-size-buffers", 5)
            queue.set_property("max-size-bytes", 0)
            queue.set_property("max-size-time", 0)

            rate = Gst.ElementFactory.make("videorate", "shm_out_videorate")
            if rate is None:
                raise RuntimeError("videorate factory failed")
            rate.set_property("skip-to-first", True)
            _set_optional_property(rate, "max-closing-segment-duplication-duration", 0)

            rate_caps = Gst.ElementFactory.make("capsfilter", "shm_out_rate_caps")
            if rate_caps is None:
                raise RuntimeError("capsfilter factory failed")
            rate_caps.set_property(
                "caps",
                Gst.Caps.from_string(
                    f"video/x-raw,width={self._width},height={self._height},framerate={self._fps}/1"
                ),
            )

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

            for el in (src, queue, rate, rate_caps, convert, caps, sink):
                pipeline.add(el)
            src.link(queue)
            queue.link(rate)
            rate.link(rate_caps)
            rate_caps.link(convert)
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

    def _maybe_write_proof_snapshot(self, data: bytes | bytearray | memoryview) -> None:
        if self._proof_snapshot_interval_s <= 0.0:
            return
        now = time.monotonic()
        with self._proof_snapshot_lock:
            if now - self._proof_snapshot_last_monotonic < self._proof_snapshot_interval_s:
                return
            if self._proof_snapshot_inflight:
                return
            self._proof_snapshot_last_monotonic = now
            self._proof_snapshot_inflight = True

        snapshot_data = bytes(data)
        thread = threading.Thread(
            target=self._write_proof_snapshot_jpeg,
            args=(snapshot_data,),
            daemon=True,
            name="shmsink-proof-snapshot",
        )
        thread.start()

    def _write_proof_snapshot_jpeg(self, data: bytes) -> None:
        """Write final-egress proof JPEG from the exact NV12 frame sent to shmsink."""
        try:
            import cv2
            import numpy as np

            expected = self._width * self._height * 3 // 2
            if len(data) < expected:
                raise ValueError(
                    f"NV12 frame too small for proof snapshot: got {len(data)}, expected {expected}"
                )
            nv12 = np.frombuffer(data[:expected], dtype=np.uint8).reshape(
                (self._height * 3 // 2, self._width)
            )
            bgr = cv2.cvtColor(nv12, cv2.COLOR_YUV2BGR_NV12)
            ok, encoded = cv2.imencode(
                ".jpg",
                bgr,
                [int(cv2.IMWRITE_JPEG_QUALITY), 85],
            )
            if not ok:
                raise RuntimeError("cv2.imencode returned false for proof snapshot")

            self._proof_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._proof_snapshot_path.with_name(self._proof_snapshot_path.name + ".tmp")
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
            try:
                os.write(fd, encoded.tobytes())
            finally:
                os.close(fd)
            tmp.replace(self._proof_snapshot_path)
            try:
                from . import metrics as _m

                _m.record_render_stage_frame("final_egress_snapshot")
            except Exception:
                pass
        except Exception as exc:
            if not self._proof_snapshot_failure_logged:
                log.warning("bridge final-egress proof snapshot unavailable: %s", exc)
                self._proof_snapshot_failure_logged = True
            else:
                log.debug("bridge final-egress proof snapshot failed", exc_info=True)
        finally:
            with self._proof_snapshot_lock:
                self._proof_snapshot_inflight = False

    def _maybe_prove_frame_from_probe(self, info: Any) -> None:
        if info is None:
            return
        get_buffer = getattr(info, "get_buffer", None)
        if get_buffer is None:
            return
        buf = get_buffer()
        if buf is None:
            return
        ok, map_info = buf.map(self._Gst.MapFlags.READ)
        if not ok:
            return
        try:
            self._maybe_write_proof_snapshot(memoryview(map_info.data))
        finally:
            buf.unmap(map_info)

    def _buffer_probe(self, pad: Any, info: Any, _user_data: Any) -> Any:
        del pad
        self._last_frame_monotonic = time.monotonic()
        self._maybe_prove_frame_from_probe(info)
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

    def cycle(self) -> bool:
        self.stop()
        time.sleep(0.2)
        return self.start()
