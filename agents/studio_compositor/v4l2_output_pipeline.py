"""Isolated v4l2 output pipeline via interpipesrc + appsink + os.write.

Decouples the v4l2 output from the main compositor pipeline. Frames
arrive through interpipesrc, reach an appsink, and are written to the
v4l2loopback device fd with os.write(). On write failure (EAGAIN, EIO,
ENODEV) the fd is closed and reopened — no GStreamer pipeline teardown
required.

Graph::

    interpipesrc(listen-to="compositor_v4l2_out")
      → queue(leaky=downstream, max-size-buffers=5)
      → videoconvert(dither=0)
      → capsfilter(video/x-raw,format=NV12,width×height,fps)
      → appsink(emit-signals=True, max-buffers=2, drop=True)

The main pipeline ends at an ``interpipesink`` named
``compositor_v4l2_out`` on ``output_tee``. This class consumes from
that channel — same pattern as ``CameraPipeline`` but inverted.
"""

from __future__ import annotations

import errno
import logging
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import SNAPSHOT_DIR

log = logging.getLogger(__name__)

INTERPIPE_CHANNEL = "compositor_v4l2_out"

_RECOVERABLE_ERRNOS = frozenset({errno.EAGAIN, errno.EIO, errno.ENODEV, errno.ENXIO})
_FD_REOPEN_DELAY_S = 0.1
_DEFAULT_PROOF_SNAPSHOT_INTERVAL_S = 1.0
_V4L2_FORMAT_GUARD_ENV = "HAPAX_V4L2_FORMAT_GUARD"
_V4L2_CTL_ENV = "HAPAX_V4L2_CTL"


def _set_optional_property(element: Any, name: str, value: Any) -> None:
    try:
        element.set_property(name, value)
    except Exception:
        log.debug("v4l2 interpipesrc property not supported: %s", name, exc_info=True)


def _v4l2_output_format_already_pinned(
    *,
    v4l2_ctl: str,
    device: str,
    width: int,
    height: int,
    fps: int,
    pixelformat: str,
) -> bool:
    try:
        result = subprocess.run(
            (
                v4l2_ctl,
                "-d",
                device,
                "--get-fmt-video-out",
                "--get-fmt-video",
                "--get-ctrl",
                "keep_format",
                "--get-parm",
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        log.debug("v4l2 format guard query failed for %s", device, exc_info=True)
        return False
    if result.returncode != 0:
        return False
    output = result.stdout
    expected_size = f"Width/Height      : {width}/{height}"
    expected_pixfmt = f"Pixel Format      : '{pixelformat}'"
    fps_match = re.search(r"Frames per second:\s*([0-9]+(?:\.[0-9]+)?)", output)
    fps_ok = fps_match is not None and abs(float(fps_match.group(1)) - float(fps)) < 0.01
    return (
        output.count(expected_size) >= 2
        and output.count(expected_pixfmt) >= 2
        and "keep_format: 1" in output
        and fps_ok
    )


def _enforce_v4l2_output_format(
    *,
    device: str,
    width: int,
    height: int,
    fps: int,
    pixelformat: str = "NV12",
) -> bool:
    if os.environ.get(_V4L2_FORMAT_GUARD_ENV, "1") == "0":
        return True
    if not device.startswith("/dev/"):
        return True

    v4l2_ctl = os.environ.get(_V4L2_CTL_ENV, "v4l2-ctl")
    if _v4l2_output_format_already_pinned(
        v4l2_ctl=v4l2_ctl,
        device=device,
        width=width,
        height=height,
        fps=fps,
        pixelformat=pixelformat,
    ):
        return True

    fmt = f"width={width},height={height},pixelformat={pixelformat}"
    commands = (
        (v4l2_ctl, "-d", device, f"--set-fmt-video-out={fmt}"),
        (v4l2_ctl, "-d", device, f"--set-fmt-video={fmt}"),
        (v4l2_ctl, "-d", device, f"--set-parm={fps}"),
        (v4l2_ctl, "-d", device, "-c", "keep_format=1"),
    )
    for command in commands:
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.error("v4l2 format guard failed before opening %s: %s", device, exc)
            return False
        if result.returncode != 0:
            log.error(
                "v4l2 format guard command failed before opening %s: %s stderr=%s",
                device,
                " ".join(command),
                result.stderr.strip(),
            )
            return False
    return True


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
        proof_snapshot_path: str | os.PathLike[str] | None = None,
        proof_snapshot_interval_s: float | None = None,
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

        self._fd: int = -1
        self._fd_lock = threading.Lock()
        self._fd_reopen_count: int = 0
        self._fd_write_error_count: int = 0

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

    @property
    def last_frame_age_seconds(self) -> float:
        if self._last_frame_monotonic <= 0.0:
            return float("inf")
        return time.monotonic() - self._last_frame_monotonic

    @property
    def fd_reopen_count(self) -> int:
        return self._fd_reopen_count

    @property
    def fd_write_error_count(self) -> int:
        return self._fd_write_error_count

    def _open_fd(self) -> bool:
        with self._fd_lock:
            if self._fd >= 0:
                return True
            if not _enforce_v4l2_output_format(
                device=self._device,
                width=self._width,
                height=self._height,
                fps=self._fps,
            ):
                return False
            try:
                self._fd = os.open(self._device, os.O_WRONLY | os.O_NONBLOCK)
                log.info("Opened v4l2 device fd=%d: %s", self._fd, self._device)
                return True
            except OSError as exc:
                log.warning("Failed to open %s: %s", self._device, exc)
                self._fd = -1
                return False

    def _close_fd(self) -> None:
        with self._fd_lock:
            if self._fd >= 0:
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = -1

    def _reopen_fd(self) -> bool:
        self._close_fd()
        time.sleep(_FD_REOPEN_DELAY_S)
        opened = self._open_fd()
        if opened:
            self._fd_reopen_count += 1
            try:
                from . import metrics as _m

                if _m.V4L2SINK_FD_REOPENS_TOTAL is not None:
                    _m.V4L2SINK_FD_REOPENS_TOTAL.inc()
            except Exception:
                pass
            log.info("Reopened v4l2 fd (total reopens: %d)", self._fd_reopen_count)
        return opened

    def _write_frame(self, data: bytes | bytearray | memoryview) -> bool:
        with self._fd_lock:
            if self._fd < 0:
                return False
            try:
                written = os.write(self._fd, data)
                if written != len(data):
                    self._fd_write_error_count += 1
                    log.warning(
                        "v4l2 partial write, scheduling fd reopen: wrote %d of %d bytes",
                        written,
                        len(data),
                    )
                    return False
                return True
            except OSError as exc:
                self._fd_write_error_count += 1
                if exc.errno in _RECOVERABLE_ERRNOS:
                    log.warning("v4l2 write error (errno=%d), scheduling fd reopen", exc.errno)
                else:
                    log.error("v4l2 write error (unexpected errno=%d): %s", exc.errno, exc)
                return False

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
            name="v4l2-proof-snapshot",
        )
        thread.start()

    def _write_proof_snapshot_jpeg(self, data: bytes) -> None:
        """Write final-egress proof JPEG from the exact NV12 frame sent to v4l2.

        The legacy ``fx-snapshot.jpg`` tee branch can go stale independently
        of the broadcast path. This writer is intentionally downstream of
        interpipesrc conversion, so a fresh proof image means the final frame
        reached the same appsink that writes ``/dev/video42``.
        """
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
                log.warning("final-egress proof snapshot unavailable: %s", exc)
                self._proof_snapshot_failure_logged = True
            else:
                log.debug("final-egress proof snapshot failed", exc_info=True)
        finally:
            with self._proof_snapshot_lock:
                self._proof_snapshot_inflight = False

    def _on_new_sample(self, appsink: Any) -> Any:
        Gst = self._Gst
        sample = appsink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK

        buf = sample.get_buffer()
        if buf is None:
            return Gst.FlowReturn.OK

        ok, map_info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK

        try:
            data = memoryview(map_info.data)
            try:
                from . import metrics as _m

                _m.record_v4l2_appsink_copy(len(data))
            except Exception:
                pass
            written = self._write_frame(data)
            if written:
                self._last_frame_monotonic = time.monotonic()
                self._maybe_write_proof_snapshot(data)
        finally:
            buf.unmap(map_info)

        if written:
            try:
                from . import metrics as _m

                _m.record_render_stage_frame("v4l2_appsink")
            except Exception:
                pass
            if self._on_frame is not None:
                try:
                    self._on_frame()
                except Exception:
                    pass
        else:
            threading.Thread(target=self._reopen_fd, daemon=True).start()

        return Gst.FlowReturn.OK

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
            _set_optional_property(src, "stream-sync", "restart-ts")
            _set_optional_property(src, "is-live", True)
            _set_optional_property(src, "format", Gst.Format.TIME)
            _set_optional_property(src, "automatic-eos", False)
            _set_optional_property(src, "accept-eos-event", False)

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

            appsink = Gst.ElementFactory.make("appsink", "output")
            if appsink is None:
                raise RuntimeError("appsink factory failed")
            appsink.set_property("emit-signals", True)
            appsink.set_property("max-buffers", 2)
            appsink.set_property("drop", True)
            appsink.set_property("sync", False)
            appsink.connect("new-sample", self._on_new_sample)

            for el in (src, queue, convert, caps, appsink):
                pipeline.add(el)
            src.link(queue)
            queue.link(convert)
            convert.link(caps)
            caps.link(appsink)

            bus = pipeline.get_bus()
            bus.add_signal_watch()
            sig_id = bus.connect("message::error", self._on_bus_error)

            self._pipeline = pipeline
            self._bus = bus
            self._bus_signal_id = sig_id
            log.info(
                "V4l2OutputPipeline built: %s → appsink → os.write(%s)",
                INTERPIPE_CHANNEL,
                self._device,
            )

    def _on_bus_error(self, _bus: Any, message: Any) -> None:
        err, debug = message.parse_error()
        log.error("V4l2OutputPipeline bus error: %s (%s)", err.message, debug)

    def start(self) -> bool:
        with self._state_lock:
            if self._pipeline is None:
                log.error("V4l2OutputPipeline: start called without build")
                return False

            if not self._open_fd():
                log.error("V4l2OutputPipeline: failed to open %s", self._device)
                return False

            Gst = self._Gst
            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                log.error("V4l2OutputPipeline: set_state(PLAYING) FAILURE")
                self._close_fd()
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
            self._close_fd()
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
