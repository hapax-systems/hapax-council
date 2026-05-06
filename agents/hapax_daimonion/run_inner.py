"""Main run loop for VoiceDaemon."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from agents.hapax_daimonion.ntfy_listener import subscribe_ntfy  # noqa: F401 (patched in tests)

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")


# BETA-FINDING-L (queue 025 Phase 2, queue 026 Phase 1): background-task
# supervisor. Prior behaviour was fire-and-forget create_task — exceptions
# were held in the Task object and only observed at shutdown, so crashes
# during normal operation were invisible. The supervisor walks the daemon's
# named task map every main-loop tick, observes crashes, and applies the
# per-task policy below.
#
# Day-1 rollout (this PR): all tasks live in RECREATE_TASKS. Recreation is
# always a strictly better signal than silent death. After a 24-hour
# observation window we can promote the three structurally critical tasks
# (audio_loop, cpal_runner, cpal_impingement_loop) into CRITICAL_TASKS so
# their crashes trigger SystemExit(1) and let systemd restart the whole
# daemon. Rationale for delaying the promotion: if the supervisor itself
# has a latent bug, RECREATE + log is strictly better than fail-hard with
# a ~2–3 min cold-start cost (STT + TTS preload + CPAL signal cache +
# bridge phrase presynthesis).
CRITICAL_TASKS: frozenset[str] = frozenset()
RECREATE_TASKS: frozenset[str] = frozenset(
    {
        "proactive_delivery_loop",
        "ntfy_subscribe",
        "workspace_monitor",
        "audio_loop",
        "perception_loop",
        "ambient_refresh_loop",
        "cpal_runner",
        "cpal_impingement_loop",
        "impingement_consumer_loop",
        "sidechat_consumer_loop",
        "actuation_loop",
        "gem_producer_loop",
        "programme_manager_loop",
        "prepared_playback_loop",
        "narrative_drive_loop",
        "salience_publish_loop",
    }
)
LOG_AND_CONTINUE_TASKS: frozenset[str] = frozenset()

# Maximum recreations before a RECREATE task escalates to SystemExit.
# Chosen so a transient network blip (ntfy, litellm) survives but a
# permanent code bug is escalated quickly enough that the operator sees it.
_RECREATE_RETRY_BUDGET = 10

# Exponential backoff ceiling when recreating a RECREATE task, seconds.
_RECREATE_BACKOFF_MAX_S = 30.0


def _make_task(
    daemon: VoiceDaemon,
    name: str,
    factory: Callable[[], Awaitable[None]],
) -> asyncio.Task:
    """Create a supervised background task.

    Populates both ``daemon._background_tasks`` (legacy list used by the
    shutdown path) and ``daemon._supervised_tasks`` (name→(task, factory)
    dict walked by the supervisor loop).
    """
    task = asyncio.create_task(factory(), name=name)
    daemon._background_tasks.append(task)
    daemon._supervised_tasks[name] = (task, factory)
    return task


def _supervise_background_tasks(daemon: VoiceDaemon) -> None:
    """Observe crashes in supervised background tasks and apply per-task policy.

    Called as the first action of every main-loop iteration. Walks
    ``daemon._supervised_tasks`` once per tick, so a crash is visible at
    most one tick (~1s) after it happens.

    Policy by task name:

    * ``CRITICAL_TASKS``: log the exception, emit a structured event, and
      raise ``SystemExit(1)`` so systemd restarts the whole daemon. These
      are tasks whose silent death yields the "alive but silent" failure
      mode that motivated this supervisor.
    * ``RECREATE_TASKS``: log the exception and schedule a delayed
      recreation via ``_relaunch_with_delay``. Exponential backoff capped
      at ``_RECREATE_BACKOFF_MAX_S``. After ``_RECREATE_RETRY_BUDGET``
      consecutive crashes the task escalates to ``SystemExit(1)`` so a
      permanent code bug does not hide in an infinite retry loop.
    * ``LOG_AND_CONTINUE_TASKS``: log the exception and drop the task
      from the supervisor map. These are strictly decorative subsystems.

    Tasks that are cancelled (shutdown path) are skipped. Tasks that
    complete normally are recreated if they belong to RECREATE_TASKS or
    CRITICAL_TASKS (all 10 daimonion background tasks are infinite
    loops, so normal return is itself unexpected and worth relaunching).
    """
    for name, (task, factory) in list(daemon._supervised_tasks.items()):
        if not task.done():
            continue
        if task.cancelled():
            # Shutdown path cancelled us — do not recreate or raise.
            continue

        exc = task.exception()
        if exc is None:
            if name in RECREATE_TASKS or name in CRITICAL_TASKS:
                log.warning(
                    "background task %s returned without exception; recreating "
                    "(infinite-loop tasks should not terminate normally)",
                    name,
                )
                daemon._background_tasks.append(asyncio.create_task(factory(), name=name))
                daemon._supervised_tasks[name] = (
                    daemon._background_tasks[-1],
                    factory,
                )
            else:
                del daemon._supervised_tasks[name]
            continue

        log.exception(
            "background task %s crashed: %s",
            name,
            exc,
            exc_info=exc,
        )

        if name in CRITICAL_TASKS:
            log.critical(
                "critical task %s crashed — daemon entering fail-closed state "
                "(systemd will restart)",
                name,
            )
            _emit_crash_event(daemon, name, exc, policy="systemexit")
            raise SystemExit(1)

        if name in RECREATE_TASKS:
            retries = int(getattr(task, "_hapax_retry_count", 0)) + 1
            if retries > _RECREATE_RETRY_BUDGET:
                log.error(
                    "background task %s exceeded retry budget (%d); escalating to SystemExit",
                    name,
                    _RECREATE_RETRY_BUDGET,
                )
                _emit_crash_event(daemon, name, exc, policy="retry_exhausted_systemexit")
                raise SystemExit(1)

            delay = min(_RECREATE_BACKOFF_MAX_S, 2.0 ** (retries - 1))
            log.info(
                "recreating %s after %.1fs (retry %d/%d)",
                name,
                delay,
                retries,
                _RECREATE_RETRY_BUDGET,
            )
            _emit_crash_event(
                daemon,
                name,
                exc,
                policy="recreate",
                retry_count=retries,
            )

            relaunch_task = asyncio.create_task(
                _relaunch_with_delay(daemon, name, factory, delay, retries),
                name=f"_relaunch_{name}",
            )
            daemon._background_tasks.append(relaunch_task)
            # Remove the dead entry; _relaunch_with_delay will repopulate it.
            del daemon._supervised_tasks[name]
            continue

        if name in LOG_AND_CONTINUE_TASKS:
            log.warning("non-critical task %s dropped after crash", name)
            _emit_crash_event(daemon, name, exc, policy="drop")
            del daemon._supervised_tasks[name]
            continue

        # Unknown task name — default to SystemExit so silent drift cannot
        # hide a new unsupervised task.
        log.critical(
            "unknown background task %s crashed — defaulting to SystemExit",
            name,
        )
        _emit_crash_event(daemon, name, exc, policy="unknown_task_systemexit")
        raise SystemExit(1)


async def _relaunch_with_delay(
    daemon: VoiceDaemon,
    name: str,
    factory: Callable[[], Awaitable[None]],
    delay: float,
    retry_count: int,
) -> None:
    """Sleep ``delay`` seconds then install a fresh task under ``name``.

    Carries the retry counter forward on the new task via a mangled
    attribute so the supervisor can observe repeated crashes against the
    budget.
    """
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return
    if not getattr(daemon, "_running", False):
        return
    inner = asyncio.create_task(factory(), name=name)
    inner._hapax_retry_count = retry_count  # type: ignore[attr-defined]
    daemon._background_tasks.append(inner)
    daemon._supervised_tasks[name] = (inner, factory)


def _emit_crash_event(
    daemon: VoiceDaemon,
    name: str,
    exc: BaseException,
    policy: str,
    retry_count: int | None = None,
) -> None:
    """Emit a structured ``background_task_crash`` event for Langfuse/telemetry.

    Swallows its own exceptions — the supervisor is the last line of
    defence and must never crash the daemon because of a telemetry bug.
    """
    try:
        event_log = getattr(daemon, "event_log", None)
        if event_log is None or not hasattr(event_log, "emit"):
            return
        payload = {
            "task_name": name,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "policy": policy,
        }
        if retry_count is not None:
            payload["retry_count"] = retry_count
        event_log.emit("background_task_crash", **payload)
    except Exception:
        log.debug("background_task_crash event emission failed", exc_info=True)


async def run_inner(daemon: VoiceDaemon) -> None:
    """Inner run loop — executes within consent_scope context."""
    from agents.hapax_daimonion.activity_mode import classify_activity_mode
    from agents.hapax_daimonion.init_pipeline import precompute_pipeline_deps
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
        sidechat_consumer_loop,
    )

    log.info("Hapax Daimonion daemon starting (backend=%s)", daemon.cfg.backend)
    daemon._loop = asyncio.get_running_loop()

    # FINDING-F (wiring audit, 2026-04-20): voice-state.json must exist
    # at startup so the compositor-side DuckController has a known
    # baseline. VadStatePublisher only writes on UserStarted/Stopped
    # frames, which require an active conversation pipeline, which
    # requires an open session — so a quiet-operator startup leaves
    # the file ABSENT and the duck never differentiates speech from
    # silence. Write False here so the file exists; the publisher
    # overwrites on real VAD events.
    try:
        from agents.studio_compositor.vad_ducking import publish_vad_state

        publish_vad_state(False)
    except Exception:
        log.debug("Failed to publish initial vad_state baseline", exc_info=True)

    await daemon.hotkey.start()

    # Preload STT + TTS models
    if not daemon._resident_stt.is_loaded:
        log.info("Preloading STT model at startup...")
        daemon._resident_stt.load()
    daemon.tts.preload()

    # TTS is now warm — expose it over UDS so the compositor can delegate
    # synthesis without loading torch. ALPHA-FINDING-1 root cause fix.
    await daemon.tts_server.start()

    # CPAL runner — sole conversation coordinator
    from agents.hapax_daimonion.cpal.runner import CpalRunner

    daemon._cpal_runner = CpalRunner(
        buffer=daemon._conversation_buffer,
        stt=daemon._resident_stt,
        salience_router=daemon._salience_router,
        audio_output=getattr(daemon, "_audio_output", None),
        grounding_ledger=getattr(daemon, "_grounding_ledger", None),
        tts_manager=daemon.tts,
        echo_canceller=getattr(daemon, "_echo_canceller", None),
        daemon=daemon,
    )

    # Engagement classifier — demoted from session-gate to gain modulator.
    # Per the no-expert-system commitment, engagement detection no longer
    # gates whether the system listens. Instead it boosts CPAL gain when
    # the operator appears engaged, making response more likely without
    # being a binary veto. The conversation buffer is always active; the
    # CPAL runner's salience-based recruitment is the sole response gate.
    from agents.hapax_daimonion.engagement import EngagementClassifier
    from agents.hapax_daimonion.session_events import on_engagement_detected

    daemon._engagement = EngagementClassifier(
        on_engaged=lambda: daemon._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(on_engagement_detected(daemon))
        ),
    )

    # Presynthesize signal cache + bridge phrases in one background thread
    import threading

    def _presynth_background() -> None:
        daemon._cpal_runner.presynthesize_signals()
        log.info("CPAL signal cache presynthesized")
        try:
            daemon._bridge_engine.presynthesize_all(daemon.tts)
            daemon._bridges_presynthesized = True
            log.info("Bridge phrases presynthesized (background)")
        except Exception:
            log.warning("Bridge presynthesis failed (will retry on first session)")

    daemon._bridges_presynthesized = False
    threading.Thread(target=_presynth_background, daemon=True, name="presynth").start()

    # Warm embedding model
    try:
        from agents._config import embed

        embed("warmup", prefix="search_query")
        log.info("Embedding model warmed up")
    except Exception:
        log.debug("Embedding warmup failed (non-fatal)", exc_info=True)

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

    # Impingement-native voice: activate the conversation buffer and start
    # the pipeline at startup so operator speech always flows through
    # buffer → STT → salience router → recruitment. No engagement gate.
    daemon._conversation_buffer.activate()
    try:
        await daemon._start_pipeline()
        if daemon._cpal_runner is not None:
            daemon._cpal_runner.set_pipeline(daemon._conversation_pipeline)
        log.info("Pipeline started at startup (impingement-native voice)")
    except Exception:
        log.exception("Pipeline start at startup failed — will retry on engagement")

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
    log.info("  Activation: impingement-native (salience recruitment)")
    log.info(
        "  Workspace monitor: %s (cameras: %s)",
        "enabled" if daemon.cfg.screen_monitor_enabled else "disabled",
        "BRIO+C920" if daemon.cfg.webcam_enabled else "screen-only",
    )

    daemon.event_log.cleanup()

    # Start background tasks via the supervised-task helper. Each task is
    # registered with a name and a zero-arg factory so the supervisor can
    # recreate it from scratch on crash. Factory closures capture `daemon`.
    _make_task(
        daemon,
        "proactive_delivery_loop",
        lambda: proactive_delivery_loop(daemon),
    )
    _make_task(
        daemon,
        "ntfy_subscribe",
        lambda: subscribe_ntfy(_NTFY_BASE_URL, _NTFY_TOPICS, lambda n: ntfy_callback(daemon, n)),
    )
    _make_task(daemon, "workspace_monitor", daemon.workspace_monitor.run)
    if daemon._audio_input.is_active:
        _make_task(daemon, "audio_loop", lambda: audio_loop(daemon))

    _make_task(daemon, "perception_loop", lambda: perception_loop(daemon))
    _make_task(daemon, "ambient_refresh_loop", lambda: ambient_refresh_loop(daemon))

    # CPAL runner + impingement consumer
    _make_task(daemon, "cpal_runner", daemon._cpal_runner.run)

    async def _cpal_impingement_loop() -> None:
        """Poll impingements and route through CPAL control loop."""
        from agents._impingement_consumer import ImpingementConsumer

        consumer = ImpingementConsumer(
            Path("/dev/shm/hapax-dmn/impingements.jsonl"),
            cursor_path=Path.home() / ".cache" / "hapax" / "impingement-cursor-daimonion-cpal.txt",
        )
        while daemon._running:
            try:
                for imp in consumer.read_new():
                    await daemon._cpal_runner.process_impingement(imp)
            except Exception:
                log.debug("CPAL impingement consumer error", exc_info=True)
            await asyncio.sleep(0.5)

    _make_task(daemon, "cpal_impingement_loop", _cpal_impingement_loop)
    # Affordance-dispatch loop: owns everything recruited EXCEPT spontaneous speech
    # (Thompson learning, notification dispatch, cross-modal coordination,
    # system awareness, capability discovery). Uses its own cursor file
    # (impingement-cursor-daimonion-affordance.txt) so it sees every impingement
    # independently of the CPAL loop. See run_loops_aux.impingement_consumer_loop
    # for the dispatch semantics; see cpal/impingement_adapter.py for CPAL's scope.
    _make_task(
        daemon,
        "impingement_consumer_loop",
        lambda: impingement_consumer_loop(daemon),
    )
    # Operator sidechat — private LOCAL-ONLY channel for the operator to
    # whisper notes/commands to Hapax during a livestream. Tails
    # /dev/shm/hapax-compositor/operator-sidechat.jsonl and enqueues
    # each message as a pattern-matched Impingement with priority boost.
    # See run_loops_aux.sidechat_consumer_loop for semantics, task #132.
    _make_task(
        daemon,
        "sidechat_consumer_loop",
        lambda: sidechat_consumer_loop(daemon),
    )
    # Endogenous narrative drive — evaluates a Bayesian posterior every
    # 10s and emits impingements to the DMN bus when internal pressure
    # (time since last narration × chronicle richness × role affinity)
    # crosses a stochastic threshold.  The pipeline then recruits
    # narration.autonomous_first_system from those impingements.
    # Replaces the decommissioned expert-system loop+gates per
    # feedback_no_expert_system_rules.
    # Design: docs/research/2026-04-27-endogenous-drive-role-semantic-surfacing.md
    from agents.hapax_daimonion.narrative_drive import narrative_drive_loop

    _make_task(
        daemon,
        "narrative_drive_loop",
        lambda: narrative_drive_loop(daemon),
    )
    # GEM producer — Hapax authors the Graffiti Emphasis Mural ward by
    # tailing gem.* impingements and writing /dev/shm/hapax-compositor/
    # gem-frames.json. Phase 3 of the GEM activation plan.
    from agents.hapax_daimonion.gem_producer import gem_producer_loop

    _make_task(
        daemon,
        "gem_producer_loop",
        lambda: gem_producer_loop(daemon),
    )
    # ProgrammeManager tick loop — closes B3 critical #4 (Prometheus
    # lifecycle) + #5 (JSONL outcome log) wire-up gap. The manager is
    # fully implemented in agents/programme_manager/manager.py but had
    # no production runner until now. 1 Hz cadence; no-op when no
    # programmes are scheduled.
    from agents.hapax_daimonion.programme_loop import programme_manager_loop

    _make_task(
        daemon,
        "programme_manager_loop",
        lambda: programme_manager_loop(daemon),
    )
    # Legacy prepared-content playback loop. It direct-plays scripts only
    # when content explicitly requests verbatim legacy mode and the runtime
    # HAPAX_PREP_VERBATIM_LEGACY gate is enabled; live-prior prepared content
    # continues through narrative_drive → live composition.
    from agents.hapax_daimonion.run_loops_aux import prepared_playback_loop

    _make_task(
        daemon,
        "prepared_playback_loop",
        lambda: prepared_playback_loop(daemon),
    )
    # Salience-router exploration-signal republish — keeps the
    # apperception-style writer-fresh signal alive during quiet operator
    # periods. Live regression: the writer goes dead the moment the
    # operator stops talking, because route() is the only publish call
    # site.
    from agents.hapax_daimonion.salience_publish_loop import salience_publish_loop

    _make_task(
        daemon,
        "salience_publish_loop",
        lambda: salience_publish_loop(daemon),
    )
    log.info(
        "CPAL runner + impingement consumers "
        "(CPAL + affordance + sidechat + gem) + programme manager + salience publish started"
    )

    if daemon.cfg.mc_enabled or daemon.cfg.obs_enabled:
        _make_task(daemon, "actuation_loop", lambda: actuation_loop(daemon))

    try:
        while daemon._running:
            # BETA-FINDING-L: observe crashes in supervised background tasks
            # before touching any other state. Crashes surface here at most
            # one tick late (~1s) rather than invisibly at shutdown.
            _supervise_background_tasks(daemon)

            # Session timeout is handled by CPAL runner (_tick session lifecycle)
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
        daemon._supervised_tasks.clear()

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

        # 9. Stop hotkey + TTS servers
        await daemon.hotkey.stop()
        await daemon.tts_server.stop()
        log.info("Hapax Daimonion daemon stopped")
