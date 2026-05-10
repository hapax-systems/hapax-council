"""Smooth delay branch for the GStreamer pipeline."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from .config import SNAPSHOT_DIR
from .diagnostic_branch import (
    DiagnosticBranchLinkError,
    add_branch_elements_or_raise,
    attach_tee_branch_or_raise,
    link_chain_or_raise,
    record_diagnostic_frame,
)

log = logging.getLogger(__name__)

OUTPUT_FPS = 2.0
"""Smooth-snapshot output rate. Matches ``smooth-rate-caps`` downstream.

Any rate advertised to the downstream ``videorate`` element is the target;
the upstream ``_gldownload_drop_probe`` uses this same value to drop
buffers BEFORE the CPU download so ~28/30 frames per second do not get
transferred across the PCIe bus. Delta drop #29 finding 3 measured
~250 MB/s of wasted GPU→CPU bandwidth before this fix."""


def should_pass_gldownload(now_ts: float, last_pass_ts: float, fps: float = OUTPUT_FPS) -> bool:
    """Return True iff a buffer at ``now_ts`` should pass the gldownload
    probe given the last successful pass at ``last_pass_ts``.

    Pure function so the pad-probe throttling logic can be unit-tested
    without a live GStreamer pipeline. Returns True when at least
    ``1/fps`` seconds have elapsed since ``last_pass_ts``.
    """
    if fps <= 0:
        return True
    min_interval = 1.0 / fps
    return (now_ts - last_pass_ts) >= min_interval


def add_smooth_delay_branch(compositor: Any, pipeline: Any, tee: Any) -> None:
    """Add smooth delay branch -- @smooth layer source."""
    Gst = compositor._Gst

    smooth_delay = Gst.ElementFactory.make("smoothdelay", "smooth-delay")
    if smooth_delay is None:
        log.warning("smoothdelay plugin not found — @smooth layer disabled")
        compositor._fx_smooth_delay = None
        return

    queue = Gst.ElementFactory.make("queue", "queue-smooth")
    queue.set_property("leaky", 2)
    queue.set_property("max-size-buffers", 2)

    convert_rgba = Gst.ElementFactory.make("videoconvert", "smooth-convert-rgba")
    convert_rgba.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    rgba_caps = Gst.ElementFactory.make("capsfilter", "smooth-rgba-caps")
    rgba_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,format=RGBA"))

    glupload = Gst.ElementFactory.make("glupload", "smooth-glupload")
    glcc_in = Gst.ElementFactory.make("glcolorconvert", "smooth-glcc-in")
    smooth_delay.set_property("delay-seconds", 5.0)
    smooth_delay.set_property("fps", compositor.config.framerate)

    glcc_out = Gst.ElementFactory.make("glcolorconvert", "smooth-glcc-out")
    gldownload = Gst.ElementFactory.make("gldownload", "smooth-gldownload")

    # Delta 2026-04-14-camera-pipeline-walk-followups finding 3
    # (cam-stability rollup Ring 1 item F): the downstream ``videorate``
    # drops 28/30 frames per second anyway, but currently runs AFTER
    # ``gldownload``, so every frame pays the full 1920×1080×4 =
    # 8.3 MB PCIe transfer. Measured waste: ~250 MB/s of GPU→CPU
    # bandwidth. This pad probe samples at ``OUTPUT_FPS`` (2 Hz) BEFORE
    # the download so only the frames that will actually survive
    # videorate make it across the bus. Idempotent monotonic check —
    # no global state, no locks required (GStreamer pad probes run
    # single-threaded per pad).
    _gldownload_last_pass_ts: list[float] = [0.0]  # mutable cell for closure

    def _gldownload_drop_probe(pad: Any, info: Any) -> Any:
        now = time.monotonic()
        if should_pass_gldownload(now, _gldownload_last_pass_ts[0], OUTPUT_FPS):
            _gldownload_last_pass_ts[0] = now
            return Gst.PadProbeReturn.OK
        return Gst.PadProbeReturn.DROP

    gldownload_sink_pad = gldownload.get_static_pad("sink")
    if gldownload_sink_pad is not None:
        gldownload_sink_pad.add_probe(Gst.PadProbeType.BUFFER, _gldownload_drop_probe)
    out_convert = Gst.ElementFactory.make("videoconvert", "smooth-out-convert")
    out_convert.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    scale = Gst.ElementFactory.make("videoscale", "smooth-scale")
    scale_caps = Gst.ElementFactory.make("capsfilter", "smooth-scale-caps")
    scale_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,width=640,height=360"))
    rate = Gst.ElementFactory.make("videorate", "smooth-rate")
    rate_caps = Gst.ElementFactory.make("capsfilter", "smooth-rate-caps")
    rate_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,framerate=2/1"))

    jpeg = Gst.ElementFactory.make("jpegenc", "smooth-jpeg")
    jpeg.set_property("quality", 85)

    sink = Gst.ElementFactory.make("appsink", "smooth-snapshot-sink")
    sink.set_property("sync", False)
    sink.set_property("async", False)
    sink.set_property("drop", True)
    sink.set_property("max-buffers", 1)

    def _on_smooth_sample(appsink: Any) -> int:
        sample = appsink.emit("pull-sample")
        if sample is None:
            return 1
        buf = sample.get_buffer()
        ok, mapinfo = buf.map(compositor._Gst.MapFlags.READ)
        if ok:
            try:
                tmp = SNAPSHOT_DIR / "smooth-snapshot.jpg.tmp"
                final_ = SNAPSHOT_DIR / "smooth-snapshot.jpg"
                data = bytes(mapinfo.data)
                fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
                try:
                    written = os.write(fd, data)
                finally:
                    os.close(fd)
                if written == len(data):
                    tmp.rename(final_)
                    record_diagnostic_frame("smooth_delay_snapshot")
            except OSError:
                pass
            finally:
                buf.unmap(mapinfo)
        return 0

    sink.set_property("emit-signals", True)
    sink.connect("new-sample", _on_smooth_sample)

    branch = "smooth delay branch"
    try:
        elements = add_branch_elements_or_raise(
            pipeline,
            [
                ("queue-smooth", queue),
                ("smooth-convert-rgba", convert_rgba),
                ("smooth-rgba-caps", rgba_caps),
                ("smooth-glupload", glupload),
                ("smooth-glcc-in", glcc_in),
                ("smooth-delay", smooth_delay),
                ("smooth-glcc-out", glcc_out),
                ("smooth-gldownload", gldownload),
                ("smooth-out-convert", out_convert),
                ("smooth-scale", scale),
                ("smooth-scale-caps", scale_caps),
                ("smooth-rate", rate),
                ("smooth-rate-caps", rate_caps),
                ("smooth-jpeg", jpeg),
                ("smooth-snapshot-sink", sink),
            ],
            branch=branch,
        )
        link_chain_or_raise(elements, branch=branch)
        attach_tee_branch_or_raise(Gst, tee, queue, branch=branch)
    except DiagnosticBranchLinkError:
        compositor._fx_smooth_delay = None
        raise

    compositor._fx_smooth_delay = smooth_delay
    log.info("Smooth delay branch: 5.0s delay -> smooth-snapshot.jpg")
