"""Inline GPU effects chain and per-frame tick callback."""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)


def build_inline_fx_chain(
    compositor: Any, pipeline: Any, pre_fx_tee: Any, output_tee: Any, fps: int
) -> bool:
    """Build graph-only GPU effects chain with switchable input source.

    Pipeline: input-selector → queue → videoconvert → capsfilter(RGBA) → glupload
      → glcolorconvert → [SlotPipeline: 8 glshader slots]
      → glcolorconvert → gldownload → videoconvert → output_tee

    Input sources: pre_fx_tee (live), smooth-delay, HLS — switched via input-selector.
    """
    Gst = compositor._Gst

    # Input selector: switchable source for the FX chain
    input_sel = Gst.ElementFactory.make("input-selector", "fx-input-selector")
    if input_sel is None:
        log.warning("input-selector not available — FX chain will use live only")
        input_sel = None

    queue = Gst.ElementFactory.make("queue", "queue-fx")
    queue.set_property("leaky", 2)
    queue.set_property("max-size-buffers", 1)

    convert_rgba = Gst.ElementFactory.make("videoconvert", "fx-convert-rgba")
    rgba_caps = Gst.ElementFactory.make("capsfilter", "fx-rgba-caps")
    rgba_caps.set_property("caps", Gst.Caps.from_string("video/x-raw,format=RGBA"))

    glupload = Gst.ElementFactory.make("glupload", "fx-glupload")
    glcolorconvert_in = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-in")

    from agents.effect_graph.pipeline import SlotPipeline

    registry = compositor._graph_runtime._registry if compositor._graph_runtime else None
    compositor._slot_pipeline = SlotPipeline(registry, num_slots=8)

    glcolorconvert_out = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-out")
    gldownload = Gst.ElementFactory.make("gldownload", "fx-gldownload")
    fx_convert = Gst.ElementFactory.make("videoconvert", "fx-out-convert")

    required = [
        queue,
        convert_rgba,
        rgba_caps,
        glupload,
        glcolorconvert_in,
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

    queue.link(convert_rgba)
    convert_rgba.link(rgba_caps)
    rgba_caps.link(glupload)
    glupload.link(glcolorconvert_in)

    compositor._slot_pipeline.build_chain(pipeline, Gst, glcolorconvert_in, glcolorconvert_out)

    glcolorconvert_out.link(gldownload)
    gldownload.link(fx_convert)
    fx_convert.link(output_tee)

    if input_sel is not None:
        pipeline.add(input_sel)
        # Link input-selector output → queue
        input_sel.link(queue)

        # Pad 0: live (pre_fx_tee) — default
        live_pad = input_sel.request_pad(input_sel.get_pad_template("sink_%u"), None, None)
        tee_pad = pre_fx_tee.request_pad(pre_fx_tee.get_pad_template("src_%u"), None, None)
        tee_pad.link(live_pad)
        input_sel.set_property("active-pad", live_pad)

        # Pad 1: smooth delay (if available)
        smooth_el = pipeline.get_by_name("smooth-out-convert")
        if smooth_el:
            smooth_pad = input_sel.request_pad(input_sel.get_pad_template("sink_%u"), None, None)
            smooth_tee = Gst.ElementFactory.make("tee", "smooth-fx-tee")
            smooth_queue = Gst.ElementFactory.make("queue", "queue-smooth-fx")
            smooth_queue.set_property("leaky", 2)
            smooth_queue.set_property("max-size-buffers", 1)
            pipeline.add(smooth_tee)
            pipeline.add(smooth_queue)
            smooth_el.link(smooth_tee)
            smooth_tee_pad = smooth_tee.request_pad(
                smooth_tee.get_pad_template("src_%u"), None, None
            )
            smooth_queue_sink = smooth_queue.get_static_pad("sink")
            smooth_tee_pad.link(smooth_queue_sink)
            smooth_queue.link_pads("src", input_sel, smooth_pad.get_name())
            log.info("FX input: smooth delay connected as pad 1")

        # Store selector and pad map for runtime switching
        compositor._fx_input_selector = input_sel
        compositor._fx_input_pads = {"@live": live_pad}
        if smooth_el:
            compositor._fx_input_pads["@smooth"] = smooth_pad
    else:
        # Fallback: direct link from live
        tee_pad = pre_fx_tee.request_pad(pre_fx_tee.get_pad_template("src_%u"), None, None)
        queue_sink = queue.get_static_pad("sink")
        tee_pad.link(queue_sink)

    log.info(
        "FX chain: graph-only pipeline with %d shader slots, %d input sources",
        compositor._slot_pipeline.num_slots,
        len(getattr(compositor, "_fx_input_pads", {"@live": None})),
    )
    return True


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

    tick_governance(compositor, t)
    tick_modulator(compositor, t, energy, b)
    tick_slot_pipeline(compositor, t)

    return True
