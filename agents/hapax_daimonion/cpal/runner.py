"""CPAL async runner -- the main conversation loop.

Sole conversation coordinator for the daemon.
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
import enum
import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from agents.hapax_daimonion.cpal.destination_channel import (
    resolve_playback_decision,
)
from agents.hapax_daimonion.cpal.evaluator import CpalEvaluator
from agents.hapax_daimonion.cpal.formulation_stream import FormulationStream
from agents.hapax_daimonion.cpal.grounding_bridge import GroundingBridge
from agents.hapax_daimonion.cpal.impingement_adapter import ImpingementAdapter
from agents.hapax_daimonion.cpal.perception_stream import PerceptionStream
from agents.hapax_daimonion.cpal.production_stream import ProductionStream
from agents.hapax_daimonion.cpal.programme_context import default_provider
from agents.hapax_daimonion.cpal.register_bridge import (
    VoiceRegisterBridge,
    textmode_prompt_prefix,
)
from agents.hapax_daimonion.cpal.shm_publisher import publish_cpal_state
from agents.hapax_daimonion.cpal.signal_cache import SignalCache
from agents.hapax_daimonion.cpal.tier_composer import TierComposer
from agents.hapax_daimonion.cpal.types import ConversationalRegion, CorrectionTier, GainUpdate
from agents.hapax_daimonion.voice_output_witness import (
    record_destination_decision,
    record_drop,
    record_playback_result,
    record_tts_synthesis,
)
from shared.voice_register import VoiceRegister

log = logging.getLogger(__name__)

TICK_INTERVAL_S = 0.15  # 150ms cognitive tick

# --- Shared Speech Event Ring ---
# Minimum viable aperture unification: a shared in-memory ring that all
# speech paths (conversational, autonomous narration, exploration
# surfacing) append to. Provides cross-path evidence of recent speech
# activity without requiring the full SelfPresenceEnvelope.
_SPEECH_EVENT_RING_MAXLEN = 20
_DIALOG_ACTIVE_WINDOW_S = 30.0  # matches impingement_adapter.DIALOG_ACTIVE_WINDOW_S


class SpeechEventKind(enum.Enum):
    """Classification of speech events for cross-path awareness."""

    RESPONSE = "response"  # conversational response to operator speech
    NARRATION = "narration"  # autonomous narrative drive
    EXPLORATION = "exploration"  # exploration surfacing


@dataclass(frozen=True)
class SpeechEvent:
    """Record of a speech emission for cross-path awareness.

    Lightweight surrogate for ApertureEvent from the Unified Self-Grounding
    Spine spec. Provides enough evidence for cross-path dialog suppression
    without the full ontology.
    """

    kind: SpeechEventKind
    timestamp: float  # time.monotonic()
    source_path: str  # e.g. "pipeline._process_utterance_inner", "autonomous_narrative"
    text_preview: str = ""  # first 40 chars for debug/context


def _prepared_playback_loop_owns_tts(programme: object | None) -> bool:
    """Return True only when the legacy prepared playback loop can speak."""

    content = getattr(programme, "content", None) if programme is not None else None
    if content is None or not getattr(content, "prepared_script", None):
        return False
    try:
        from agents.hapax_daimonion.run_loops_aux import (
            _prepared_verbatim_legacy_allowed,
        )

        return bool(_prepared_verbatim_legacy_allowed(content))
    except Exception:
        return False


_STIMMUNG_PATH = Path("/dev/shm/hapax-stimmung/state.json")
_TPN_PATH = Path("/dev/shm/hapax-dmn/tpn_active")


_TICK_DURATION_MS = None
_TICKS_TOTAL = None
_TICKS_BY_TYPE = None
_COLD_START_EVENTS = None

try:
    from prometheus_client import Counter, Histogram

    # Queue #225: exposed via hapax-daimonion's /metrics server (started in
    # agents/hapax_daimonion/__main__.py). A Counter with a `type` label is
    # used instead of the queue-spec-suggested Gauge: a Gauge over three
    # mutually exclusive categorical states would force 0/1 flips every tick
    # and drop cumulative history. ValueError catches duplicate-registration
    # on test re-imports and leaves the sentinels as None.
    try:
        _TICK_DURATION_MS = Histogram(
            "hapax_cpal_tick_duration_ms",
            "Wallclock duration of a CPAL cognitive tick, in milliseconds",
            buckets=(10, 25, 50, 100, 150, 300, 500, 1000, 2500),
        )
        _TICKS_TOTAL = Counter(
            "hapax_cpal_ticks_total",
            "Total CPAL cognitive ticks",
        )
        _TICKS_BY_TYPE = Counter(
            "hapax_cpal_ticks_by_type_total",
            "CPAL ticks by activity classification",
            labelnames=("type",),
        )
        _COLD_START_EVENTS = Counter(
            "hapax_cpal_cold_start_events_total",
            "CpalRunner.run() entries — target stays at 1 for a healthy daemon",
        )
    except ValueError:
        log.debug(
            "CPAL metrics already registered (test re-import); tick "
            "instrumentation will be a no-op in this interpreter."
        )
except ImportError:
    pass


from shared.public_speech_index import (
    PublicSpeechEventRecord,
    append_public_speech_event,
    compute_utterance_hash,
)


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
        daemon: object | None = None,
        music_policy: object | None = None,
    ) -> None:
        # Streams
        self._perception = PerceptionStream(buffer=buffer)
        self._formulation = FormulationStream(stt=stt, salience_router=salience_router)
        self._production = ProductionStream(
            audio_output=audio_output,
            on_speaking_changed=lambda speaking: buffer.set_speaking(speaking),
        )

        # Control components
        self._evaluator = CpalEvaluator(
            perception=self._perception,
            formulation=self._formulation,
            production=self._production,
        )
        self._grounding = GroundingBridge(ledger=grounding_ledger)
        # Phase 6: programme-aware should_surface threshold via the
        # default_provider that reads the canonical programme store.
        # Operator speech evidence: buffer state provider lets the
        # adapter incorporate speech_active/in_cooldown as downward
        # evidence on the surfacing posterior.
        from agents.hapax_daimonion.cpal.impingement_adapter import (
            BufferSpeechState,
            DialogState,
        )

        def _buffer_state_provider() -> BufferSpeechState:
            return BufferSpeechState(
                speech_active=getattr(buffer, "_speech_active", False),
                in_cooldown=getattr(buffer, "in_cooldown", False),
            )

        def _dialog_state_provider() -> DialogState:
            """Evidence of recent conversational response activity."""
            now = time.monotonic()
            for evt in reversed(self._recent_speech_events):
                if evt.kind == SpeechEventKind.RESPONSE:
                    elapsed = now - evt.timestamp
                    return DialogState(
                        seconds_since_last_response=elapsed,
                        dialog_active=elapsed < _DIALOG_ACTIVE_WINDOW_S,
                    )
            return DialogState(
                seconds_since_last_response=float("inf"),
                dialog_active=False,
            )

        self._impingement_adapter = ImpingementAdapter(
            programme_provider=default_provider,
            buffer_state_provider=_buffer_state_provider,
            dialog_state_provider=_dialog_state_provider,
        )
        self._tier_composer = TierComposer()
        self._signal_cache = SignalCache()
        # HOMAGE Phase 7 — voice register bridge. Single instance per runner
        # so the 250ms read-cache is shared across every TTS emission path.
        self._register_bridge = VoiceRegisterBridge()

        # External components
        self._buffer = buffer
        self._stt = stt
        self._tts_manager = tts_manager
        self._audio_output = audio_output
        self._echo_canceller = echo_canceller
        self._pipeline = conversation_pipeline  # T3 delegate
        self._daemon = daemon

        # GEAL Phase 2 Task 2.1 — TTS envelope publisher. Taps the TTS
        # PCM stream so GEAL can drive V1 Chladni ignition / V2 halo
        # radius / future voicing-gated primitives with ≤ 50 ms lag.
        # Defaults ON; disable with ``HAPAX_TTS_ENVELOPE_PUBLISH=0``.
        #
        # The publisher is created here unconditionally (so the SHM
        # file exists and consumers can read 0s during silence) but the
        # audio_output wrap is deferred until ``attach_audio_output()``
        # because daemon._audio_output is None at construction time —
        # ``pipeline_start.py`` patches it on later. attach_audio_output
        # MUST be called once the real audio_output is available.
        self._tts_envelope_publisher: object | None = None
        self._envelope_wrap_done = False
        try:
            from agents.hapax_daimonion.tts_envelope_publisher import (
                TtsEnvelopePublisher,
                envelope_publish_enabled,
            )

            if envelope_publish_enabled():
                self._tts_envelope_publisher = TtsEnvelopePublisher()
                if audio_output is not None:
                    self._wrap_audio_output_for_envelope_tap()
                    log.info(
                        "TTS envelope publisher enabled at construction "
                        "(SHM ring at 100 Hz, wrapped at construction)"
                    )
                else:
                    log.info(
                        "TTS envelope publisher enabled (SHM ring at 100 Hz, "
                        "wrap deferred until attach_audio_output)"
                    )
        except Exception:
            # Never block CpalRunner construction on the publisher —
            # voice must always come up; envelope is a visual side-channel.
            log.debug("TTS envelope publisher init failed", exc_info=True)

        # D-18 (proof-of-wiring): music policy evaluator. Default is
        # NullMusicDetector → always returns detected=False → no behavior
        # change. Operator swaps in a real detector when one exists; the
        # wire (this attribute + the per-tick evaluate() call) is what was
        # missing per AUDIT §7.1. The Prometheus counter
        # `hapax_demonet_music_policy_mutes_total` (D-23) lights up when
        # decisions cross the mute threshold.
        if music_policy is None:
            from shared.governance.music_policy import default_policy

            music_policy = default_policy()
        self._music_policy = music_policy
        self._music_mute_active = False  # tracks transition for logging

        # State
        self._running = False
        self._tick_count = 0
        self._last_tick_at = 0.0
        self._accumulated_silence_s = 0.0
        self._processing_utterance = False
        self._last_stimmung_check = 0.0
        self._queued_utterance: bytes | None = None
        self._last_speech_end: float = 0.0  # monotonic timestamp of last system speech end
        # Shared speech event ring: minimum viable aperture unification.
        # All speech paths (response, narration, exploration) append here
        # so cross-path evidence is available. Replaces the split-hemisphere
        # where conversational and narration paths had no awareness of each other.
        self._recent_speech_events: deque[SpeechEvent] = deque(maxlen=_SPEECH_EVENT_RING_MAXLEN)
        # Speech mutex: prevents autonomous narration bypass and exploration
        # surfacing from producing concurrent audio streams. Both paths
        # acquire this lock before TTS synthesis. This is infrastructure
        # serialization, not an expert rule — it doesn't decide whether
        # to speak, only prevents physical audio overlap.
        self._speech_lock = asyncio.Lock()
        # Queue #225: flipped to True by process_impingement(); reset each tick.
        # Drives the "impingement" label on hapax_cpal_ticks_by_type_total.
        self._impingement_since_last_tick: bool = False

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

    @property
    def current_register(self) -> VoiceRegister:
        """Active voice register published by the HOMAGE choreographer.

        Read-only view for external consumers (tests, the conversation
        pipeline's spontaneous-speech framing). Falls back to the default
        register when no HOMAGE package has published, or the file is
        stale — see ``VoiceRegisterBridge`` for the fail-open contract.
        """
        return self._register_bridge.current_register()

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
        if _COLD_START_EVENTS is not None:
            _COLD_START_EVENTS.inc()

        try:
            while self._running:
                tick_start = time.monotonic()
                dt = tick_start - self._last_tick_at
                self._last_tick_at = tick_start

                await self._tick(dt)
                self._tick_count += 1

                tick_duration_s = time.monotonic() - tick_start
                if _TICK_DURATION_MS is not None:
                    _TICK_DURATION_MS.observe(tick_duration_s * 1000.0)
                if _TICKS_TOTAL is not None:
                    _TICKS_TOTAL.inc()
                if _TICKS_BY_TYPE is not None:
                    _TICKS_BY_TYPE.labels(type=self._classify_tick()).inc()
                self._impingement_since_last_tick = False

                # Publish state every 10 ticks (~1.5s)
                if self._tick_count % 10 == 0:
                    self._publish_state()
                    self._check_stimmung()

                # Sleep for remainder of tick interval. tick_duration_s already
                # covers the time from tick_start through the end-of-tick
                # instrumentation, so reuse it as the elapsed time here.
                sleep_time = max(0, TICK_INTERVAL_S - tick_duration_s)
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            log.info("CPAL runner cancelled")
        except Exception:
            log.exception("CPAL runner error")
        finally:
            self._running = False
            log.info("CPAL runner stopped after %d ticks", self._tick_count)

    def _classify_tick(self) -> str:
        """Queue #225 label value for hapax_cpal_ticks_by_type_total.

        Priority: impingement > utterance > producing > idle. An impingement
        arriving mid-tick dominates classification because it's the most
        information-dense signal the loop handles; utterance processing and
        speech production are already-scheduled work.
        """
        if self._impingement_since_last_tick:
            return "impingement"
        if self._processing_utterance:
            return "utterance"
        if self._production.is_producing:
            return "producing"
        return "idle"

    def stop(self) -> None:
        """Signal the runner to stop."""
        self._running = False

    def _evaluate_music_policy(self, frame: object) -> None:
        """D-18 wire: call music_policy.evaluate() per tick + log transitions.

        Behavior intentionally narrow for the proof-of-wiring ship:
          - Always call evaluate() so the gate is exercised on every tick
          - Log the BLOCKED↔ALLOWED transition (mute boundary) for journalctl
            visibility; the per-decision Prometheus counter is incremented
            inside MusicPolicy.evaluate() itself (D-23).
          - Do NOT mute production yet — D-18b is the production-mute
            integration that activates when a real (non-Null) detector is
            wired. Decoupling the wire from the mute action means swapping
            in a detector with false-positives won't suddenly drop legitimate
            Hapax speech.
          - Failure inside evaluate() is fail-CLOSED to should_mute=True
            (D-23); we log the transition same as a real detection.
        """
        try:
            decision = self._music_policy.evaluate(frame)
        except Exception:
            log.warning("music_policy.evaluate raised — gate skipped this tick", exc_info=True)
            return
        if decision.should_mute and not self._music_mute_active:
            log.info("music policy → MUTE: %s", decision.reason)
            self._music_mute_active = True
        elif not decision.should_mute and self._music_mute_active:
            log.info("music policy → ALLOWED: %s", decision.reason)
            self._music_mute_active = False

    async def _tick(self, dt: float) -> None:
        """Run one cognitive tick."""
        # 1. Update perception from buffer state
        frame = self._get_audio_frame()
        vad_prob = self._get_vad_prob()
        self._perception.update(frame, vad_prob=vad_prob)
        signals = self._perception.signals

        # 1b. D-18: music policy evaluation. With the default
        # NullMusicDetector, decision.should_mute is always False — wire is
        # established without behavior change. Behavior activates when the
        # operator swaps in a real detector. Failures inside evaluate() are
        # already logged + Prometheus-counted there (D-23 fail-closed
        # detector wrap); we just log the transition to make state visible
        # in journalctl. Production-mute integration is D-18b (deferred).
        self._evaluate_music_policy(frame)

        # 2. Track accumulated silence (C: I1)
        if signals.speech_active or self._processing_utterance:
            self._accumulated_silence_s = 0.0
        else:
            self._accumulated_silence_s += dt

        # 2b. Session timeout check — close session if silence exceeds timeout
        if self._daemon is not None:
            d = self._daemon
            if (
                d.session.is_active
                and d.session.is_timed_out
                and not self._processing_utterance
                and not self._production.is_producing
            ):
                from functools import partial

                from agents.hapax_daimonion.persona import session_end_message
                from agents.hapax_daimonion.pw_audio_output import play_pcm
                from agents.hapax_daimonion.session_events import close_session

                msg = session_end_message(d.notifications.pending_count)
                log.info("CPAL session timeout: %s", msg)
                if d._conversation_pipeline and d._conversation_pipeline._audio_output:
                    try:
                        decision = self._resolve_direct_pcm_decision(
                            source="cpal_session_timeout_goodbye",
                            text=msg,
                        )
                        if decision is None:
                            await close_session(d, reason="silence_timeout")
                            return
                        loop = asyncio.get_running_loop()
                        pcm = await loop.run_in_executor(
                            None, d.tts.synthesize, msg, "notification"
                        )
                        if pcm:
                            playback_result = await loop.run_in_executor(
                                None,
                                partial(
                                    play_pcm,
                                    pcm,
                                    24000,
                                    1,
                                    decision.target,
                                    decision.media_role,
                                ),
                            )
                            witness = record_playback_result(
                                text=msg,
                                playback_result=playback_result,
                                destination=decision.destination.value,
                                target=decision.target,
                                media_role=decision.media_role,
                            )
                            if decision.destination.value == "livestream":
                                scope = (
                                    "public_broadcast" if playback_result.completed else "failed"
                                )
                                record = PublicSpeechEventRecord(
                                    speech_event_id=f"se-{time.time_ns()}",
                                    impulse_id=None,
                                    triad_ids=[],
                                    utterance_hash=compute_utterance_hash(msg),
                                    route_decision=witness.last_destination_decision or {},
                                    tts_result=witness.last_tts_synthesis,
                                    playback_result=witness.last_playback,
                                    audio_safety_refs=[],
                                    egress_refs=[],
                                    wcs_snapshot_refs=[],
                                    chronicle_refs=[],
                                    temporal_span_refs=[],
                                    scope=scope,
                                    created_at=witness.updated_at,
                                )
                                append_public_speech_event(record)
                    except Exception:
                        log.debug("Goodbye TTS failed", exc_info=True)
                await close_session(d, reason="silence_timeout")

        # 3. Gain drivers beyond just speech (C: I5, I6)
        self._apply_gain_drivers(signals, dt)

        # 4. Check for utterances — dispatch T3 via pipeline
        # Discard utterances during own speech (echo from speakers)
        if self._production.is_producing or self._buffer.is_speaking:
            _ = self._perception.get_utterance()  # drain without processing
            self._queued_utterance = None
        else:
            utterance = self._queued_utterance or self._perception.get_utterance()
            self._queued_utterance = None
            if utterance is not None and self._processing_utterance:
                log.info("CPAL: utterance arrived during processing — queued for next tick")
                self._queued_utterance = utterance
            elif utterance is not None:
                asyncio.create_task(self._process_utterance(utterance))

        # 4b. Mark session activity during production/processing
        if self._daemon is not None and self._daemon.session.is_active:
            if self._processing_utterance or self._production.is_producing or signals.speech_active:
                self._daemon.session.mark_activity()

        # 5. Speculative formulation during operator speech
        # Guard: no speculation during our own speech or utterance processing
        if (
            signals.speech_active
            and not signals.is_speaking
            and not self._processing_utterance
            and not self._production.is_producing
            and hasattr(self._buffer, "speech_frames_snapshot")
        ):
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

        # 12. Publish simplified perception behaviors
        if self._daemon is not None and hasattr(self._daemon, "perception"):
            _now = time.monotonic()
            _behaviors = self._daemon.perception.behaviors
            if "turn_phase" in _behaviors:
                _phase = "hapax_speaking" if self._production.is_producing else "mutual_silence"
                _behaviors["turn_phase"].update(_phase, _now)
            if "cognitive_readiness" in _behaviors:
                _readiness = 1.0 if not self._processing_utterance else 0.0
                _behaviors["cognitive_readiness"].update(_readiness, _now)

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

        # Always apply speech driver + decay (low cost, latency-sensitive)
        # but throttle filesystem reads (presence, stimmung) to every 10 ticks (~1.5s)
        if signals.speech_active and signals.vad_confidence > 0.3:
            gc.apply(GainUpdate(delta=0.05, source="operator_speech"))
        else:
            gc.decay(dt)

        # Driver: presence from perception engine (throttled — filesystem read)
        self._gain_driver_tick = getattr(self, "_gain_driver_tick", 0) + 1
        if self._gain_driver_tick % 10 != 0:
            return
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
        system_speech_observed = False

        try:
            # T0: Visual acknowledgment (instant)
            self._production.produce_t0(
                signal_type="attentional_shift",
                intensity=self._evaluator.gain_controller.gain,
            )

            # T1: Acknowledgment (if cache ready, gain high enough, and outside echo window)
            # Cooldown prevents T1 from firing on echo of system's own speech.
            # Without this, T1 plays "mm-hmm" on echo → echo of "mm-hmm" → T1 again → loop.
            _echo_cooldown_s = 2.0
            _since_last_speech = time.monotonic() - self._last_speech_end
            region = ConversationalRegion.from_gain(self._evaluator.gain_controller.gain)
            if (
                region.value >= ConversationalRegion.ATTENTIVE.value
                and _since_last_speech > _echo_cooldown_s
            ):
                ack = self._signal_cache.select("acknowledgment")
                if ack is not None:
                    _, pcm = ack
                    system_speech_observed = (
                        await self._play_guarded_t1_pcm(
                            pcm,
                            source="cpal_t1_acknowledgement",
                            text="acknowledgment",
                        )
                        or system_speech_observed
                    )

            # T3: Full formulation via pipeline
            if self._pipeline is not None:
                # Impingement-native: if the pipeline was stopped (e.g., by
                # silence timeout closing the session), restart it. The
                # utterance IS the impingement that recruits the pipeline.
                if not self._pipeline._running:
                    await self._pipeline.start()
                # Acquire speech lock: prevents autonomous narration and
                # exploration surfacing from producing audio during a
                # multi-sentence conversational response.
                async with self._speech_lock:
                    await self._pipeline.process_utterance(utterance)
                    system_speech_observed = True

                # Record grounding outcome based on pipeline result (C: C1)
                self._evaluator.gain_controller.record_grounding_outcome(success=True)

                # Gain driver: closed-loop confirmation
                self._evaluator.gain_controller.apply(
                    GainUpdate(delta=0.05, source="response_delivered")
                )

                # Notify engagement classifier that system spoke (follow-up window)
                if self._daemon is not None and hasattr(self._daemon, "_engagement"):
                    self._daemon._engagement.notify_system_spoke()
            else:
                log.warning("CPAL: no pipeline for T3 — utterance dropped")

        except Exception:
            log.exception("CPAL: utterance processing failed")
            self._evaluator.gain_controller.record_grounding_outcome(success=False)
        finally:
            if system_speech_observed:
                self._last_speech_end = time.monotonic()
                self._recent_speech_events.append(
                    SpeechEvent(
                        kind=SpeechEventKind.RESPONSE,
                        timestamp=self._last_speech_end,
                        source_path="pipeline._process_utterance_inner",
                    )
                )
            self._processing_utterance = False
            self._production.mark_t3_end()
            self._formulation.reset()

    def attach_audio_output(self, audio_output: object) -> None:
        """Late-bind audio_output and wire the envelope tap.

        ``run_inner.py`` constructs CpalRunner before the conversation
        pipeline (and thus the audio_output) exists; ``pipeline_start.py``
        then patches ``self._audio_output`` directly. Call this method
        instead so the envelope publisher can wrap the write path. Idempotent.
        """
        self._audio_output = audio_output
        if (
            self._tts_envelope_publisher is not None
            and audio_output is not None
            and not self._envelope_wrap_done
        ):
            self._wrap_audio_output_for_envelope_tap()
            log.info("TTS envelope publisher tap wired into audio_output (deferred)")

    def _wrap_audio_output_for_envelope_tap(self) -> None:
        """Decorate ``self._audio_output.write`` to tee PCM to the envelope publisher.

        The underlying ``write`` method is preserved; the wrapper calls
        it first (so latency-sensitive playback wins) and then feeds
        PCM to the publisher. Analysis failures never propagate to the
        playback path — they're logged at debug level and dropped so
        a broken mmap never impacts voice.
        """
        if self._audio_output is None or self._tts_envelope_publisher is None:
            return
        original_write = self._audio_output.write
        publisher = self._tts_envelope_publisher

        def _wrapped_write(pcm, *args, **kwargs):
            try:
                original_write(pcm, *args, **kwargs)
            finally:
                try:
                    publisher.feed(pcm)  # type: ignore[attr-defined]
                except Exception:
                    log.debug("TTS envelope feed failed", exc_info=True)

        self._audio_output.write = _wrapped_write  # type: ignore[assignment]
        self._envelope_wrap_done = True

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

    def _resolve_direct_pcm_decision(
        self,
        *,
        source: str,
        text: str,
        impulse_id: str | None = None,
    ):
        """Resolve direct PCM playback through the private-or-drop hard stop."""

        decision = resolve_playback_decision(None)
        destination = decision.destination
        destination_target = decision.target
        destination_role = decision.media_role
        record_destination_decision(
            source=source,
            destination=destination.value,
            route_accepted=decision.allowed,
            reason=decision.reason_code,
            safety_gate=decision.safety_gate,
            target=destination_target,
            media_role=destination_role,
            text=text,
            impulse_id=impulse_id,
            terminal_state="pending" if decision.allowed else "inhibited",
        )
        if not decision.allowed:
            record_drop(
                reason=decision.reason_code,
                source=source,
                destination=destination.value,
                target=destination_target,
                media_role=destination_role,
                text=text,
                impulse_id=impulse_id,
                terminal_state="inhibited",
            )
            return None
        if destination_target is None or destination_role is None:
            record_drop(
                reason="semantic_route_incomplete",
                source=source,
                destination=destination.value,
                target=destination_target,
                media_role=destination_role,
                text=text,
                impulse_id=impulse_id,
                terminal_state="inhibited",
            )
            return None
        return decision

    async def _play_guarded_t1_pcm(self, pcm: bytes, *, source: str, text: str) -> bool:
        """Play a presynthesized T1 clip only after route witness accepts it."""

        if self._audio_output is None:
            return False
        decision = self._resolve_direct_pcm_decision(source=source, text=text)
        if decision is None:
            return False
        from functools import partial

        self._buffer.set_speaking(True)
        try:
            if self._echo_canceller:
                self._echo_canceller.feed_reference(pcm)
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(
                    None,
                    partial(
                        self._audio_output.write,
                        pcm,
                        target=decision.target,
                        media_role=decision.media_role,
                    ),
                )
            except TypeError:
                record_drop(
                    reason="audio_output_route_kwargs_unsupported",
                    source=source,
                    destination=decision.destination.value,
                    target=decision.target,
                    media_role=decision.media_role,
                    text=text,
                    terminal_state="inhibited",
                )
                return False
        finally:
            self._buffer.set_speaking(False)
        return True

    async def process_impingement(self, impingement: object) -> None:
        """Process an impingement through the CPAL control loop.

        Replaces the old speech recruitment pathway. Impingements
        modulate gain and, if they should surface, trigger T3 via
        the pipeline's spontaneous speech path.
        """
        self._impingement_since_last_tick = True
        effect = self._impingement_adapter.adapt(impingement)

        if effect.gain_update is not None:
            self._evaluator.gain_controller.apply(effect.gain_update)

        # AUTONOMOUS-NARRATIVE BYPASS — fires regardless of effect.should_surface
        # because the autonomous narrative composer's emissions are designed to
        # request speech even when strength=0.6 doesn't trip the per-programme
        # surface threshold. The route still fails closed below unless the
        # broadcast authorization and audio safety gates pass.
        # Decouples autonomous narration from operator-private conversation
        # pipeline state without granting broadcast by default. The autonomous
        # narrative composer produces speech-ready first-person text; we
        # synthesize and play it directly via daemon.tts + play_pcm only after
        # the resolved destination decision accepts the route.
        source = getattr(impingement, "source", "")
        if source == "autonomous_narrative" and self._daemon is not None:
            # The dedicated prepared_playback_loop owns TTS only for explicit
            # legacy verbatim playback. Live-prior prepared scripts are source
            # context for composition and must not suppress autonomous narration.
            try:
                from shared.programme_store import default_store as _ds

                _ap = _ds().active_programme()
                if _prepared_playback_loop_owns_tts(_ap):
                    log.debug(
                        "Autonomous narrative skipped: prepared_playback_loop owns legacy TTS"
                    )
                    return
            except Exception:
                pass  # fail-open: let it through if store is unavailable
            tts = getattr(self._daemon, "tts", None)
            content = getattr(impingement, "content", {})
            narrative = content.get("narrative") if isinstance(content, dict) else None
            impulse_id = content.get("impulse_id") if isinstance(content, dict) else None
            impulse_id = str(impulse_id) if impulse_id else None
            narrative = narrative or effect.narrative

            # Resolve the destination explicitly before synthesis/playback.
            # Autonomous narration only reaches broadcast when the public gates
            # pass and the impingement already carries bridge-produced public
            # metadata. CPAL's broadcast bias is a candidate trigger only; this
            # runner must not mint broadcast intent or programme authorization.
            register = self._register_bridge.current_register()
            decision = resolve_playback_decision(impingement, voice_register=register)
            destination = decision.destination
            destination_target = decision.target
            destination_role = decision.media_role
            record_destination_decision(
                source=source,
                destination=destination.value,
                route_accepted=decision.allowed,
                reason=decision.reason_code,
                safety_gate=decision.safety_gate,
                target=destination_target,
                media_role=destination_role,
                text=narrative or "",
                impulse_id=impulse_id,
                terminal_state="pending" if decision.allowed else "inhibited",
            )

            if not decision.allowed:
                record_drop(
                    reason=decision.reason_code,
                    source=source,
                    destination=destination.value,
                    target=destination_target,
                    media_role=destination_role,
                    text=narrative or "",
                    impulse_id=impulse_id,
                    terminal_state="inhibited",
                )
            elif tts is None:
                record_drop(
                    reason="tts_manager_missing",
                    source=source,
                    destination=destination.value,
                    target=destination_target,
                    media_role=destination_role,
                    text=narrative or "",
                    impulse_id=impulse_id,
                )
            elif not narrative:
                record_drop(
                    reason="autonomous_narrative_text_missing",
                    source=source,
                    destination=destination.value,
                    target=destination_target,
                    media_role=destination_role,
                    impulse_id=impulse_id,
                )
            else:
                from functools import partial

                from agents.hapax_daimonion.pw_audio_output import play_pcm

                try:
                    if self._speech_lock.locked():
                        log.debug("Autonomous narrative deferred: speech lock held")
                        return
                    if self._processing_utterance:
                        log.debug("Autonomous narrative deferred: conversational response active")
                        return
                    async with self._speech_lock:
                        loop = asyncio.get_running_loop()
                        pcm = await loop.run_in_executor(
                            None, tts.synthesize, narrative, "proactive"
                        )
                        if not pcm:
                            record_tts_synthesis(
                                status="empty",
                                text=narrative,
                                pcm=b"",
                                impulse_id=impulse_id,
                            )
                            record_drop(
                                reason="tts_empty_pcm",
                                source=source,
                                destination=destination.value,
                                target=destination_target,
                                media_role=destination_role,
                                text=narrative,
                                impulse_id=impulse_id,
                            )
                        else:
                            record_tts_synthesis(
                                status="completed",
                                text=narrative,
                                pcm=pcm,
                                impulse_id=impulse_id,
                            )
                            # Speaking gate: suppress VAD during playback
                            # to prevent the Yeti mic from capturing our
                            # own TTS output as an "operator utterance."
                            # Also register the narrative text with the
                            # pipeline's echo history so _is_echo() can
                            # reject mic-captured echoes of this TTS.
                            if self._pipeline and hasattr(self._pipeline, "_recent_tts_texts"):
                                self._pipeline._recent_tts_texts.append(
                                    (
                                        time.monotonic(),
                                        narrative.lower().strip().rstrip(".,!?"),
                                    )
                                )
                            self._buffer.set_speaking(True)
                            if self._echo_canceller:
                                self._echo_canceller.feed_reference(pcm)
                            try:
                                playback_result = await loop.run_in_executor(
                                    None,
                                    partial(
                                        play_pcm,
                                        pcm,
                                        24000,
                                        1,
                                        destination_target,
                                        destination_role,
                                    ),
                                )
                            finally:
                                # Hold the speaking gate for a few seconds
                                # past playback end to cover residual room
                                # echo. Without this holdover, the Yeti mic
                                # captures the echo tail as "operator speech"
                                # and the pipeline processes it as a response.
                                await asyncio.sleep(3.0)
                                self._buffer.set_speaking(False)
                            witness = record_playback_result(
                                text=narrative,
                                playback_result=playback_result,
                                destination=destination.value,
                                target=destination_target,
                                media_role=destination_role,
                                impulse_id=impulse_id,
                            )
                            if destination.value == "livestream":
                                scope = (
                                    "public_broadcast" if playback_result.completed else "failed"
                                )
                                record = PublicSpeechEventRecord(
                                    speech_event_id=f"se-{time.time_ns()}",
                                    impulse_id=impulse_id,
                                    triad_ids=[],
                                    utterance_hash=compute_utterance_hash(narrative),
                                    route_decision=witness.last_destination_decision or {},
                                    tts_result=witness.last_tts_synthesis,
                                    playback_result=witness.last_playback,
                                    audio_safety_refs=[],
                                    egress_refs=[],
                                    wcs_snapshot_refs=[],
                                    chronicle_refs=[],
                                    temporal_span_refs=[],
                                    scope=scope,
                                    created_at=witness.updated_at,
                                )
                                append_public_speech_event(record)
                            if playback_result.completed:
                                self._last_speech_end = time.monotonic()
                                self._recent_speech_events.append(
                                    SpeechEvent(
                                        kind=SpeechEventKind.NARRATION,
                                        timestamp=self._last_speech_end,
                                        source_path="autonomous_narrative",
                                        text_preview=narrative[:40],
                                    )
                                )
                                log.info(
                                    "Autonomous narrative spoken: %s",
                                    narrative[:60],
                                )
                            else:
                                log.warning(
                                    "Autonomous narrative playback failed: status=%s target=%s role=%s",
                                    playback_result.status,
                                    destination_target,
                                    destination_role,
                                )
                except Exception as exc:
                    record_tts_synthesis(
                        status="failed",
                        text=narrative,
                        error=str(exc),
                        impulse_id=impulse_id,
                    )
                    record_drop(
                        reason="autonomous_narrative_tts_or_playback_exception",
                        source=source,
                        destination=destination.value,
                        target=destination_target,
                        media_role=destination_role,
                        text=narrative,
                        impulse_id=impulse_id,
                    )
                    log.warning(
                        "Autonomous narrative TTS failed",
                        exc_info=True,
                    )
            # Always return — autonomous narrative does not fall through to
            # the conversation pipeline path. If the bypass synthesis fails,
            # the impingement is dropped for this tick (next autonomous
            # narrative will retry; never bypasses the route gate).
            return

        if effect.should_surface:
            # Refractory inhibition for exploration surfacing.
            # Same mechanism as autonomous narration's 120s refractory
            # (run_loops_aux._NARRATION_REFRACTORY_S). After successful
            # spontaneous speech, suppress subsequent exploration
            # surfacing for a period. This is a temporal suppression
            # field per the conative-impingement spec, not a hard rule.
            _EXPLORATION_REFRACTORY_S = 60.0
            since_last_speech = time.monotonic() - self._last_speech_end
            if self._last_speech_end > 0.0 and since_last_speech < _EXPLORATION_REFRACTORY_S:
                log.debug(
                    "CPAL: exploration surfacing suppressed by refractory "
                    "(%.1fs since last speech, refractory=%.0fs)",
                    since_last_speech,
                    _EXPLORATION_REFRACTORY_S,
                )
                return
            log.info("CPAL: impingement surfacing: %s", effect.narrative[:60])
            # Classify destination BEFORE T0 so both signals (visual and
            # audio) follow the same routing decision, and so the counter
            # increments even when T3 ultimately fails. Classification
            # plus INFO log never touch narrative text — only source tag.
            register = self._register_bridge.current_register()
            decision = resolve_playback_decision(impingement, voice_register=register)
            destination = decision.destination
            destination_target = decision.target
            destination_role = decision.media_role
            record_destination_decision(
                source=source,
                destination=destination.value,
                route_accepted=decision.allowed,
                reason=decision.reason_code,
                safety_gate=decision.safety_gate,
                target=destination_target,
                media_role=destination_role,
                text=effect.narrative,
                terminal_state="pending" if decision.allowed else "inhibited",
            )

            if not decision.allowed:
                record_drop(
                    reason=decision.reason_code,
                    source=source,
                    destination=destination.value,
                    target=destination_target,
                    media_role=destination_role,
                    text=effect.narrative,
                    terminal_state="inhibited",
                )
                return

            # T0 visual signal
            self._production.produce_t0(
                signal_type="impingement_alert",
                intensity=min(1.0, effect.error_boost + 0.5),
            )

            # T3 via pipeline spontaneous speech (if available)
            if self._pipeline is not None and hasattr(
                self._pipeline, "generate_spontaneous_speech"
            ):
                # HOMAGE Phase 7: pass the active register's framing
                # directive to the pipeline so the LLM tunes tonality
                # before synthesis. Only TEXTMODE carries a non-trivial
                # hint today (spec §4.8 — ANNOUNCING and CONVERSING are
                # handled by the persona's baseline prompt).
                register_hint: str | None = (
                    textmode_prompt_prefix() if register == VoiceRegister.TEXTMODE else None
                )
                if self._speech_lock.locked():
                    log.debug("CPAL: exploration surfacing deferred: speech lock held")
                    record_drop(
                        reason="speech_lock_held",
                        source=source,
                        destination=destination.value,
                        target=destination_target,
                        media_role=destination_role,
                        text=effect.narrative,
                        terminal_state="failed",
                    )
                    return
                if self._processing_utterance:
                    log.debug(
                        "CPAL: exploration surfacing deferred: conversational response active"
                    )
                    record_drop(
                        reason="conversation_active",
                        source=source,
                        destination=destination.value,
                        target=destination_target,
                        media_role=destination_role,
                        text=effect.narrative,
                        terminal_state="failed",
                    )
                    return
                async with self._speech_lock:
                    # Set speaking gate for the ENTIRE duration — LLM +
                    # TTS + playback + holdover. The pipeline's _speak_sentence
                    # only gates per-sentence; between sentences the gate drops
                    # and the buffer captures inter-sentence audio as "operator."
                    self._buffer.set_speaking(True)
                    try:
                        await self._pipeline.generate_spontaneous_speech(
                            impingement,
                            register_hint=register_hint,
                            destination_target=destination_target,
                            destination_role=destination_role,
                            destination=destination.value,
                        )
                    except TypeError:
                        # Older pipelines without one of the new kwargs — fall
                        # back through progressively so the impingement is
                        # never dropped when the signature shifts.
                        log.debug(
                            "generate_spontaneous_speech rejected kwarg; "
                            "retrying with narrower signature",
                            exc_info=True,
                        )
                        try:
                            await self._pipeline.generate_spontaneous_speech(
                                impingement,
                                register_hint=register_hint,
                                destination_target=destination_target,
                            )
                        except TypeError:
                            try:
                                await self._pipeline.generate_spontaneous_speech(
                                    impingement,
                                    register_hint=register_hint,
                                )
                            except TypeError:
                                try:
                                    await self._pipeline.generate_spontaneous_speech(impingement)
                                except Exception:
                                    log.debug("Spontaneous speech failed", exc_info=True)
                            except Exception:
                                log.debug("Spontaneous speech failed", exc_info=True)
                        except Exception:
                            log.debug("Spontaneous speech failed", exc_info=True)
                    except Exception:
                        log.debug("Spontaneous speech failed", exc_info=True)
                    finally:
                        # Hold the speaking gate past playback end to cover
                        # room echo tail, same as autonomous narrative path.
                        await asyncio.sleep(3.0)
                        self._buffer.set_speaking(False)
                        self._last_speech_end = time.monotonic()
                        self._recent_speech_events.append(
                            SpeechEvent(
                                kind=SpeechEventKind.EXPLORATION,
                                timestamp=self._last_speech_end,
                                source_path="exploration_surfacing",
                                text_preview=effect.narrative[:40],
                            )
                        )
            else:
                record_drop(
                    reason="pipeline_unavailable",
                    source=source,
                    destination=destination.value,
                    target=destination_target,
                    media_role=destination_role,
                    text=effect.narrative,
                )
