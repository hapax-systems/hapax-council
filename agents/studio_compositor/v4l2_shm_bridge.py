"""SHM-to-v4l2 sidecar using appsink + ``os.write``.

The compositor can write final NV12 frames to ``shmsink``. This module reads
that socket with ``shmsrc`` and writes frames to ``/dev/video42`` directly.
It deliberately avoids GStreamer's ``v4l2sink`` because runtime canaries found
that the sink can fail inside the v4l2 buffer pool while the same loopback
device remains writable through the direct ``os.write`` path.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .v4l2_output_pipeline import _RECOVERABLE_ERRNOS, _enforce_v4l2_output_format

log = logging.getLogger(__name__)

DEFAULT_DEVICE = "/dev/video42"
DEFAULT_SOCKET = "/dev/shm/hapax-compositor/v4l2-bridge.sock"
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_FPS = 30
DEFAULT_WAIT_SECONDS = 60
DEFAULT_METRICS_PATH = "/dev/shm/hapax-compositor/v4l2-bridge.prom"
_FD_REOPEN_DELAY_S = 0.1


@dataclass(frozen=True)
class BridgeConfig:
    device: str
    socket_path: str
    width: int
    height: int
    fps: int
    wait_seconds: int
    metrics_path: Path

    @property
    def caps(self) -> str:
        return (
            "video/x-raw,format=NV12,"
            f"width={self.width},height={self.height},framerate={self.fps}/1"
        )


@dataclass
class BridgeCounters:
    frames: int = 0
    bytes: int = 0
    errors: int = 0
    reconnects: int = 0
    last_frame_monotonic: float = 0.0


def socket_listening(socket_path: str) -> bool:
    try:
        result = subprocess.run(
            ("ss", "-xlH"),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[1] == "LISTEN" and fields[4] == socket_path:
            return True
    return False


def wait_for_socket(socket_path: str, wait_seconds: int) -> bool:
    waited = 0
    while waited < wait_seconds:
        if Path(socket_path).is_socket() and socket_listening(socket_path):
            log.info("socket listening after %ss: %s", waited, socket_path)
            return True
        time.sleep(1)
        waited += 1
    return Path(socket_path).is_socket() and socket_listening(socket_path)


class ShmToV4l2Bridge:
    def __init__(self, config: BridgeConfig, gst: Any, glib: Any) -> None:
        self._config = config
        self._Gst = gst
        self._GLib = glib
        self._pipeline: Any = None
        self._fd = -1
        self._fd_lock = threading.Lock()
        self._counters = BridgeCounters()
        self._metrics_lock = threading.Lock()
        self._loop: Any = None
        self._stopping = False
        self._failed = False

    @property
    def counters(self) -> BridgeCounters:
        return self._counters

    def _open_fd(self) -> bool:
        with self._fd_lock:
            if self._fd >= 0:
                return True
            if not _enforce_v4l2_output_format(
                device=self._config.device,
                width=self._config.width,
                height=self._config.height,
                fps=self._config.fps,
            ):
                return False
            try:
                self._fd = os.open(self._config.device, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as exc:
                log.warning("failed to open %s: %s", self._config.device, exc)
                self._fd = -1
                return False
            log.info("opened v4l2 device fd=%d: %s", self._fd, self._config.device)
            return True

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
            self._counters.reconnects += 1
            self._write_metrics()
        return opened

    def _write_frame(self, data: bytes | bytearray | memoryview) -> bool:
        with self._fd_lock:
            if self._fd < 0:
                return False
            try:
                written = os.write(self._fd, data)
            except OSError as exc:
                self._counters.errors += 1
                level = logging.WARNING if exc.errno in _RECOVERABLE_ERRNOS else logging.ERROR
                log.log(level, "v4l2 write failed errno=%s: %s", exc.errno, exc)
                return False
            if written != len(data):
                self._counters.errors += 1
                log.warning("partial v4l2 write: wrote %d of %d bytes", written, len(data))
                return False
            return True

    def _on_sample(self, appsink: Any) -> Any:
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

        written = False
        try:
            data = memoryview(map_info.data)
            written = self._write_frame(data)
            if written:
                self._counters.frames += 1
                self._counters.bytes += len(data)
                self._counters.last_frame_monotonic = time.monotonic()
                self._write_metrics()
        finally:
            buf.unmap(map_info)

        if not written and not self._stopping:
            self._write_metrics()
            self._reopen_fd()
        return Gst.FlowReturn.OK

    def _on_bus_error(self, _bus: Any, message: Any) -> None:
        err, debug = message.parse_error()
        log.error("bridge pipeline error: %s (%s)", err.message, debug)
        self._failed = True
        self.stop()

    def _on_bus_eos(self, _bus: Any, _message: Any) -> None:
        log.warning("bridge pipeline received EOS")
        self._failed = True
        self.stop()

    def build(self) -> None:
        Gst = self._Gst
        pipeline = Gst.Pipeline.new("hapax_v4l2_shm_bridge")

        src = Gst.ElementFactory.make("shmsrc", "bridge_shmsrc")
        if src is None:
            raise RuntimeError("shmsrc factory failed")
        src.set_property("socket-path", self._config.socket_path)
        src.set_property("do-timestamp", True)
        src.set_property("is-live", True)

        src_caps = Gst.ElementFactory.make("capsfilter", "bridge_src_caps")
        src_caps.set_property("caps", Gst.Caps.from_string(self._config.caps))

        queue = Gst.ElementFactory.make("queue", "bridge_queue")
        queue.set_property("leaky", 2)
        queue.set_property("max-size-buffers", 5)
        queue.set_property("max-size-bytes", 0)
        queue.set_property("max-size-time", 0)

        convert = Gst.ElementFactory.make("videoconvert", "bridge_convert")
        convert.set_property("dither", 0)

        out_caps = Gst.ElementFactory.make("capsfilter", "bridge_out_caps")
        out_caps.set_property("caps", Gst.Caps.from_string(self._config.caps))

        appsink = Gst.ElementFactory.make("appsink", "bridge_output")
        if appsink is None:
            raise RuntimeError("appsink factory failed")
        appsink.set_property("emit-signals", True)
        appsink.set_property("max-buffers", 2)
        appsink.set_property("drop", True)
        appsink.set_property("sync", False)
        appsink.connect("new-sample", self._on_sample)

        for element in (src, src_caps, queue, convert, out_caps, appsink):
            pipeline.add(element)
        src.link(src_caps)
        src_caps.link(queue)
        queue.link(convert)
        convert.link(out_caps)
        out_caps.link(appsink)

        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_bus_error)
        bus.connect("message::eos", self._on_bus_eos)
        self._pipeline = pipeline

    def start(self) -> bool:
        if self._pipeline is None:
            self.build()
        if not self._open_fd():
            return False
        ret = self._pipeline.set_state(self._Gst.State.PLAYING)
        if ret == self._Gst.StateChangeReturn.FAILURE:
            log.error("bridge pipeline refused PLAYING")
            self._close_fd()
            return False
        self._write_metrics()
        log.info("bridge pipeline started")
        return True

    def _metrics_tick(self) -> bool:
        self._write_metrics()
        return not self._stopping

    def stop(self) -> None:
        self._stopping = True
        if self._pipeline is not None:
            self._pipeline.set_state(self._Gst.State.NULL)
        self._close_fd()
        self._write_metrics()
        if self._loop is not None and self._loop.is_running():
            self._loop.quit()

    def run(self) -> int:
        if not self.start():
            self._counters.errors += 1
            self._write_metrics()
            return 1
        self._loop = self._GLib.MainLoop()
        self._GLib.timeout_add_seconds(1, self._metrics_tick)
        try:
            self._loop.run()
        except KeyboardInterrupt:
            self.stop()
        return 1 if self._failed else 0

    def _write_metrics(self) -> None:
        with self._metrics_lock:
            last = self._counters.last_frame_monotonic
            age = 9999.0 if last <= 0 else max(0.0, time.monotonic() - last)
            text = (
                "# HELP hapax_v4l2_bridge_write_frames_total Frames written by the SHM bridge to v4l2.\n"
                "# TYPE hapax_v4l2_bridge_write_frames_total counter\n"
                f"hapax_v4l2_bridge_write_frames_total {self._counters.frames}\n"
                "# HELP hapax_v4l2_bridge_write_bytes_total Bytes written by the SHM bridge to v4l2.\n"
                "# TYPE hapax_v4l2_bridge_write_bytes_total counter\n"
                f"hapax_v4l2_bridge_write_bytes_total {self._counters.bytes}\n"
                "# HELP hapax_v4l2_bridge_write_errors_total Failed writes by the SHM bridge.\n"
                "# TYPE hapax_v4l2_bridge_write_errors_total counter\n"
                f"hapax_v4l2_bridge_write_errors_total {self._counters.errors}\n"
                "# HELP hapax_v4l2_bridge_reconnects_total v4l2 fd reopen attempts that succeeded.\n"
                "# TYPE hapax_v4l2_bridge_reconnects_total counter\n"
                f"hapax_v4l2_bridge_reconnects_total {self._counters.reconnects}\n"
                "# HELP hapax_v4l2_bridge_heartbeat_seconds_ago Seconds since bridge last wrote a frame.\n"
                "# TYPE hapax_v4l2_bridge_heartbeat_seconds_ago gauge\n"
                f"hapax_v4l2_bridge_heartbeat_seconds_ago {age:.6f}\n"
            )
            self._config.metrics_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._config.metrics_path.with_name(self._config.metrics_path.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self._config.metrics_path)


def _parse_args(argv: list[str]) -> BridgeConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device", default=os.environ.get("HAPAX_V4L2_BRIDGE_DEVICE", DEFAULT_DEVICE)
    )
    parser.add_argument(
        "--socket", default=os.environ.get("HAPAX_V4L2_BRIDGE_SOCKET", DEFAULT_SOCKET)
    )
    parser.add_argument(
        "--width", type=int, default=int(os.environ.get("HAPAX_V4L2_BRIDGE_WIDTH", DEFAULT_WIDTH))
    )
    parser.add_argument(
        "--height",
        type=int,
        default=int(os.environ.get("HAPAX_V4L2_BRIDGE_HEIGHT", DEFAULT_HEIGHT)),
    )
    parser.add_argument(
        "--fps", type=int, default=int(os.environ.get("HAPAX_V4L2_BRIDGE_FPS", DEFAULT_FPS))
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=int(os.environ.get("HAPAX_V4L2_BRIDGE_WAIT_SECONDS", DEFAULT_WAIT_SECONDS)),
    )
    parser.add_argument(
        "--metrics-path",
        default=os.environ.get("HAPAX_V4L2_BRIDGE_METRICS_PATH", DEFAULT_METRICS_PATH),
    )
    args = parser.parse_args(argv)
    return BridgeConfig(
        device=args.device,
        socket_path=args.socket,
        width=args.width,
        height=args.height,
        fps=args.fps,
        wait_seconds=args.wait_seconds,
        metrics_path=Path(args.metrics_path),
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("HAPAX_V4L2_BRIDGE_LOG_LEVEL", "INFO"))
    config = _parse_args(sys.argv[1:] if argv is None else argv)
    if not wait_for_socket(config.socket_path, config.wait_seconds):
        log.error(
            "socket %s missing or not listening after %ss",
            config.socket_path,
            config.wait_seconds,
        )
        return 1

    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import GLib, Gst

    Gst.init(None)
    bridge = ShmToV4l2Bridge(config, Gst, GLib)

    def _stop(_signum: int, _frame: object) -> None:
        bridge.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    return bridge.run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
