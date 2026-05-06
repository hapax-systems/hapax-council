"""State reader loop and camera reconnection."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from . import metrics as _metrics
from .config import PERCEPTION_STATE_PATH, SNAPSHOT_DIR
from .effects import try_graph_preset
from .follow_mode import FollowModeController, read_follow_mode_recommendation
from .layout import compute_tile_layout
from .models import OverlayData
from .profiles import apply_camera_profile, evaluate_active_profile

log = logging.getLogger(__name__)

# Task #136 — follow-mode controller singleton. One instance per
# compositor process; reused by the state reader loop at 2 Hz. The
# controller keeps a 30-s rolling hero-history in memory so the
# repetition penalty works across ticks.
_FOLLOW_MODE_CONTROLLER: FollowModeController | None = None


def _get_follow_mode_controller() -> FollowModeController:
    global _FOLLOW_MODE_CONTROLLER
    if _FOLLOW_MODE_CONTROLLER is None:
        _FOLLOW_MODE_CONTROLLER = FollowModeController()
    return _FOLLOW_MODE_CONTROLLER


def process_livestream_control(compositor: Any, snapshot_dir: Path | None = None) -> bool:
    """Consume a pending livestream-control.json from the daimonion.

    Reads ``{activate, reason, requested_at}`` and dispatches
    ``compositor.toggle_livestream(activate, reason)`` on the GLib main
    loop, then writes a ``livestream-status.json`` artifact with the
    result so the daimonion (or an operator) can inspect the outcome
    asynchronously. The control file is deleted after read regardless
    of success, to prevent retry storms on a malformed payload.

    Returns True if a control file was consumed, False otherwise.
    """
    control_path = (snapshot_dir or SNAPSHOT_DIR) / "livestream-control.json"
    status_path = (snapshot_dir or SNAPSHOT_DIR) / "livestream-status.json"
    if not control_path.exists():
        return False

    try:
        payload = json.loads(control_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.exception("Failed to read livestream-control.json: %s", exc)
        control_path.unlink(missing_ok=True)
        return True
    finally:
        control_path.unlink(missing_ok=True)

    activate = bool(payload.get("activate", False))
    reason = str(payload.get("reason") or "").strip() or "unspecified"
    requested_at = payload.get("requested_at")

    def _dispatch() -> bool:
        try:
            success, message = compositor.toggle_livestream(activate, reason)
        except Exception:
            log.exception("toggle_livestream raised during livestream control dispatch")
            success, message = False, "toggle_livestream raised"
        status = {
            "activate": activate,
            "reason": reason,
            "requested_at": requested_at,
            "processed_at": time.time(),
            "success": bool(success),
            "message": str(message),
        }
        try:
            status_path.write_text(json.dumps(status))
        except OSError:
            log.exception("Failed to write livestream-status.json")
        return False  # GLib.idle_add one-shot

    glib = getattr(compositor, "_GLib", None)
    if glib is not None:
        glib.idle_add(_dispatch)
    else:
        _dispatch()
    return True


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

    When the initial layout mode is ``"packed"``, hero-override and
    follow-mode switches are suppressed — packed mode manages camera
    placement via the PackedCamerasCairoSource overlay, not cudacompositor
    pad geometry.
    """
    # Guard: packed mode is not overridable by hero switches
    initial_mode = getattr(compositor, "_initial_layout_mode", None)
    if initial_mode == "packed" and mode != "packed":
        log.debug("Layout mode %s suppressed — packed mode is active", mode)
        return

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
    """Attempt to reconnect an offline camera.

    Phase 2 (hot-swap architecture): the per-camera supervisor thread in
    PipelineManager owns reconnection via exponential-backoff rebuild of the
    producer sub-pipeline. When this function is called from the state reader
    loop, we simply ask the manager to schedule an immediate attempt — it is
    a no-op if one is already in flight. The old in-place set_state NULL/PLAYING
    dance doesn't apply to interpipesrc consumers.

    Phase 3 replaces this function with direct CameraStateMachine dispatch.
    """
    pm = getattr(compositor, "_pipeline_manager", None)
    if pm is not None:
        try:
            pm._schedule_reconnect(role, 0.0)
        except Exception:
            log.exception("Phase 2 reconnect schedule raised for %s", role)
            return False
        return True

    # Legacy path (pre-Phase 2). Should never execute once Phase 2 ships,
    # but kept briefly as a safety net during the overlap window.
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

        # Phase 6 follow-up (volitional-director epic): live-video egress
        # compose-safe hot-swap. The persistence-allowed check above guards
        # the *recording valve*; this block additionally publishes a
        # consent-safe-active signal so the live video output layer can
        # swap in `consent-safe.json` when a non-operator face is detected
        # without an active consent contract (closes axiom
        # it-irreversible-broadcast at egress, not just persistence).
        try:
            from .consent_live_egress import (
                CONSENT_SAFE_LAYOUT_NAME,
                should_egress_compose_safe,
            )

            with compositor._overlay_state._lock:
                od = compositor._overlay_state._data
            compose_safe = should_egress_compose_safe(od)
            prev = getattr(compositor, "_compose_safe_active", False)
            if compose_safe != prev:
                compositor._compose_safe_active = compose_safe
                # Publish signal for layout-swap consumers (current signal-file
                # pattern; in-process LayoutStore.set_active is also called for
                # the existing advisory registry).
                import json as _json
                import time as _time
                from pathlib import Path as _P

                marker = _P("/dev/shm/hapax-compositor/consent-safe-active.json")
                try:
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    tmp = marker.with_suffix(".json.tmp")
                    tmp.write_text(
                        _json.dumps(
                            {
                                "active": compose_safe,
                                "since_ts": _time.time(),
                                "target_layout": (
                                    CONSENT_SAFE_LAYOUT_NAME if compose_safe else "default.json"
                                ),
                            }
                        ),
                        encoding="utf-8",
                    )
                    tmp.replace(marker)
                except Exception:
                    log.debug("consent-safe-active marker write failed", exc_info=True)
                # Advisory LayoutStore toggle — consumer code can read
                # active_name() when available. Graceful no-op if either
                # the target layout isn't loaded or the store is absent.
                store = getattr(compositor, "_layout_store", None)
                if store is not None:
                    target = "consent-safe" if compose_safe else "default"
                    try:
                        if target in store.list_available():
                            store.set_active(target)
                    except Exception:
                        log.debug("layout_store.set_active failed", exc_info=True)
                # Phase 6c hot-swap consumer wiring. The LayoutStore
                # toggle above is advisory — no rendering code binds to
                # it yet. The PipelineManager pin is the enforced path:
                # it swaps every camera interpipesrc to its fallback and
                # blocks any subsequent swap_to_primary for the duration
                # of the pin. Closes axiom it-irreversible-broadcast at
                # the live GStreamer egress, not just at persistence.
                pm = getattr(compositor, "_pipeline_manager", None)
                if pm is not None:
                    try:
                        pm.set_compose_safe(compose_safe)
                    except Exception:
                        log.exception(
                            "pipeline_manager.set_compose_safe failed (compose_safe=%s)",
                            compose_safe,
                        )
                log.info(
                    "compose-safe egress %s (prev=%s)",
                    "ACTIVE" if compose_safe else "cleared",
                    prev,
                )
        except Exception:
            log.debug("compose-safe egress block failed", exc_info=True)

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
            preset_hint = "unknown"
            try:
                raw = graph_mutation_path.read_text().strip()
                graph_mutation_path.unlink(missing_ok=True)
                if raw and compositor._graph_runtime is not None:
                    from agents.effect_graph.types import EffectGraph

                    from .effects import merge_default_modulations

                    # Pre-extract a preset hint from the raw JSON for
                    # the failure path's metric label. Best-effort —
                    # any error here is swallowed so the actual load
                    # path's exception is the one that surfaces.
                    try:
                        _hint = json.loads(raw).get("name")
                        if isinstance(_hint, str):
                            preset_hint = _hint
                    except Exception:
                        pass
                    parsed = json.loads(raw)
                    # Source-aware hold lifecycle. Recruitment-driven
                    # mutations (preset_recruitment_consumer._write_mutation)
                    # tag with _source="recruitment" and get a 25s hold so
                    # the next director recruitment can land. Operator-manual
                    # paths (chain builder PUT, chat reactor, untagged) keep
                    # the 600s hold that protects authored intent from
                    # director thrash. _source is not an EffectGraph field,
                    # so pop before construction.
                    source_tag = parsed.pop("_source", None)
                    graph = EffectGraph(**parsed)
                    graph = merge_default_modulations(graph)
                    compositor._graph_runtime.load_graph(graph)
                    compositor._current_preset_name = graph.name
                    if source_tag == "recruitment":
                        compositor._user_preset_hold_until = time.monotonic() + 25.0
                    else:
                        compositor._user_preset_hold_until = time.monotonic() + 600.0
                    try:
                        (SNAPSHOT_DIR / "fx-current.txt").write_text(graph.name)
                    except OSError:
                        pass
                    log.info("Loaded graph from mutation file: %s", graph.name)
            except Exception as exc:
                # Researcher audit 2026-05-03: was DEBUG-swallowed; the
                # 64% load-fail rate was invisible in dashboards. Now
                # WARNING + Prometheus counter so failures surface.
                log.warning("preset load failed: %s — %s", preset_hint, exc, exc_info=True)
                _metrics.record_preset_load_failed(preset=preset_hint, reason=type(exc).__name__)
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
            preset_name = "unknown"
            try:
                preset_name = fx_request_path.read_text().strip() or "unknown"
                fx_request_path.unlink(missing_ok=True)
                if (
                    preset_name
                    and preset_name != "unknown"
                    and compositor._graph_runtime is not None
                ):
                    try_graph_preset(compositor, preset_name)
                    compositor._current_preset_name = preset_name
                    # 2026-05-04 hot-fix: 600.0 s → 25.0 s. The 10-min hold blocked
                    # recruitment-driven mutations (which use the same bus) from
                    # advancing for 10 min after each director cycle. Operator
                    # manual changes still get a brief 25 s lock — sufficient to
                    # avoid director thrash without freezing the chain.
                    compositor._user_preset_hold_until = time.monotonic() + 25.0
                    try:
                        (SNAPSHOT_DIR / "fx-current.txt").write_text(preset_name)
                    except OSError:
                        pass
            except Exception as exc:
                # Researcher audit 2026-05-03: parallel to the
                # graph-mutation path, was DEBUG-swallowed; promoted to
                # WARNING + counter so preset_recruitment / chat-driven
                # request failures surface.
                log.warning("preset load failed: %s — %s", preset_name, exc, exc_info=True)
                _metrics.record_preset_load_failed(preset=preset_name, reason=type(exc).__name__)
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

        # stream-mode-intent.json consumer (meta-structural audit fix #6).
        # compositional_consumer.dispatch_stream_mode_transition writes
        # the recruited target_mode; nothing read it before. Converts
        # the recruitment into an actual shared/stream_mode.set call so
        # the new mode is honoured by every get_stream_mode() consumer
        # (chat-reactor cooldowns, stimmung redaction, fortress gate,
        # captions style, etc.). Same idempotency guard via set_at.
        sm_intent_path = Path("/dev/shm/hapax-compositor/stream-mode-intent.json")
        if sm_intent_path.exists():
            try:
                sm_payload = json.loads(sm_intent_path.read_text(encoding="utf-8"))
                sm_set_at = float(sm_payload.get("set_at", 0.0))
                target_mode_raw = str(sm_payload.get("target_mode") or "").strip()
                sm_last_applied = getattr(compositor, "_stream_mode_last_applied_set_at", 0.0)
                if target_mode_raw and sm_set_at > sm_last_applied:
                    normalized = target_mode_raw.replace("-", "_").lower()
                    try:
                        from shared.stream_mode import StreamMode, set_stream_mode

                        mode = StreamMode(normalized)
                    except ValueError:
                        mode = None
                    if mode is not None:
                        compositor._stream_mode_last_applied_set_at = sm_set_at
                        set_stream_mode(mode)
                        log.info(
                            "stream-mode-intent applied: target=%s (%s)",
                            target_mode_raw,
                            mode.value,
                        )
            except Exception:
                log.debug("stream-mode-intent consumer failed", exc_info=True)

        # Task #136 — follow-mode tick at ~2 Hz (every 5th 100 ms loop iter).
        # The controller reads IR fleet + camera classifications and
        # publishes follow-mode-recommendation.json. Always runs; the
        # HAPAX_FOLLOW_MODE_ACTIVE feature flag gates whether the
        # recommendation is *honoured* downstream (see follow-mode
        # fallback in the hero-override block below), not whether it's
        # computed.
        follow_tick_counter = getattr(compositor, "_follow_mode_tick_counter", 0) + 1
        compositor._follow_mode_tick_counter = follow_tick_counter
        if follow_tick_counter >= 5:
            compositor._follow_mode_tick_counter = 0
            try:
                _get_follow_mode_controller().tick()
            except Exception:
                log.debug("follow-mode tick failed", exc_info=True)

        # hero-camera-override.json consumer (meta-structural audit fix #4).
        # compositional_consumer.dispatch_camera_hero writes this file when
        # the affordance pipeline recruits a `cam.hero.<role>.<context>`
        # capability; the compositor side previously had zero readers so
        # recruitment was writing into the void. Applying the override
        # here (inside the 1s state-reader loop) converts a recruited
        # hero-camera selection into an actual layout-mode change.
        #
        # Task #136 follow-mode fallback: when the manual override is
        # absent or expired AND follow-mode is active AND a fresh
        # recommendation exists, use the recommended role instead of
        # leaving the hero untouched. Manual override always wins when
        # present — follow-mode is only the fallback source.
        hero_override_path = Path("/dev/shm/hapax-compositor/hero-camera-override.json")
        override_camera_role: str | None = None
        override_set_at = 0.0
        override_source = ""
        if hero_override_path.exists():
            try:
                payload = json.loads(hero_override_path.read_text(encoding="utf-8"))
                set_at = float(payload.get("set_at", 0.0))
                ttl_s = float(payload.get("ttl_s", 30.0))
                camera_role = payload.get("camera_role")
                if isinstance(camera_role, str) and camera_role and (time.time() - set_at) <= ttl_s:
                    override_camera_role = camera_role
                    override_set_at = set_at
                    override_source = "manual"
            except Exception:
                log.debug("hero-camera-override consumer failed", exc_info=True)
        if override_camera_role is None:
            # Follow-mode fallback. ``read_follow_mode_recommendation``
            # returns None when the flag is off, the file is missing,
            # expired, or active=False — all of which mean "leave the
            # hero as-is".
            fm_rec = read_follow_mode_recommendation()
            if fm_rec is not None:
                override_camera_role = fm_rec.camera_role
                override_set_at = fm_rec.ts
                override_source = "follow_mode"
        if override_camera_role is not None:
            try:
                requested_mode = f"packed/{override_camera_role}"
                current_mode = getattr(compositor, "_layout_mode", "balanced")
                last_applied = getattr(compositor, "_hero_override_last_applied_set_at", 0.0)
                # Min-hold debounce: only swap if (a) it's been ≥3s since the last
                # follow_mode swap, and (b) the proposed role has been the
                # recommendation for ≥3s. Without this, noisy IR/operator-location
                # signals cause the layout to flap every ~1s, which wedges
                # the v4l2sink (the cudacompositor reconfigure cost > sink budget).
                # Manual overrides bypass the role-stability gate; they're operator
                # intent, not noise.
                _MIN_FOLLOW_HOLD_S = 3.0
                now_ts = time.time()
                role_first_seen = getattr(compositor, "_hero_override_role_first_seen", {})
                seen_role = role_first_seen.get("role")
                if seen_role != override_camera_role:
                    role_first_seen = {"role": override_camera_role, "ts": now_ts}
                    compositor._hero_override_role_first_seen = role_first_seen
                role_age = now_ts - role_first_seen.get("ts", now_ts)
                debounce_ok = (now_ts - last_applied) >= _MIN_FOLLOW_HOLD_S
                role_stable = override_source != "follow_mode" or role_age >= _MIN_FOLLOW_HOLD_S
                if (
                    requested_mode != current_mode
                    and override_set_at > last_applied
                    and debounce_ok
                    and role_stable
                ):
                    previous_role = ""
                    if isinstance(current_mode, str) and (
                        current_mode.startswith("packed/") or current_mode.startswith("hero/")
                    ):
                        previous_role = current_mode.split("/", 1)[1]
                    compositor._hero_override_last_applied_set_at = override_set_at
                    GLib = compositor._GLib
                    if GLib:
                        GLib.idle_add(
                            lambda m=requested_mode: apply_layout_mode(compositor, m) or False
                        )
                    else:
                        apply_layout_mode(compositor, requested_mode)
                    if override_source == "follow_mode":
                        try:
                            _metrics.record_follow_mode_cut(previous_role, override_camera_role)
                        except Exception:
                            log.debug("record_follow_mode_cut failed", exc_info=True)
                    log.info(
                        "hero-camera-override applied: role=%s mode=%s source=%s",
                        override_camera_role,
                        requested_mode,
                        override_source,
                    )
            except Exception:
                log.debug("hero-camera-override apply failed", exc_info=True)

        # Livestream control (from daimonion affordance dispatch)
        try:
            process_livestream_control(compositor)
        except Exception:
            log.exception("process_livestream_control raised (non-fatal)")

        # Preset recruitment consumer — closes director→chain mutation loop.
        # Director emits ``preset.bias = <family>`` impingement; AffordancePipeline
        # recruits ``fx.family.<family>``; this consumer reads the recruitment
        # and writes graph-mutation.json to actually change the chain. Without
        # it the director's recruitment is observable but inert (chain stays
        # on whatever activated at boot). 8s cooldown protects against thrash.
        # Per operator directive 2026-04-20: 'no random_mode; all effects
        # recruited by Hapax via director loop and content programming'.
        try:
            from .preset_recruitment_consumer import process_preset_recruitment

            # Pass the compositor so the consumer can extend
            # _user_preset_hold_until on a successful dispatch — protects
            # the recruitment-driven chain change from being clobbered by
            # the 30 fps atmospheric governance tick. Without this hold,
            # tick_governance reverts to _STATE_MATRIX defaults within
            # 33 ms (the halftone-monoculture symptom).
            process_preset_recruitment(compositor)
        except Exception:
            log.exception("process_preset_recruitment raised (non-fatal)")

        # Graph-patch recruitment consumer — closes the chain-composition
        # primitive (architectural fix per memory
        # ``feedback_no_presets_use_parametric_modulation``). Where preset
        # recruitment swaps among 30 fixed preset graphs, the patch consumer
        # mutates the live graph in place via ``EffectGraph.apply_patch``:
        # affordance-recruited ``node.add.<type>`` and ``node.remove.<id>``
        # capabilities translate to a ``GraphPatch`` and the patched graph
        # is written as a mutation file. Same egress channel, finer
        # granularity. The two consumers can coexist — preset recruitment
        # changes the family, patch recruitment adds/removes specific nodes
        # within whatever graph is live.
        try:
            from .graph_patch_consumer import (
                process_graph_patch_recruitment,
                set_current_graph_provider,
            )

            # Bind the live graph provider once; idempotent on re-entry.
            if compositor._graph_runtime is not None and not getattr(
                compositor, "_graph_patch_provider_set", False
            ):
                set_current_graph_provider(lambda: compositor._graph_runtime.current_graph)
                compositor._graph_patch_provider_set = True
            process_graph_patch_recruitment()
        except Exception:
            log.exception("process_graph_patch_recruitment raised (non-fatal)")

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
