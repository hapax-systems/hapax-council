"""Inline GPU effects chain and per-frame tick callback."""

from __future__ import annotations

import logging
import random
from typing import Any

log = logging.getLogger(__name__)


def build_inline_fx_chain(
    compositor: Any, pipeline: Any, pre_fx_tee: Any, output_tee: Any, fps: int
) -> bool:
    """Build GPU-accelerated effects chain inline between pre_fx_tee and output_tee.

    Returns True if chain was built, False if GL elements unavailable.
    """
    Gst = compositor._Gst

    from agents.studio_effects import PRESETS, load_shader

    initial_preset = PRESETS.get("clean", list(PRESETS.values())[0])

    queue = Gst.ElementFactory.make("queue", "queue-fx")
    queue.set_property("leaky", 2)
    queue.set_property("max-size-buffers", 2)

    from agents.studio_stutter import StutterElement

    stutter_el = StutterElement()
    stutter_el.set_property("check-interval", 999)
    stutter_el.set_property("freeze-chance", 0.0)

    convert_rgba = Gst.ElementFactory.make("videoconvert", "fx-convert-rgba")
    rgba_caps = Gst.ElementFactory.make("capsfilter", "fx-rgba-caps")
    rgba_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,format=RGBA"))

    glupload = Gst.ElementFactory.make("glupload", "fx-glupload")
    glcolorconvert_in = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-in")

    from agents.effect_graph.pipeline import SlotPipeline

    registry = compositor._graph_runtime._registry if compositor._graph_runtime else None
    compositor._slot_pipeline = SlotPipeline(registry, num_slots=8)

    glow_effect = Gst.ElementFactory.make("gleffects", "fx-glow")
    glow_effect.set_property("effect", 0)

    post_proc = Gst.ElementFactory.make("glshader", "fx-post-process")
    post_frag = load_shader("post_process.frag")
    if post_frag:
        post_proc.set_property("fragment", post_frag)
        pp = initial_preset.post_process
        pp_uniforms = Gst.Structure.from_string(
            f"uniforms, u_vignette_strength=(float){pp.vignette_strength}, "
            f"u_scanline_alpha=(float){pp.scanline_alpha}, "
            f"u_time=(float)0.0, "
            f"u_band_active=(float)0.0, "
            f"u_band_y=(float)0.0, u_band_height=(float)0.0, u_band_shift=(float)0.0, "
            f"u_syrup_active=(float){1.0 if pp.syrup_gradient else 0.0}, "
            f"u_syrup_color_r=(float){pp.syrup_color[0]}, "
            f"u_syrup_color_g=(float){pp.syrup_color[1]}, "
            f"u_syrup_color_b=(float){pp.syrup_color[2]}"
        )
        post_proc.set_property("uniforms", pp_uniforms[0])

    glcolorconvert_out = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-out")
    gldownload = Gst.ElementFactory.make("gldownload", "fx-gldownload")
    fx_convert = Gst.ElementFactory.make("videoconvert", "fx-out-convert")

    required = [
        queue,
        stutter_el,
        convert_rgba,
        rgba_caps,
        glupload,
        glcolorconvert_in,
        glow_effect,
        post_proc,
        glcolorconvert_out,
        gldownload,
        fx_convert,
    ]
    for el in required:
        if el is None:
            log.error("Failed to create required FX element — effects disabled")
            return False

    for el in required:
        pipeline.add(el)

    queue.link(stutter_el)
    stutter_el.link(convert_rgba)
    convert_rgba.link(rgba_caps)
    rgba_caps.link(glupload)
    glupload.link(glcolorconvert_in)

    compositor._slot_pipeline.build_chain(pipeline, Gst, glcolorconvert_in, glow_effect)

    temporal_fx = Gst.ElementFactory.make("temporalfx", "fx-temporal")
    crossfade_fx = Gst.ElementFactory.make("crossfade", "fx-crossfade")

    prev = glow_effect
    if temporal_fx is not None:
        pipeline.add(temporal_fx)
        temporal_fx.set_property("feedback-amount", 0.0)
        prev.link(temporal_fx)
        prev = temporal_fx
    else:
        log.error("temporalfx plugin not found! Install libgsttemporalfx.so")

    if crossfade_fx is not None:
        pipeline.add(crossfade_fx)
        crossfade_fx.set_property("transition-ms", 500)
        prev.link(crossfade_fx)
        prev = crossfade_fx
    else:
        log.warning("crossfade plugin not found — preset transitions will be instant")

    prev.link(post_proc)
    post_proc.link(glcolorconvert_out)
    glcolorconvert_out.link(gldownload)
    gldownload.link(fx_convert)
    fx_convert.link(output_tee)

    tee_pad = pre_fx_tee.request_pad(pre_fx_tee.get_pad_template("src_%u"), None, None)
    queue_sink = queue.get_static_pad("sink")
    tee_pad.link(queue_sink)

    compositor._fx_temporal = temporal_fx
    compositor._fx_crossfade = crossfade_fx
    compositor._fx_stutter = stutter_el
    compositor._fx_glow_effect = glow_effect
    compositor._fx_post_proc = post_proc
    compositor._fx_active_preset = initial_preset.name
    compositor._fx_graph_mode = False
    compositor._fx_tick = 0
    log.info("FX chain: inline GL effects before all display outputs")
    return True


def fx_tick_callback(compositor: Any) -> bool:
    """GLib timeout: update time-varying FX shader uniforms at ~30fps."""
    if not compositor._running:
        return False
    if not hasattr(compositor, "_slot_pipeline"):
        return False

    from agents.studio_effects import PRESETS

    from .fx_tick import tick_governance, tick_modulator, tick_slot_pipeline

    compositor._fx_tick += 1
    t = compositor._fx_tick * 0.04
    Gst = compositor._Gst

    preset = PRESETS.get(compositor._fx_active_preset)
    if not preset:
        return True

    # Beat reactivity
    with compositor._overlay_state._lock:
        energy = compositor._overlay_state._data.audio_energy_rms
    beat = min(energy * 4.0, 1.0)
    if not hasattr(compositor, "_fx_beat_smooth"):
        compositor._fx_beat_smooth = 0.0
    compositor._fx_beat_smooth = max(beat, compositor._fx_beat_smooth * 0.85)
    b = compositor._fx_beat_smooth

    # Post-process band displacement
    pp = preset.post_process
    beat_band_chance = pp.band_chance + b * 0.3
    beat_band_shift = pp.band_max_shift * (1.0 + b * 1.0)

    band_active = 1.0 if beat_band_chance > 0 and random.random() < beat_band_chance else 0.0
    band_y = random.random() * 0.6 + 0.2 if band_active else 0.0
    band_h = random.random() * 0.03 + 0.005 if band_active else 0.0
    band_shift = (random.random() - 0.5) * 2 * beat_band_shift / 1920.0 if band_active else 0.0

    beat_vignette = pp.vignette_strength * (1.0 - b * 0.3)

    pp_u = Gst.Structure.from_string(
        f"uniforms, u_vignette_strength=(float){beat_vignette}, "
        f"u_scanline_alpha=(float){pp.scanline_alpha}, "
        f"u_time=(float){t}, "
        f"u_band_active=(float){band_active}, "
        f"u_band_y=(float){band_y}, u_band_height=(float){band_h}, u_band_shift=(float){band_shift}, "
        f"u_syrup_active=(float){1.0 if pp.syrup_gradient else 0.0}, "
        f"u_syrup_color_r=(float){pp.syrup_color[0]}, "
        f"u_syrup_color_g=(float){pp.syrup_color[1]}, "
        f"u_syrup_color_b=(float){pp.syrup_color[2]}"
    )
    compositor._fx_post_proc.set_property("uniforms", pp_u[0])

    tick_governance(compositor, t)
    tick_modulator(compositor, t, energy, b)
    tick_slot_pipeline(compositor, t)

    return True
