"""Cognitive loop — continuous conversational cognition during voice sessions.

Replaces the 10ms poll `_conversation_loop` with a 150ms cognitive tick that
tracks turn phase, drives speculative STT, manages a conversational model,
dispatches utterances, and handles active silence.

Architecture:
    AUDIO LOOP (30ms) ──► ConversationBuffer (feed + VAD)
    COGNITIVE LOOP (150ms) ──► reads buffer state, drives all session cognition
    PERCEPTION LOOP (2.5s) ──► sensor fusion, governance, consent, pipeline sync

The cognitive loop owns utterance dispatch, turn phase tracking, speculative
STT, and conversational model updates. Perception→pipeline sync stays in the
perception loop (2.5s cadence) because the data only changes there.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from agents.hapax_daimonion.perception import PerceptionTier as BackendTier
from agents.hapax_daimonion.primitives import Behavior

if TYPE_CHECKING:
    from agents.hapax_daimonion.conversation_buffer import ConversationBuffer
    from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline
    from agents.hapax_daimonion.conversational_model import ConversationalModel
    from agents.hapax_daimonion.event_log import EventLog
    from agents.hapax_daimonion.salience_router import SalienceRouter
    from agents.hapax_daimonion.session import SessionManager
    from agents.hapax_daimonion.speaker_id import SpeakerIdentifier
    from agents.hapax_daimonion.speculative_stt import SpeculativeTranscriber

log = logging.getLogger(__name__)

TICK_INTERVAL_S = 0.15  # 150ms cognitive tick
TPN_ACTIVE_FILE = Path("/dev/shm/hapax-dmn/tpn_active")


def write_tpn_active(active: bool, path: Path = TPN_ACTIVE_FILE) -> None:
    """Write TPN active signal for DMN anti-correlation."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        value = "1" if active else "0"
        tmp.write_text(f"{value}:{time.time():.3f}")
        tmp.rename(path)
    except OSError:
        pass


_VERIFY_MIN_SAMPLES = 16000 * 3  # 3s of 16kHz audio for reliable speaker ID
_PAUSING_THRESHOLD_S = 1.5  # silence duration before OPERATOR_PAUSING → MUTUAL_SILENCE


class TurnPhase(StrEnum):
    """Conversational phase tracked each cognitive tick."""

    OPERATOR_SPEAKING = "operator_speaking"
    OPERATOR_PAUSING = "operator_pausing"
    TRANSITION = "transition"
    HAPAX_SPEAKING = "hapax_speaking"
    MUTUAL_SILENCE = "mutual_silence"


class CognitiveLoop:
    """Continuous cognitive loop driving voice session cognition.

    Runs as an asyncio task during active voice sessions. Each tick:
    1. Derives turn phase from buffer + pipeline state
    2. Polls for pending utterances (any phase except HAPAX_SPEAKING)
    3. During OPERATOR_SPEAKING: speculative partial STT + pre-routing
    4. During MUTUAL_SILENCE: tick conversational model, check timeout
    5. Update Behaviors for perception engine
    """

    def __init__(
        self,
        *,
        buffer: ConversationBuffer,
        pipeline: ConversationPipeline,
        session: SessionManager,
        speaker_identifier: SpeakerIdentifier | None = None,
        salience_router: SalienceRouter | None = None,
        speculative_stt: SpeculativeTranscriber | None = None,
        conversational_model: ConversationalModel | None = None,
        event_log: EventLog,
        active_silence_enabled: bool = False,
        silence_notification_threshold_s: float = 8.0,
        silence_winddown_threshold_s: float = 20.0,
        notification_queue=None,
    ) -> None:
        self._buffer = buffer
        self._pipeline = pipeline
        self._session = session
        self._speaker_identifier = speaker_identifier
        self._salience_router = salience_router
        self._speculative_stt = speculative_stt
        self._model = conversational_model
        self._event_log = event_log
        self._active_silence_enabled = active_silence_enabled
        self._session_recorder = None
        self._silence_notification_threshold_s = silence_notification_threshold_s
        self._silence_winddown_threshold_s = silence_winddown_threshold_s
        self._notification_queue = notification_queue

        # Internal state
        self._running = False
        self._turn_phase = TurnPhase.MUTUAL_SILENCE
        self._last_operator_speaking_at: float = 0.0
        self._mutual_silence_start: float = 0.0
        self._predicted_tier: str = ""
        self._cognitive_readiness: float = 0.0
        self._wind_down_sent = False
        self._processing_task: asyncio.Task | None = None  # non-blocking utterance dispatch
        self._response_start_at: float = 0.0  # for on_response timing via phase transitions

        # Speaker verification state (session-scoped)
        self._speaker_verified = False
        self._speaker_audio_buf: list[bytes] = []
        self._speaker_audio_samples = 0

        # Behaviors (exposed to perception engine)
        self._b_turn_phase: Behavior[str] = Behavior(TurnPhase.MUTUAL_SILENCE)
        self._b_cognitive_readiness: Behavior[float] = Behavior(0.0)
        self._b_conversation_temperature: Behavior[float] = Behavior(0.0)
        self._b_predicted_tier: Behavior[str] = Behavior("")

        # Exploration tracking (spec §8: kappa=0.008, T_patience=360s)
        from shared.exploration_tracker import ExplorationTrackerBundle

        self._exploration = ExplorationTrackerBundle(
            component="voice_state",
            edges=["turn_phase_changes", "readiness_level"],
            traces=["phase_stability", "temperature"],
            neighbors=["salience_router", "stimmung"],
            kappa=0.008,
            t_patience=360.0,
        )
        self._prev_phase_hash: float = 0.0
        self._prev_readiness: float = 0.0

    # ── PerceptionBackend interface ────────────────────────────────

    @property
    def name(self) -> str:
        return "cognitive_loop"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset(
            {"turn_phase", "cognitive_readiness", "conversation_temperature", "predicted_tier"}
        )

    @property
    def tier(self) -> BackendTier:
        return BackendTier.FAST

    def available(self) -> bool:
        return True

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Push current cognitive state into perception behaviors."""
        now = time.monotonic()
        if "turn_phase" in behaviors:
            behaviors["turn_phase"].update(self._turn_phase.value, now)
        if "cognitive_readiness" in behaviors:
            behaviors["cognitive_readiness"].update(self._cognitive_readiness, now)
        if "conversation_temperature" in behaviors:
            temp = self._model.conversation_temperature if self._model else 0.0
            behaviors["conversation_temperature"].update(temp, now)
        if "predicted_tier" in behaviors:
            behaviors["predicted_tier"].update(self._predicted_tier, now)

        # Exploration signal
        phase_hash = hash(self._turn_phase.value) % 100 / 100.0
        self._exploration.feed_habituation(
            "turn_phase_changes", phase_hash, self._prev_phase_hash, 0.3
        )
        self._exploration.feed_habituation(
            "readiness_level", self._cognitive_readiness, self._prev_readiness, 0.2
        )
        self._exploration.feed_interest("phase_stability", phase_hash, 0.3)
        temp = self._model.conversation_temperature if self._model else 0.0
        self._exploration.feed_interest("temperature", temp, 0.2)
        self._exploration.feed_error(0.0)
        self._exploration.compute_and_publish()
        self._prev_phase_hash = phase_hash
        self._prev_readiness = self._cognitive_readiness

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    # ── Main loop ──────────────────────────────────────────────────

    async def run(self) -> None:
        """Main cognitive loop — runs until stopped or pipeline ends."""
        self._running = True
        self._mutual_silence_start = time.monotonic()
        log.info("Cognitive loop started (tick=%.0fms)", TICK_INTERVAL_S * 1000)

        try:
            while self._running and self._pipeline.is_active:
                tick_start = time.monotonic()

                # 1. Derive turn phase
                prev_phase = self._turn_phase
                self._turn_phase = self._derive_phase()

                if self._turn_phase != prev_phase:
                    log.info("turn_phase: %s → %s", prev_phase.value, self._turn_phase.value)
                    self._on_phase_transition(prev_phase, self._turn_phase)

                # 2. Operator utterances always preempt spontaneous speech.
                utterance = self._buffer.get_utterance()
                if utterance is not None:
                    # Cancel in-flight spontaneous speech for operator utterance
                    if self._processing_task is not None and not self._processing_task.done():
                        self._processing_task.cancel()
                        log.info("Cancelled spontaneous speech for operator utterance")
                    self._dispatch_utterance(utterance)
                elif (
                    not self._is_processing
                    and self._turn_phase
                    not in (TurnPhase.HAPAX_SPEAKING, TurnPhase.OPERATOR_SPEAKING)
                    and self._turn_phase == TurnPhase.MUTUAL_SILENCE
                    and hasattr(self, "_speech_capability")
                    and self._speech_capability is not None
                    and self._speech_capability.has_pending()
                    and self._pipeline.turn_count > 0
                ):
                    imp = self._speech_capability.consume_pending()
                    if imp is not None:
                        self._dispatch_spontaneous_speech(imp)

                # 3. Phase-specific cognition
                if self._turn_phase == TurnPhase.OPERATOR_SPEAKING:
                    await self._tick_operator_speaking()
                    self._session.mark_activity()  # keep session alive while operator speaks
                elif self._turn_phase == TurnPhase.MUTUAL_SILENCE:
                    await self._tick_mutual_silence()
                elif self._turn_phase in (TurnPhase.HAPAX_SPEAKING, TurnPhase.TRANSITION):
                    # Keep session alive during processing/speaking
                    self._session.mark_activity()

                # 4. Update cognitive readiness
                self._cognitive_readiness = self._compute_readiness()

                # 5. Update Behaviors
                now = time.monotonic()
                self._b_turn_phase.update(self._turn_phase.value, now)
                self._b_cognitive_readiness.update(self._cognitive_readiness, now)
                if self._model:
                    self._b_conversation_temperature.update(
                        self._model.conversation_temperature, now
                    )
                self._b_predicted_tier.update(self._predicted_tier, now)

                # Session timeout is handled by the daemon's main loop, which
                # speaks a goodbye message before closing. The cognitive loop
                # just checks if the pipeline is still active (set to False
                # by _stop_pipeline when the daemon closes the session).

                # Sleep remainder of tick
                elapsed = time.monotonic() - tick_start
                sleep_time = max(0, TICK_INTERVAL_S - elapsed)
                await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("Cognitive loop error")
        finally:
            self._running = False
            write_tpn_active(False)
            log.info("Cognitive loop stopped")

    def stop_loop(self) -> None:
        """Signal the loop to stop."""
        self._running = False
        write_tpn_active(False)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def turn_phase(self) -> TurnPhase:
        return self._turn_phase

    @property
    def predicted_tier(self) -> str:
        return self._predicted_tier

    # ── Phase derivation ───────────────────────────────────────────

    def _derive_phase(self) -> TurnPhase:
        """Derive current turn phase from buffer + pipeline state."""
        speech_active = self._buffer.speech_active
        is_speaking = self._buffer.is_speaking

        if speech_active and not is_speaking:
            return TurnPhase.OPERATOR_SPEAKING
        if not speech_active and is_speaking:
            return TurnPhase.HAPAX_SPEAKING
        if speech_active and is_speaking:
            # Barge-in: operator takes priority
            return TurnPhase.OPERATOR_SPEAKING

        # Neither speaking
        from agents.hapax_daimonion.conversation_pipeline import ConvState

        if self._pipeline.state in (ConvState.TRANSCRIBING, ConvState.THINKING):
            return TurnPhase.TRANSITION
        if self._last_operator_speaking_at > 0:
            silence_s = time.monotonic() - self._last_operator_speaking_at
            if silence_s < _PAUSING_THRESHOLD_S:
                return TurnPhase.OPERATOR_PAUSING
        return TurnPhase.MUTUAL_SILENCE

    def _on_phase_transition(self, from_phase: TurnPhase, to_phase: TurnPhase) -> None:
        """Handle phase transitions."""
        now = time.monotonic()
        if to_phase == TurnPhase.MUTUAL_SILENCE:
            self._mutual_silence_start = now
            self._wind_down_sent = False
        if from_phase == TurnPhase.OPERATOR_SPEAKING:
            self._last_operator_speaking_at = now
        if to_phase == TurnPhase.OPERATOR_SPEAKING:
            # Reset speculative STT for new speech segment
            if self._speculative_stt is not None:
                self._speculative_stt.reset()

        # TPN_ACTIVE signal for DMN anti-correlation
        _tpn_active = to_phase in (TurnPhase.TRANSITION, TurnPhase.HAPAX_SPEAKING)
        write_tpn_active(_tpn_active)

        # Track response timing from phase transitions — now that
        # process_utterance runs as a background task, the cognitive loop
        # observes TRANSITION and HAPAX_SPEAKING phases in real time.
        if to_phase == TurnPhase.TRANSITION:
            self._response_start_at = time.monotonic()
        if from_phase == TurnPhase.HAPAX_SPEAKING and self._model is not None:
            if self._response_start_at > 0:
                response_time = now - self._response_start_at
                self._model.on_response("", response_time)
                self._response_start_at = 0.0

    # ── Phase-specific ticks ───────────────────────────────────────

    async def _tick_operator_speaking(self) -> None:
        """During operator speech: speculative STT + pre-routing."""
        if self._speculative_stt is None:
            return

        speech_s = self._buffer.speech_duration_s
        if speech_s < 1.0:
            return

        frames = self._buffer.speech_frames_snapshot
        partial = await self._speculative_stt.maybe_speculate(frames, speech_s)
        if partial and self._salience_router is not None:
            try:
                decision = self._salience_router.route(
                    partial,
                    turn_count=self._pipeline.turn_count,
                    activity_mode=getattr(self._pipeline, "_activity_mode", "idle"),
                )
                self._predicted_tier = decision.tier.name
                log.debug("Speculative route: '%s' → %s", partial[:50], self._predicted_tier)
            except Exception:
                log.debug("Speculative routing failed", exc_info=True)

    async def _tick_mutual_silence(self) -> None:
        """During mutual silence: tick model, handle active silence."""
        silence_s = time.monotonic() - self._mutual_silence_start

        # Tick conversational model
        if self._model is not None:
            self._model.on_silence_tick(TICK_INTERVAL_S)

        # Active silence handling (feature-flagged)
        if self._active_silence_enabled:
            await self._handle_silence(silence_s)

    # ── Utterance dispatch ─────────────────────────────────────────

    @property
    def _is_processing(self) -> bool:
        """True if an utterance is currently being processed by the pipeline.

        Also true if the pipeline is in SPEAKING state — TTS audio may still
        be playing even after the processing task completes. Dispatching a new
        utterance during playback would cut off the current response.
        """
        if self._processing_task is not None and not self._processing_task.done():
            return True
        from agents.hapax_daimonion.conversation_pipeline import ConvState

        return self._pipeline.state == ConvState.SPEAKING

    def _dispatch_utterance(self, utterance: bytes) -> None:
        """Dispatch utterance processing as a background task.

        The cognitive loop continues ticking while STT+LLM+TTS runs,
        enabling speculative STT, phase tracking, and model updates.
        """
        # Cancel any in-flight speculative STT — final transcription is about
        # to use the same single-threaded executor
        if self._speculative_stt is not None:
            self._speculative_stt.reset()

        self._processing_task = asyncio.create_task(self._process_utterance(utterance))
        self._processing_task.add_done_callback(self._on_processing_done)

    def _dispatch_spontaneous_speech(self, impingement: object) -> None:
        """Dispatch spontaneous speech from an impingement cascade activation.

        Unlike _dispatch_utterance (which processes operator audio through STT),
        this skips STT and routes directly to LLM generation with impingement
        context as the "user intent."
        """
        log.info(
            "Spontaneous speech dispatched: %s",
            getattr(impingement, "content", {}).get("metric", "unknown"),
        )
        self._processing_task = asyncio.create_task(
            self._pipeline.generate_spontaneous_speech(impingement)
        )
        self._processing_task.add_done_callback(self._on_processing_done)

    def _on_processing_done(self, task: asyncio.Task) -> None:
        """Callback when utterance processing completes."""
        self._processing_task = None
        self._predicted_tier = ""
        try:
            exc = task.exception()
            if exc is not None:
                log.exception("Utterance processing failed", exc_info=exc)
        except asyncio.CancelledError:
            pass

    async def _process_utterance(self, utterance: bytes) -> None:
        """Process an utterance through speaker verify + pipeline.

        Runs as a background task — does NOT block the cognitive loop.
        """
        # Record raw operator audio BEFORE any processing
        if self._session_recorder is not None:
            self._session_recorder.record_operator_audio(utterance)

        # Speaker verification gate
        if self._speaker_identifier is not None and not self._speaker_verified:
            utterance_samples = len(utterance) // 2
            self._speaker_audio_buf.append(utterance)
            self._speaker_audio_samples += utterance_samples

            if self._speaker_audio_samples >= _VERIFY_MIN_SAMPLES:
                longest = max(self._speaker_audio_buf, key=len)
                speaker = await self._verify_speaker(longest)

                if speaker == "operator":
                    self._speaker_verified = True
                    self._session.set_speaker("operator", 0.0)
                    log.info("Speaker gate: operator verified, session trusted")
                    for buffered in self._speaker_audio_buf:
                        self._session.mark_activity()
                        await self._pipeline.process_utterance(buffered)
                        self._session.mark_activity()
                    self._speaker_audio_buf.clear()
                    self._update_model_on_utterance(utterance)
                    return
                elif speaker == "not_operator":
                    log.info("Speaker gate: DROPPED — not operator")
                    self._speaker_audio_buf.clear()
                    self._speaker_audio_samples = 0
                    return
                else:
                    self._speaker_verify_attempts = getattr(self, "_speaker_verify_attempts", 0) + 1
                    if self._speaker_verify_attempts >= 2:
                        self._speaker_verified = True
                        self._session.set_speaker("operator", 0.0)
                        log.info(
                            "Speaker gate: verification inconclusive after %d attempts, "
                            "trusting wake word (fail-open)",
                            self._speaker_verify_attempts,
                        )
                        for buffered in self._speaker_audio_buf:
                            self._session.mark_activity()
                            await self._pipeline.process_utterance(buffered)
                            self._session.mark_activity()
                        self._speaker_audio_buf.clear()
                        self._update_model_on_utterance(utterance)
                        return
                    log.info("Speaker gate: uncertain, will retry on next utterance")

        self._session.mark_activity()
        self._update_model_on_utterance(utterance)

        await self._pipeline.process_utterance(utterance)
        self._session.mark_activity()

        # Record what happened (transcript + response) after pipeline completes
        if self._session_recorder is not None:
            self._session_recorder.capture_pipeline_results(self._pipeline)

    def _update_model_on_utterance(self, utterance: bytes) -> None:
        """Update conversational model after an utterance is processed."""
        if self._model is None:
            return
        speech_s = len(utterance) / 2 / 16000  # int16 at 16kHz
        tier = self._predicted_tier or "FAST"
        # Transcript is not available here (STT runs inside pipeline);
        # topic tracking would need a pipeline callback to get it.
        self._model.on_utterance("", tier, speech_s)

    async def _verify_speaker(self, audio_bytes: bytes) -> str:
        """Run speaker verification on accumulated PCM audio.

        Returns "operator", "not_operator", or "uncertain".
        """
        try:
            import numpy as np

            audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            if len(audio) < 8000:
                return "uncertain"

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self._speaker_identifier.identify_audio(audio, 16000),
            )
            log.info(
                "Speaker verification: %s (confidence=%.3f, audio=%.1fs)",
                result.label,
                result.confidence,
                len(audio) / 16000,
            )
            return result.label
        except Exception:
            log.debug("Speaker verification failed (fail-open)", exc_info=True)
            return "uncertain"

    # ── Active silence handling (Batch 6) ──────────────────────────

    async def _handle_silence(self, silence_s: float) -> None:
        """Contextual actions during mutual silence. Feature-flagged."""
        temperature = self._model.conversation_temperature if self._model else 0.0

        # Don't interrupt high-temperature silence (operator is thinking)
        if temperature > 0.5:
            return

        # Surface notification after threshold
        if (
            silence_s > self._silence_notification_threshold_s
            and temperature < 0.3
            and self._notification_queue is not None
            and self._notification_queue.pending_count > 0
            and not self._is_processing
        ):
            notification = self._notification_queue.next()
            if notification is not None:
                log.info(
                    "Active silence: delivering notification %r (silence=%.1fs)",
                    notification.title,
                    silence_s,
                )
                delivered = await self._pipeline.deliver_notification(
                    title=notification.title,
                    message=notification.message,
                    source=notification.source,
                )
                if not delivered:
                    self._notification_queue.requeue(notification)
                    log.debug("Notification requeued (pipeline busy)")

        # Wind-down after extended silence
        if (
            silence_s > self._silence_winddown_threshold_s
            and temperature < 0.2
            and not self._wind_down_sent
        ):
            self._wind_down_sent = True
            log.info(
                "Active silence: wind-down (silence=%.1fs, temp=%.2f)",
                silence_s,
                temperature,
            )
            # Session close will be handled by the timeout check in run()

    # ── Readiness computation ──────────────────────────────────────

    def _compute_readiness(self) -> float:
        """Compute cognitive readiness score (0-1).

        High readiness = system is prepared to respond quickly.
        """
        readiness = 0.5  # baseline

        # Higher if we have a predicted tier (speculative routing done)
        if self._predicted_tier:
            readiness += 0.2

        # Higher if speaker is already verified
        if self._speaker_verified or self._speaker_identifier is None:
            readiness += 0.2

        # Lower during transition (already processing)
        if self._turn_phase == TurnPhase.TRANSITION:
            readiness = 0.1

        return min(1.0, readiness)
