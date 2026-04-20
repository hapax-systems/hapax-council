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

Audio-pathways Phase 3 (#134, B1): the publisher gates the True
publish through ``shared/agents.hapax_daimonion.voice_gate.should_duck``
when an ``embedding_match_provider`` is wired by the daimonion
startup. Without a provider, the publisher preserves pre-gate
behavior (always publish on Started). With a provider, low-similarity
VAD events (YouTube crossfeed, ambient voice) get classified as
phantom-VAD and the publish is suppressed — the duck never fires
on non-operator audio. Stop frames always publish False (the duck
release path must never be gated).

Install in the pipeline by inserting this processor before the STT
stage — VAD frames flow through first.

Privacy posture (per operator 2026-04-16 "standard" approval):
- VAD state is ephemeral: /dev/shm only, lost on reboot, not persisted.
- No VAD events are logged to Langfuse.
- No audio payload leaves this processor — only a boolean gate signal.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from pipecat.frames.frames import (
    Frame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from agents.hapax_daimonion.voice_gate import evaluate_and_emit
from agents.studio_compositor.vad_ducking import publish_vad_state

log = logging.getLogger(__name__)


# Callable returning the latest cosine similarity between the most recent
# audio window and the enrolled operator embedding. The daimonion
# startup wires this from a SpeakerIdentifier-backed provider that
# maintains a rolling embedding of the most recent VAD audio. None
# means "no provider wired" — the gate falls open (every Started
# publishes), preserving pre-gate behavior.
EmbeddingMatchProvider = Callable[[], float]


class VadStatePublisher(FrameProcessor):
    """Publish operator-speech-active transitions to the compositor side.

    Pipecat frame flow: transport.input() → VadStatePublisher → STT → …
    So ``UserStartedSpeakingFrame`` and ``UserStoppedSpeakingFrame`` arrive
    before any downstream STT/LLM/TTS stages.

    The processor is a pure side-effect node; it does not modify or consume
    the frames — it lets them continue downstream via ``push_frame`` after
    emitting the state transition.

    With an ``embedding_match_provider`` injected, UserStartedSpeakingFrames
    are gated through ``voice_gate.should_duck`` so phantom-VAD triggers
    (YouTube crossfeed, ambient room voice) don't flip
    ``operator_speech_active`` to True. Without a provider, the gate is
    bypassed (current behavior preserved as the default).
    """

    def __init__(
        self,
        *,
        embedding_match_provider: EmbeddingMatchProvider | None = None,
    ) -> None:
        super().__init__()
        self._embedding_match_provider = embedding_match_provider

    def _should_publish_start(self) -> bool:
        """Run the voice-gate decision when a provider is wired.

        Returns True (publish) when:
        - no provider wired (backward-compat fall-open posture), OR
        - provider raises (defensive — never block the pipeline on
          a sensor failure), OR
        - the gate's decision is duck=True (operator speech detected
          with sufficient embedding confidence).

        Returns False (suppress publish) only when the provider
        returned a real value AND the gate classified the trigger
        as phantom-VAD (embedding match below the phantom threshold).
        """
        if self._embedding_match_provider is None:
            return True
        try:
            from shared.director_observability import emit_audio_ducking_decision

            match = float(self._embedding_match_provider())
            decision = evaluate_and_emit(
                vad_active=True,
                embedding_match=match,
                emit=emit_audio_ducking_decision,
            )
        except Exception:  # noqa: BLE001 — never block pipeline on sensor failure
            log.debug("voice_gate evaluate failed; falling open", exc_info=True)
            return True
        return decision.duck

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        # Upstream FrameProcessor.process_frame does bookkeeping (metrics,
        # interrupt handling). Call it when available; skip gracefully when
        # running under the stubbed test conftest that swaps pipecat out.
        if hasattr(super(), "process_frame"):
            await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame):
            if self._should_publish_start():
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
