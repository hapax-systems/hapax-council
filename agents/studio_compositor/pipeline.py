"""GStreamer pipeline construction for the compositor."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from .cameras import add_camera_branch
from .cuda_caps import cuda_output_caps_string
from .layout import compute_safe_tile_layout
from .layout_safety import (
    BASE_COMPOSITOR_BACKGROUND_PROPERTY_VALUE,
    BASE_COMPOSITOR_MATERIAL,
    resolve_startup_layout_mode,
)
from .pipeline_manager import PipelineManager
from .recording import add_hls_branch
from .smooth_delay import add_smooth_delay_branch
from .snapshots import add_llm_frame_snapshot_branch, add_snapshot_branch

log = logging.getLogger(__name__)


def init_gstreamer() -> tuple[Any, Any]:
    """Import and initialize GStreamer. Returns (GLib, Gst) modules."""
    import gi as _gi

    _gi.require_version("Gst", "1.0")
    from gi.repository import GLib as _GLib
    from gi.repository import Gst as _Gst

    _Gst.init(None)
    return _GLib, _Gst


def _pin_black_background(comp_element: Any) -> None:
    """Prefer black compositor fill instead of checkerboard/transparent defaults."""
    try:
        comp_element.set_property("background", BASE_COMPOSITOR_BACKGROUND_PROPERTY_VALUE)
        log.info("compositor background material pinned: %s", BASE_COMPOSITOR_MATERIAL)
    except Exception:
        log.debug("compositor background property not supported", exc_info=True)


def _make_cudacompositor(Gst: Any) -> Any | None:
    """Construct cudacompositor with live aggregation enabled when possible."""

    try:
        if hasattr(Gst, "parse_launch"):
            element = Gst.parse_launch("cudacompositor name=compositor force-live=true")
            if element is not None:
                log.info("cudacompositor constructed with force-live=true")
                return element
    except Exception:
        log.debug("cudacompositor force-live construction failed", exc_info=True)

    element = Gst.ElementFactory.make("cudacompositor", "compositor")
    if element is not None:
        try:
            element.set_property("force-live", True)
        except Exception:
            log.debug(
                "cudacompositor: force-live property not settable post-construction", exc_info=True
            )
    return element


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _set_optional_property(element: Any, name: str, value: Any, *, context: str) -> None:
    try:
        element.set_property(name, value)
    except Exception:
        log.debug("%s: %s property not supported", context, name, exc_info=True)


def _add_render_stage_probe(Gst: Any, element: Any, pad_name: str, stage: str) -> None:
    try:
        pad = element.get_static_pad(pad_name)
        if pad is None:
            log.debug("render-stage probe skipped: %s.%s missing", element.get_name(), pad_name)
            return

        def _probe(_pad: Any, _info: Any) -> Any:
            try:
                from . import metrics

                metrics.record_render_stage_frame(stage)
            except Exception:
                pass
            return Gst.PadProbeReturn.OK

        pad.add_probe(Gst.PadProbeType.BUFFER, _probe)
    except Exception:
        log.debug("render-stage probe install failed for %s", stage, exc_info=True)


def _pad_link_ok(Gst: Any, result: Any) -> bool:
    ok = getattr(getattr(Gst, "PadLinkReturn", None), "OK", None)
    if ok is not None:
        return result == ok
    return result == 0


def _link_tee_to_queue_or_raise(Gst: Any, tee: Any, queue: Any, *, branch: str) -> None:
    template = tee.get_pad_template("src_%u")
    if template is None:
        raise RuntimeError(f"{branch}: output tee src_%u pad template missing")
    tee_pad = tee.request_pad(template, None, None)
    if tee_pad is None:
        raise RuntimeError(f"{branch}: failed to request output tee src pad")
    queue_sink = queue.get_static_pad("sink")
    if queue_sink is None:
        raise RuntimeError(f"{branch}: queue sink pad missing")
    result = tee_pad.link(queue_sink)
    if not _pad_link_ok(Gst, result):
        raise RuntimeError(f"{branch}: failed to link output tee to queue: {result}")


def _publish_runtime_features(*, force_cpu: bool, use_cuda: bool) -> None:
    try:
        from . import metrics
        from .shmsink_output_pipeline import is_bridge_enabled, is_v4l2_output_disabled

        feature_states = {
            "force_cpu": force_cpu,
            "cuda_aggregator": use_cuda,
            "inline_fx": os.environ.get("HAPAX_COMPOSITOR_DISABLE_INLINE_FX") != "1",
            "hero_effect": os.environ.get("HAPAX_COMPOSITOR_DISABLE_HERO_EFFECT") != "1",
            "follow_mode": os.environ.get("HAPAX_FOLLOW_MODE_ACTIVE", "1") != "0",
            "ward_modulator": os.environ.get("HAPAX_WARD_MODULATOR_ACTIVE", "1") != "0",
            "direct_v4l2": not is_bridge_enabled() and not is_v4l2_output_disabled(),
            "shmsink_bridge": is_bridge_enabled() and not is_v4l2_output_disabled(),
            "v4l2_output": not is_v4l2_output_disabled(),
        }
        for feature, active in feature_states.items():
            metrics.set_runtime_feature_active(feature, active)
    except Exception:
        log.debug("runtime feature metrics publish failed", exc_info=True)


def _publish_runtime_feature(feature: str, active: bool) -> None:
    try:
        from . import metrics

        metrics.set_runtime_feature_active(feature, active)
    except Exception:
        log.debug("runtime feature metric publish failed for %s", feature, exc_info=True)


def build_pipeline(compositor: Any) -> Any:
    """Build the full GStreamer pipeline."""
    Gst = compositor._Gst

    pipeline = Gst.Pipeline.new("studio-compositor")

    # 3D compositor bypass — when the wgpu imagination pipeline owns
    # rendering and v4l2 output, skip glvideomixer/FX/v4l2sink entirely.
    # Camera capture sub-pipelines still run for JPEG snapshots.
    if os.environ.get("HAPAX_3D_COMPOSITOR") == "1":
        log.info(
            "HAPAX_3D_COMPOSITOR=1 — skipping GStreamer compositing/FX/v4l2 output. "
            "Camera capture pipelines will start independently."
        )
        fps = compositor.config.framerate
        compositor._pipeline_manager = PipelineManager(
            specs=list(compositor.config.cameras),
            gst=Gst,
            glib=compositor._GLib,
            fps=fps,
            on_transition=_on_pipeline_manager_transition_factory(compositor),
        )
        compositor._pipeline_manager.build()
        with compositor._camera_status_lock:
            for role, status in compositor._pipeline_manager.status_all().items():
                compositor._camera_status[role] = status
        compositor._v4l2_output_pipeline = None
        compositor._use_cuda = False
        compositor._tile_layout = {}
        compositor._initial_layout_mode = "3d"
        compositor._layout_mode = "3d"
        return pipeline
    startup_mode = resolve_startup_layout_mode()
    if compositor.config.cameras:
        layout = compute_safe_tile_layout(
            compositor.config.cameras,
            compositor.config.output_width,
            compositor.config.output_height,
            mode=startup_mode.mode,
        )
    else:
        layout = {}
        log.warning("No cameras configured; startup layout safety has no visible regions to check")
    compositor._tile_layout = layout
    compositor._initial_layout_mode = startup_mode.mode
    compositor._layout_mode = startup_mode.mode
    try:
        from .active_wards import publish_current_layout_state

        publish_current_layout_state(layout_mode=startup_mode.mode)
    except Exception:
        log.debug("startup layout state publish failed", exc_info=True)
    log.info(
        "Startup layout mode: %s (source=%s%s)",
        startup_mode.mode,
        startup_mode.source,
        f", path={startup_mode.path}" if startup_mode.path is not None else "",
    )

    force_cpu = os.environ.get("HAPAX_COMPOSITOR_FORCE_CPU") == "1"
    # Try cudacompositor first, fall back to CPU compositor. During live
    # incident containment HAPAX_COMPOSITOR_FORCE_CPU=1 is an actual
    # construction gate, not just a preflight label.
    comp_element = None if force_cpu else _make_cudacompositor(Gst)
    compositor._use_cuda = comp_element is not None
    if comp_element is None:
        if force_cpu:
            log.warning("HAPAX_COMPOSITOR_FORCE_CPU=1 — using CPU compositor")
        else:
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
    _pin_black_background(comp_element)
    _publish_runtime_features(force_cpu=force_cpu, use_cuda=compositor._use_cuda)
    pipeline.add(comp_element)
    _add_render_stage_probe(Gst, comp_element, "src", "compositor_src")

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
        cuda_out_caps = Gst.ElementFactory.make("capsfilter", "cuda-output-caps")
        cuda_out_caps.set_property(
            "caps",
            Gst.Caps.from_string(
                cuda_output_caps_string(
                    compositor.config.output_width,
                    compositor.config.output_height,
                    fps,
                )
            ),
        )
        download = Gst.ElementFactory.make("cudadownload", "download")
        elements_pre = [cuda_out_caps, download, convert_bgra, bgra_caps, pre_fx_tee]
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
    if compositor._use_cuda:
        _add_render_stage_probe(Gst, download, "src", "cudadownload_src")
    _add_render_stage_probe(Gst, pre_fx_tee, "sink", "pre_fx_tee_sink")

    add_snapshot_branch(compositor, pipeline, pre_fx_tee)
    # Phase 3 (AUDIT-07 layer 4): camera-only frame for LLM prompts —
    # cuts the ward-OCR-dominance hallucination class. Same upstream
    # tap as snapshot.jpg, distinct file path so consumers don't mix.
    add_llm_frame_snapshot_branch(compositor, pipeline, pre_fx_tee)

    output_tee = Gst.ElementFactory.make("tee", "output-tee")
    pipeline.add(output_tee)

    # GL chain output probe — direct detection of GL chain death.
    # Fires on every frame that exits the GL chain and reaches output_tee.
    # If this probe hasn't fired for >30s while cameras are active, the
    # GL chain is dead and the watchdog can exit immediately.
    def _gl_output_probe(pad: Any, info: Any) -> Any:
        compositor._gl_last_frame_monotonic = time.monotonic()
        try:
            from . import metrics

            metrics.record_render_stage_frame("output_tee_sink")
        except Exception:
            pass
        return Gst.PadProbeReturn.OK

    output_tee.get_static_pad("sink").add_probe(Gst.PadProbeType.BUFFER, _gl_output_probe)

    from .fx_chain import build_inline_fx_chain

    fx_ok = build_inline_fx_chain(compositor, pipeline, pre_fx_tee, output_tee, fps)
    _publish_runtime_feature("inline_fx_built", fx_ok)
    _publish_runtime_feature("fx_bypass", not fx_ok)

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
    from .shmsink_output_pipeline import (
        INTERPIPE_CHANNEL,
        is_bridge_enabled,
        is_v4l2_output_disabled,
    )
    from .v4l2_output_pipeline import V4l2OutputPipeline

    if is_v4l2_output_disabled():
        compositor._v4l2_output_pipeline = None
        log.warning("HAPAX_COMPOSITOR_DISABLE_V4L2_OUTPUT=1 — skipping v4l2/shmsink output branch")
    else:
        v4l2_queue = Gst.ElementFactory.make("queue", "queue-v4l2-egress")
        if v4l2_queue is None:
            raise RuntimeError("queue-v4l2-egress factory failed")
        v4l2_queue.set_property("leaky", 2)
        v4l2_queue.set_property("max-size-buffers", 4)
        v4l2_queue.set_property("max-size-time", 500 * 1_000_000)
        v4l2_interpipe = Gst.ElementFactory.make("interpipesink", INTERPIPE_CHANNEL)
        if v4l2_interpipe is None:
            raise RuntimeError("interpipesink factory failed — gst-plugin-interpipe not installed")
        v4l2_interpipe.set_property("sync", False)
        v4l2_interpipe.set_property("async", False)
        v4l2_interpipe.set_property("forward-events", False)
        v4l2_interpipe.set_property("forward-eos", False)
        pipeline.add(v4l2_queue)
        pipeline.add(v4l2_interpipe)
        _add_render_stage_probe(Gst, v4l2_queue, "sink", "v4l2_output_queue_sink")
        _add_render_stage_probe(Gst, v4l2_interpipe, "sink", "v4l2_interpipe_sink")

        _link_tee_to_queue_or_raise(Gst, output_tee, v4l2_queue, branch="V4L2 output branch")
        if not v4l2_queue.link(v4l2_interpipe):
            raise RuntimeError("V4L2 output branch: failed to link queue-v4l2-egress -> interpipe")

        if is_bridge_enabled():
            from .shmsink_output_pipeline import ShmsinkOutputPipeline

            compositor._v4l2_output_pipeline = ShmsinkOutputPipeline(
                gst=Gst,
                width=compositor.config.output_width,
                height=compositor.config.output_height,
                fps=fps,
                on_frame=compositor._on_shmsink_frame_pushed,
            )
            log.info(
                "v4l2 output: shmsink bridge path (sidecar writes to %s)",
                compositor.config.output_device,
            )
        else:
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

    # ``fx-snapshot.jpg`` is now the final-egress proof image emitted by
    # V4l2OutputPipeline after a successful /dev/video42 write. Keep that
    # artifact single-owner so a revived sibling tee branch cannot race it.
    if _env_truthy("HAPAX_COMPOSITOR_DISABLE_SMOOTH_DELAY"):
        compositor._fx_smooth_delay = None
        log.warning("HAPAX_COMPOSITOR_DISABLE_SMOOTH_DELAY=1 — skipping smooth-delay branch")
    else:
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
