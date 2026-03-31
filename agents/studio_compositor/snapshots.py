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
    scale = Gst.ElementFactory.make("videoscale", "snapshot-scale")
    scale_caps = Gst.ElementFactory.make("capsfilter", "snapshot-scale-caps")
    scale_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,width=1920,height=1080"))
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
    """Add effected frame snapshot: tee -> queue -> jpeg -> appsink -> fx-snapshot.jpg."""
    Gst = compositor._Gst

    queue = Gst.ElementFactory.make("queue", "queue-fx-snap")
    queue.set_property("leaky", 2)
    queue.set_property("max-size-buffers", 1)
    convert = Gst.ElementFactory.make("videoconvert", "fx-snap-convert")
    scale = Gst.ElementFactory.make("videoscale", "fx-snap-scale")
    scale_caps = Gst.ElementFactory.make("capsfilter", "fx-snap-scale-caps")
    scale_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,width=1920,height=1080"))
    rate = Gst.ElementFactory.make("videorate", "fx-snap-rate")
    rate_caps = Gst.ElementFactory.make("capsfilter", "fx-snap-rate-caps")
    rate_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,framerate=12/1"))

    jpeg = Gst.ElementFactory.make("jpegenc", "fx-snap-jpeg")
    jpeg.set_property("quality", 85)

    appsink = Gst.ElementFactory.make("appsink", "fx-snapshot-sink")
    appsink.set_property("sync", False)
    appsink.set_property("async", False)
    appsink.set_property("drop", True)
    appsink.set_property("max-buffers", 1)

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    def _on_fx_sample(sink: Any) -> int:
        sample = sink.emit("pull-sample")
        if sample is None:
            return 1
        buf = sample.get_buffer()
        ok, mapinfo = buf.map(compositor._Gst.MapFlags.READ)
        if ok:
            try:
                tmp = SNAPSHOT_DIR / "fx-snapshot.jpg.tmp"
                final = SNAPSHOT_DIR / "fx-snapshot.jpg"
                data = bytes(mapinfo.data)
                fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
                try:
                    written = os.write(fd, data)
                finally:
                    os.close(fd)
                if written == len(data):
                    tmp.rename(final)
            except OSError:
                pass
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

    queue.link(convert)
    convert.link(scale)
    scale.link(scale_caps)
    scale_caps.link(rate)
    rate.link(rate_caps)
    rate_caps.link(jpeg)
    jpeg.link(appsink)

    tee_pad = tee.request_pad(tee.get_pad_template("src_%u"), None, None)
    queue_sink = queue.get_static_pad("sink")
    tee_pad.link(queue_sink)
