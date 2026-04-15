"""GStreamer pipeline construction for the compositor."""

from __future__ import annotations

import logging
from typing import Any

from .cameras import add_camera_branch
from .layout import compute_tile_layout
from .pipeline_manager import PipelineManager
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
    else:
        # Delta 2026-04-14-sprint-5-delta-audit finding C2/C3 + 2026-04-14-
        # camera-pipeline-systematic-walk finding F7: explicitly pin the
        # compositor to CUDA device 0. Phase 10 PR #801 already set
        # ``Environment=CUDA_VISIBLE_DEVICES=0`` on the systemd unit so
        # from this process's perspective device 0 is the only visible
        # GPU, but declaring the pin in code too makes the intent durable
        # and survives any future env change. Prevents silent drift if
        # CUDA enumeration order or the systemd override ever changes.
        try:
            comp_element.set_property("cuda-device-id", 0)
        except Exception:
            log.debug("cudacompositor: cuda-device-id property not supported", exc_info=True)
        # Delta drop #35 COMP-1: GstAggregator default `latency=0` means the
        # aggregator produces output as soon as any sink pad has data, using
        # the last-repeated buffer from pads that are still behind. Per-camera
        # producer pipelines introduce a few ms of JPEG-decode variance, so
        # some fraction of output frames carry one-frame-old content from the
        # slower pads. One frame of grace (33 ms at 30 fps) aligns all pads
        # on the same source-frame timestamp at ~10-33% of the existing
        # 100-300 ms end-to-end latency budget.
        try:
            comp_element.set_property("latency", 33_000_000)
        except Exception:
            log.debug("cudacompositor: latency property not supported", exc_info=True)
        # Delta drop #35 COMP-2: `ignore-inactive-pads=true` lets the
        # aggregator produce output even when a sink pad has no data. This
        # matters during primary→fallback interpipesrc hot-swap (Camera 24/7
        # epic): the swap briefly leaves one pad buffer-less, and without
        # this flag the whole composite stalls on the missing pad.
        try:
            comp_element.set_property("ignore-inactive-pads", True)
        except Exception:
            log.debug("cudacompositor: ignore-inactive-pads property not supported", exc_info=True)
    pipeline.add(comp_element)

    fps = compositor.config.framerate

    # --- ALPHA PHASE 2: per-camera producer pipelines ---
    # Build all producer + fallback sub-pipelines before the composite camera
    # branches are wired. Each producer pipeline runs independently; their
    # errors are scoped to their own pipeline bus and never reach the composite.
    compositor._pipeline_manager = PipelineManager(
        specs=list(compositor.config.cameras),
        gst=Gst,
        glib=compositor._GLib,
        fps=fps,
        on_transition=_on_pipeline_manager_transition_factory(compositor),
    )
    compositor._pipeline_manager.build()
    # Seed the compositor's visible _camera_status from the PM's current view
    with compositor._camera_status_lock:
        for role, status in compositor._pipeline_manager.status_all().items():
            compositor._camera_status[role] = status
    # --- END ALPHA PHASE 2 ---

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
    # Delta 2026-04-14-camera-pipeline-systematic-walk finding F9: bump
    # the v4l2sink branch's buffer cushion from 1 to 5 frames. A 1-buffer
    # queue drops the frame on any 33 ms hiccup — a tight window for OBS
    # reads that can stall briefly under GPU contention. 5 frames at
    # 30fps is ~167 ms of cushion, still well within the 2-second
    # watchdog timeout, and v4l2loopback's kernel-side max_buffers=2
    # (operator-gated modprobe reload per drop follow-ups) remains the
    # hard ceiling upstream of this queue. ``leaky=downstream`` is
    # preserved so back-pressure still results in frame drops at the
    # queue rather than upstream.
    queue_v4l2.set_property("max-size-buffers", 5)
    convert_out = Gst.ElementFactory.make("videoconvert", "convert-out")
    convert_out.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    sink_caps = Gst.ElementFactory.make("capsfilter", "sink-caps")
    # F6 (drop #32 B7): format is NV12, not YUY2. NV12 is cheaper to convert
    # from the upstream BGRA source (compositor mix → BGRA → NV12 costs ~30-40%
    # less CPU on the videoconvert step than BGRA → YUY2), matches the
    # livestream standard for v4l2loopback + OBS consumption, and is supported
    # by v4l2loopback 0.15.3 on exclusive_caps=1 devices (verified via isolated
    # gst-launch test on /dev/video10 2026-04-15). Operator-confirmed; applies
    # on next compositor restart.
    sink_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            f"video/x-raw,format=NV12,width={compositor.config.output_width},"
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
    # Drop #50 OBS-N1: disable last-sample caching. v4l2sink's default
    # `enable-last-sample=true` holds a ref to the most recently pushed
    # buffer so `get-last-sample` queries can read it back. The compositor
    # never calls `get-last-sample` on the output sink, so the cache is
    # just dead pinning ~4 MB of BGRA memory per frame indefinitely.
    try:
        sink.set_property("enable-last-sample", False)
    except Exception:
        log.debug("v4l2sink: enable-last-sample property not supported", exc_info=True)
    # Drop #50 OBS-N3: disable QoS back-pressure. v4l2loopback's kernel
    # buffering is small (max_buffers=2 default) and with an absent or
    # slow consumer the sink emits QoS events upstream, which propagate
    # through the fx chain and can back-pressure cudacompositor. The
    # compositor should be OBS-agnostic: frames are produced at the
    # pipeline's natural rate and drop at the v4l2sink boundary if OBS
    # can't keep up, rather than stalling the whole upstream chain.
    try:
        sink.set_property("qos", False)
    except Exception:
        log.debug("v4l2sink: qos property not supported", exc_info=True)

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

    # Phase 5: instantiate the RTMP output bin (detached by default).
    # It is attached on toggle_livestream affordance activation; consent gate
    # lives in the affordance pipeline, not here.
    from .rtmp_output import RtmpOutputBin

    compositor._output_tee = output_tee
    compositor._rtmp_bin = RtmpOutputBin(
        gst=Gst,
        video_tee=output_tee,
        rtmp_location="rtmp://127.0.0.1:1935/studio",
        bitrate_kbps=6000,
        # F3 (drop #33): gop_size drops from 2*fps (60) to fps (30), 1 keyframe
        # per second. Matches YouTube-recommended sweet spot and reduces
        # HLS-equivalent latency on RTMP ingest. Operator-confirmed 2026-04-15.
        gop_size=fps,
    )
    log.info("rtmp output bin constructed (detached until toggle_livestream)")

    return pipeline


def _on_pipeline_manager_transition_factory(compositor: Any) -> Any:
    """Build a callback that bridges PipelineManager transitions back into
    the compositor's visible _camera_status dict + ntfy notifier."""

    def _cb(role: str, from_state: str, to_state: str, reason: str) -> None:
        with compositor._camera_status_lock:
            compositor._camera_status[role] = to_state
        if to_state == "offline":
            compositor._notify_camera_transition(role, from_state, "offline")
        elif to_state == "active":
            compositor._notify_camera_transition(role, from_state, "active")
        compositor._write_status("running")

    return _cb
