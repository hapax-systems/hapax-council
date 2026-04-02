"""Pipeline start/stop lifecycle for VoiceDaemon."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.daemon import VoiceDaemon

log = logging.getLogger("hapax_daimonion")


async def start_pipeline(daemon: VoiceDaemon) -> None:
    """Start the voice pipeline for the current session."""
    if daemon._conversation_pipeline is not None and daemon._conversation_pipeline.is_active:
        log.warning("Pipeline already running, skipping start")
        return

    if daemon.cfg.backend == "gemini":
        await _start_gemini_session(daemon)
    else:
        from agents.hapax_daimonion.pipeline_start import start_conversation_pipeline

        await start_conversation_pipeline(daemon)
        _pause_vision_for_conversation(daemon)


async def _start_gemini_session(daemon: VoiceDaemon) -> None:
    """Connect and start a Gemini Live session."""
    from agents.hapax_daimonion.conversational_policy import get_policy
    from agents.hapax_daimonion.gemini_live import GeminiLiveSession
    from agents.hapax_daimonion.persona import system_prompt

    policy_block = get_policy(
        env=daemon.perception.latest,
        guest_mode=daemon.session.is_guest_mode,
    )
    prompt = system_prompt(
        guest_mode=daemon.session.is_guest_mode,
        policy_block=policy_block,
    )
    session = GeminiLiveSession(
        model=daemon.cfg.gemini_model,
        system_prompt=prompt,
    )
    await session.connect()
    if session.is_connected:
        daemon._gemini_session = session
        log.info("Gemini Live session started")
    else:
        log.error("Gemini Live session failed to connect")


async def stop_pipeline(daemon: VoiceDaemon) -> None:
    """Stop the active pipeline or Gemini session."""
    if daemon._gemini_session is not None:
        await daemon._gemini_session.disconnect()
        daemon._gemini_session = None
        log.info("Gemini Live session stopped")

    if daemon._conversation_pipeline is not None:
        await daemon._conversation_pipeline.stop()
        daemon._conversation_pipeline = None

    # Unwire CPAL runner to prevent stale pipeline references
    if daemon._cpal_runner is not None:
        daemon._cpal_runner.set_pipeline(None)
        daemon._cpal_runner._audio_output = None

    if daemon._pipeline_task is not None:
        daemon._pipeline_task.cancel()
        try:
            await daemon._pipeline_task
        except asyncio.CancelledError:
            pass
        daemon._pipeline_task = None
        log.info("Conversation pipeline stopped")

    if daemon._salience_router is not None:
        daemon._salience_router._recent_turns.clear()
    if daemon._salience_concern_graph is not None:
        daemon._salience_concern_graph._recent_utterances.clear()

    _resume_vision_after_conversation(daemon)


def _pause_vision_for_conversation(daemon: VoiceDaemon) -> None:
    """Pause vision inference to free ~2-3GB VRAM for voice models."""
    for backend in daemon.perception.registered_backends.values():
        if hasattr(backend, "pause_for_conversation"):
            try:
                backend.pause_for_conversation()
            except Exception:
                log.debug("Vision pause failed", exc_info=True)


def _resume_vision_after_conversation(daemon: VoiceDaemon) -> None:
    """Resume vision inference after conversation ends."""
    for backend in daemon.perception.registered_backends.values():
        if hasattr(backend, "resume_after_conversation"):
            try:
                backend.resume_after_conversation()
            except Exception:
                log.debug("Vision resume failed", exc_info=True)
