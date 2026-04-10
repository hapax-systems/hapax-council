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

    # Try cudacompositor first, fall back to CPU compositor
    comp_element = Gst.ElementFactory.make("cudacompositor", "compositor")
    compositor._use_cuda = comp_element is not None
    if comp_element is None:
        log.warning("cudacompositor unavailable — falling back to CPU compositor")
        comp_element = Gst.ElementFactory.make("compositor", "compositor")
        if comp_element is None:
            raise RuntimeError("Neither cudacompositor nor compositor plugin available")
    pipeline.add(comp_element)

    fps = compositor.config.framerate

    for cam in compositor.config.cameras:
        tile = layout.get(cam.role)
        if tile is None:
            log.warning("No tile for camera %s, skipping", cam.role)
            continue
        add_camera_branch(compositor, pipeline, comp_element, cam, tile, fps)

    # Output chain: compositor -> [cudadownload] -> BGRA -> pre_fx_tee
    convert_bgra = Gst.ElementFactory.make("videoconvert", "convert-bgra")
    convert_bgra.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    bgra_caps = Gst.ElementFactory.make("capsfilter", "bgra-caps")
    bgra_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            f"video/x-raw,format=BGRA,width={compositor.config.output_width},"
            f"height={compositor.config.output_height},framerate={fps}/1"
        ),
    )

    pre_fx_tee = Gst.ElementFactory.make("tee", "pre-fx-tee")

    # cudadownload only if we're using the CUDA compositor
    if compositor._use_cuda:
        download = Gst.ElementFactory.make("cudadownload", "download")
        elements_pre = [download, convert_bgra, bgra_caps, pre_fx_tee]
    else:
        elements_pre = [convert_bgra, bgra_caps, pre_fx_tee]
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

    # TODO: Individual camera FX sources cause caps negotiation deadlock
    # at pipeline startup. The input-selector can't resolve BGRA vs I420
    # across 7 pads simultaneously. Needs a different approach — either
    # dynamic relinking or a separate pipeline per source.
    # For now, the tiled composite is the only FX source.

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

    # v4l2sink branch — with caps dedup probe to prevent renegotiation on source switch
    queue_v4l2 = Gst.ElementFactory.make("queue", "queue-v4l2")
    queue_v4l2.set_property("leaky", 2)
    queue_v4l2.set_property("max-size-buffers", 1)
    convert_out = Gst.ElementFactory.make("videoconvert", "convert-out")
    convert_out.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    sink_caps = Gst.ElementFactory.make("capsfilter", "sink-caps")
    sink_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            f"video/x-raw,format=YUY2,width={compositor.config.output_width},"
            f"height={compositor.config.output_height},framerate={fps}/1"
        ),
    )
    # identity drop-allocation=true: standard v4l2loopback workaround for
    # allocation query renegotiation (defense-in-depth alongside caps probe)
    identity = Gst.ElementFactory.make("identity", "v4l2-identity")
    identity.set_property("drop-allocation", True)
    sink = Gst.ElementFactory.make("v4l2sink", "output")
    sink.set_property("device", compositor.config.output_device)
    sink.set_property("sync", False)

    for el in [queue_v4l2, convert_out, sink_caps, identity, sink]:
        pipeline.add(el)

    queue_v4l2.link(convert_out)
    convert_out.link(sink_caps)
    sink_caps.link(identity)
    identity.link(sink)

    # Caps dedup probe: drop CAPS events with identical content to prevent
    # v4l2sink renegotiation when input-selector switches between sources.
    # GStreamer uses pointer comparison for event identity — even identical
    # caps from a different pad trigger full renegotiation without this.
    _last_caps: list[Any] = [None]

    def _caps_dedup_probe(pad: Any, info: Any) -> Any:
        event = info.get_event()
        if event is None or event.type != Gst.EventType.CAPS:
            return Gst.PadProbeReturn.OK
        try:
            result = event.parse_caps()
            # GStreamer Python binding returns (bool, Caps) or just Caps depending on version
            caps = result[1] if isinstance(result, tuple) else result
        except Exception:
            return Gst.PadProbeReturn.OK
        if _last_caps[0] is not None and _last_caps[0].is_equal(caps):
            return Gst.PadProbeReturn.DROP
        _last_caps[0] = caps
        return Gst.PadProbeReturn.OK

    queue_v4l2.get_static_pad("sink").add_probe(
        Gst.PadProbeType.EVENT_DOWNSTREAM, _caps_dedup_probe
    )

    tee_pad = output_tee.request_pad(output_tee.get_pad_template("src_%u"), None, None)
    queue_sink_pad = queue_v4l2.get_static_pad("sink")
    tee_pad.link(queue_sink_pad)

    if compositor.config.hls.enabled:
        add_hls_branch(compositor, pipeline, output_tee, fps)

    add_fx_snapshot_branch(compositor, pipeline, output_tee)
    add_smooth_delay_branch(compositor, pipeline, output_tee)

    return pipeline


def _add_camera_fx_sources(compositor: Any, pipeline: Any, Gst: Any, fps: int) -> None:
    """Wire each camera's tee to the FX input-selector as a selectable source.

    Each camera feed is scaled to output resolution and linked as a separate
    input-selector pad. The source field on PresetChain controls which pad
    is active during playback.
    """
    input_sel = compositor._fx_input_selector

    for cam in compositor.config.cameras:
        role = cam.role.replace("-", "_")
        cam_tee = pipeline.get_by_name(f"tee_{role}")
        if cam_tee is None:
            log.debug("FX source: camera tee for %s not found, skipping", role)
            continue

        # Branch: camera_tee → queue → videoconvert(BGRA) → input-selector
        # Cameras are already 1080p from jpegdec — no scale needed.
        q = Gst.ElementFactory.make("queue", f"queue-fxsrc-{role}")
        q.set_property("leaky", 2)
        q.set_property("max-size-buffers", 1)
        convert = Gst.ElementFactory.make("videoconvert", f"fxsrc-convert-{role}")
        convert.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
        caps = Gst.ElementFactory.make("capsfilter", f"fxsrc-caps-{role}")
        caps.set_property(
            "caps",
            Gst.Caps.from_string("video/x-raw,format=BGRA"),
        )

        for el in [q, convert, caps]:
            pipeline.add(el)
        q.link(convert)
        convert.link(caps)

        # Connect camera tee → queue
        tee_pad = cam_tee.request_pad(cam_tee.get_pad_template("src_%u"), None, None)
        q_sink = q.get_static_pad("sink")
        tee_pad.link(q_sink)

        # Connect caps → input-selector
        sel_pad = input_sel.request_pad(input_sel.get_pad_template("sink_%u"), None, None)
        caps.link_pads("src", input_sel, sel_pad.get_name())

        # Store the pad using the camera's original role name (with dashes)
        compositor._fx_input_pads[cam.role] = sel_pad
        log.info("FX source: %s connected to input-selector", cam.role)

    log.info("FX sources available: %s", ", ".join(sorted(compositor._fx_input_pads.keys())))
