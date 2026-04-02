"""Smooth delay branch for the GStreamer pipeline."""

from __future__ import annotations

import logging
import os
from typing import Any

from .config import SNAPSHOT_DIR

log = logging.getLogger(__name__)


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
    rgba_caps = Gst.ElementFactory.make("capsfilter", "smooth-rgba-caps")
    rgba_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,format=RGBA"))

    glupload = Gst.ElementFactory.make("glupload", "smooth-glupload")
    glcc_in = Gst.ElementFactory.make("glcolorconvert", "smooth-glcc-in")
    smooth_delay.set_property("delay-seconds", 5.0)
    smooth_delay.set_property("fps", 10)  # must match pipeline framerate

    glcc_out = Gst.ElementFactory.make("glcolorconvert", "smooth-glcc-out")
    gldownload = Gst.ElementFactory.make("gldownload", "smooth-gldownload")
    out_convert = Gst.ElementFactory.make("videoconvert", "smooth-out-convert")
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
            except OSError:
                pass
            finally:
                buf.unmap(mapinfo)
        return 0

    sink.set_property("emit-signals", True)
    sink.connect("new-sample", _on_smooth_sample)

    elements = [
        queue,
        convert_rgba,
        rgba_caps,
        glupload,
        glcc_in,
        smooth_delay,
        glcc_out,
        gldownload,
        out_convert,
        scale,
        scale_caps,
        rate,
        rate_caps,
        jpeg,
        sink,
    ]
    for el in elements:
        if el is None:
            log.error("Failed to create smooth delay pipeline element")
            compositor._fx_smooth_delay = None
            return
        pipeline.add(el)

    queue.link(convert_rgba)
    convert_rgba.link(rgba_caps)
    rgba_caps.link(glupload)
    glupload.link(glcc_in)
    glcc_in.link(smooth_delay)
    smooth_delay.link(glcc_out)
    glcc_out.link(gldownload)
    gldownload.link(out_convert)
    out_convert.link(scale)
    scale.link(scale_caps)
    scale_caps.link(rate)
    rate.link(rate_caps)
    rate_caps.link(jpeg)
    jpeg.link(sink)

    tee_pad = tee.request_pad(tee.get_pad_template("src_%u"), None, None)
    queue_sink = queue.get_static_pad("sink")
    tee_pad.link(queue_sink)

    compositor._fx_smooth_delay = smooth_delay
    log.info("Smooth delay branch: 5.0s delay -> smooth-snapshot.jpg")
