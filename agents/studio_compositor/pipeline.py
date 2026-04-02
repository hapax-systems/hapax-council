"""GStreamer pipeline construction for the compositor."""

from __future__ import annotations

import logging
from typing import Any

from .cameras import add_camera_branch
from .layout import compute_tile_layout
from .recording import add_hls_branch
from .smooth_delay import add_smooth_delay_branch
from .snapshots import add_fx_snapshot_branch, add_snapshot_branch

log = logging.getLogger(__name__)


def init_gstreamer() -> tuple[Any, Any]:
    """Import and initialize GStreamer. Returns (GLib, Gst) modules."""
    import gi as _gi

    _gi.require_version("Gst", "1.0")
    from gi.repository import GLib as _GLib
    from gi.repository import Gst as _Gst

    _Gst.init(None)
    return _GLib, _Gst


def build_pipeline(compositor: Any) -> Any:
    """Build the full GStreamer pipeline."""
    Gst = compositor._Gst

    pipeline = Gst.Pipeline.new("studio-compositor")
    layout = compute_tile_layout(
        compositor.config.cameras, compositor.config.output_width, compositor.config.output_height
    )
    compositor._tile_layout = layout

    comp_element = Gst.ElementFactory.make("cudacompositor", "compositor")
    if comp_element is None:
        raise RuntimeError(
            "cudacompositor plugin not available -- install gst-plugins-bad with CUDA"
        )
    pipeline.add(comp_element)

    fps = compositor.config.framerate

    for cam in compositor.config.cameras:
        tile = layout.get(cam.role)
        if tile is None:
            log.warning("No tile for camera %s, skipping", cam.role)
            continue
        add_camera_branch(compositor, pipeline, comp_element, cam, tile, fps)

    # Output chain: compositor -> cudadownload -> BGRA -> cairooverlay -> pre_fx_tee
    download = Gst.ElementFactory.make("cudadownload", "download")
    convert_bgra = Gst.ElementFactory.make("videoconvert", "convert-bgra")
    bgra_caps = Gst.ElementFactory.make("capsfilter", "bgra-caps")
    bgra_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            f"video/x-raw,format=BGRA,width={compositor.config.output_width},"
            f"height={compositor.config.output_height},framerate={fps}/1"
        ),
    )

    from .overlay import on_draw, on_overlay_caps_changed

    overlay = Gst.ElementFactory.make("cairooverlay", "overlay")
    overlay.connect("draw", lambda o, cr, ts, dur: on_draw(compositor, o, cr, ts, dur))
    overlay.connect("caps-changed", lambda o, caps: on_overlay_caps_changed(compositor, o, caps))

    pre_fx_tee = Gst.ElementFactory.make("tee", "pre-fx-tee")

    elements_pre = [download, convert_bgra, bgra_caps, overlay, pre_fx_tee]
    for el in elements_pre:
        if el is None:
            raise RuntimeError("Failed to create GStreamer element")
        pipeline.add(el)

    prev = comp_element
    for el in elements_pre:
        if not prev.link(el):
            raise RuntimeError(f"Failed to link {prev.get_name()} -> {el.get_name()}")
        prev = el

    add_snapshot_branch(compositor, pipeline, pre_fx_tee)

    output_tee = Gst.ElementFactory.make("tee", "output-tee")
    pipeline.add(output_tee)

    from .fx_chain import build_inline_fx_chain

    fx_ok = build_inline_fx_chain(compositor, pipeline, pre_fx_tee, output_tee, fps)
    if not fx_ok:
        log.warning("FX chain failed to initialize — bypassing effects")
        bypass_queue = Gst.ElementFactory.make("queue", "queue-fx-bypass")
        bypass_queue.set_property("leaky", 2)
        bypass_queue.set_property("max-size-buffers", 2)
        pipeline.add(bypass_queue)
        bypass_queue.link(output_tee)
        tee_pad = pre_fx_tee.request_pad(pre_fx_tee.get_pad_template("src_%u"), None, None)
        queue_sink = bypass_queue.get_static_pad("sink")
        tee_pad.link(queue_sink)

    # v4l2sink branch
    queue_v4l2 = Gst.ElementFactory.make("queue", "queue-v4l2")
    queue_v4l2.set_property("leaky", 2)  # drop oldest, keep newest for temporal coherence
    queue_v4l2.set_property("max-size-buffers", 2)
    convert_out = Gst.ElementFactory.make("videoconvert", "convert-out")
    sink_caps = Gst.ElementFactory.make("capsfilter", "sink-caps")
    sink_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            f"video/x-raw,format=YUY2,width={compositor.config.output_width},"
            f"height={compositor.config.output_height},framerate={fps}/1"
        ),
    )
    sink = Gst.ElementFactory.make("v4l2sink", "output")
    sink.set_property("device", compositor.config.output_device)
    sink.set_property("sync", False)

    for el in [queue_v4l2, convert_out, sink_caps, sink]:
        pipeline.add(el)

    queue_v4l2.link(convert_out)
    convert_out.link(sink_caps)
    sink_caps.link(sink)

    tee_pad = output_tee.request_pad(output_tee.get_pad_template("src_%u"), None, None)
    queue_sink_pad = queue_v4l2.get_static_pad("sink")
    tee_pad.link(queue_sink_pad)

    if compositor.config.hls.enabled:
        add_hls_branch(compositor, pipeline, output_tee, fps)

    add_fx_snapshot_branch(compositor, pipeline, output_tee)
    add_smooth_delay_branch(compositor, pipeline, output_tee)

    return pipeline
