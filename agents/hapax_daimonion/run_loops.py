"""Core async run loops for VoiceDaemon (audio, actuation)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from agents.hapax_daimonion.voice_pitch_baseline import publish_operator_voice_pitch_sample

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")

# Re-export perception_loop from its own module
from agents.hapax_daimonion.perception_loop import perception_loop  # noqa: F401


async def audio_loop(daemon: VoiceDaemon) -> None:
    """Distribute audio frames to VAD, conversation buffer, and Gemini consumers.

    Impingement-native architecture: every operator utterance flows through
    the conversation buffer to STT → salience router → recruitment. No
    expert-system engagement gate — the CPAL runner's existing salience-based
    recruitment decides whether to respond.
    """

    _VAD_CHUNK = 512 * 2
    _vad_buf = bytearray()

    _recovery_delay = 5.0
    while daemon._running:
        try:
            frame = await daemon._audio_input.get_frame(timeout=1.0)
        except Exception as exc:
            log.warning("Audio stream error: %s — recovering in %.0fs", exc, _recovery_delay)
            daemon._audio_input.stop()
            await asyncio.sleep(_recovery_delay)
            daemon._audio_input.start()
            _recovery_delay = min(_recovery_delay * 2, 60.0)
            continue
        if frame is None:
            continue
        _recovery_delay = 5.0

        if daemon._gemini_session is not None and daemon._gemini_session.is_connected:
            try:
                await daemon._gemini_session.send_audio(frame)
            except Exception as exc:
                log.warning("Gemini audio consumer error: %s", exc)

        if daemon._echo_canceller is not None:
            frame = daemon._echo_canceller.process(frame)
        if daemon._noise_reference is not None:
            frame = daemon._noise_reference.subtract(frame)
        if daemon._audio_preprocessor is not None:
            frame = daemon._audio_preprocessor.process(frame)

        _vad_buf.extend(frame)

        # Always feed audio to the conversation buffer — the buffer's own
        # VAD gating (speech start/end detection) handles accumulation.
        # No session or engagement gate: speech is an impingement, not a
        # permission-gated event.
        daemon._conversation_buffer.feed_audio(frame)

        while len(_vad_buf) >= _VAD_CHUNK:
            chunk = bytes(_vad_buf[:_VAD_CHUNK])
            del _vad_buf[:_VAD_CHUNK]
            try:
                daemon.presence.process_audio_frame(chunk)
                vad_prob = daemon.presence._latest_vad_confidence
                daemon._conversation_buffer.update_vad(vad_prob)
                if vad_prob >= 0.3:
                    speaker = getattr(daemon.session, "speaker", "operator")
                    consent_phase = getattr(
                        getattr(getattr(daemon, "consent_tracker", None), "phase", None),
                        "value",
                        "no_guest",
                    )
                    operator_speech = (
                        not daemon.session.is_active or speaker == "operator"
                    ) and consent_phase == "no_guest"
                    if operator_speech:
                        try:
                            publish_operator_voice_pitch_sample(
                                chunk,
                                sample_rate_hz=16000,
                            )
                        except Exception:
                            log.debug("operator voice pitch sample publish failed", exc_info=True)
                # Engagement is a gain/context modulator only. It never
                # gates buffer ingestion above; audio has already reached
                # the always-on conversation buffer before this point.
                if vad_prob >= 0.3 and hasattr(daemon, "_engagement"):
                    behaviors = daemon.perception.behaviors
                    ps = behaviors.get("presence_state")
                    if ps is not None and getattr(ps, "value", "") == "PRESENT":
                        daemon._engagement.on_speech_detected(behaviors)
            except Exception as exc:
                log.warning("Presence consumer error: %s", exc)


async def actuation_loop(daemon: VoiceDaemon) -> None:
    """Drain ScheduleQueue, resolve resource contention, dispatch winners."""
    from agents.hapax_daimonion.arbiter import ResourceClaim
    from agents.hapax_daimonion.resource_config import DEFAULT_PRIORITIES, RESOURCE_MAP

    tick_s = daemon.cfg.actuation_tick_ms / 1000.0
    while daemon._running:
        try:
            now = time.monotonic()
            ready = daemon.schedule_queue.drain(now)

            for schedule in ready:
                resource = RESOURCE_MAP.get(schedule.command.action)
                if resource:
                    claim = ResourceClaim(
                        resource=resource,
                        chain=schedule.command.trigger_source,
                        priority=DEFAULT_PRIORITIES.get(
                            (resource, schedule.command.trigger_source), 0
                        ),
                        command=schedule.command,
                    )
                    daemon.arbiter.claim(claim)
                else:
                    dispatched = daemon.executor_registry.dispatch(schedule.command)
                    daemon.event_log.emit(
                        "actuation",
                        action=schedule.command.action,
                        latency_ms=round((now - schedule.wall_time) * 1000.0, 1),
                        dispatched=dispatched,
                    )

            for winner in daemon.arbiter.drain_winners(now):
                dispatched = daemon.executor_registry.dispatch(winner.command)
                daemon.event_log.emit(
                    "actuation",
                    action=winner.command.action,
                    chain=winner.chain,
                    resource=winner.resource,
                    latency_ms=round((now - winner.created_at) * 1000.0, 1),
                    dispatched=dispatched,
                )

            await asyncio.sleep(tick_s)
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("Error in actuation loop")
