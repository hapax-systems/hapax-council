"""Snapshot branches for the GStreamer pipeline."""

from __future__ import annotations

import logging
import os
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


def add_llm_frame_snapshot_branch(compositor: Any, pipeline: Any, tee: Any) -> None:
    """Add LLM-bound frame snapshot branch — camera-only, NO Cairo wards.

    Phase 3 of the AUDIT-07 hallucination structural fix (companion to
    Phase 2 VinylSpinningEngine and Phase 2b MusicPlayingEngine). The
    director loop's prior LLM-bound capture used the post-FX, post-Cairo
    ``fx-snapshot.jpg``, which produced an OCR-dominance failure mode:
    the LLM read the cairo overlays it had previously authored and
    cycled them back into its next prompt as observed ground truth.

    This branch taps the SAME ``pre_fx_tee`` as ``add_snapshot_branch``
    (camera-only, post-cudacompositor, pre-FX-pre-Cairo) but writes to a
    distinct file ``frame_for_llm.jpg`` so the semantic boundary stays
    crisp: ``snapshot.jpg`` for arbitrary downstream consumers,
    ``frame_for_llm.jpg`` exclusively for LLM prompt context.

    Wards REMAIN visible to viewers — the broadcast frame is unchanged.
    Only the LLM's input switches to the camera-only buffer. Per-ward
    posterior badges (next phase, generalization of the splattribution
    fix) re-add wards with confidence-quantified visual contracts back
    into the LLM input where appropriate.
    """
    Gst = compositor._Gst

    queue = Gst.ElementFactory.make("queue", "queue-llm-frame")
    queue.set_property("leaky", 2)
    queue.set_property("max-size-buffers", 1)
    convert = Gst.ElementFactory.make("videoconvert", "llm-frame-convert")
    convert.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    scale = Gst.ElementFactory.make("videoscale", "llm-frame-scale")
    scale_caps = Gst.ElementFactory.make("capsfilter", "llm-frame-scale-caps")
    scale_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,width=1280,height=720"))
    rate = Gst.ElementFactory.make("videorate", "llm-frame-rate")
    rate_caps = Gst.ElementFactory.make("capsfilter", "llm-frame-rate-caps")
    # Director loop ticks at ~3-5s; 3fps cadence is more than enough and
    # cuts the JPEG-encode + atomic-write cost vs. snapshot.jpg's 10fps.
    rate_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,framerate=3/1"))
    encoder = Gst.ElementFactory.make("jpegenc", "llm-frame-jpeg")
    encoder.set_property("quality", 85)
    appsink = Gst.ElementFactory.make("appsink", "llm-frame-sink")
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
                tmp = SNAPSHOT_DIR / "frame_for_llm.jpg.tmp"
                final = SNAPSHOT_DIR / "frame_for_llm.jpg"
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
    log.info("LLM-bound frame snapshot branch: pre_fx_tee → frame_for_llm.jpg @ 3fps")


def add_fx_snapshot_branch(compositor: Any, pipeline: Any, tee: Any) -> None:
    """Add effected frame snapshot: tee -> queue -> nvjpegenc -> appsink -> fx-snapshot.jpg.

    Uses NVIDIA hardware JPEG encoder for GPU-speed encoding.  Falls back to
    CPU jpegenc if nvjpegenc is unavailable. Target 3fps at 720p for
    production inspection via /dev/shm/hapax-compositor/fx-snapshot.jpg.
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
    scale_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,width=1280,height=720"))
    # 2026-04-17 CPU audit: jpegenc at 30fps x 1280x720 dominated this
    # branch of the tee. The current production consumer is the atomic SHM
    # snapshot inspected through logos-api/studio tooling, so rate-limit to
    # 3fps and avoid the retired Tauri TCP frame relay entirely.
    rate = Gst.ElementFactory.make("videorate", "fx-snap-rate")
    if rate is not None:
        rate.set_property("drop-only", True)
        rate.set_property("max-rate", 3)
    rate_caps = Gst.ElementFactory.make("capsfilter", "fx-snap-rate-caps")
    rate_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,framerate=3/1"))
    jpeg = Gst.ElementFactory.make("jpegenc", "fx-snap-jpeg")
    jpeg.set_property("quality", 85)
    log.info("FX snapshot: CPU jpegenc at 1280x720, rate-limited to 3fps")

    appsink = Gst.ElementFactory.make("appsink", "fx-snapshot-sink")
    appsink.set_property("sync", False)
    appsink.set_property("async", False)
    appsink.set_property("drop", True)
    appsink.set_property("max-buffers", 1)

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    import threading

    _fx_frame_count = [0]
    # Latest frame for background writer - overwritten each frame (drop-newest)
    _pending_frame: list[bytes | None] = [None]
    _frame_event = threading.Event()

    def _sender_loop() -> None:
        """Background thread: writes the newest frame to shm.
        Decoupled from the GStreamer streaming thread to prevent stalls."""
        while True:
            _frame_event.wait()
            _frame_event.clear()
            data = _pending_frame[0]
            if data is None:
                continue
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

    elements = [queue, convert, scale, scale_caps, rate, rate_caps, jpeg, appsink]

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
