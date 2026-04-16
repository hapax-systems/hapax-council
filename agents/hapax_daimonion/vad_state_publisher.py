"""Pipecat frame processor that publishes VAD state transitions.

LRR Phase 9 hook 4. Daimonion's pipecat pipeline already runs a
SileroVADAnalyzer (see ``pipeline.py``) whose state transitions are
emitted as ``UserStartedSpeakingFrame`` / ``UserStoppedSpeakingFrame``.

This processor intercepts those frames and publishes a boolean
``operator_speech_active`` flag to
``/dev/shm/hapax-compositor/voice-state.json`` via
``agents.studio_compositor.vad_ducking.publish_vad_state``. The
compositor-side ``DuckController`` polls that file and drives
``YouTubeAudioControl.duck() / .restore()``.

Install in the pipeline by inserting this processor before the STT
stage — VAD frames flow through first.

Privacy posture (per operator 2026-04-16 "standard" approval):
- VAD state is ephemeral: /dev/shm only, lost on reboot, not persisted.
- No VAD events are logged to Langfuse.
- No audio payload leaves this processor — only a boolean gate signal.
"""

from __future__ import annotations

import logging

from pipecat.frames.frames import (
    Frame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from agents.studio_compositor.vad_ducking import publish_vad_state

log = logging.getLogger(__name__)


class VadStatePublisher(FrameProcessor):
    """Publish operator-speech-active transitions to the compositor side.

    Pipecat frame flow: transport.input() → VadStatePublisher → STT → …
    So ``UserStartedSpeakingFrame`` and ``UserStoppedSpeakingFrame`` arrive
    before any downstream STT/LLM/TTS stages.

    The processor is a pure side-effect node; it does not modify or consume
    the frames — it lets them continue downstream via ``push_frame`` after
    emitting the state transition.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        # Upstream FrameProcessor.process_frame does bookkeeping (metrics,
        # interrupt handling). Call it when available; skip gracefully when
        # running under the stubbed test conftest that swaps pipecat out.
        if hasattr(super(), "process_frame"):
            await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            try:
                publish_vad_state(True)
            except Exception as exc:  # noqa: BLE001 — never block pipeline
                log.warning("vad_state publish (start) failed: %s", exc)
        elif isinstance(frame, UserStoppedSpeakingFrame):
            try:
                publish_vad_state(False)
            except Exception as exc:  # noqa: BLE001 — never block pipeline
                log.warning("vad_state publish (stop) failed: %s", exc)

        await self.push_frame(frame, direction)
