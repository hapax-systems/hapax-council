"""Inline GPU effects chain and per-frame tick callback."""

from __future__ import annotations

import logging
import random
import time
from typing import TYPE_CHECKING, Any

import cairo

from shared.compositor_model import SurfaceGeometry

if TYPE_CHECKING:
    from agents.studio_compositor.layout_state import LayoutState
    from agents.studio_compositor.source_registry import SourceRegistry

log = logging.getLogger(__name__)


def blit_scaled(
    cr: cairo.Context,
    src: cairo.ImageSurface,
    geom: SurfaceGeometry,
    opacity: float,
    blend_mode: str,
) -> None:
    """Place a natural-size source surface at ``geom``'s rect with scaling.

    Matches the scale-on-blit design from Phase E of the source-registry
    spec: each source renders once at its natural resolution on its own
    render thread, and the GStreamer cairooverlay draw callback scales
    on blit to the assigned surface geometry. Non-rect surfaces (main-
    layer ``fx_chain_input`` pads, ``wgpu_binding``, ``video_out``) are
    silently skipped — those are handled by the glvideomixer appsrc
    path, not the cairooverlay path.
    """
    if geom.kind != "rect":
        return
    cr.save()
    cr.translate(geom.x or 0, geom.y or 0)
    src_w = max(src.get_width(), 1)
    src_h = max(src.get_height(), 1)
    sx = (geom.w or src_w) / src_w
    sy = (geom.h or src_h) / src_h
    cr.scale(sx, sy)
    cr.set_source_surface(src, 0, 0)
    pattern = cr.get_source()
    try:
        pattern.set_filter(cairo.FILTER_BILINEAR)
    except Exception:
        log.debug("cairo FILTER_BILINEAR unavailable on this pattern", exc_info=True)
    if blend_mode == "plus":
        cr.set_operator(cairo.OPERATOR_ADD)
    else:
        cr.set_operator(cairo.OPERATOR_OVER)
    cr.paint_with_alpha(opacity)
    cr.restore()


def pip_draw_from_layout(
    cr: cairo.Context,
    layout_state: LayoutState,
    source_registry: SourceRegistry,
) -> None:
    """Walk the current layout's assignments by z_order and blit each one.

    Called from the GStreamer cairooverlay draw callback on the
    streaming thread. Must stay cheap — no allocation in the hot path
    beyond sorting the assignment list. Surfaces whose geometry is not
    ``kind="rect"`` are skipped; they land on the glvideomixer appsrc
    path set up by Phase H.

    When a source's ``get_current_surface()`` returns ``None``, the blit
    is simply skipped for this frame — there is no fallback to the
    legacy ``compositor._token_pole.draw(cr)`` path. The legacy facades
    stay instantiated (backward compat during transition) but their
    ``draw()`` methods are only called by deprecated code paths that
    this callback has replaced.
    """
    layout = layout_state.get()
    pairs: list[tuple[Any, Any]] = []
    for assignment in layout.assignments:
        surface_schema = layout.surface_by_id(assignment.surface)
        if surface_schema is None:
            continue
        if surface_schema.geometry.kind != "rect":
            continue
        pairs.append((assignment, surface_schema))
    pairs.sort(key=lambda p: p[1].z_order)

    for assignment, surface_schema in pairs:
        try:
            src = source_registry.get_current_surface(assignment.source)
        except KeyError:
            continue
        if src is None:
            continue
        blit_scaled(
            cr,
            src,
            surface_schema.geometry,
            opacity=assignment.opacity,
            blend_mode=surface_schema.blend_mode,
        )


def build_source_appsrc_branches(
    pipeline: Any,
    layout_state: LayoutState,
    source_registry: SourceRegistry,
) -> dict[str, dict[str, Any]]:
    """For each source in the current layout, add an appsrc branch to the pipeline.

    Phase 6 (parent task H24). The branch shape per source is:

        appsrc -> videoconvert -> glupload -> [mixer sink pad]

    This function stops at the ``glupload`` output so the caller can
    link each branch into whatever ``glvideomixer`` / tee / preset-chain
    input is appropriate for the operator's current pipeline topology.
    Returns a dict keyed by ``source_id`` with ``{"appsrc", "videoconvert",
    "glupload"}`` sub-elements — sources with no ``gst_appsrc()``
    support (or any element factory missing) are skipped entirely and
    logged.

    Inactive sources (those without a main-layer assignment in the
    current layout) still get a branch: preset switches are alpha-snap
    decisions on already-linked pads, not pipeline rewiring. The caller
    sets each mixer sink pad's ``alpha`` to 0.0 at startup and flips it
    on preset load.

    Gracefully no-ops and returns an empty dict if GStreamer / ``gi``
    isn't importable in the current environment — callers can check
    ``if not branches: …`` for headless / unit-test paths.
    """
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst  # type: ignore[import-not-found]
    except (ImportError, ValueError):
        log.debug("build_source_appsrc_branches: GStreamer unavailable, returning empty")
        return {}
    Gst.init(None)

    branches: dict[str, dict[str, Any]] = {}
    layout = layout_state.get()
    for src in layout.sources:
        backend = source_registry._backends.get(src.id)  # noqa: SLF001
        if backend is None:
            log.debug("build_source_appsrc_branches: no backend for %s, skipping", src.id)
            continue
        if not hasattr(backend, "gst_appsrc"):
            log.debug(
                "build_source_appsrc_branches: backend for %s has no gst_appsrc, skipping",
                src.id,
            )
            continue
        appsrc = backend.gst_appsrc()
        if appsrc is None:
            continue
        vconv = Gst.ElementFactory.make("videoconvert", f"vconv-{src.id}")
        glupload = Gst.ElementFactory.make("glupload", f"glupload-{src.id}")
        if vconv is None or glupload is None:
            log.warning(
                "build_source_appsrc_branches: missing videoconvert/glupload factory for %s",
                src.id,
            )
            continue
        pipeline.add(appsrc)
        pipeline.add(vconv)
        pipeline.add(glupload)
        if not appsrc.link(vconv):
            log.warning(
                "build_source_appsrc_branches: appsrc->videoconvert link failed for %s",
                src.id,
            )
            continue
        if not vconv.link(glupload):
            log.warning(
                "build_source_appsrc_branches: videoconvert->glupload link failed for %s",
                src.id,
            )
            continue
        branches[src.id] = {
            "appsrc": appsrc,
            "videoconvert": vconv,
            "glupload": glupload,
        }
        log.info(
            "build_source_appsrc_branches: %s branch built (appsrc->videoconvert->glupload)",
            src.id,
        )
    return branches


def _pip_draw(compositor: Any, cr: Any) -> None:
    """Post-FX cairooverlay callback — drives pip_draw_from_layout only.

    Phase 9 Task 29 of the compositor unification epic removed the
    pre-Phase-3 legacy fallback and the cross-facade double-draw for
    ``_stream_overlay``. Layout state + source registry are always
    populated by ``StudioCompositor.start_layout_only`` (PR #735),
    so the layout walk is the only render path.
    """
    layout_state = getattr(compositor, "layout_state", None)
    source_registry = getattr(compositor, "source_registry", None)
    if layout_state is not None and source_registry is not None:
        pip_draw_from_layout(cr, layout_state, source_registry)


class FlashScheduler:
    """Audio-reactive live overlay flash on the camera base.

    Kick onsets trigger a flash. Flash duration scales with bass energy.
    Random baseline schedule fills gaps when no kicks are detected.
    Alpha decays smoothly from 0.6 → 0.0 for organic feel.
    """

    FLASH_ALPHA = 0.5
    # Random baseline — more on than off (bad reception feel)
    MIN_INTERVAL = 0.1  # very short gaps between flashes
    MAX_INTERVAL = 1.0  # max 1s gap
    MIN_DURATION = 0.5  # flashes last longer
    MAX_DURATION = 3.0
    # Audio-reactive
    KICK_COOLDOWN = 0.2  # normal mode
    KICK_COOLDOWN_VINYL = 0.4  # vinyl mode: half-speed = longer between kicks

    def __init__(self) -> None:
        self._next_flash_at: float = time.monotonic() + random.uniform(1.0, 3.0)
        self._flash_end_at: float = 0.0
        self._flashing: bool = False
        self._current_alpha: float = 0.0
        self._last_kick_at: float = 0.0

    def kick(self, t: float, bass_energy: float) -> None:
        """Called when a kick onset is detected. Triggers a flash."""
        cooldown = (
            self.KICK_COOLDOWN_VINYL if getattr(self, "_vinyl_mode", False) else self.KICK_COOLDOWN
        )
        if t - self._last_kick_at < cooldown:
            return  # cooldown
        self._last_kick_at = t
        self._flashing = True
        # Duration scales with bass energy: more bass = longer flash
        duration = 0.1 + bass_energy * 0.4  # 0.1s to 0.5s — short punch
        self._flash_end_at = t + min(duration, self.MAX_DURATION)
        self._current_alpha = self.FLASH_ALPHA

    def tick(self, t: float) -> float | None:
        """Returns target alpha if changed, None if no change needed."""
        if self._flashing:
            # Smooth decay toward end of flash
            remaining = self._flash_end_at - t
            total = self._flash_end_at - self._last_kick_at if self._last_kick_at > 0 else 1.0
            if remaining <= 0:
                self._flashing = False
                self._next_flash_at = t + random.uniform(self.MIN_INTERVAL, self.MAX_INTERVAL)
                if self._current_alpha != 0.0:
                    self._current_alpha = 0.0
                    return 0.0
            else:
                # Fade out over the last 40% of the flash
                fade_point = total * 0.6
                if remaining < fade_point and fade_point > 0:
                    target = self.FLASH_ALPHA * (remaining / fade_point)
                else:
                    target = self.FLASH_ALPHA
                if abs(target - self._current_alpha) > 0.02:
                    self._current_alpha = target
                    return target
        else:
            # Random baseline flash (fills silence)
            if t >= self._next_flash_at:
                self._flashing = True
                duration = random.uniform(self.MIN_DURATION, self.MAX_DURATION)
                self._flash_end_at = t + duration
                self._last_kick_at = t
                self._current_alpha = self.FLASH_ALPHA
                return self.FLASH_ALPHA
        return None


def build_inline_fx_chain(
    compositor: Any, pipeline: Any, pre_fx_tee: Any, output_tee: Any, fps: int
) -> bool:
    """Build GPU effects chain with glvideomixer for camera+live flash overlay.

    Pipeline:
      input-selector (camera) → queue → cairooverlay → glupload → glcolorconvert ─→ glvideomixer sink_0 (base, alpha=1)
      pre_fx_tee (live flash)  → queue →                glupload → glcolorconvert ─→ glvideomixer sink_1 (flash, alpha=0↔0.6)
                                                                                            ↓
                                                                                   [24 glfeedback slots]
                                                                                            ↓
                                                                                   glcolorconvert → gldownload → output_tee

    Both sources composited on GPU via glvideomixer. FlashScheduler
    animates the flash pad's alpha property (0.0 ↔ 0.6) on a random
    schedule. Text overlay (cairooverlay) on the base path goes through
    all shader effects.
    """
    Gst = compositor._Gst

    # --- Input selector for camera source switching ---
    input_sel = Gst.ElementFactory.make("input-selector", "fx-input-selector")
    input_sel.set_property("sync-streams", False)
    pipeline.add(input_sel)

    # --- Base path: input-selector → queue → cairooverlay → glupload → glcolorconvert ---
    queue_base = Gst.ElementFactory.make("queue", "queue-fx-base")
    queue_base.set_property("leaky", 2)
    queue_base.set_property("max-size-buffers", 2)

    from .overlay import on_draw, on_overlay_caps_changed

    overlay = Gst.ElementFactory.make("cairooverlay", "overlay")
    overlay.connect("draw", lambda o, cr, ts, dur: on_draw(compositor, o, cr, ts, dur))
    overlay.connect("caps-changed", lambda o, caps: on_overlay_caps_changed(compositor, o, caps))

    convert_base = Gst.ElementFactory.make("videoconvert", "fx-convert-base")
    convert_base.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    glupload_base = Gst.ElementFactory.make("glupload", "fx-glupload-base")
    glcc_base = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-base")

    # --- Flash path: pre_fx_tee → queue → glupload → glcolorconvert ---
    queue_flash = Gst.ElementFactory.make("queue", "queue-fx-flash")
    queue_flash.set_property("leaky", 2)
    queue_flash.set_property("max-size-buffers", 2)
    convert_flash = Gst.ElementFactory.make("videoconvert", "fx-convert-flash")
    convert_flash.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    glupload_flash = Gst.ElementFactory.make("glupload", "fx-glupload-flash")
    glcc_flash = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-flash")

    # --- glvideomixer: GPU-native compositing ---
    glmixer = Gst.ElementFactory.make("glvideomixer", "fx-glmixer")
    glmixer.set_property("background", 1)  # 1=black (default is 0=checker!)

    # --- Post-mixer: shader chain → output ---
    from agents.effect_graph.pipeline import SlotPipeline

    registry = compositor._graph_runtime._registry if compositor._graph_runtime else None
    compositor._slot_pipeline = SlotPipeline(registry, num_slots=24)

    glcolorconvert_out = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-out")
    gldownload = Gst.ElementFactory.make("gldownload", "fx-gldownload")
    fx_convert = Gst.ElementFactory.make("videoconvert", "fx-out-convert")
    fx_convert.set_property("dither", 0)  # none — Bayer default creates sawtooth columns

    all_elements = [
        input_sel,
        queue_base,
        overlay,
        convert_base,
        glupload_base,
        glcc_base,
        queue_flash,
        convert_flash,
        glupload_flash,
        glcc_flash,
        glmixer,
        glcolorconvert_out,
        gldownload,
        fx_convert,
    ]
    for el in all_elements:
        if el is None:
            log.error("Failed to create FX element — effects disabled")
            return False
        pipeline.add(el)

    # --- Link base path ---
    input_sel.link(queue_base)
    queue_base.link(overlay)
    overlay.link(convert_base)
    convert_base.link(glupload_base)
    glupload_base.link(glcc_base)

    # --- Link flash path ---
    tee_pad_flash = pre_fx_tee.request_pad(pre_fx_tee.get_pad_template("src_%u"), None, None)
    tee_pad_flash.link(queue_flash.get_static_pad("sink"))
    queue_flash.link(convert_flash)
    convert_flash.link(glupload_flash)
    glupload_flash.link(glcc_flash)

    # --- glvideomixer pads ---
    base_pad = glmixer.request_pad(glmixer.get_pad_template("sink_%u"), None, None)
    base_pad.set_property("zorder", 0)
    base_pad.set_property("alpha", 1.0)
    glcc_base.link_pads("src", glmixer, base_pad.get_name())

    flash_pad = glmixer.request_pad(glmixer.get_pad_template("sink_%u"), None, None)
    flash_pad.set_property("zorder", 1)
    flash_pad.set_property("alpha", 0.0)  # hidden until flash
    glcc_flash.link_pads("src", glmixer, flash_pad.get_name())

    # --- Store glmixer ref ---
    compositor._fx_glmixer = glmixer

    # --- Shader chain after mixer ---
    compositor._slot_pipeline.build_chain(pipeline, Gst, glmixer, glcolorconvert_out)

    glcolorconvert_out.link(gldownload)
    gldownload.link(fx_convert)

    # --- Post-FX cairooverlay: composites YouTube PiP AFTER shader chain ---
    # Uses CPU compositing (640x360 PiP on 1920x1080 output = trivial).
    # Avoids glvideomixer deadlock from dynamic pad addition.
    pip_overlay = Gst.ElementFactory.make("cairooverlay", "pip-overlay")
    pip_overlay.connect("draw", lambda o, cr, ts, dur: _pip_draw(compositor, cr))
    pipeline.add(pip_overlay)
    fx_convert.link(pip_overlay)
    pip_overlay.link(output_tee)

    # --- Input-selector: default to live (tiled composite) ---
    live_pad = input_sel.request_pad(input_sel.get_pad_template("sink_%u"), None, None)
    tee_pad_live = pre_fx_tee.request_pad(pre_fx_tee.get_pad_template("src_%u"), None, None)
    tee_pad_live.link(live_pad)
    input_sel.set_property("active-pad", live_pad)

    # --- Store everything ---
    compositor._fx_input_selector = input_sel
    compositor._fx_input_pads = {"live": live_pad}
    compositor._fx_active_source = "live"
    compositor._fx_camera_branch = []  # list[Any] — camera branch elements for teardown
    compositor._fx_switching = False
    compositor._fx_flash_pad = flash_pad
    compositor._fx_flash_scheduler = FlashScheduler()

    # PiP cairo sources (token_pole, album, stream_overlay) are now
    # instantiated by the SourceRegistry from default.json — Phase 9 Task 29
    # removed their legacy facade construction sites.
    #
    # SierpinskiLoader + SierpinskiRenderer remain: Sierpinski is a full-
    # canvas main-layer render (not a PiP) driven by overlay.py::on_draw,
    # with the renderer holding set_active_slot / set_audio_energy state.
    # Migrating Sierpinski to the source registry's fx_chain_input surface
    # is a separate refactor tracked as a follow-up ticket.
    from .sierpinski_loader import SierpinskiLoader
    from .sierpinski_renderer import SierpinskiRenderer

    compositor._sierpinski_loader = SierpinskiLoader()
    compositor._sierpinski_loader.start()
    compositor._sierpinski_renderer = SierpinskiRenderer()
    compositor._sierpinski_renderer.start()
    log.info("SierpinskiLoader + SierpinskiRenderer created (render thread at 10fps)")

    log.info(
        "FX chain: %d shader slots, glvideomixer (camera base + live flash 60%%)",
        compositor._slot_pipeline.num_slots,
    )
    return True


def switch_fx_source(compositor: Any, source: str) -> bool:
    """Switch FX chain input to a different camera or back to tiled composite.

    Uses IDLE pad probe to safely modify the pipeline while PLAYING.
    Creates camera branch on-demand (lazy), tears down old one.
    """
    if not hasattr(compositor, "_fx_input_selector"):
        return False
    if source == getattr(compositor, "_fx_active_source", "live"):
        return True  # already active
    if getattr(compositor, "_fx_switching", False):
        return False  # switch in progress

    Gst = compositor._Gst
    input_sel = compositor._fx_input_selector
    pipeline = compositor.pipeline

    if source == "live":
        # Switch back to tiled composite — just set active pad
        live_pad = compositor._fx_input_pads.get("live")
        if live_pad is None:
            return False
        input_sel.set_property("active-pad", live_pad)
        _teardown_camera_branch(compositor, Gst)
        compositor._fx_active_source = "live"
        log.info("FX source: switched to live (tiled composite)")
        return True

    # YouTube source: v4l2src from /dev/video50
    is_youtube = source == "youtube"

    if not is_youtube:
        # Switch to individual camera — need to create branch on-demand
        role = source.replace("-", "_")
        cam_tee = pipeline.get_by_name(f"tee_{role}")
        if cam_tee is None:
            log.warning("FX source: camera tee for %s not found", source)
            return False

    compositor._fx_switching = True

    # Use IDLE probe on input-selector src pad for safe modification
    src_pad = input_sel.get_static_pad("src")

    def _probe_callback(pad: Any, info: Any) -> Any:
        try:
            # Tear down previous camera branch if any
            _teardown_camera_branch(compositor, Gst)

            out_w = compositor.config.output_width
            out_h = compositor.config.output_height
            fps = compositor.config.framerate

            if is_youtube:
                # YouTube: v4l2src from /dev/video50
                v4l2 = Gst.ElementFactory.make("v4l2src", "fxsrc-yt")
                v4l2.set_property("device", "/dev/video50")
                v4l2.set_property("do-timestamp", True)
                q = Gst.ElementFactory.make("queue", "fxsrc-q")
                q.set_property("leaky", 2)
                q.set_property("max-size-buffers", 1)
                convert = Gst.ElementFactory.make("videoconvert", "fxsrc-convert")
                convert.set_property("dither", 0)
                scale = Gst.ElementFactory.make("videoscale", "fxsrc-scale")
                caps = Gst.ElementFactory.make("capsfilter", "fxsrc-caps")
                caps.set_property(
                    "caps",
                    Gst.Caps.from_string(f"video/x-raw,format=BGRA,width={out_w},height={out_h}"),
                )
                elements = [v4l2, q, convert, scale, caps]
                for el in elements:
                    pipeline.add(el)
                v4l2.link(q)
                q.link(convert)
                convert.link(scale)
                scale.link(caps)
                for el in elements:
                    el.sync_state_with_parent()
            else:
                # Camera: branch from camera_tee
                q = Gst.ElementFactory.make("queue", "fxsrc-q")
                q.set_property("leaky", 2)
                q.set_property("max-size-buffers", 1)
                convert = Gst.ElementFactory.make("videoconvert", "fxsrc-convert")
                convert.set_property("dither", 0)
                scale = Gst.ElementFactory.make("videoscale", "fxsrc-scale")
                caps = Gst.ElementFactory.make("capsfilter", "fxsrc-caps")
                caps.set_property(
                    "caps",
                    Gst.Caps.from_string(
                        f"video/x-raw,format=BGRA,width={out_w},height={out_h},framerate={fps}/1"
                    ),
                )

                elements = [q, convert, scale, caps]
                for el in elements:
                    pipeline.add(el)
                q.link(convert)
                convert.link(scale)
                scale.link(caps)
                for el in elements:
                    el.sync_state_with_parent()

                # Link camera tee → queue
                tee_pad = cam_tee.request_pad(cam_tee.get_pad_template("src_%u"), None, None)
                q_sink = q.get_static_pad("sink")
                tee_pad.link(q_sink)

            # Link caps → new input-selector pad
            sel_pad = input_sel.request_pad(input_sel.get_pad_template("sink_%u"), None, None)
            caps.link_pads("src", input_sel, sel_pad.get_name())

            # Switch active pad
            input_sel.set_property("active-pad", sel_pad)

            # Store for teardown
            if is_youtube:
                elements = [
                    el
                    for el in [
                        pipeline.get_by_name("fxsrc-yt"),
                        pipeline.get_by_name("fxsrc-q"),
                        pipeline.get_by_name("fxsrc-convert"),
                        pipeline.get_by_name("fxsrc-scale"),
                        pipeline.get_by_name("fxsrc-caps"),
                    ]
                    if el is not None
                ]
            compositor._fx_camera_branch = elements
            compositor._fx_camera_tee_pad = None if is_youtube else tee_pad
            compositor._fx_camera_sel_pad = sel_pad
            compositor._fx_active_source = source
            compositor._fx_switching = False

            log.info("FX source: switched to %s (lazy branch created)", source)
        except Exception:
            log.exception("FX source switch failed")
            compositor._fx_switching = False

        return Gst.PadProbeReturn.REMOVE

    src_pad.add_probe(Gst.PadProbeType.IDLE, _probe_callback)
    return True


def _teardown_camera_branch(compositor: Any, Gst: Any) -> None:
    """Remove the previous camera-specific FX source branch."""
    elements = getattr(compositor, "_fx_camera_branch", [])
    if not elements:
        return

    pipeline = compositor.pipeline

    # Unlink camera tee pad
    tee_pad = getattr(compositor, "_fx_camera_tee_pad", None)
    if tee_pad is not None:
        peer = tee_pad.get_peer()
        if peer is not None:
            tee_pad.unlink(peer)

    # Release input-selector pad
    sel_pad = getattr(compositor, "_fx_camera_sel_pad", None)
    if sel_pad is not None:
        compositor._fx_input_selector.release_request_pad(sel_pad)

    # Stop and remove elements
    for el in reversed(elements):
        el.set_state(Gst.State.NULL)
        pipeline.remove(el)

    compositor._fx_camera_branch = []
    compositor._fx_camera_tee_pad = None
    compositor._fx_camera_sel_pad = None


def fx_tick_callback(compositor: Any) -> bool:
    """GLib timeout: update graph shader uniforms at ~30fps."""
    if not compositor._running:
        return False
    if not hasattr(compositor, "_slot_pipeline") or compositor._slot_pipeline is None:
        return False

    from .fx_tick import tick_governance, tick_modulator, tick_slot_pipeline

    if not hasattr(compositor, "_fx_monotonic_start"):
        compositor._fx_monotonic_start = time.monotonic()
    t = time.monotonic() - compositor._fx_monotonic_start

    with compositor._overlay_state._lock:
        energy = compositor._overlay_state._data.audio_energy_rms
    beat = min(energy * 4.0, 1.0)
    if not hasattr(compositor, "_fx_beat_smooth"):
        compositor._fx_beat_smooth = 0.0
    compositor._fx_beat_smooth = max(beat, compositor._fx_beat_smooth * 0.85)
    b = compositor._fx_beat_smooth

    # Cache audio signals BEFORE tick_modulator (which calls get_signals and decays them)
    cached_audio: dict[str, float] = {}
    if hasattr(compositor, "_audio_capture"):
        cached_audio = compositor._audio_capture.get_signals()
    compositor._cached_audio = cached_audio

    tick_governance(compositor, t)
    tick_modulator(compositor, t, energy, b)
    tick_slot_pipeline(compositor, t)

    # Flash scheduler: animate glvideomixer flash pad alpha
    scheduler = getattr(compositor, "_fx_flash_scheduler", None)
    flash_pad = getattr(compositor, "_fx_flash_pad", None)
    if scheduler and flash_pad:
        now = time.monotonic()
        kick = cached_audio.get("onset_kick", 0.0)
        beat = cached_audio.get("beat_pulse", 0.0)
        bass = cached_audio.get("mixer_bass", 0.0)
        if kick > 0.3 or beat > 0.6:
            scheduler.kick(now, bass)
        alpha = scheduler.tick(now)
        if alpha is not None:
            flash_pad.set_property("alpha", alpha)

    # Facade tick() hooks removed in Phase 9 Task 29. Cairo sources now
    # tick autonomously on their CairoSourceRunner background threads.
    return True
