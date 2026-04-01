"""CPAL async runner -- the main conversation loop.

Replaces CognitiveLoop as the daemon's conversation coordinator.
Ticks at ~150ms, driving perception, formulation, and production
streams through the control law evaluator.

Key design: CPAL does NOT rewrite the LLM/TTS pipeline. It delegates
T3 (substantive response) to the existing ConversationPipeline, which
handles STT, echo rejection, salience routing, LLM streaming, and TTS.
CPAL decides WHEN T3 fires based on the control law. The pipeline is
the T3 production capability.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from agents.hapax_daimonion.cpal.evaluator import CpalEvaluator
from agents.hapax_daimonion.cpal.formulation_stream import FormulationStream
from agents.hapax_daimonion.cpal.grounding_bridge import GroundingBridge
from agents.hapax_daimonion.cpal.impingement_adapter import ImpingementAdapter
from agents.hapax_daimonion.cpal.perception_stream import PerceptionStream
from agents.hapax_daimonion.cpal.production_stream import ProductionStream
from agents.hapax_daimonion.cpal.shm_publisher import publish_cpal_state
from agents.hapax_daimonion.cpal.signal_cache import SignalCache
from agents.hapax_daimonion.cpal.tier_composer import TierComposer
from agents.hapax_daimonion.cpal.types import ConversationalRegion, CorrectionTier, GainUpdate

log = logging.getLogger(__name__)

TICK_INTERVAL_S = 0.15  # 150ms cognitive tick
_STIMMUNG_PATH = Path("/dev/shm/hapax-stimmung/state.json")
_TPN_PATH = Path("/dev/shm/hapax-dmn/tpn_active")


class CpalRunner:
    """Async run loop for CPAL-based conversation.

    Wires perception, formulation, production, evaluator, grounding,
    and impingement adapter. Delegates T3 (substantive response) to
    the existing ConversationPipeline.
    """

    def __init__(
        self,
        *,
        buffer: object,
        stt: object,
        salience_router: object,
        audio_output: object | None = None,
        grounding_ledger: object | None = None,
        tts_manager: object | None = None,
        conversation_pipeline: object | None = None,
        echo_canceller: object | None = None,
    ) -> None:
        # Streams
        self._perception = PerceptionStream(buffer=buffer)
        self._formulation = FormulationStream(stt=stt, salience_router=salience_router)
        self._production = ProductionStream(audio_output=audio_output)

        # Control components
        self._evaluator = CpalEvaluator(
            perception=self._perception,
            formulation=self._formulation,
            production=self._production,
        )
        self._grounding = GroundingBridge(ledger=grounding_ledger)
        self._impingement_adapter = ImpingementAdapter()
        self._tier_composer = TierComposer()
        self._signal_cache = SignalCache()

        # External components
        self._buffer = buffer
        self._stt = stt
        self._tts_manager = tts_manager
        self._audio_output = audio_output
        self._echo_canceller = echo_canceller
        self._pipeline = conversation_pipeline  # T3 delegate

        # State
        self._running = False
        self._tick_count = 0
        self._last_tick_at = 0.0
        self._accumulated_silence_s = 0.0
        self._processing_utterance = False
        self._last_stimmung_check = 0.0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def evaluator(self) -> CpalEvaluator:
        return self._evaluator

    @property
    def signal_cache(self) -> SignalCache:
        return self._signal_cache

    def set_pipeline(self, pipeline: object) -> None:
        """Set the conversation pipeline for T3 delegation. Called after pipeline creation."""
        self._pipeline = pipeline

    def set_grounding_ledger(self, ledger: object) -> None:
        """Update grounding ledger (may be created after runner init)."""
        self._grounding = GroundingBridge(ledger=ledger)

    def presynthesize_signals(self) -> None:
        """Presynthesize T1 signal cache. Call once at startup."""
        if self._tts_manager is not None:
            self._signal_cache.presynthesize(self._tts_manager)

    async def run(self) -> None:
        """Main async run loop. Ticks at TICK_INTERVAL_S."""
        self._running = True
        self._last_tick_at = time.monotonic()
        log.info("CPAL runner started (tick=%.0fms)", TICK_INTERVAL_S * 1000)

        try:
            while self._running:
                tick_start = time.monotonic()
                dt = tick_start - self._last_tick_at
                self._last_tick_at = tick_start

                await self._tick(dt)
                self._tick_count += 1

                # Publish state every 10 ticks (~1.5s)
                if self._tick_count % 10 == 0:
                    self._publish_state()
                    self._check_stimmung()

                # Sleep for remainder of tick interval
                elapsed = time.monotonic() - tick_start
                sleep_time = max(0, TICK_INTERVAL_S - elapsed)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            log.info("CPAL runner cancelled")
        except Exception:
            log.exception("CPAL runner error")
        finally:
            self._running = False
            log.info("CPAL runner stopped after %d ticks", self._tick_count)

    def stop(self) -> None:
        """Signal the runner to stop."""
        self._running = False

    async def _tick(self, dt: float) -> None:
        """Run one cognitive tick."""
        # 1. Update perception from buffer state
        frame = self._get_audio_frame()
        vad_prob = self._get_vad_prob()
        self._perception.update(frame, vad_prob=vad_prob)
        signals = self._perception.signals

        # 2. Track accumulated silence (C: I1)
        if signals.speech_active or self._processing_utterance:
            self._accumulated_silence_s = 0.0
        else:
            self._accumulated_silence_s += dt

        # 3. Gain drivers beyond just speech (C: I5, I6)
        self._apply_gain_drivers(signals, dt)

        # 4. Check for utterances — dispatch T3 via pipeline
        utterance = self._perception.get_utterance()
        if utterance is not None and not self._processing_utterance:
            asyncio.create_task(self._process_utterance(utterance))

        # 5. Speculative formulation during operator speech
        if signals.speech_active and hasattr(self._buffer, "speech_frames_snapshot"):
            frames = self._buffer.speech_frames_snapshot
            if frames:
                await self._formulation.speculate(
                    frames, speech_duration_s=signals.speech_duration_s
                )

        # 6. Run evaluator with real grounding state (C: C2)
        gs = self._grounding.snapshot()
        result = self._evaluator._control_law.evaluate(
            gain=self._evaluator.gain_controller.gain,
            ungrounded_du_count=gs.ungrounded_du_count,
            repair_rate=gs.repair_rate,
            gqi=gs.gqi,
            silence_s=self._accumulated_silence_s,
        )

        # 7. GQI → loop gain feedback (C: C8)
        if gs.gqi < 0.4:
            self._evaluator.gain_controller.apply(GainUpdate(delta=-0.02, source="low_gqi"))
        elif gs.gqi > 0.8 and self._evaluator.gain_controller.gain > 0.3:
            self._evaluator.gain_controller.apply(GainUpdate(delta=0.01, source="high_gqi"))

        # 8. Barge-in detection
        if self._production.is_producing and signals.speech_active and signals.vad_confidence > 0.9:
            self._production.interrupt()
            if self._pipeline and hasattr(self._pipeline, "buffer") and self._pipeline.buffer:
                self._pipeline.buffer.set_speaking(False)
            log.info("CPAL barge-in: operator interrupted production")

        # 9. Backchannel selection (independent of T3)
        bc = self._formulation.select_backchannel(
            region=ConversationalRegion.from_gain(self._evaluator.gain_controller.gain),
            speech_active=signals.speech_active,
            speech_duration_s=signals.speech_duration_s,
            trp_probability=signals.trp_probability,
        )
        if bc is not None and not self._processing_utterance:
            self._execute_backchannel(bc)

        # 10. Compose and execute tiered action for non-utterance triggers
        if (
            not self._production.is_producing
            and not self._processing_utterance
            and signals.trp_probability > 0.5
            and result.action_tier.value >= CorrectionTier.T1_PRESYNTHESIZED.value
        ):
            composed = self._tier_composer.compose(
                action_tier=result.action_tier,
                region=result.region,
            )
            self._execute_composed(composed)

        # 11. TPN signal for DMN anti-correlation
        self._signal_tpn(self._processing_utterance or self._production.is_producing)

    def _get_audio_frame(self) -> bytes:
        """Get the latest audio frame from the buffer for energy/prosodic analysis."""
        if hasattr(self._buffer, "_pre_roll") and self._buffer._pre_roll:
            return self._buffer._pre_roll[-1]
        return b"\x00\x00" * 480

    def _get_vad_prob(self) -> float:
        """Get VAD probability from buffer state."""
        if hasattr(self._buffer, "speech_active"):
            return 0.8 if self._buffer.speech_active else 0.0
        return 0.0

    def _apply_gain_drivers(self, signals, dt: float) -> None:
        """Apply all gain drivers and dampers beyond basic speech detection."""
        gc = self._evaluator.gain_controller

        # Driver: operator speech
        if signals.speech_active and signals.vad_confidence > 0.3:
            gc.apply(GainUpdate(delta=0.05, source="operator_speech"))
        else:
            gc.decay(dt)

        # Driver: presence from perception engine
        try:
            presence_path = Path("/dev/shm/hapax-perception/state.json")
            if presence_path.exists():
                state = json.loads(presence_path.read_text())
                presence = state.get("presence_score", "likely_absent")
                if presence == "likely_present" and gc.gain < 0.1:
                    gc.apply(GainUpdate(delta=0.01, source="presence"))
        except Exception:
            pass

        # Damper: prolonged silence beyond decay
        if self._accumulated_silence_s > 30.0:
            gc.apply(GainUpdate(delta=-0.01, source="prolonged_silence"))

    async def _process_utterance(self, utterance: bytes) -> None:
        """Process an operator utterance through the full pipeline (T3).

        Delegates to ConversationPipeline.process_utterance() which handles
        STT, echo rejection, salience routing, LLM streaming, TTS, and
        audio output. CPAL controls the orchestration — T0/T1 signals
        fire before T3, and gain updates happen after.
        """
        self._processing_utterance = True
        self._production.mark_t3_start()

        try:
            # T0: Visual acknowledgment (instant)
            self._production.produce_t0(
                signal_type="attentional_shift",
                intensity=self._evaluator.gain_controller.gain,
            )

            # T1: Acknowledgment (if cache ready and gain high enough)
            region = ConversationalRegion.from_gain(self._evaluator.gain_controller.gain)
            if region.value >= ConversationalRegion.ATTENTIVE.value:
                ack = self._signal_cache.select("acknowledgment")
                if ack is not None:
                    _, pcm = ack
                    if self._audio_output is not None:
                        if self._echo_canceller:
                            self._echo_canceller.feed_reference(pcm)
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(None, self._audio_output.write, pcm)

            # T3: Full formulation via pipeline
            if self._pipeline is not None:
                await self._pipeline.process_utterance(utterance)

                # Record grounding outcome based on pipeline result (C: C1)
                self._evaluator.gain_controller.record_grounding_outcome(success=True)

                # Gain driver: closed-loop confirmation
                self._evaluator.gain_controller.apply(
                    GainUpdate(delta=0.05, source="response_delivered")
                )
            else:
                log.warning("CPAL: no pipeline for T3 — utterance dropped")

        except Exception:
            log.exception("CPAL: utterance processing failed")
            self._evaluator.gain_controller.record_grounding_outcome(success=False)
        finally:
            self._processing_utterance = False
            self._production.mark_t3_end()
            self._formulation.reset()

    def _execute_backchannel(self, bc) -> None:
        """Execute a backchannel decision from the formulation stream."""
        if bc.tier == CorrectionTier.T0_VISUAL:
            self._production.produce_t0(signal_type=bc.signal_type, intensity=0.5)
        elif bc.tier == CorrectionTier.T1_PRESYNTHESIZED:
            signal = self._signal_cache.select(bc.signal_type)
            if signal is not None:
                _, pcm = signal
                if self._echo_canceller:
                    self._echo_canceller.feed_reference(pcm)
                self._production.produce_t1(pcm_data=pcm)

    def _execute_composed(self, composed) -> None:
        """Execute a composed tier sequence."""
        for tier, signal_type in zip(composed.tiers, composed.signal_types, strict=False):
            if tier == CorrectionTier.T0_VISUAL:
                self._production.produce_t0(
                    signal_type=signal_type,
                    intensity=self._evaluator.gain_controller.gain,
                )
            elif tier == CorrectionTier.T1_PRESYNTHESIZED:
                signal = self._signal_cache.select(signal_type)
                if signal is not None:
                    _, pcm = signal
                    if self._echo_canceller:
                        self._echo_canceller.feed_reference(pcm)
                    self._production.produce_t1(pcm_data=pcm)

    def _check_stimmung(self) -> None:
        """Read stimmung stance and set gain ceiling (C: C15)."""
        try:
            if _STIMMUNG_PATH.exists():
                data = json.loads(_STIMMUNG_PATH.read_text())
                stance = data.get("overall_stance", "nominal")
                self._evaluator.gain_controller.set_stimmung_ceiling(stance)
        except Exception:
            pass

    def _signal_tpn(self, active: bool) -> None:
        """Signal DMN that task-positive network is active."""
        try:
            _TPN_PATH.parent.mkdir(parents=True, exist_ok=True)
            _TPN_PATH.write_text("1" if active else "0", encoding="utf-8")
        except OSError:
            pass

    def _publish_state(self) -> None:
        """Publish CPAL state to /dev/shm."""
        try:
            gs = self._grounding.snapshot()
            result = self._evaluator._control_law.evaluate(
                gain=self._evaluator.gain_controller.gain,
                ungrounded_du_count=gs.ungrounded_du_count,
                repair_rate=gs.repair_rate,
                gqi=gs.gqi,
                silence_s=self._accumulated_silence_s,
            )
            publish_cpal_state(
                gain_controller=self._evaluator.gain_controller,
                error=result.error,
                action_tier=result.action_tier,
            )
        except Exception:
            log.debug("CPAL state publish failed", exc_info=True)

    async def process_impingement(self, impingement: object) -> None:
        """Process an impingement through the CPAL control loop.

        Replaces the old speech recruitment pathway. Impingements
        modulate gain and, if they should surface, trigger T3 via
        the pipeline's spontaneous speech path.
        """
        effect = self._impingement_adapter.adapt(impingement)

        if effect.gain_update is not None:
            self._evaluator.gain_controller.apply(effect.gain_update)

        if effect.should_surface:
            log.info("CPAL: impingement surfacing: %s", effect.narrative[:60])
            # T0 visual signal
            self._production.produce_t0(
                signal_type="impingement_alert",
                intensity=min(1.0, effect.error_boost + 0.5),
            )
            # T3 via pipeline spontaneous speech (if available)
            if self._pipeline is not None and hasattr(
                self._pipeline, "generate_spontaneous_speech"
            ):
                try:
                    await self._pipeline.generate_spontaneous_speech(impingement)
                except Exception:
                    log.debug("Spontaneous speech failed", exc_info=True)
