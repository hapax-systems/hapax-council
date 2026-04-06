"""Snapshot branches for the GStreamer pipeline."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from .config import SNAPSHOT_DIR

log = logging.getLogger(__name__)


def add_snapshot_branch(compositor: Any, pipeline: Any, tee: Any) -> None:
    """Add composited frame snapshot branch: tee -> queue -> jpeg -> appsink."""
    Gst = compositor._Gst

    queue = Gst.ElementFactory.make("queue", "queue-snapshot")
    queue.set_property("leaky", 2)
    queue.set_property("max-size-buffers", 1)
    convert = Gst.ElementFactory.make("videoconvert", "snapshot-convert")
    convert.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    scale = Gst.ElementFactory.make("videoscale", "snapshot-scale")
    scale_caps = Gst.ElementFactory.make("capsfilter", "snapshot-scale-caps")
    scale_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,width=1280,height=720"))
    rate = Gst.ElementFactory.make("videorate", "snapshot-rate")
    rate_caps = Gst.ElementFactory.make("capsfilter", "snapshot-rate-caps")
    rate_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,framerate=10/1"))
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
            return 1
        buf = sample.get_buffer()
        ok, mapinfo = buf.map(compositor._Gst.MapFlags.READ)
        if ok:
            try:
                tmp = SNAPSHOT_DIR / "snapshot.jpg.tmp"
                final = SNAPSHOT_DIR / "snapshot.jpg"
                data = bytes(mapinfo.data)
                fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
                try:
                    written = os.write(fd, data)
                finally:
                    os.close(fd)
                if written == len(data):
                    tmp.rename(final)
            finally:
                buf.unmap(mapinfo)
        return 0

    appsink.set_property("emit-signals", True)
    appsink.connect("new-sample", _on_new_sample)

    elements = [queue, convert, scale, scale_caps, rate, rate_caps, encoder, appsink]
    for el in elements:
        pipeline.add(el)

    queue.link(convert)
    convert.link(scale)
    scale.link(scale_caps)
    scale_caps.link(rate)
    rate.link(rate_caps)
    rate_caps.link(encoder)
    encoder.link(appsink)

    tee_pad = tee.request_pad(tee.get_pad_template("src_%u"), None, None)
    queue_sink = queue.get_static_pad("sink")
    tee_pad.link(queue_sink)


def add_fx_snapshot_branch(compositor: Any, pipeline: Any, tee: Any) -> None:
    """Add effected frame snapshot: tee -> queue -> nvjpegenc -> appsink -> fx-snapshot.jpg.

    Uses NVIDIA hardware JPEG encoder for GPU-speed encoding.  Falls back to
    CPU jpegenc if nvjpegenc is unavailable.  Target 30fps at 720p for smooth
    fullscreen preview in the Tauri frame server (:8053/fx).
    """
    Gst = compositor._Gst

    queue = Gst.ElementFactory.make("queue", "queue-fx-snap")
    queue.set_property("leaky", 2)
    queue.set_property("max-size-buffers", 2)

    # Simple CPU path: videoconvert → videoscale(640x360) → jpegenc(q=70)
    # Small resolution keeps CPU encoding fast enough for 30fps.
    # The WebSocket relay eliminates file I/O — the bottleneck that caused 1fps.
    convert = Gst.ElementFactory.make("videoconvert", "fx-snap-convert")
    convert.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    scale = Gst.ElementFactory.make("videoscale", "fx-snap-scale")
    scale_caps = Gst.ElementFactory.make("capsfilter", "fx-snap-scale-caps")
    scale_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,width=640,height=360"))
    jpeg = Gst.ElementFactory.make("jpegenc", "fx-snap-jpeg")
    jpeg.set_property("quality", 70)
    log.info("FX snapshot: CPU jpegenc at 640x360")

    appsink = Gst.ElementFactory.make("appsink", "fx-snapshot-sink")
    appsink.set_property("sync", False)
    appsink.set_property("async", False)
    appsink.set_property("drop", True)
    appsink.set_property("max-buffers", 1)

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    # TCP push socket to Tauri frame server (ws bridge at :8054)
    import socket
    import struct
    import threading

    frame_sock: socket.socket | None = None
    sock_lock = threading.Lock()
    last_connect_attempt: float = 0.0
    RECONNECT_COOLDOWN = 5.0  # seconds between TCP reconnect attempts

    def _ensure_sock() -> socket.socket | None:
        nonlocal frame_sock, last_connect_attempt
        if frame_sock is not None:
            return frame_sock
        now = time.monotonic()
        if now - last_connect_attempt < RECONNECT_COOLDOWN:
            return None  # backoff — don't spam reconnects
        last_connect_attempt = now
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.settimeout(0.5)
            s.connect(("127.0.0.1", 8054))
            frame_sock = s
            log.info("FX snapshot: connected to frame relay at :8054")
            return s
        except OSError:
            return None

    _fx_frame_count = [0]
    # Latest frame for background sender — overwritten each frame (drop-newest)
    _pending_frame: list[bytes | None] = [None]
    _frame_event = threading.Event()

    def _sender_loop() -> None:
        """Background thread: sends frames via TCP + writes to shm.
        Decoupled from the GStreamer streaming thread to prevent stalls."""
        nonlocal frame_sock
        while True:
            _frame_event.wait()
            _frame_event.clear()
            data = _pending_frame[0]
            if data is None:
                continue
            # TCP push
            with sock_lock:
                s = _ensure_sock()
                if s is not None:
                    try:
                        s.sendall(struct.pack("<I", len(data)) + data)
                    except OSError:
                        try:
                            s.close()
                        except OSError:
                            pass
                        frame_sock = None
            # File write (atomic rename)
            try:
                tmp = SNAPSHOT_DIR / "fx-snapshot.jpg.tmp"
                final = SNAPSHOT_DIR / "fx-snapshot.jpg"
                fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
                try:
                    os.write(fd, data)
                finally:
                    os.close(fd)
                tmp.rename(final)
            except OSError:
                pass

    sender_thread = threading.Thread(target=_sender_loop, daemon=True, name="fx-frame-sender")
    sender_thread.start()

    def _on_fx_sample(sink: Any) -> int:
        _fx_frame_count[0] += 1
        if _fx_frame_count[0] <= 3 or _fx_frame_count[0] % 300 == 0:
            log.info("FX snapshot: frame %d received", _fx_frame_count[0])
        sample = sink.emit("pull-sample")
        if sample is None:
            return 1
        buf = sample.get_buffer()
        ok, mapinfo = buf.map(compositor._Gst.MapFlags.READ)
        if ok:
            try:
                # Copy bytes and hand off to background sender — return immediately
                _pending_frame[0] = bytes(mapinfo.data)
                _frame_event.set()
            finally:
                buf.unmap(mapinfo)
        return 0

    appsink.set_property("emit-signals", True)
    appsink.connect("new-sample", _on_fx_sample)

    elements = [queue, convert, scale, scale_caps, jpeg, appsink]

    for el in elements:
        if el is None:
            log.error("Failed to create FX snapshot element")
            return
        pipeline.add(el)

    # Link chain sequentially
    for i in range(len(elements) - 1):
        if not elements[i].link(elements[i + 1]):
            log.error(
                "FX snapshot: failed to link %s → %s",
                elements[i].get_name(),
                elements[i + 1].get_name(),
            )

    tee_pad = tee.request_pad(tee.get_pad_template("src_%u"), None, None)
    queue_sink = queue.get_static_pad("sink")
    tee_pad.link(queue_sink)
