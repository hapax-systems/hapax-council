"""CPAL async runner -- the main conversation loop.

Replaces CognitiveLoop as the daemon's conversation coordinator.
Ticks at ~150ms, driving perception, formulation, and production
streams through the control law evaluator.

This module is the entry point for CPAL-based conversation. It
wires together all Phase 1-4 components into a running system.
"""

from __future__ import annotations

import asyncio
import logging
import time

from agents.hapax_daimonion.cpal.evaluator import CpalEvaluator
from agents.hapax_daimonion.cpal.formulation_stream import FormulationStream
from agents.hapax_daimonion.cpal.grounding_bridge import GroundingBridge
from agents.hapax_daimonion.cpal.impingement_adapter import ImpingementAdapter
from agents.hapax_daimonion.cpal.perception_stream import PerceptionStream
from agents.hapax_daimonion.cpal.production_stream import ProductionStream
from agents.hapax_daimonion.cpal.shm_publisher import publish_cpal_state
from agents.hapax_daimonion.cpal.signal_cache import SignalCache
from agents.hapax_daimonion.cpal.tier_composer import TierComposer
from agents.hapax_daimonion.cpal.types import CorrectionTier

log = logging.getLogger(__name__)

TICK_INTERVAL_S = 0.15  # 150ms cognitive tick


class CpalRunner:
    """Async run loop for CPAL-based conversation.

    Wires perception, formulation, production, evaluator, grounding,
    and impingement adapter into a single tick loop.
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

        # State
        self._buffer = buffer
        self._tts_manager = tts_manager
        self._running = False
        self._tick_count = 0
        self._last_tick_at = 0.0

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
        # (In the full daemon integration, this would read audio frames.
        #  For now, we update from buffer state which is fed externally.)
        frame = b"\x00\x00" * 480  # placeholder silent frame
        vad_prob = 0.0
        if hasattr(self._buffer, "speech_active"):
            vad_prob = 0.8 if self._buffer.speech_active else 0.0
        self._perception.update(frame, vad_prob=vad_prob)

        # 2. Check for utterances
        utterance = self._perception.get_utterance()
        if utterance is not None:
            log.info("CPAL: utterance received (%d bytes)", len(utterance))
            # TODO Phase 5: dispatch through formulation → LLM → production

        # 3. Speculative formulation during operator speech
        signals = self._perception.signals
        if signals.speech_active and hasattr(self._buffer, "speech_frames_snapshot"):
            frames = self._buffer.speech_frames_snapshot
            if frames:
                await self._formulation.speculate(
                    frames, speech_duration_s=signals.speech_duration_s
                )

        # 4. Run evaluator with real grounding state
        self._grounding.snapshot()
        result = self._evaluator.tick(dt)

        # 5. Compose and execute tiered action
        if not self._production.is_producing and signals.trp_probability > 0.3:
            composed = self._tier_composer.compose(
                action_tier=result.action_tier,
                region=result.region,
            )
            self._execute_composed(composed)

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
                    self._production.produce_t1(pcm_data=pcm)

    def _publish_state(self) -> None:
        """Publish CPAL state to /dev/shm."""
        try:
            gs = self._grounding.snapshot()
            from agents.hapax_daimonion.cpal.control_law import ConversationControlLaw

            law = ConversationControlLaw()
            result = law.evaluate(
                gain=self._evaluator.gain_controller.gain,
                ungrounded_du_count=gs.ungrounded_du_count,
                repair_rate=gs.repair_rate,
                gqi=gs.gqi,
                silence_s=0.0,
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

        Called by the daemon's impingement consumer when an impingement
        arrives. Replaces the old speech recruitment pathway.
        """
        effect = self._impingement_adapter.adapt(impingement)

        if effect.gain_update is not None:
            self._evaluator.gain_controller.apply(effect.gain_update)

        if effect.should_surface:
            log.info(
                "CPAL: impingement surfacing as speech: %s",
                effect.narrative[:60],
            )
            # T0 visual + T1 acknowledgment for now
            # Full T3 LLM response will come in daemon integration
            self._production.produce_t0(
                signal_type="impingement_alert",
                intensity=min(1.0, effect.error_boost + 0.5),
            )
