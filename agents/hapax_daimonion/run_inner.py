"""Main run loop for VoiceDaemon."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from agents.hapax_daimonion.ntfy_listener import subscribe_ntfy  # noqa: F401 (patched in tests)

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")


async def run_inner(daemon: VoiceDaemon) -> None:
    """Inner run loop — executes within consent_scope context."""
    from agents.hapax_daimonion.activity_mode import classify_activity_mode
    from agents.hapax_daimonion.init_pipeline import precompute_pipeline_deps
    from agents.hapax_daimonion.persona import session_end_message
    from agents.hapax_daimonion.run_loops import (
        actuation_loop,
        audio_loop,
        perception_loop,
    )
    from agents.hapax_daimonion.run_loops_aux import (
        _NTFY_BASE_URL,
        _NTFY_TOPICS,
        ambient_refresh_loop,
        impingement_consumer_loop,
        ntfy_callback,
        proactive_delivery_loop,
    )
    from agents.hapax_daimonion.session_events import close_session, engagement_processor

    log.info("Hapax Daimonion daemon starting (backend=%s)", daemon.cfg.backend)
    daemon._loop = asyncio.get_running_loop()

    await daemon.hotkey.start()

    # Preload STT + TTS models
    if not daemon._resident_stt.is_loaded:
        log.info("Preloading STT model at startup...")
        daemon._resident_stt.load()
    daemon.tts.preload()

    # CPAL mode: use CpalRunner instead of session/engagement/cognitive loop
    if daemon.cfg.use_cpal:
        log.info("CPAL mode enabled — using CpalRunner")
        from agents.hapax_daimonion.cpal.runner import CpalRunner

        daemon._cpal_runner = CpalRunner(
            buffer=daemon._conversation_buffer,
            stt=daemon._resident_stt,
            salience_router=daemon._salience_router,
            audio_output=getattr(daemon, "_audio_output", None),
            grounding_ledger=getattr(daemon, "_grounding_ledger", None),
            tts_manager=daemon.tts,
        )

        import threading

        def _cpal_presynth() -> None:
            daemon._cpal_runner.presynthesize_signals()
            log.info("CPAL signal cache presynthesized")

        threading.Thread(target=_cpal_presynth, daemon=True, name="cpal-presynth").start()
    else:
        daemon._cpal_runner = None

        # Initialize engagement classifier (replaces wake word)
        from agents.hapax_daimonion.engagement import EngagementClassifier
        from agents.hapax_daimonion.session_events import on_engagement_detected

        daemon._engagement = EngagementClassifier(
            on_engaged=lambda: on_engagement_detected(daemon),
        )

        # Bridge presynthesis — run in background to avoid blocking audio input start
        daemon._bridges_presynthesized = False

        def _presynth_background() -> None:
            try:
                daemon._bridge_engine.presynthesize_all(daemon.tts)
                daemon._bridges_presynthesized = True
                log.info("Bridge phrases presynthesized (background)")
            except Exception:
                log.warning("Bridge presynthesis failed (will retry on first session)")

        import threading

        threading.Thread(target=_presynth_background, daemon=True, name="bridge-presynth").start()

    # Warm embedding model
    try:
        from agents._config import embed

        embed("warmup", prefix="search_query")
        log.info("Embedding model warmed up")
    except Exception:
        log.debug("Embedding warmup failed (non-fatal)", exc_info=True)

    daemon._cognitive_loop = None
    precompute_pipeline_deps(daemon)

    if daemon.cfg.chime_enabled:
        daemon.chime_player.load()

    # Start audio input
    daemon._audio_input.start()
    if daemon._audio_input.is_active:
        daemon.event_log.emit("audio_input_started")
        log.info("  Audio input: active (source=%s)", daemon.cfg.audio_input_source)
    else:
        daemon.event_log.emit("audio_input_failed", error="Stream not active after start")
        log.info("  Audio input: unavailable (visual-only mode)")

    log.info("Subsystems initialized:")
    log.info("  Backend: %s", daemon.cfg.backend)
    log.info("  Session: silence_timeout=%ds", daemon.cfg.silence_timeout_s)
    log.info(
        "  Presence: window=%dmin, threshold=%.1f",
        daemon.cfg.presence_window_minutes,
        daemon.cfg.presence_vad_threshold,
    )
    log.info(
        "  Context gate: volume_threshold=%.0f%%", daemon.cfg.context_gate_volume_threshold * 100
    )
    log.info("  Notifications: %d pending", daemon.notifications.pending_count)
    log.info("  Activation: engagement classifier")
    log.info(
        "  Workspace monitor: %s (cameras: %s)",
        "enabled" if daemon.cfg.screen_monitor_enabled else "disabled",
        "BRIO+C920" if daemon.cfg.webcam_enabled else "screen-only",
    )

    daemon.event_log.cleanup()

    # Start background tasks
    daemon._background_tasks.append(asyncio.create_task(proactive_delivery_loop(daemon)))
    daemon._background_tasks.append(
        asyncio.create_task(
            subscribe_ntfy(_NTFY_BASE_URL, _NTFY_TOPICS, lambda n: ntfy_callback(daemon, n))
        )
    )
    daemon._background_tasks.append(asyncio.create_task(daemon.workspace_monitor.run()))
    if daemon._audio_input.is_active:
        daemon._background_tasks.append(asyncio.create_task(audio_loop(daemon)))

    daemon._background_tasks.append(asyncio.create_task(perception_loop(daemon)))
    daemon._background_tasks.append(asyncio.create_task(ambient_refresh_loop(daemon)))

    if daemon.cfg.use_cpal:
        # CPAL mode: run CpalRunner instead of engagement/session/cognitive loop
        daemon._background_tasks.append(asyncio.create_task(daemon._cpal_runner.run()))
        log.info("CPAL runner started as background task")
    else:
        daemon._background_tasks.append(asyncio.create_task(engagement_processor(daemon)))
        daemon._background_tasks.append(asyncio.create_task(impingement_consumer_loop(daemon)))

    if daemon.cfg.mc_enabled or daemon.cfg.obs_enabled:
        daemon._background_tasks.append(asyncio.create_task(actuation_loop(daemon)))

    try:
        while daemon._running:
            # Session timeout check (skip in CPAL mode — no sessions)
            if not daemon.cfg.use_cpal and daemon.session.is_active and daemon.session.is_timed_out:
                if daemon._cognitive_loop and daemon._cognitive_loop.turn_phase in (
                    "hapax_speaking",
                    "transition",
                    "operator_speaking",
                ):
                    daemon.session.mark_activity()
                else:
                    msg = session_end_message(daemon.notifications.pending_count)
                    log.info("Session closing: %s", msg)
                    if (
                        daemon._conversation_pipeline
                        and daemon._conversation_pipeline._audio_output
                    ):
                        try:
                            pcm = daemon.tts.synthesize(msg, "conversation")
                            if pcm:
                                daemon._conversation_pipeline._audio_output.write(pcm)
                        except Exception:
                            log.debug("Goodbye TTS failed", exc_info=True)
                    await close_session(daemon, reason="silence_timeout")

            daemon.notifications.prune_expired()

            # Sweep orphan temp wav files
            if not hasattr(daemon, "_wav_sweep_counter"):
                daemon._wav_sweep_counter = 0
            daemon._wav_sweep_counter += 1
            if daemon._wav_sweep_counter >= 60:
                daemon._wav_sweep_counter = 0
                from agents._tmp_wav import cleanup_stale_wavs

                cleanup_stale_wavs()

            await asyncio.sleep(1)

            analysis = daemon.workspace_monitor.latest_analysis
            if analysis is not None:
                _desk_b = daemon.perception.behaviors.get("desk_activity")
                _desk_act = str(_desk_b.value) if _desk_b is not None else ""
                mode = classify_activity_mode(analysis, desk_activity=_desk_act)
                daemon.gate.set_activity_mode(mode)
                daemon.perception.update_slow_fields(
                    activity_mode=mode,
                    workspace_context=getattr(analysis, "context", ""),
                )
    finally:
        from agents.hapax_daimonion.pipeline_lifecycle import stop_pipeline

        # 1. Stop audio input first (breaks frame source)
        daemon._audio_input.stop()

        # 2. Stop noise reference
        if daemon._noise_reference is not None:
            daemon._noise_reference.stop()

        # 3. Stop pipeline (drains remaining frames)
        await stop_pipeline(daemon)

        # 4. Stop perception
        daemon.perception.stop()

        # 5. Cancel background tasks (before closing resources they may use)
        for task in daemon._background_tasks:
            task.cancel()
        await asyncio.gather(*daemon._background_tasks, return_exceptions=True)
        daemon._background_tasks.clear()

        # 6. Stop managed resources (thread pools, etc.)
        if hasattr(daemon, "resource_registry"):
            failed = daemon.resource_registry.stop_all(timeout=5.0)
            if failed:
                log.warning("Resources failed to stop: %s", failed)

        # 7. Close resources (chime, executors)
        daemon.chime_player.close()
        daemon.executor_registry.close_all()

        # 8. Flush telemetry
        daemon.event_log.close()
        from opentelemetry.trace import get_tracer_provider

        provider = get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=5000)

        # 9. Stop hotkey
        await daemon.hotkey.stop()
        log.info("Hapax Daimonion daemon stopped")
