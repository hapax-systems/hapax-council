"""GStreamer pipeline construction for the compositor."""

from __future__ import annotations

import logging
from typing import Any

from .cameras import add_camera_branch
from .layout import compute_tile_layout
from .pipeline_manager import PipelineManager
from .recording import add_hls_branch
from .smooth_delay import add_smooth_delay_branch
from .snapshots import add_fx_snapshot_branch, add_llm_frame_snapshot_branch, add_snapshot_branch

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
    # Phase 3 (AUDIT-07 layer 4): camera-only frame for LLM prompts —
    # cuts the ward-OCR-dominance hallucination class. Same upstream
    # tap as snapshot.jpg, distinct file path so consumers don't mix.
    add_llm_frame_snapshot_branch(compositor, pipeline, pre_fx_tee)

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

    # v4l2 output — isolated via interpipesink. The consumer side
    # (interpipesrc → queue → videoconvert → v4l2sink) runs in a
    # separate Gst.Pipeline (V4l2OutputPipeline) so state-cycling the
    # v4l2sink does not require flushing the upstream GL chain. This
    # eliminates the 15-30s ASYNC timeout that caused persistent v4l2
    # stalls and OBS source loss. Recovery transitions now complete
    # in <1s because the output pipeline has no GL elements.
    from .v4l2_output_pipeline import INTERPIPE_CHANNEL, V4l2OutputPipeline

    v4l2_interpipe = Gst.ElementFactory.make("interpipesink", INTERPIPE_CHANNEL)
    if v4l2_interpipe is None:
        raise RuntimeError("interpipesink factory failed — gst-plugin-interpipe not installed")
    v4l2_interpipe.set_property("sync", False)
    v4l2_interpipe.set_property("async", False)
    v4l2_interpipe.set_property("forward-events", False)
    v4l2_interpipe.set_property("forward-eos", False)
    pipeline.add(v4l2_interpipe)

    tee_pad = output_tee.request_pad(output_tee.get_pad_template("src_%u"), None, None)
    tee_pad.link(v4l2_interpipe.get_static_pad("sink"))

    compositor._v4l2_output_pipeline = V4l2OutputPipeline(
        gst=Gst,
        device=compositor.config.output_device,
        width=compositor.config.output_width,
        height=compositor.config.output_height,
        fps=fps,
        on_frame=compositor._on_v4l2_frame_pushed,
    )
    compositor._v4l2_output_pipeline.build()

    if compositor.config.hls.enabled:
        add_hls_branch(compositor, pipeline, output_tee, fps)

    add_fx_snapshot_branch(compositor, pipeline, output_tee)
    add_smooth_delay_branch(compositor, pipeline, output_tee)

    # Phase 5: instantiate the RTMP output bin (detached by default).
    # It is attached on toggle_livestream affordance activation; consent gate
    # lives in the affordance pipeline, not here.
    from .rtmp_output import MobileRtmpOutputBin, RtmpOutputBin

    compositor._output_tee = output_tee
    compositor._rtmp_bin = RtmpOutputBin(
        gst=Gst,
        video_tee=output_tee,
        rtmp_location="rtmp://127.0.0.1:1935/studio",
        # 2026-04-20 (post-Tauri-decom): 3000 → 9000 kbps. The A+ Stage 0
        # cut (2026-04-17) was a perf-headroom move when the WebKit JPEG
        # decoder was burning ~60% CPU + 5-10% GPU rendering the Tauri
        # preview surface. With hapax-logos.service decommissioned, we
        # have headroom; reverting to a higher bitrate is the single
        # highest-impact viewer-side quality win per
        # docs/research/2026-04-20-tauri-decommission-freed-resources.md
        # §11. YouTube Live accepts up to 9000 kbps for 720p30/60; 9000
        # gives meaningful headroom for high-frequency-content scenes
        # (HARDM cells, granular wash, halftone shaders) that were
        # bitrate-starved at 3000.
        bitrate_kbps=9000,
        # A+ Stage 0: GOP back to 2*fps (60) = 2s keyframe interval,
        # matching Twitch/YouTube recommendation for 720p30 and reducing
        # encoder work vs the 1-second keyframes. Operator's low-latency
        # need is served by tune=ll in rtmp_output.py, not by more I-frames.
        gop_size=fps * 2,
    )
    compositor._mobile_rtmp_bin = MobileRtmpOutputBin(
        gst=Gst,
        glib=compositor._GLib,
        video_tee=output_tee,
        source_width=compositor.config.output_width,
        source_height=compositor.config.output_height,
        bitrate_kbps=3500,
        gop_size=fps * 2,
    )
    log.info("rtmp output bins constructed (detached until toggle_livestream)")

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
