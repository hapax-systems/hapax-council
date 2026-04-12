"""State reader loop and camera reconnection."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from .config import PERCEPTION_STATE_PATH, SNAPSHOT_DIR
from .effects import try_graph_preset
from .layout import compute_tile_layout
from .models import OverlayData
from .profiles import apply_camera_profile, evaluate_active_profile

log = logging.getLogger(__name__)


def evaluate_camera_profile(compositor: Any) -> None:
    """Evaluate and apply camera profiles if changed."""
    if not compositor._camera_profiles:
        return
    overlay_data = compositor._overlay_state.data
    profile = evaluate_active_profile(compositor._camera_profiles, overlay_data)
    if profile is None:
        if compositor._active_profile_name:
            log.info("No camera profile matches, clearing active profile")
            compositor._active_profile_name = ""
        return
    if profile.name != compositor._active_profile_name:
        log.info(
            "Switching camera profile: %s -> %s", compositor._active_profile_name, profile.name
        )
        compositor._active_profile_name = profile.name
        apply_camera_profile(profile)


def apply_layout_mode(compositor: Any, mode: str) -> None:
    """Recompute the tile layout and update compositor sink pad properties.

    Runtime layout switch: no pipeline rebuild, no caps renegotiation.
    GStreamer compositor scales each camera input to fit its pad's
    width/height automatically.
    """
    cameras = list(getattr(compositor, "_camera_specs", {}).values())
    if not cameras:
        return

    canvas_w = compositor.config.output_width
    canvas_h = compositor.config.output_height
    new_layout = compute_tile_layout(cameras, canvas_w, canvas_h, mode=mode)

    applied = 0
    for role, tile in new_layout.items():
        elements = compositor._camera_elements.get(role, {})
        pad = elements.get("comp_pad")
        if pad is None:
            continue
        try:
            pad.set_property("xpos", int(tile.x))
            pad.set_property("ypos", int(tile.y))
            pad.set_property("width", int(tile.w))
            pad.set_property("height", int(tile.h))
            applied += 1
        except Exception:
            log.debug("Failed to update pad for camera %s", role, exc_info=True)

    compositor._layout_mode = mode
    log.info("Layout mode: %s (applied to %d cameras)", mode, applied)


def try_reconnect_camera(compositor: Any, role: str) -> bool:
    """Attempt to reconnect an offline camera."""
    spec = compositor._camera_specs.get(role) if hasattr(compositor, "_camera_specs") else None
    if not spec or not Path(spec.device).exists():
        return False

    elements = (
        compositor._camera_elements.get(role, {}) if hasattr(compositor, "_camera_elements") else {}
    )
    src = elements.get("src")
    if src is None:
        return False

    src.set_state(compositor._Gst.State.NULL)
    time.sleep(0.5)
    ret = src.set_state(compositor._Gst.State.PLAYING)

    if ret == compositor._Gst.StateChangeReturn.FAILURE:
        log.warning("Failed to reconnect camera %s", role)
        return False

    with compositor._camera_status_lock:
        compositor._camera_status[role] = "active"
    log.info("Camera %s reconnected", role)
    compositor._write_status("running")
    return True


def state_reader_loop(compositor: Any) -> None:
    """Daemon thread: read perception-state.json every 1s."""

    profile_check_counter = 0
    reconnect_counter = 0
    layout_check_counter = 0
    while compositor._running:
        try:
            if PERCEPTION_STATE_PATH.exists():
                raw = PERCEPTION_STATE_PATH.read_text()
                data = OverlayData(**json.loads(raw))
                if time.time() - data.timestamp > 10:
                    compositor._overlay_state.mark_stale()
                else:
                    compositor._overlay_state.update(data)
            else:
                compositor._overlay_state.mark_stale()
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            log.debug("Failed to read perception state: %s", exc)
            compositor._overlay_state.mark_stale()

        # Consent enforcement
        with compositor._overlay_state._lock:
            consent_ok = compositor._overlay_state._data.persistence_allowed
        if consent_ok != compositor._consent_recording_allowed:
            compositor._consent_recording_allowed = consent_ok
            GLib = compositor._GLib
            if GLib:
                from .consent import disable_persistence, enable_persistence

                if consent_ok:
                    GLib.idle_add(lambda: enable_persistence(compositor))
                else:
                    GLib.idle_add(lambda: disable_persistence(compositor))

        # Layout hot-reload every ~1s (Phase 2c — currently advisory only;
        # no rendering code consumes the active Layout yet)
        layout_check_counter += 1
        if layout_check_counter >= 10:
            layout_check_counter = 0
            try:
                if hasattr(compositor, "_layout_store"):
                    changed = compositor._layout_store.reload_changed()
                    if changed:
                        log.info("Layouts reloaded: %s", changed)
            except Exception as exc:
                log.debug("Layout reload failed: %s", exc)

        # Camera profiles every ~10s
        profile_check_counter += 1
        if profile_check_counter >= 100:
            profile_check_counter = 0
            try:
                evaluate_camera_profile(compositor)
            except Exception as exc:
                log.debug("Failed to evaluate camera profile: %s", exc)

            reconnect_counter += 1
            if reconnect_counter >= 3:
                reconnect_counter = 0
                with compositor._camera_status_lock:
                    offline = [r for r, s in compositor._camera_status.items() if s == "offline"]
                for role in offline:
                    try:
                        try_reconnect_camera(compositor, role)
                    except Exception as exc:
                        log.debug("Camera reconnect failed for %s: %s", role, exc)

        # FX graph replacement (from chain builder PUT)
        graph_mutation_path = SNAPSHOT_DIR / "graph-mutation.json"
        if graph_mutation_path.exists():
            try:
                raw = graph_mutation_path.read_text().strip()
                graph_mutation_path.unlink(missing_ok=True)
                if raw and compositor._graph_runtime is not None:
                    from agents.effect_graph.types import EffectGraph

                    from .effects import merge_default_modulations

                    graph = EffectGraph(**json.loads(raw))
                    graph = merge_default_modulations(graph)
                    compositor._graph_runtime.load_graph(graph)
                    compositor._current_preset_name = graph.name
                    compositor._user_preset_hold_until = time.monotonic() + 600.0
                    try:
                        (SNAPSHOT_DIR / "fx-current.txt").write_text(graph.name)
                    except OSError:
                        pass
                    log.info("Loaded graph from mutation file: %s", graph.name)
            except Exception as exc:
                log.debug("Failed to process graph mutation: %s", exc)
                graph_mutation_path.unlink(missing_ok=True)

        # FX input source switching (independent of graph mutation)
        source_path = SNAPSHOT_DIR / "fx-source.txt"
        if source_path.exists():
            try:
                source = source_path.read_text().strip()
                has_sel = hasattr(compositor, "_fx_input_selector")
                log.info("FX source request: %s (has_selector=%s)", source, has_sel)
                if has_sel:
                    from .fx_chain import switch_fx_source

                    switch_fx_source(compositor, source)
            except Exception:
                log.exception("FX source switch failed")
            finally:
                source_path.unlink(missing_ok=True)

        # FX preset switch requests
        fx_request_path = SNAPSHOT_DIR / "fx-request.txt"
        if fx_request_path.exists():
            try:
                preset_name = fx_request_path.read_text().strip()
                fx_request_path.unlink(missing_ok=True)
                if preset_name and compositor._graph_runtime is not None:
                    try_graph_preset(compositor, preset_name)
                    compositor._current_preset_name = preset_name
                    compositor._user_preset_hold_until = time.monotonic() + 600.0
                    try:
                        (SNAPSHOT_DIR / "fx-current.txt").write_text(preset_name)
                    except OSError:
                        pass
            except Exception as exc:
                log.debug("Failed to process FX request: %s", exc)
                fx_request_path.unlink(missing_ok=True)
        # Layout mode switch (balanced / hero/{role} / sierpinski)
        layout_path = SNAPSHOT_DIR / "layout-mode.txt"
        if layout_path.exists():
            try:
                requested = layout_path.read_text().strip() or "balanced"
                layout_path.unlink(missing_ok=True)
                current = getattr(compositor, "_layout_mode", "balanced")
                if requested != current:
                    GLib = compositor._GLib
                    if GLib:
                        GLib.idle_add(lambda m=requested: apply_layout_mode(compositor, m) or False)
                    else:
                        apply_layout_mode(compositor, requested)
            except Exception:
                log.debug("Layout mode switch failed", exc_info=True)

        # Vinyl mode toggle (Stream Deck / API)
        vinyl_path = SNAPSHOT_DIR / "vinyl-mode.txt"
        if vinyl_path.exists():
            try:
                vinyl = vinyl_path.read_text().strip() == "true"
                from .audio_capture import CompositorAudioCapture

                if vinyl != CompositorAudioCapture.VINYL_MODE:
                    CompositorAudioCapture.VINYL_MODE = vinyl
                    scheduler = getattr(compositor, "_fx_flash_scheduler", None)
                    if scheduler:
                        scheduler._vinyl_mode = vinyl
                    log.info("Vinyl mode: %s", "ON" if vinyl else "OFF")
            except Exception:
                pass

        if hasattr(compositor, "_overlay_zone_manager"):
            compositor._overlay_zone_manager.tick()
        time.sleep(0.1)
