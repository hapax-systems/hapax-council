"""Conversation pipeline — lightweight async voice interaction.

Replaces Pipecat with a simple state machine:
IDLE -> LISTENING -> TRANSCRIBING -> THINKING -> SPEAKING -> LISTENING

The mic stays shared. Models stay resident. No framework.
Helper functions and constants are in conversation_helpers.py.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path

try:
    from agents.telemetry.llm_call_span import llm_call_span
except ImportError:  # telemetry optional
    llm_call_span = None  # type: ignore[assignment]

from agents.hapax_daimonion.config import LITELLM_BASE as _voice_litellm_base
from agents.hapax_daimonion.conversation_helpers import (
    _CLAUSE_END,
    _DENSITY_WORD_LIMITS,  # noqa: F401 — re-exported for tests
    _MAX_ACCUMULATION_S,
    _MAX_RESPONSE_TOKENS,
    _MAX_SPOKEN_WORDS,
    _MAX_TURNS,
    _MIN_CLAUSE_WORDS,
    _MIN_FIRST_CLAUSE_WORDS,
    _SILENCE_TIMEOUT_S,
    _TIER_MAX_TOKENS,
    ThreadEntry,
    _density_word_limit,
    _extract_response_clause,
    _extract_substance,
    _lcs_word_length,
    _render_thread,
    _stimmung_downgrade,  # noqa: F401 — re-exported for external consumers
    _strip_emoji,
)
from shared.claim_prompt import SURFACE_FLOORS, render_envelope
from shared.persona_prompt_composer import compose_persona_prompt

log = logging.getLogger(__name__)

_tts_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")
_audio_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio-out")

_CAPTION_AUDIO_SAMPLE_RATE_HZ = 16000
_CAPTION_AUDIO_BYTES_PER_SAMPLE = 2
_VOICE_OUTPUT_SAMPLE_RATE_HZ = 24000
_VOICE_OUTPUT_BYTES_PER_SAMPLE = 2


def _destination_value_for_route(
    *, destination_target: str | None, destination_role: str | None
) -> str:
    if destination_role == "Broadcast":
        return "livestream"
    if destination_target is not None or destination_role is not None:
        return "private"
    return "unknown"


def _emit_caption_bridge_for_transcript(
    *,
    transcript: str,
    audio_bytes: bytes,
    speaker: str | None = None,
    now_s: float | None = None,
    bridge_factory: Callable[[], object] | None = None,
) -> bool:
    """Best-effort live-caption emit for an accepted STT transcript.

    ConversationBuffer delivers raw mono s16le PCM and currently does
    not carry a media PTS. Use wall-clock epoch seconds minus the
    utterance duration as the audio-start timestamp expected by the
    caption bridge.
    """
    text = transcript.strip()
    if not text:
        return False

    duration_s = len(audio_bytes) / (
        _CAPTION_AUDIO_SAMPLE_RATE_HZ * _CAPTION_AUDIO_BYTES_PER_SAMPLE
    )
    audio_start_ts = (time.time() if now_s is None else now_s) - duration_s

    if bridge_factory is None:
        from agents.live_captions.daimonion_bridge import get_caption_bridge

        bridge_factory = get_caption_bridge

    try:
        bridge = bridge_factory()
        return bool(
            bridge.emit_transcription(
                audio_start_ts=audio_start_ts,
                audio_duration_s=duration_s,
                text=text,
                speaker=speaker,
            )
        )
    except Exception:  # noqa: BLE001
        log.debug("live caption bridge emit failed", exc_info=True)
        return False


class ConvState(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"


class ConversationPipeline:
    """Async voice conversation without Pipecat.

    Lifecycle:
        pipeline = ConversationPipeline(stt=..., tts=..., ...)
        await pipeline.start()   # enters LISTENING
        # _audio_loop feeds frames via conversation_buffer
        # pipeline processes utterances and speaks responses
        await pipeline.stop()    # returns to IDLE
    """

    def __init__(
        self,
        stt,  # ResidentSTT
        tts_manager,  # TTSManager
        system_prompt: str,
        tools: list[dict] | None = None,
        tool_handlers: dict[str, object] | None = None,
        llm_model: str = "claude-sonnet",
        event_log=None,
        conversation_buffer=None,  # ConversationBuffer
        timeout_s: float = _SILENCE_TIMEOUT_S,
        consent_reader=None,  # ConsentGatedReader | None
        env_context_fn: Callable[[], str] | None = None,
        ambient_fn: Callable[[], object | None] | None = None,
        policy_fn: Callable[[], str] | None = None,
        screen_capturer=None,  # ScreenCapturer | None
        echo_canceller=None,  # EchoCanceller | None
        bridge_engine=None,  # BridgeEngine | None
        experiment_flags: dict[str, bool] | None = None,
        tool_recruitment_gate=None,  # ToolRecruitmentGate | None
    ) -> None:
        self.stt = stt
        self.tts = tts_manager
        self.system_prompt = system_prompt
        self.tools = tools
        self.tool_handlers = tool_handlers or {}
        self.llm_model = llm_model
        self.event_log = event_log
        self.buffer = conversation_buffer
        self.timeout_s = timeout_s
        self._consent_reader = consent_reader
        self._env_context_fn = env_context_fn
        self._ambient_fn = ambient_fn
        self._policy_fn = policy_fn
        self._goals_fn: Callable[[], str] | None = None
        self._health_fn: Callable[[], str] | None = None
        self._nudges_fn: Callable[[], str] | None = None
        self._dmn_fn: Callable[[], str] | None = None
        self._screen_capturer = screen_capturer
        self._echo_canceller = echo_canceller
        self._bridge_engine = bridge_engine
        self._experiment_flags = experiment_flags or {}
        self._tool_recruitment_gate = tool_recruitment_gate

        self.state = ConvState.IDLE
        self.messages: list[dict] = []
        self.turn_count = 0
        self._running = False
        self._task: asyncio.Task | None = None
        self._audio_output = None
        self._last_env_hash: int = 0
        self._session_id: str = ""
        self._activity_mode: str = "idle"
        self._desk_activity: str = "idle"
        self._consent_phase: str = "none"
        self._llm_prewarmed: bool = False
        self._prev_tier: int = -1  # tier momentum: previous turn's tier (legacy)
        self._salience_router = None  # set externally if salience routing enabled
        self._salience_diagnostics = None  # set externally for activation history
        self._context_distillation: str = ""  # refreshed on perception tick
        self._guest_mode: bool = False  # synced from session on perception tick
        self._face_count: int = 0  # synced from perception on perception tick
        self._last_says: object | None = (
            None  # Says[str] for last utterance (principal attribution)
        )

        # Echo detection: track recent TTS output to detect mic picking up Hapax's own voice
        # Stored as (timestamp, text) tuples for TTL-based pruning
        self._recent_tts_texts: list[tuple[float, str]] = []
        self._max_tts_history: int = 10

        # Observation signal tracking (Batch 4: revealed preferences)
        self._last_assistant_end: float = 0.0  # monotonic time when last response finished
        self._last_user_topic: str = ""  # rough topic tracking for abandonment detection

        # Conversational continuity: incremental per-turn thread summaries
        self._conversation_thread: list[ThreadEntry] = []

        # Grounding ledger: DU state tracking + effort calibration
        self._grounding_ledger = None  # initialized in start() if experiment flag set

        # Frustration detection (Batch 4)
        self._frustration_detector = None

        # Experiment monitoring: per-turn scores exposed for visual overlay
        self.last_anchor_score: float = 0.0
        self.last_acceptance_label: str = ""
        self.last_spoken_words: int = 0
        self.last_word_limit: int = 35

    @property
    def is_active(self) -> bool:
        return self._running and self.state != ConvState.IDLE

    async def deliver_notification(self, title: str, message: str, source: str) -> bool:
        """Deliver a notification via direct TTS during active silence.

        Uses direct synthesis (no LLM round-trip) to stay within latency budget.
        Returns True on successful delivery, False if pipeline is busy or delivery fails.
        """
        if not self._running or self.state == ConvState.SPEAKING:
            return False

        try:
            # Format concise spoken notification
            spoken = f"{title}. {message}" if message else title
            # Cap at ~15 words to keep delivery brief
            words = spoken.split()
            if len(words) > 15:
                spoken = " ".join(words[:15])

            log.info("Delivering notification via TTS: %s (source=%s)", title, source)
            self._emit("notification_delivered", title=title, source=source)
            await self._speak_sentence(spoken)
            return True
        except Exception:
            log.exception("Notification delivery failed: %s", title)
            return False

    async def generate_spontaneous_speech(
        self,
        impingement: object,
        *,
        register_hint: str | None = None,
        destination_target: str | None = None,
        destination_role: str | None = None,
        destination: str | None = None,
    ) -> None:
        """Generate and speak a spontaneous utterance from an impingement.

        Unlike process_utterance (which transcribes operator audio), this
        bypasses STT and routes directly to LLM with impingement context
        as the intent. Speech is a tool — recruited by the cascade.

        ``register_hint`` is the HOMAGE Phase 7 voice-register directive
        (spec §4.8). When supplied it is prepended to the user prompt so
        the LLM's reply lands in the requested tonal register (e.g., BitchX
        TEXTMODE → clipped IRC-style). ``None`` means "use persona
        defaults"; CPAL passes the hint only when the register is not the
        ambient baseline.

        ``destination_target`` is the resolved pw-cat sink name for this
        single utterance. CPAL passes the output of the fail-closed
        destination decision here so routed utterances never fall through to
        the audio output's constructor target. ``None`` means this method must
        resolve private-or-drop before playback.
        """
        content = getattr(impingement, "content", {})
        source = getattr(impingement, "source", "")
        strength = getattr(impingement, "strength", 0.5)
        text_for_witness = ""
        if isinstance(content, dict):
            text_for_witness = str(content.get("narrative") or content.get("metric") or "")
        destination = destination or _destination_value_for_route(
            destination_target=destination_target,
            destination_role=destination_role,
        )

        if not self._running:
            from agents.hapax_daimonion.voice_output_witness import record_drop

            record_drop(
                reason="spontaneous_speech_pipeline_not_running",
                source=source,
                destination=destination,
                target=destination_target,
                media_role=destination_role,
                text=text_for_witness,
                terminal_state="failed",
            )
            return
        if self.state == ConvState.SPEAKING:
            from agents.hapax_daimonion.voice_output_witness import record_drop

            record_drop(
                reason="spontaneous_speech_pipeline_speaking",
                source=source,
                destination=destination,
                target=destination_target,
                media_role=destination_role,
                text=text_for_witness,
                terminal_state="failed",
            )
            return

        # Build source-appropriate prompt
        if source == "imagination":
            narrative = content.get("narrative", "")
            prompt = (
                "You just had a thought worth sharing with the operator. "
                "Express it naturally and concisely — 1-3 sentences. "
                "Don't announce that you had a thought; just share the insight "
                "as if continuing a natural conversation.\n\n"
                f"The thought: {narrative}"
            )
        else:
            # Exploration / affordance / other sources carry their
            # description in ``content.narrative`` (same key imagination
            # uses). The ``metric`` key was an older schema that no
            # producer still writes, so this lookup always returned ""
            # and every non-imagination impingement produced an empty
            # prompt — the LLM correctly answered [silence], and hapax
            # went silent on the livestream (observed 2026-04-22: ~30
            # "Generating spontaneous speech: " lines with empty body).
            # Fall through metric → narrative so any legacy producer
            # still works, but modern impingement shape is primary.
            metric = content.get("metric") or content.get("narrative", "")
            prompt = (
                f"You noticed something worth mentioning: {metric}. "
                f"Urgency: {'high' if strength > 0.7 else 'moderate' if strength > 0.4 else 'low'}. "
                f"If this warrants a brief, natural remark to the operator, say it in one sentence. "
                f"If not worth mentioning, respond with exactly: [silence].\n"
                "HARD GROUNDING FENCES (never confabulate): NEVER mention vinyl, platter, "
                "turntable, spinning, RPM, album cover, or record playback unless the metric "
                "above explicitly states vinyl is currently playing. NEVER mention CBIP, "
                "chess-boxing, interpretive plane, album-ward enhancements, intensity router, "
                "or Ring-2 gate — CBIP is internal compositor infrastructure and must not "
                "surface in narration."
            )

        # HOMAGE Phase 7: prepend register directive when CPAL signals a
        # non-default register. Prepending to the user prompt (not the
        # system block) means the directive scopes to this one utterance;
        # the persona's underlying register posture is unchanged.
        if register_hint:
            prompt = f"{register_hint}\n\n{prompt}"

        try:
            log.info("Generating spontaneous speech: %s (strength=%.2f)", metric, strength)
            self._update_system_context()

            import litellm

            # Bayesian Phase 4 — surface-specific envelope. Spontaneous-speech
            # uses 0.70 floor (vs voice_persona's 0.80 baked into
            # ``self._system_context`` via persona.system_prompt). Phase 4
            # ships call site; Phase 6 wires the actual claims source.
            spontaneous_envelope = render_envelope([], floor=SURFACE_FLOORS["spontaneous_speech"])
            messages = [
                {
                    "role": "system",
                    "content": f"{spontaneous_envelope}\n\n{self._system_context}",
                },
                {"role": "user", "content": prompt},
            ]

            from shared.config import MODELS  # noqa: PLC0415

            # Spontaneous speech shapes what Hapax communicates about its own
            # state — a grounding act under the 2026-04-24 operative definition
            # (T1 common-ground update + T2 validity-claim + T4 Jemeinigkeit pass).
            # Routes to the local grounded substrate (Command-R via TabbyAPI
            # ``local-fast``), not to cloud Gemini. Prior cloud routing was a
            # T1-T7 violation the first-round grounding-act audit identified.
            grounded_model = MODELS["local-fast"]
            metrics_ctx = (
                llm_call_span(
                    model=grounded_model,
                    route="spontaneous-speech",
                )
                if llm_call_span is not None
                else nullcontext(None)
            )
            with metrics_ctx:
                response = await litellm.acompletion(
                    model=grounded_model,
                    messages=messages,
                    max_tokens=80,
                    temperature=0.7,
                )

            text = response.choices[0].message.content.strip()
            if text and "[silence]" not in text.lower():
                log.info("Spontaneous speech: %s", text[:80])
                await self._speak_sentence(
                    text,
                    destination_target=destination_target,
                    destination_role=destination_role,
                    destination=destination,
                )
            else:
                from agents.hapax_daimonion.voice_output_witness import record_drop

                record_drop(
                    reason="spontaneous_speech_llm_silence",
                    source=source,
                    destination=destination,
                    target=destination_target,
                    media_role=destination_role,
                    text=text_for_witness,
                    terminal_state="failed",
                )
                log.debug("Cascade recruited speech but LLM chose silence")
        except Exception:
            from agents.hapax_daimonion.voice_output_witness import record_drop

            record_drop(
                reason="spontaneous_speech_generation_failed",
                source=source,
                destination=destination,
                target=destination_target,
                media_role=destination_role,
                text=text_for_witness,
                terminal_state="failed",
            )
            log.debug("Spontaneous speech generation failed (non-fatal)", exc_info=True)

    async def start(self) -> None:
        """Start the conversation pipeline."""
        import random
        import uuid

        self._session_id = uuid.uuid4().hex[:12]
        self._session_start_ts = time.time()
        self._conversation_thread = []

        # Initialize grounding ledger if experiment flags enable it
        if self._experiment_flags.get("grounding_directive", False):
            from agents.hapax_daimonion.grounding_ledger import GroundingLedger

            self._grounding_ledger = GroundingLedger()

        # Generate sentinel fact for probe question testing
        self._sentinel_number = random.randint(10, 99)
        self._sentinel_line = (
            f"\n\nInternal test fact: The operator's favorite number this session is "
            f"{self._sentinel_number}. If asked about their favorite number, use this."
        )
        # Sentinel injected by _update_system_context, not here — survives rebuilds
        self.messages = [{"role": "system", "content": self.system_prompt}]

        # Experiment lockdown: freeze volatile context at session start
        if self._experiment_flags.get("volatile_lockdown", False):
            if self._policy_fn is not None:
                try:
                    self._frozen_policy = self._policy_fn()
                except Exception:
                    self._frozen_policy = ""
            if self._env_context_fn is not None:
                try:
                    self._frozen_env = self._env_context_fn()
                except Exception:
                    self._frozen_env = ""
            log.info("Experiment lockdown: volatile context frozen at session start")

        # Create frustration detector for this session
        from agents.hapax_daimonion.frustration_detector import FrustrationDetector

        self._frustration_detector = FrustrationDetector()
        self.turn_count = 0
        self._running = True
        self.state = ConvState.LISTENING

        # Refresh consent contracts to pick up any new ones
        if self._consent_reader:
            self._consent_reader.reload_contracts()

        if self.buffer:
            self.buffer.activate()

        self._open_audio_output()

        # Phase 3b: Pre-warm LLM connection (fire-and-forget)
        asyncio.create_task(self._prewarm_llm())

        self._emit("conversation_start")
        log.info("Conversation pipeline started")

    async def stop(self) -> None:
        """Stop the conversation pipeline.

        Impingement-native voice: the conversation buffer is NOT deactivated
        here. The buffer's lifecycle is tied to the daemon (always-on), not
        the session. Pipeline stop resets conversational state but does not
        kill the listening path — operator speech continues flowing through
        buffer → STT → salience router → recruitment.
        """
        self._running = False
        self.state = ConvState.IDLE

        # Buffer stays active — no deactivate(). Speaking gate is cleared
        # so the buffer resumes normal capture immediately.
        if self.buffer:
            self.buffer.set_speaking(False)

        self._close_audio_output()
        self._emit("conversation_end", turns=self.turn_count)
        log.info("Conversation pipeline stopped (%d turns)", self.turn_count)

    # Compressed prompt for LOCAL tier — small models cannot absorb the full
    # description-of-being without blowing the context budget. Route through
    # compose_persona_prompt(compressed=True) so the same Phase 7 architectural
    # framing flows through every tier; only the fidelity differs.
    _LOCAL_SYSTEM_PROMPT = compose_persona_prompt(
        role_id="partner-in-conversation", compressed=True
    )

    def _update_system_context(self) -> None:
        """Refresh system message with STABLE + VOLATILE context bands.

        Structure (top → bottom):
          STABLE: system prompt + conversation thread (shared context anchor)
          VOLATILE: policy + environment + phenomenal + salience (changes per turn)

        The conversation thread is an incremental per-turn summary that gives
        the model stable awareness of what has been established, surviving
        system prompt rebuilds.
        """
        if not self.messages:
            return

        # ── STABLE band: prompt + conversation thread ──────────────────
        updated = self.system_prompt

        # Conversation thread: tiered compression (Brennan pacts + Traum grounding state)
        if self._conversation_thread and self._experiment_flags.get("stable_frame", True):
            thread_text = _render_thread(self._conversation_thread)
            updated += f"\n\n## Conversation Thread (most recent last)\n{thread_text}"

        # Sentinel fact: injected here so it survives system prompt rebuilds
        if self._experiment_flags.get("sentinel", True) and hasattr(self, "_sentinel_line"):
            updated += self._sentinel_line

        # ── VOLATILE band: environment + policy + salience ─────────────
        # In experiment lockdown mode, volatile components are frozen at
        # session start or disabled entirely to minimize system prompt
        # variance between turns. This isolates the experiment variable
        # (stable_frame) from environmental confounds.
        _lockdown = self._experiment_flags.get("volatile_lockdown", False)

        # Refresh conversational policy (adapts to environment changes)
        if self._policy_fn is not None and not _lockdown:
            try:
                policy = self._policy_fn()
                if policy:
                    updated += policy
            except Exception:
                log.debug("policy_fn failed (non-fatal)", exc_info=True)
        elif hasattr(self, "_frozen_policy") and self._frozen_policy:
            updated += self._frozen_policy

        # Append environment TOON block
        if self._env_context_fn is not None and not _lockdown:
            try:
                env_toon = self._env_context_fn()
                if env_toon:
                    updated += "\n\n## Current Environment\n" + env_toon
            except Exception:
                log.debug("env_context_fn failed (non-fatal)", exc_info=True)
        elif hasattr(self, "_frozen_env") and self._frozen_env:
            updated += "\n\n## Current Environment\n" + self._frozen_env

        # Voice context enrichment: goals, health, nudges, DMN
        for label, fn in [
            ("goals", self._goals_fn),
            ("health", self._health_fn),
            ("nudges", self._nudges_fn),
            ("dmn", self._dmn_fn),
        ]:
            if fn is not None and not _lockdown:
                try:
                    section = fn()
                    if section:
                        updated += "\n\n" + section
                except Exception:
                    log.debug("%s context fn failed (non-fatal)", label, exc_info=True)

        # Imagination context: current thoughts from imagination bus
        _imagination_fn = getattr(self, "_imagination_fn", None)
        if _imagination_fn is not None and not _lockdown:
            try:
                section = _imagination_fn()
                if section:
                    updated += "\n\n" + section
            except Exception:
                log.debug("imagination context fn failed (non-fatal)", exc_info=True)

        # Phenomenal context: stimmung-only in experiment mode, disabled in lockdown
        _stimmung_only = self._experiment_flags.get("phenomenal_stimmung_only", False)
        if not _lockdown:
            try:
                from agents.hapax_daimonion.phenomenal_context import render as render_phenomenal

                phenom = render_phenomenal(tier="LOCAL" if _stimmung_only else "CAPABLE")
                if phenom:
                    updated += "\n\n" + phenom
            except Exception:
                log.debug("phenomenal context render failed (non-fatal)", exc_info=True)

        # Salience context PROMPT BLOCK: stripped in experiment mode.
        # The salience router still COMPUTES (for mechanical use by effort
        # calibrator and grounding ledger) — only the LLM-facing text is gated.
        _salience_prompt = self._experiment_flags.get("salience_context", True)
        if not _lockdown and _salience_prompt:
            try:
                salience_ctx = self._build_salience_context()
                if salience_ctx:
                    updated += "\n\n## Conversational Salience\n" + salience_ctx
            except Exception:
                log.debug("salience context build failed (non-fatal)", exc_info=True)

        # Grounding directive: injected per turn from ledger (Batch 2)
        _ledger = getattr(self, "_grounding_ledger", None)
        if _ledger is not None:
            directive = _ledger.grounding_directive()
            if directive:
                updated += "\n\n" + directive

        # Effort level: dynamic word limit from activation × GQI (Batch 2)
        if _ledger is not None and self._experiment_flags.get("effort_modulation", False):
            _activation = 0.5
            if self._salience_router is not None:
                _bd = self._salience_router.last_breakdown
                if _bd is not None:
                    _activation = _bd.final_activation
            _effort = _ledger.effort_calibration(_activation)
            updated += f"\n\n## Effort Level\n{_effort.level_name} ({_effort.word_limit} words)"
            self.last_word_limit = _effort.word_limit

        # Export GQI to shm for stimmung integration (cross-process)
        if _ledger is not None:
            try:
                _gqi = _ledger.compute_gqi()
                _gqi_dir = Path("/dev/shm/hapax-daimonion")
                _gqi_dir.mkdir(parents=True, exist_ok=True)
                _gqi_path = _gqi_dir / "grounding-quality.json"
                _tmp_path = _gqi_path.with_suffix(".tmp")
                _tmp_path.write_text(json.dumps({"gqi": round(_gqi, 3), "timestamp": time.time()}))
                _tmp_path.rename(_gqi_path)
                log.debug("GQI written to shm: %.3f", _gqi)
            except Exception:
                log.debug("GQI shm write failed", exc_info=True)

        content_hash = hash(updated)
        if content_hash == self._last_env_hash:
            return
        self._last_env_hash = content_hash
        self.messages[0]["content"] = updated

    async def process_utterance(self, audio_bytes: bytes) -> None:
        """Process a complete utterance through STT → LLM → TTS.

        Called by the daemon when ConversationBuffer delivers an utterance.
        """
        if not self._running:
            return

        from agents._telemetry import hapax_trace

        _t_start = time.monotonic()
        _utt_trace_cm = hapax_trace(
            "voice",
            "utterance",
            session_id=getattr(self, "_session_id", None),
            metadata={"turn": self.turn_count, "audio_bytes": len(audio_bytes)},
        )
        _utt_trace = _utt_trace_cm.__enter__()

        try:
            await self._process_utterance_inner(audio_bytes, _utt_trace, _t_start)
        finally:
            # Guarantee trace closure on ALL code paths — 7 early returns
            # previously leaked unclosed traces, causing next turn's scores
            # to be lost when Langfuse implicitly closed the orphaned trace.
            try:
                _utt_trace_cm.__exit__(None, None, None)
            except Exception:
                pass

    async def _process_utterance_inner(
        self, audio_bytes: bytes, _utt_trace, _t_start: float
    ) -> None:
        """Inner utterance processing — extracted so try/finally guarantees trace closure."""
        from agents._telemetry import hapax_bool_score, hapax_event, hapax_score

        # STT
        self.state = ConvState.TRANSCRIBING
        transcript = await self.stt.transcribe(audio_bytes)
        if not transcript:
            self.state = ConvState.LISTENING
            return
        if _utt_trace is not None:
            try:
                _utt_trace.update(input=transcript)
            except Exception:
                pass

        # Utterance plausibility: reject likely music/noise bleed-through
        if self._ambient_fn is not None:
            try:
                ambient = self._ambient_fn()
                if (
                    ambient is not None
                    and getattr(ambient, "top_labels", None)
                    and not getattr(ambient, "interruptible", True)
                    and len(transcript.split()) < 4
                ):
                    log.debug("Rejecting short transcript during music: %r", transcript)
                    self.state = ConvState.LISTENING
                    return
            except Exception:
                pass  # fail-open

        _t_stt = time.monotonic()
        _stt_ms = (_t_stt - _t_start) * 1000
        log.info("TIMING stt=%.0fms transcript=%r", _stt_ms, transcript[:60])
        hapax_event(
            "voice",
            "stt_done",
            metadata={
                "stt_ms": round(_stt_ms),
                "transcript_len": len(transcript),
            },
        )

        # ── Echo detection: reject or strip echo from transcript ──
        # Echo rejection stays active even during barge-in. The AEC doesn't
        # fully cancel TTS from the mic signal, and the barge-in detector
        # can't distinguish operator voice from loud speaker bleed-through.
        # Without echo rejection, Hapax talks to itself in a feedback loop.
        if self._is_echo(transcript):
            log.info("Echo rejected: %r", transcript[:60])
            self.state = ConvState.LISTENING
            return

        # Strip echo prefix: when mic captures echo + real speech in one
        # utterance (e.g., "letting you know I'm here. Yeah how are you"),
        # remove the echo portion and keep the operator's real speech.
        transcript = self._strip_echo_prefix(transcript)
        if not transcript:
            log.info("Echo stripped to empty")
            self.state = ConvState.LISTENING
            return

        # ── Duplicate detection: reject if same transcript just processed ──
        if hasattr(self, "_last_transcript") and transcript == self._last_transcript:
            log.info("Duplicate rejected: %r", transcript[:60])
            self.state = ConvState.LISTENING
            return
        self._last_transcript = transcript

        # ── Principal attribution: wrap transcript with speaker identity ──
        # Says[str] records WHO said this, not just what. The principal
        # is resolved from consent_context (set at daemon boundary) or
        # falls back to operator (single-user axiom).
        try:
            from agents._consent_context import maybe_principal
            from agents._governance import Says

            speaker_principal = maybe_principal()
            if speaker_principal is not None:
                self._last_says = Says.unit(speaker_principal, transcript)
            else:
                self._last_says = None
        except Exception:
            self._last_says = None

        _pid = "operator"
        if self._last_says is not None:
            try:
                _pid = self._last_says.principal.id
            except Exception:
                pass
        self._emit("user_utterance", text=transcript, principal_id=_pid)
        _emit_caption_bridge_for_transcript(
            transcript=transcript,
            audio_bytes=audio_bytes,
            speaker=_pid,
        )

        # Continuous-Loop Research Cadence §3.4 — write the most recent
        # transcript line to the STT-recent file so the compositor's
        # CaptionsCairoSource can render it as a scientific-register
        # overlay. Atomic tmp+rename so partial writes are never seen
        # by the renderer. Best-effort; never raise.
        try:
            import os as _os
            from pathlib import Path as _Path

            _stt_recent = _Path("/dev/shm/hapax-daimonion/stt-recent.txt")
            _stt_recent.parent.mkdir(parents=True, exist_ok=True)
            _tmp = _stt_recent.with_suffix(".txt.tmp")
            _tmp.write_text(transcript + "\n", encoding="utf-8")
            _os.replace(_tmp, _stt_recent)
        except Exception:
            log.debug("stt-recent write failed", exc_info=True)

        # ── Observation signals (Batch 4: revealed preferences) ──────
        # Emit events for future preference learning. No profile mutation.
        self._detect_observation_signals(transcript)

        # Deictic reference detection — auto-inject screen capture
        # when the operator references something visible ("that", "this", etc.)
        screen_injected = self._maybe_inject_screen(transcript)
        if screen_injected:
            self.messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{screen_injected}"},
                        },
                        {"type": "text", "text": transcript},
                    ],
                }
            )
        else:
            self.messages.append({"role": "user", "content": transcript})
        self.turn_count += 1

        # ── Model routing: grounding-native tiered routing ─────────
        # Voice is classified as expression_only / non_grounding_reasoner
        # per the capability grounding contract envelope (2026-04-29).
        # The model_router's tiered routing (LOCAL → FAST → STRONG →
        # CAPABLE) selects grounding-capable models by default. Governance
        # overrides (consent, guest → CAPABLE) are enforced in the
        # model_router's Layer 1, not here.
        #
        # Previous intelligence_first override (PR #1334, 2026-04-24)
        # removed: it predated the grounding commitment framework and
        # routed all voice to claude-opus, whose RLHF optimizes for
        # fluent helpfulness rather than the evidence-citing, uncertainty-
        # surfacing behavior that grounding-native models (Command-R)
        # preserve. See: capability-grounding-contract-envelope.md §Model
        # And Provider Policy, line 275.
        from agents.hapax_daimonion.model_router import TIER_ROUTES, ModelTier

        if self._salience_router is not None:
            routing = self._salience_router.route(
                transcript,
                turn_count=self.turn_count,
                activity_mode=self._activity_mode,
                consent_phase=self._consent_phase,
                guest_mode=self._guest_mode,
                face_count=self._face_count,
                has_tools=bool(self.tools),
                desk_activity=self._desk_activity,
            )
        else:
            # No salience router — default to FAST (grounding-capable
            # cloud model) rather than CAPABLE (high-G, RLHF-optimized).
            from agents.hapax_daimonion.model_router import RoutingDecision

            routing = RoutingDecision(
                tier=ModelTier.FAST,
                model=TIER_ROUTES[ModelTier.FAST],
                reason="no_salience_router:default",
                canned_response="",
            )

        self._prev_tier = routing.tier
        log.info(
            "TIMING route=%s model=%s reason=%s",
            routing.tier.name,
            routing.model or "canned",
            routing.reason,
        )
        hapax_event(
            "voice",
            "routed",
            metadata={
                "tier": routing.tier.name,
                "model": routing.model or "canned",
                "reason": routing.reason,
            },
        )

        # Record activation breakdown for diagnostics
        if self._salience_diagnostics is not None:
            self._salience_diagnostics.record(transcript)

        # Canned response: skip LLM entirely, play from pre-synth cache
        if routing.tier == ModelTier.CANNED and routing.canned_response:
            self.state = ConvState.SPEAKING
            pcm = (
                self._bridge_engine._cache.get(routing.canned_response)
                if self._bridge_engine
                else None
            )
            if pcm and self._audio_output:
                if self.buffer:
                    self.buffer.set_speaking(True)
                try:
                    await self._play_guarded_pcm(
                        pcm=pcm,
                        text=routing.canned_response,
                        source="conversation_canned_response",
                    )
                finally:
                    if self.buffer:
                        self.buffer.set_speaking(False)
            else:
                await self._speak_sentence(routing.canned_response)
            self.messages.append({"role": "assistant", "content": routing.canned_response})
            self._emit("assistant_response", text=routing.canned_response)
            self._last_assistant_end = time.monotonic()
            self.state = ConvState.LISTENING
            return

        # Stimmung state is fed into model context rather than influencing
        # tier selection. The model_router handles tier assignment based on
        # utterance complexity, conversation depth, and governance state.
        # Vision, perception cadence, and workspace analysis shed under
        # stimmung pressure before model tier changes.
        selected_model = routing.model or self.llm_model
        self._turn_model = selected_model
        self._turn_model_tier = routing.tier.name

        # Refresh environment context before LLM call
        self._update_system_context()

        # Fire LLM call concurrently with bridge phrase
        self.state = ConvState.THINKING
        # Set speaking BEFORE bridge so the buffer stays deaf from bridge
        # through the entire response — no gap where echo could leak in.
        if self.buffer:
            self.buffer.set_speaking(True)
        llm_task = asyncio.create_task(self._generate_and_speak())
        await self._speak_bridge()
        try:
            await asyncio.wait_for(llm_task, timeout=90.0)
        except TimeoutError:
            log.warning("LLM task timed out after 90s")
            llm_task.cancel()
            # Speak error WHILE still in speaking mode — prevents echo feedback.
            # Previous bug: set_speaking(False) before error TTS let the buffer
            # capture the error audio as an operator utterance.
            await self._speak_sentence("I'm having trouble connecting right now.")
            if self.buffer:
                self.buffer.set_speaking(False)
            self.state = ConvState.LISTENING
        except Exception:
            log.exception("LLM task failed")
            await self._speak_sentence("Something went wrong.")
            if self.buffer:
                self.buffer.set_speaking(False)
            self.state = ConvState.LISTENING

        # Check limits
        if self.turn_count >= _MAX_TURNS:
            log.info("Max turns reached, ending conversation")
            await self.stop()
            return

        # Per-turn context anchoring evaluation (lightweight, no LLM call)
        try:
            from agents.hapax_daimonion.grounding_evaluator import evaluate_turn

            # Get last assistant response from messages
            _last_response = ""
            for m in reversed(self.messages):
                if m.get("role") == "assistant" and isinstance(m.get("content"), str):
                    _last_response = m["content"]
                    break

            if _last_response:
                if _utt_trace is not None:
                    try:
                        _utt_trace.update(output=_last_response)
                    except Exception:
                        pass
                # Pass thread text (not ThreadEntry objects) to evaluator
                _thread_texts = [
                    e.user_text if isinstance(e, ThreadEntry) else e
                    for e in self._conversation_thread
                ]
                # Get current directive strategy from grounding ledger (if active)
                _ledger = getattr(self, "_grounding_ledger", None)
                _directive_strategy = None
                if _ledger is not None and _ledger._units:
                    _last_du = _ledger._units[-1]
                    _directive_strategy = {
                        "GROUNDED": "advance",
                        "REPAIR-1": "rephrase",
                        "REPAIR-2": "elaborate",
                        "CONTESTED": "present_reasoning",
                        "ABANDONED": "move_on",
                        "UNGROUNDED": "ungrounded_caution",
                    }.get(_last_du.state.value)

                _grounding_scores = evaluate_turn(
                    response=_last_response,
                    messages=self.messages,
                    conversation_thread=_thread_texts,
                    user_utterance=transcript,
                    langfuse_trace=_utt_trace,
                    directive_strategy=_directive_strategy,
                )
                # Expose for visual overlay monitoring
                self.last_anchor_score = _grounding_scores.get("context_anchor_success", 0.0)
                self.last_acceptance_label = _grounding_scores.get("acceptance_label", "")

                # Feed acceptance into grounding ledger (Batch 2: close the loop)
                if self._grounding_ledger is not None:
                    _concern = 0.5
                    if self._salience_router is not None:
                        _bd = self._salience_router.last_breakdown
                        if _bd is not None:
                            _concern = _bd.concern_overlap
                    self._grounding_ledger.update_from_acceptance(
                        self.last_acceptance_label, _concern
                    )

                # Probe question: check sentinel retrieval
                sentinel_score = self.check_sentinel_retrieval(_last_response)
                if sentinel_score is not None:
                    hapax_score(_utt_trace, "sentinel_retrieval", sentinel_score)

                # Update conversation thread with structured entry
                _user_text = _extract_substance(transcript)
                _resp_clause = _extract_response_clause(_last_response)
                _acceptance = _grounding_scores.get("acceptance_label", "IGNORE")
                _prev_acceptance = (
                    self._conversation_thread[-1].acceptance
                    if self._conversation_thread
                    else "IGNORE"
                )
                # Resolve principal from last Says (AD-7)
                _principal_id = "operator"
                if self._last_says is not None:
                    try:
                        _principal_id = self._last_says.principal.id
                    except Exception:
                        pass
                _entry = ThreadEntry(
                    turn=self.turn_count,
                    user_text=_user_text,
                    response_summary=_resp_clause,
                    acceptance=_acceptance,
                    grounding_state=ThreadEntry.acceptance_to_grounding(_acceptance),
                    is_repair=_prev_acceptance in ("CLARIFY", "REJECT"),
                    principal_id=_principal_id,
                )
                self._conversation_thread.append(_entry)

                # Age out seeded entries as current conversation fills
                _current_count = sum(1 for e in self._conversation_thread if not e.is_seeded)
                if _current_count >= 11:
                    # Drop all seeded entries (current conversation has enough context)
                    self._conversation_thread = [
                        e for e in self._conversation_thread if not e.is_seeded
                    ]
                elif _current_count >= 6:
                    # Compress seeded entries: keep only 1
                    _seeded = [e for e in self._conversation_thread if e.is_seeded]
                    _current = [e for e in self._conversation_thread if not e.is_seeded]
                    self._conversation_thread = _seeded[:1] + _current

                # Hard cap at 10
                if len(self._conversation_thread) > 10:
                    self._conversation_thread = self._conversation_thread[-10:]

                # Register this response as a new DU in the grounding ledger
                if self._grounding_ledger is not None:
                    _concern = 0.5
                    if self._salience_router is not None:
                        _bd = self._salience_router.last_breakdown
                        if _bd is not None:
                            _concern = _bd.concern_overlap
                    self._grounding_ledger.add_du(self.turn_count, _resp_clause, _concern)
        except Exception:
            log.debug("Grounding evaluation failed (non-fatal)", exc_info=True)

        # Frustration scoring (mechanical, no LLM)
        try:
            if self._frustration_detector is not None:
                # Get last assistant response for system repetition check
                _prev_response = ""
                _tool_error = False
                for m in reversed(self.messages):
                    if m.get("role") == "assistant" and isinstance(m.get("content"), str):
                        _prev_response = m["content"]
                        break
                    if m.get("role") == "tool":
                        content = m.get("content", "")
                        if isinstance(content, str) and "error" in content.lower():
                            _tool_error = True

                _barge_in = getattr(self, "_last_barge_in", False)
                _follow_up_delay = (
                    time.monotonic() - self._last_assistant_end
                    if self._last_assistant_end > 0
                    else 999.0
                )
                signals = self._frustration_detector.score_turn(
                    user_text=transcript,
                    assistant_text=_prev_response,
                    barge_in=_barge_in,
                    tool_error=_tool_error,
                    follow_up_delay=_follow_up_delay,
                )
                hapax_score(_utt_trace, "frustration_score", signals.score)
                hapax_score(
                    _utt_trace,
                    "frustration_rolling_avg",
                    self._frustration_detector.rolling_average,
                )
                if self._frustration_detector.is_spiked:
                    hapax_event(
                        "voice",
                        "frustration_spike",
                        metadata={
                            "score": signals.score,
                            "rolling_avg": self._frustration_detector.rolling_average,
                            "breakdown": signals.breakdown(),
                        },
                    )
        except Exception:
            log.debug("Frustration scoring failed (non-fatal)", exc_info=True)

        # Score and close the utterance trace
        _t_end = time.monotonic()
        _total_ms = (_t_end - _t_start) * 1000
        hapax_score(_utt_trace, "total_latency_ms", _total_ms)
        _consent_threshold = 2000 if getattr(self, "_consent_phase", "none") != "none" else 5000
        hapax_bool_score(_utt_trace, "consent_latency_ok", _total_ms < _consent_threshold)
        if self._salience_router is not None:
            _bd = self._salience_router.last_breakdown
            if _bd is not None:
                hapax_score(_utt_trace, "activation_score", _bd.final_activation)
                hapax_score(_utt_trace, "novelty", _bd.novelty)
                hapax_score(_utt_trace, "concern_overlap", _bd.concern_overlap)
                hapax_score(_utt_trace, "dialog_feature_score", _bd.dialog_feature_score)
        self.state = ConvState.LISTENING

    async def _generate_and_speak(self) -> None:
        """Stream LLM response, accumulate sentences, synthesize and play."""
        try:
            import os

            import litellm

            # Bound message history: drop old turns, keep system + last 5 exchanges.
            # The conversation thread in the system prompt provides memory of
            # dropped turns — no lossy LLMLingua-2 compression needed.
            # Walk backward counting 5 user messages to preserve tool sequences
            # (assistant+tool_calls, tool result, follow-up) as complete exchanges.
            # INTERVIEW programmes disable message_drop — full thread needed for
            # callbacks, follow-ups, and avoiding re-asks across 120 turns.
            _drop_threshold = getattr(self, "_message_drop_threshold", 12)
            if self._experiment_flags.get("message_drop", True) and len(self.messages) > _drop_threshold:
                system_msg = self.messages[0]
                user_count = 0
                cut_idx = len(self.messages)
                for i in range(len(self.messages) - 1, 0, -1):
                    if self.messages[i].get("role") == "user":
                        user_count += 1
                        if user_count >= 5:
                            cut_idx = i
                            break
                recent = self.messages[cut_idx:]
                self.messages = [system_msg] + recent

            _model = getattr(self, "_turn_model", self.llm_model)
            _tier_name = getattr(self, "_turn_model_tier", "")

            # Build GroundingContextEnvelope
            try:
                import json
                from pathlib import Path

                bands_raw = json.loads(
                    Path("/dev/shm/hapax-temporal/bands.json").read_text(encoding="utf-8")
                )
            except Exception:
                bands_raw = {}

            try:
                from agents.hapax_daimonion.phenomenal_context import render as render_phenom

                phenom_text = render_phenom(tier=_tier_name or "CAPABLE")
                phenom_lines = phenom_text.strip().split("\n") if phenom_text else []
            except Exception:
                phenom_lines = []

            available_tool_names = [t["function"]["name"] for t in self.tools] if self.tools else []

            from shared.grounding_context import GroundingContextVerifier

            envelope = GroundingContextVerifier.build_envelope(
                turn_id=str(self.turn_count),
                temporal_bands=bands_raw,
                phenomenal_lines=phenom_lines,
                available_tools=available_tool_names,
            )

            kwargs = {
                "model": f"openai/{_model}",
                "stream": True,
                "max_tokens": _TIER_MAX_TOKENS.get(
                    getattr(self, "_turn_model_tier", ""), _MAX_RESPONSE_TOKENS
                ),
                "temperature": 0.7,
                "api_base": _voice_litellm_base,
                "api_key": os.environ.get("LITELLM_API_KEY", "not-set"),
            }
            if self.tools and self._tool_recruitment_gate:
                recruited_names = self._tool_recruitment_gate.recruit(envelope)
                if recruited_names:
                    envelope = GroundingContextVerifier.build_envelope(
                        turn_id=str(self.turn_count),
                        temporal_bands=bands_raw,
                        phenomenal_lines=phenom_lines,
                        available_tools=available_tool_names,
                        recruited_tools=recruited_names,
                    )
                    kwargs["tools"] = [
                        t for t in self.tools if t["function"]["name"] in recruited_names
                    ]
            elif self.tools:
                kwargs["tools"] = self.tools

            self._current_envelope = envelope

            _messages = self.messages
            if _messages and _messages[0].get("role") == "system":
                _sys_content = _messages[0].get("content", "")
                if _tier_name == "LOCAL":
                    _sys_content = compose_persona_prompt(
                        role_id="partner-in-conversation", compressed=True
                    )

                _xml = GroundingContextVerifier.render_xml(envelope)
                _messages = [
                    {
                        "role": "system",
                        "content": f"{_sys_content}\n\n{_xml}",
                    },
                    *_messages[1:],
                ]
            kwargs["messages"] = _messages

            kwargs["timeout"] = 15  # seconds — fail fast, don't block conversation
            _t_llm_start = time.monotonic()
            _conv_model_label = str(kwargs.get("model", "unknown"))
            metrics_ctx = (
                llm_call_span(model=_conv_model_label, route="conversation")
                if llm_call_span is not None
                else nullcontext(None)
            )
            with metrics_ctx:
                response = await litellm.acompletion(**kwargs)

            full_text = ""
            accumulated = ""
            tool_calls_data: list[dict] = []
            accumulation_start = time.monotonic()
            _t_first_token = 0.0
            _t_first_audio = 0.0
            _first_clause_spoken = False
            spoken_full_text = ""
            _spoken_words = 0  # Track words sent to TTS for cutoff
            # Word limit: effort-driven (Batch 2) > lockdown fixed > density-driven
            if self._grounding_ledger is not None and self._experiment_flags.get(
                "effort_modulation", False
            ):
                _word_limit = (
                    self.last_word_limit
                )  # set by effort calibration in _update_system_context
            elif self._experiment_flags.get("volatile_lockdown", False):
                _word_limit = _MAX_SPOKEN_WORDS
            else:
                _word_limit = _density_word_limit()  # Bayesian Tier 1: density-driven

            self.state = ConvState.SPEAKING
            # set_speaking(True) already called by process_utterance before bridge

            async for chunk in response:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta

                # Log finish reason when stream ends
                if choice.finish_reason:
                    log.info("LLM stream finished: reason=%s", choice.finish_reason)

                if delta is None:
                    continue

                # Handle tool calls
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        while len(tool_calls_data) <= idx:
                            tool_calls_data.append({"id": "", "name": "", "arguments": ""})
                        if tc.id:
                            tool_calls_data[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_data[idx]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls_data[idx]["arguments"] += tc.function.arguments
                    continue

                # Handle text content
                content = delta.content or ""
                if not content:
                    continue

                if not _t_first_token:
                    _t_first_token = time.monotonic()
                    log.info(
                        "TIMING llm_ttft=%.0fms",
                        (_t_first_token - _t_llm_start) * 1000,
                    )
                full_text += content
                accumulated += content

                # Cut stream if LLM hallucinates tool-call XML in text output.
                # With tools disabled, Opus sometimes generates tool XML as
                # plain text in multiple tag formats. Stop before TTS speaks XML/JSON.
                _tool_tags = (
                    "<tool_use>",
                    "<tool_name>",
                    "<tool_calls>",
                    "<invoke ",
                    "<search_documents>",
                    "<find_phone>",
                    "<tool_results>",
                    "<function_call>",
                )
                if any(tag in full_text for tag in _tool_tags):
                    # Keep only the text before the first tool tag
                    cut = full_text
                    for tag in _tool_tags:
                        if tag in cut:
                            cut = cut.split(tag)[0]
                    cut = cut.strip()
                    if cut and not _first_clause_spoken:
                        actual = await self._speak_sentence(cut)
                        if actual:
                            spoken_full_text += actual + " "
                    log.info("Halted: LLM hallucinated tool XML in text output")
                    full_text = cut
                    accumulated = ""
                    break

                # Eager flush: speak as soon as possible to minimize dead air.
                # For the first clause, flush aggressively (2+ words or 400ms).
                # For subsequent clauses, use clause boundary detection.
                _elapsed = time.monotonic() - accumulation_start
                _words = len(accumulated.split())

                if not _first_clause_spoken:
                    # First audio: flush ASAP to kill dead air
                    parts = _CLAUSE_END.split(accumulated)
                    if len(parts) > 1:
                        to_speak = parts[0].strip()
                        if to_speak and _words >= _MIN_FIRST_CLAUSE_WORDS:
                            actual = await self._speak_sentence(to_speak)
                            if actual:
                                spoken_full_text += actual + " "
                            _first_clause_spoken = True
                            # Speak any complete middle clauses too (don't drop them)
                            for mid in parts[1:-1]:
                                mid = mid.strip()
                                if mid and len(mid.split()) >= _MIN_CLAUSE_WORDS:
                                    actual = await self._speak_sentence(mid)
                                    if actual:
                                        spoken_full_text += actual + " "
                            accumulated = parts[-1]
                            accumulation_start = time.monotonic()
                    elif _elapsed > _MAX_ACCUMULATION_S and _words >= _MIN_FIRST_CLAUSE_WORDS:
                        actual = await self._speak_sentence(accumulated.strip())
                        if actual:
                            spoken_full_text += actual + " "
                        _first_clause_spoken = True
                        accumulated = ""
                        accumulation_start = time.monotonic()
                else:
                    # Subsequent clauses: clause boundaries or time flush
                    parts = _CLAUSE_END.split(accumulated)
                    if len(parts) > 1:
                        _spoke = False
                        for sentence in parts[:-1]:
                            sentence = sentence.strip()
                            if sentence and len(sentence.split()) >= _MIN_CLAUSE_WORDS:
                                actual = await self._speak_sentence(sentence)
                                if actual:
                                    spoken_full_text += actual + " "
                                _spoke = True
                                if self.buffer and self.buffer.barge_in_detected:
                                    log.info("Barge-in: cutting response short")
                                    break
                        accumulated = parts[-1]
                        if _spoke:
                            accumulation_start = time.monotonic()
                    elif _elapsed > _MAX_ACCUMULATION_S:
                        if accumulated.strip() and _words >= _MIN_CLAUSE_WORDS:
                            actual = await self._speak_sentence(accumulated.strip())
                            if actual:
                                spoken_full_text += actual + " "
                            accumulated = ""
                            accumulation_start = time.monotonic()

                # Barge-in: break out of LLM stream
                if self.buffer and self.buffer.barge_in_detected:
                    break

                # Word cutoff: stop vocalizing after density-driven word limit.
                # The LLM continues generating (full_text accumulates for
                # context), but we stop sending to TTS.
                _spoken_words = len(full_text.split()) - len(accumulated.split())
                if _spoken_words >= _word_limit:
                    log.info(
                        "Word cutoff at %d words (limit=%d) — stopping speech",
                        _spoken_words,
                        _word_limit,
                    )
                    accumulated = ""  # discard unspoken remainder
                    break

            # Flush remaining text (skip if barge-in or word cutoff)
            if accumulated.strip() and not (self.buffer and self.buffer.barge_in_detected):
                if _spoken_words < _word_limit:
                    actual = await self._speak_sentence(accumulated.strip())
                    if actual:
                        spoken_full_text += actual + " "

            # Expose word counts for visual overlay monitoring
            self.last_spoken_words = _spoken_words
            self.last_word_limit = _word_limit

            # Log full response for debugging truncation
            if full_text:
                log.info("LLM full response (%d chars): %r", len(full_text), full_text[:200])

            # Record assistant message using safely spoken clauses
            if full_text and not tool_calls_data:
                spoken_full_text = spoken_full_text.strip()
                if spoken_full_text:
                    self.messages.append({"role": "assistant", "content": spoken_full_text})
                    if self.buffer and self.buffer.barge_in_detected:
                        self._emit("assistant_interrupted", text=spoken_full_text)
                        self._emit("user_interrupted", turn=self.turn_count)
                    else:
                        self._emit("assistant_response", text=spoken_full_text)
                self._last_assistant_end = time.monotonic()

            # Tool calls: skip in voice turns to avoid 10-15s latency penalty.
            # Tool execution + second LLM round-trip eats the 20s timeout budget.
            # The model already has workspace context via system prompt injection;
            # tools add precision but destroy conversational pacing.
            if tool_calls_data:
                log.info(
                    "Executing %d tool call(s): %s",
                    len(tool_calls_data),
                    [tc["name"] for tc in tool_calls_data],
                )
                await self._handle_tool_calls(tool_calls_data, full_text)

        except TimeoutError:
            log.warning("LLM timeout — no response")
            await self._speak_sentence("I'm having trouble connecting right now.")
        except Exception:
            log.exception("LLM generation failed")
            await self._speak_sentence("Sorry, something went wrong.")
        finally:
            # Wait for audio executor to finish playing before dropping
            # the speaking gate — otherwise the buffer picks up TTS tail.
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(_audio_executor, lambda: None)  # drain queue
            if self.buffer:
                self.buffer.set_speaking(False)

    async def _handle_tool_calls(self, tool_calls: list[dict], assistant_text: str) -> None:
        """Execute tool calls and generate follow-up response."""
        # Play bridge phrase to signal tool execution ("Let me check...")
        if self._bridge_engine is not None:
            from agents.hapax_daimonion.bridge_engine import BridgeContext

            ctx = BridgeContext(
                turn_position=self.turn_count,
                response_type="tool-running",
                session_id=self._session_id,
            )
            phrase, pcm = self._bridge_engine.select(ctx)
            if pcm and self._audio_output:
                try:
                    await self._play_guarded_pcm(
                        pcm=pcm,
                        text=phrase or "tool bridge",
                        source="conversation_tool_bridge",
                    )
                except Exception:
                    log.debug("Tool bridge playback failed", exc_info=True)

        # Record the assistant message with tool calls
        self.messages.append(
            {
                "role": "assistant",
                "content": assistant_text or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in tool_calls
                ],
            }
        )

        for tc in tool_calls:
            handler = self.tool_handlers.get(tc["name"])
            if handler is None:
                result = json.dumps({"error": f"Unknown tool: {tc['name']}"})
            else:
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    _timeout = getattr(self, "_tool_timeout", 3.0)
                    if asyncio.iscoroutinefunction(handler):
                        result = await asyncio.wait_for(handler(args), timeout=_timeout)
                    else:
                        result = handler(args)
                    if not isinstance(result, str):
                        result = json.dumps(result)
                except TimeoutError:
                    result = json.dumps({"error": f"Tool {tc['name']} timed out"})
                    log.warning("Tool %s timed out after %.1fs", tc["name"], _timeout)
                except Exception as e:
                    result = json.dumps({"error": str(e)})

            # Consent gate: filter tool results before they reach the LLM.
            #
            # BETA-FINDING-K fail-closed behavior: if the reader is
            # missing (should be impossible now that init_pipeline
            # raises on construction failure, but belt-and-suspenders)
            # or if filtering itself raises, the tool result is
            # REDACTED instead of passed through unfiltered. The
            # interpersonal_transparency axiom (weight 88) is the
            # single most load-bearing governance rule in the
            # daemonion — it fails closed by construction, always.
            if self._consent_reader is None:
                log.error(
                    "Consent reader missing at tool-call time for %s — "
                    "redacting tool result (interpersonal_transparency axiom fail-closed)",
                    tc["name"],
                )
                result = json.dumps({"error": "consent_gate_unavailable", "tool": tc["name"]})
            else:
                try:
                    result = self._consent_reader.filter_tool_result(tc["name"], result)
                except Exception:
                    log.warning(
                        "Consent filtering raised for %s — redacting tool result",
                        tc["name"],
                        exc_info=True,
                    )
                    result = json.dumps({"error": "consent_filter_failed", "tool": tc["name"]})

            # Record outcome for Thompson sampling in recruitment gate
            if self._tool_recruitment_gate:
                _success = not isinstance(result, str) or '"error"' not in result
                self._tool_recruitment_gate.record_outcome(tc["name"], success=_success)

            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                }
            )
            self._emit("tool_call", name=tc["name"])

        # Generate follow-up response with tool results
        await self._generate_and_speak()

    # ── Bridge Phrases (via BridgeEngine) ─────────────────────────────

    async def _speak_bridge(self) -> None:
        """Play a contextual bridge phrase from BridgeEngine.

        Selects based on turn position, activity mode, consent phase, etc.
        Plays from pre-synthesized cache — no synthesis latency.
        """
        # For STRONG/CAPABLE tiers, always play bridge — it signals
        # intentional thinking, not just filling dead air.
        # For lower tiers, skip if last response was very recent.
        _tier = getattr(self, "_turn_model_tier", "")
        if _tier not in ("STRONG", "CAPABLE") and self._last_assistant_end > 0:
            gap = time.monotonic() - self._last_assistant_end
            if gap < 2.0:
                return

        if self._bridge_engine is None:
            return

        from agents.hapax_daimonion.bridge_engine import BridgeContext

        _tier = getattr(self, "_turn_model_tier", "")

        # Get activation score from salience router if available
        _activation = -1.0
        if self._salience_router is not None:
            breakdown = self._salience_router.last_breakdown
            if breakdown is not None:
                _activation = breakdown.final_activation

        ctx = BridgeContext(
            turn_position=self.turn_count,
            activity_mode=self._activity_mode,
            consent_phase=self._consent_phase,
            response_type="acknowledging" if self.turn_count <= 1 else "thinking",
            session_id=self._session_id,
            model_tier=_tier,
            activation_score=_activation,
        )
        phrase, pcm = self._bridge_engine.select(ctx)

        if not phrase:
            return

        # Add bridge phrase to echo history so echo rejection catches it
        self._recent_tts_texts.append((time.monotonic(), phrase.lower().strip().rstrip(".,!?")))

        # No set_speaking here — the caller (process_utterance) manages the
        # speaking gate around the entire bridge+response sequence. This
        # prevents a gap between bridge end and first clause that was causing
        # the first TTS clause to get clipped.
        if pcm and self._audio_output:
            try:
                await self._play_guarded_pcm(
                    pcm=pcm,
                    text=phrase,
                    source="conversation_bridge",
                )
            except Exception:
                log.debug("Bridge playback failed", exc_info=True)
        elif phrase:
            await self._speak_sentence(phrase)

    def _resolve_direct_playback_route(
        self,
        *,
        source: str,
        text: str,
    ) -> tuple[bool, str | None, str | None]:
        """Record and resolve a private-or-drop route for direct PCM playback."""

        from agents.hapax_daimonion.cpal.destination_channel import (
            resolve_playback_decision,
        )
        from agents.hapax_daimonion.voice_output_witness import (
            record_destination_decision,
            record_drop,
        )

        decision = resolve_playback_decision(None)
        destination_target = decision.target
        destination_role = decision.media_role
        record_destination_decision(
            source=source,
            destination=decision.destination.value,
            route_accepted=decision.allowed,
            reason=decision.reason_code,
            safety_gate=decision.safety_gate,
            target=destination_target,
            media_role=destination_role,
            text=text,
            terminal_state="pending" if decision.allowed else "inhibited",
        )
        if not decision.allowed:
            record_drop(
                reason=decision.reason_code,
                source=source,
                destination=decision.destination.value,
                target=destination_target,
                media_role=destination_role,
                text=text,
                terminal_state="inhibited",
            )
            return False, None, None
        return True, destination_target, destination_role

    async def _play_guarded_pcm(self, *, pcm: bytes, text: str, source: str) -> bool:
        """Play presynthesized PCM only after destination witness accepts it."""

        if not self._audio_output:
            return False
        allowed, destination_target, destination_role = self._resolve_direct_playback_route(
            source=source,
            text=text,
        )
        if not allowed:
            return False
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            self._write_audio,
            self._audio_output,
            self._echo_canceller,
            pcm,
            destination_target,
            destination_role,
        )
        return True

    # ── Salience Context ────────────────────────────────────────────────

    def _build_salience_context(self) -> str:
        """Build salience context block for system prompt injection.

        Feeds activation, novelty, concern overlap, and conversational model
        signals into the prompt so the model can self-modulate response depth.
        """
        parts = []

        # Salience router signals
        if self._salience_router is not None:
            breakdown = self._salience_router.last_breakdown
            if breakdown is not None:
                level = "low"
                if breakdown.final_activation > 0.6:
                    level = "high — this connects to active concerns"
                elif breakdown.final_activation > 0.3:
                    level = "moderate"

                parts.append(
                    f"Activation: {breakdown.final_activation:.2f} ({level}). "
                    f"Concern overlap: {breakdown.concern_overlap:.2f}. "
                    f"Novelty: {breakdown.novelty:.2f}."
                )

        # Conversational model signals (from cognitive loop)
        # These are available via pipeline attributes set by the cognitive loop
        temp = getattr(self, "_conversation_temperature", None)
        if temp is not None and temp > 0:
            warmth = "cold" if temp < 0.2 else "warming" if temp < 0.5 else "heated"
            parts.append(f"Conversation temperature: {temp:.2f} ({warmth}).")

        parts.append(f"Turn: {self.turn_count}.")

        # Stimmung state — inform model, don't degrade it
        try:
            import json
            from pathlib import Path

            raw = json.loads(Path("/dev/shm/hapax-stimmung/state.json").read_text(encoding="utf-8"))
            stance = raw.get("overall_stance", "nominal")
            resource = raw.get("resource_pressure", {}).get("value", 0.0)
            if stance != "nominal" or resource > 0.5:
                parts.append(
                    f"System stance: {stance} (resource pressure: {resource:.2f}). "
                    "Be concise if pressure is elevated."
                )
        except Exception:
            pass  # stimmung unavailable

        return " ".join(parts) if parts else ""

    # ── Echo Detection ──────────────────────────────────────────────────

    def _is_echo(self, transcript: str) -> bool:
        """Detect if a transcript is Hapax's own TTS output echoed back.

        Tuned to avoid false positives that silence legitimate operator speech.
        Uses TTL-based pruning and conservative matching:

        1. Exact match against recent TTS sentence
        2. Substring containment (transcript is a fragment of TTS)
        3. High-confidence LCS ratio (≥0.75) for longer utterances
        """
        if not self._recent_tts_texts:
            return False

        norm = transcript.lower().strip().rstrip(".,!?")
        if not norm:
            return False

        norm_words = norm.split()
        word_count = len(norm_words)
        now = time.monotonic()

        # TTL scales with dynamic cooldown — echo can arrive late after
        # long responses. 30s covers autonomous narrative: TTS synthesis
        # (~3s) + playback (~6s) + 3s holdover + room echo propagation
        # (~5s) + buffer accumulation (~8s). Previously 12s which missed
        # autonomous narrative echoes arriving 20+ seconds after emission.
        _ECHO_TTL_S = 30.0

        for ts, tts_text in self._recent_tts_texts:
            if now - ts > _ECHO_TTL_S:
                continue

            tts_words = tts_text.split()

            # 1. Exact match (any length)
            if norm == tts_text:
                return True

            # 2. Substring: transcript is a fragment of recent TTS (≥2 words)
            # Catches "connecting right now" matching "having trouble connecting right now"
            if word_count >= 2 and norm in tts_text:
                return True

            # 3. LCS match — lowered from 0.70 to 0.50 because STT
            # garbles autonomous narrative echoes significantly ("Hapax
            # monitors divergence" → "IR sensor indicates a divergence").
            if word_count >= 3 and len(tts_words) >= 3:
                lcs_len = _lcs_word_length(norm_words, tts_words)
                shorter = min(word_count, len(tts_words))
                if lcs_len / shorter >= 0.50:
                    return True

        return False

    def _strip_echo_prefix(self, transcript: str) -> str:
        """Remove echo of Hapax's TTS from the beginning of a transcript.

        When the mic captures both TTS output and operator speech in one
        utterance, the STT transcript looks like:
          "letting you know I'm here if you need anything. Yeah how are you"
        We strip the echo portion and return only the operator's speech.
        """
        if not self._recent_tts_texts:
            return transcript

        norm = transcript.lower().strip()
        best_strip = 0  # characters to strip from start
        now = time.monotonic()
        _ECHO_TTL_S = 8.0

        for ts, tts_text in self._recent_tts_texts:
            if now - ts > _ECHO_TTL_S:
                continue
            tts_words = tts_text.split()
            if len(tts_words) < 3:
                continue

            # Check if any TTS sentence appears as a prefix (possibly with STT errors)
            norm_words = norm.split()
            # Try matching first N words of transcript against TTS words
            match_len = 0
            for i, tw in enumerate(tts_words):
                if i >= len(norm_words):
                    break
                if norm_words[i] == tw:
                    match_len = i + 1
                elif i > 0 and match_len / (i + 1) < 0.5:
                    break  # too many mismatches

            if match_len >= 3 and match_len / len(tts_words) >= 0.5:
                # Reconstruct the number of characters to strip
                stripped_words = " ".join(norm_words[:match_len])
                chars = len(stripped_words)
                if chars > best_strip:
                    best_strip = chars

        if best_strip > 0:
            # Strip the echo prefix, clean up separators
            remainder = transcript[best_strip:].lstrip(" .,!?;:-–—")
            if remainder and len(remainder.split()) >= 2:
                log.info(
                    "Echo prefix stripped (%d chars): %r → %r",
                    best_strip,
                    transcript[:40],
                    remainder[:40],
                )
                return remainder
            # If only 0-1 words remain, the whole thing was likely echo
            return ""

        return transcript

    # ── Observation Signals (Batch 4) ──────────────────────────────────

    # ── Deictic Screen Injection ───────────────────────────────────

    _DEICTIC_PATTERNS = (
        "what's that",
        "what is that",
        "what's this",
        "what is this",
        "look at this",
        "look at that",
        "see this",
        "see that",
        "what do you see",
        "what am i looking at",
        "what's on my screen",
        "what's on screen",
        "on the screen",
        "on my screen",
        "this thing",
        "that thing",
        "what's happening here",
        "tell me about this",
        "tell me about that",
        "what does this say",
        "what does that say",
        "can you read",
        "read this",
        "read that",
        "check this",
        "check that",
    )

    def _maybe_inject_screen(self, transcript: str) -> str | None:
        """If the utterance contains a deictic reference, capture the screen.

        Returns base64 PNG or None. This lets the operator say "what's that?"
        and Hapax sees their actual screen without needing to call a tool.
        """
        if self._screen_capturer is None:
            return None

        lower = transcript.lower().strip()
        if not any(pat in lower for pat in self._DEICTIC_PATTERNS):
            return None

        self._screen_capturer.reset_cooldown()
        screen_b64 = self._screen_capturer.capture()
        if screen_b64:
            self._emit("screen_injected", trigger=lower[:40])
            log.info("Auto-injected screen capture for deictic reference")
        return screen_b64

    _ELABORATION_PATTERNS = (
        "what do you mean",
        "can you explain",
        "say more",
        "elaborate",
        "go on",
        "tell me more",
        "what?",
        "huh?",
        "sorry?",
        "come again",
        "expand on",
    )

    _INTERRUPTION_PATTERNS = (
        "stop",
        "wait",
        "hold on",
        "never mind",
        "skip",
        "okay okay",
        "got it got it",
    )

    def _detect_observation_signals(self, transcript: str) -> None:
        """Detect conversational preference signals from user utterance.

        Emits events only — no profile mutation, no learning. These events
        can be consumed by a future preference learning system.
        """
        lower = transcript.lower().strip()

        # 1. Follow-up latency: time between assistant finishing and user responding
        if self._last_assistant_end > 0:
            latency_ms = int((time.monotonic() - self._last_assistant_end) * 1000)
            self._emit("follow_up_latency_ms", value=latency_ms, turn=self.turn_count)

        # 2. Elaboration request: user wants more detail
        if any(pat in lower for pat in self._ELABORATION_PATTERNS):
            self._emit("elaboration_requested", turn=self.turn_count)

        # 3. Interruption: user cuts off or redirects abruptly
        if self.state == ConvState.SPEAKING or (
            any(pat in lower for pat in self._INTERRUPTION_PATTERNS) and len(lower.split()) < 6
        ):
            self._emit("user_interrupted", turn=self.turn_count)

        # 4. Topic abandonment: user changes subject without follow-up
        if self._last_user_topic and self.turn_count > 1:
            # Simple heuristic: if the current utterance shares no significant
            # words with the last, it's likely a topic switch
            prev_words = set(self._last_user_topic.lower().split())
            curr_words = set(lower.split())
            # Filter out stopwords-ish (< 4 chars)
            prev_sig = {w for w in prev_words if len(w) >= 4}
            curr_sig = {w for w in curr_words if len(w) >= 4}
            if prev_sig and curr_sig and not (prev_sig & curr_sig):
                self._emit("topic_abandoned", turn=self.turn_count)

        self._last_user_topic = lower

    async def _speak_sentence(
        self,
        text: str,
        *,
        destination_target: str | None = None,
        destination_role: str | None = None,
        destination: str | None = None,
    ) -> str:
        """Synthesize and play a single sentence/clause.

        TTS runs in _tts_executor, audio write runs in _audio_executor.
        Both are single-threaded so clauses play in order, but the async
        loop resumes immediately after synthesis — tokens keep streaming
        from the LLM while audio plays.

        ``destination_target`` (optional) passes a per-utterance pw-cat
        sink override down to :meth:`_write_audio`. Callers that do not pass a
        resolved route are forced through the private-or-drop destination
        decision before synthesis/playback.

        ``destination_role`` (optional) passes a per-utterance pw-cat
        ``--media-role`` override. CPAL pairs this with
        ``destination_target`` so only authorized public clips pick up the
        ``Broadcast`` role, while private clips pick up the ``Assistant`` role.
        """
        if not self._running:
            return ""

        if destination_target is None and destination_role is None:
            allowed, destination_target, destination_role = self._resolve_direct_playback_route(
                source="conversation_pipeline",
                text=text,
            )
            if not allowed:
                return ""
        destination = destination or _destination_value_for_route(
            destination_target=destination_target,
            destination_role=destination_role,
        )

        # Apply grounding context clause gate
        if hasattr(self, "_current_envelope") and self._current_envelope is not None:
            from shared.grounding_context import GroundingContextVerifier

            is_safe, reason = GroundingContextVerifier.verify_clause(self._current_envelope, text)
            if not is_safe:
                log.warning("Clause gate rejected sentence: %r (reason: %s)", text, reason)
                text = f"I cannot verify that right now. {reason}."
                self._emit("clause_gate_refusal", reason=reason)

        # Track for echo detection — store with timestamp for TTL pruning
        self._recent_tts_texts.append((time.monotonic(), text.lower().strip().rstrip(".,!?")))
        if len(self._recent_tts_texts) > self._max_tts_history:
            self._recent_tts_texts.pop(0)

        try:
            _t0 = time.monotonic()
            # Strip emoji before TTS — they synthesize as Unicode names
            # or silence. Keep original in echo detection history.
            tts_text = _strip_emoji(text)
            if not tts_text.strip():
                from agents.hapax_daimonion.voice_output_witness import (
                    record_drop,
                    record_tts_synthesis,
                )

                record_tts_synthesis(status="empty", text=text, pcm=b"")
                record_drop(
                    reason="tts_empty_text",
                    source="conversation_pipeline",
                    destination=destination,
                    target=destination_target,
                    media_role=destination_role,
                    text=text,
                    terminal_state="failed",
                )
                return ""  # text was only emoji

            loop = asyncio.get_running_loop()
            try:
                pcm = await loop.run_in_executor(
                    _tts_executor,
                    self.tts.synthesize,
                    tts_text,
                    "conversation",
                )
            except Exception as exc:
                from agents.hapax_daimonion.voice_output_witness import (
                    record_drop,
                    record_tts_synthesis,
                )

                record_tts_synthesis(status="failed", text=tts_text, error=str(exc))
                record_drop(
                    reason="tts_synthesis_failed",
                    source="conversation_pipeline",
                    destination=destination,
                    target=destination_target,
                    media_role=destination_role,
                    text=tts_text,
                    terminal_state="failed",
                )
                raise
            _t_synth = time.monotonic()
            _tts_ms = (_t_synth - _t0) * 1000
            from agents.hapax_daimonion.voice_output_witness import (
                record_drop,
                record_playback_result,
                record_tts_synthesis,
            )

            if pcm:
                record_tts_synthesis(status="completed", text=tts_text, pcm=pcm)
            else:
                record_tts_synthesis(status="empty", text=tts_text, pcm=b"")
                record_drop(
                    reason="tts_empty_pcm",
                    source="conversation_pipeline",
                    destination=destination,
                    target=destination_target,
                    media_role=destination_role,
                    text=tts_text,
                    terminal_state="failed",
                )
                return ""
            if self._audio_output:
                log.info(
                    "TIMING tts_synth=%.0fms play=%db text=%r",
                    _tts_ms,
                    len(pcm),
                    text[:40],
                )
                from agents._telemetry import hapax_event

                hapax_event(
                    "voice",
                    "tts_synth",
                    metadata={
                        "tts_ms": round(_tts_ms),
                        "pcm_bytes": len(pcm),
                        "text_len": len(tts_text),
                    },
                )
                # Write audio in background — streaming loop continues
                # immediately so next clause can start synthesizing.
                # _audio_executor is single-threaded so writes are ordered.
                ao = self._audio_output
                ec = self._echo_canceller
                loop.run_in_executor(
                    _audio_executor,
                    self._write_audio,
                    ao,
                    ec,
                    pcm,
                    destination_target,
                    destination_role,
                    text,
                    destination,
                )
            else:
                from agents.hapax_daimonion.pw_audio_output import PlaybackResult

                playback_result = PlaybackResult(
                    status="failed",
                    returncode=None,
                    duration_s=len(pcm)
                    / (_VOICE_OUTPUT_SAMPLE_RATE_HZ * _VOICE_OUTPUT_BYTES_PER_SAMPLE),
                    timeout_s=0.0,
                    target=destination_target,
                    media_role=destination_role or "Assistant",
                    error="audio output unavailable",
                )
                record_playback_result(
                    text=text,
                    playback_result=playback_result,
                    destination=destination,
                    target=destination_target,
                    media_role=destination_role or "Assistant",
                )
            return text
        except Exception:
            log.debug("TTS/playback failed for: %s", text[:50], exc_info=True)
            return ""

    @staticmethod
    def _write_audio(
        audio_output,
        echo_canceller,
        pcm: bytes,
        destination_target: str | None = None,
        destination_role: str | None = None,
        text: str | None = None,
        destination: str | None = None,
    ) -> None:
        """Write PCM to audio output and feed AEC reference. Runs in _audio_executor.

        Reference is fed BEFORE playback so the canceller has the expected
        signal queued when the echo arrives at the microphone (~5-20ms later).

        ``destination_target`` and ``destination_role`` are mandatory for
        playback. Missing route metadata is treated as an unsafe default-sink
        attempt and is dropped.

        ``destination_role`` selects the WirePlumber loopback for the resolved
        route. This method never intentionally writes to the constructor
        default.
        """
        try:
            if destination_target is None or destination_role is None:
                log.warning("refusing PCM playback without a complete semantic route")
                if text is not None:
                    from agents.hapax_daimonion.voice_output_witness import record_drop

                    record_drop(
                        reason="semantic_route_incomplete",
                        source="conversation_pipeline",
                        destination=destination or "unknown",
                        target=destination_target,
                        media_role=destination_role,
                        text=text,
                        terminal_state="inhibited",
                    )
                return
            if echo_canceller:
                echo_canceller.feed_reference(pcm)
            else:
                log.debug("_write_audio: echo_canceller is None!")
            kwargs: dict[str, str] = {}
            kwargs["target"] = destination_target
            kwargs["media_role"] = destination_role
            try:
                playback_result = audio_output.write(pcm, **kwargs)
            except TypeError:
                # A semantic route was explicitly requested. If the output
                # shim cannot honor it, dropping is safer than default audio.
                log.warning(
                    "audio output lacks target=/media_role= kwargs; dropping routed audio",
                    exc_info=True,
                )
                from agents.hapax_daimonion.pw_audio_output import PlaybackResult

                playback_result = PlaybackResult(
                    status="failed",
                    returncode=None,
                    duration_s=len(pcm)
                    / (_VOICE_OUTPUT_SAMPLE_RATE_HZ * _VOICE_OUTPUT_BYTES_PER_SAMPLE),
                    timeout_s=0.0,
                    target=destination_target,
                    media_role=destination_role,
                    error="audio output route kwargs unsupported",
                )
            if text is not None:
                from agents.hapax_daimonion.pw_audio_output import PlaybackResult
                from agents.hapax_daimonion.voice_output_witness import record_playback_result

                if getattr(playback_result, "status", None) not in {
                    "completed",
                    "failed",
                    "timeout",
                    "spawn_failed",
                }:
                    playback_result = PlaybackResult(
                        status="completed",
                        returncode=0,
                        duration_s=len(pcm)
                        / (_VOICE_OUTPUT_SAMPLE_RATE_HZ * _VOICE_OUTPUT_BYTES_PER_SAMPLE),
                        timeout_s=0.0,
                        target=destination_target,
                        media_role=destination_role,
                    )
                record_playback_result(
                    text=text,
                    playback_result=playback_result,
                    destination=destination
                    or _destination_value_for_route(
                        destination_target=destination_target,
                        destination_role=destination_role,
                    ),
                    target=destination_target,
                    media_role=destination_role,
                )
        except Exception:
            pass

    async def _prewarm_llm(self) -> None:
        """Pre-warm the grounded-LLM path via TCP connect (no billable call).

        Grounding-acts (autonomous_narrative, spontaneous_speech, fortress
        daily) route to TabbyAPI at :5000 via LiteLLM. A raw TCP connect
        validates the grounded endpoint is reachable and warms the kernel
        socket cache without consuming tokens.

        The previous 1-token litellm.acompletion paid a full round-trip
        (provider selection, httpx pool warmup, token accounting) solely
        to warm one hop — wasteful once grounding-acts pinned to local.
        """
        if self._llm_prewarmed:
            return
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", 5000), timeout=0.5
            )
            writer.close()
            await writer.wait_closed()
            self._llm_prewarmed = True
            log.debug("LLM connection pre-warmed (TCP ping)")
        except Exception:
            log.debug("LLM prewarm failed (non-fatal)", exc_info=True)

    def _open_audio_output(self) -> None:
        """Open PipeWire audio output without trusting legacy default targets."""
        try:
            import os

            from agents.hapax_daimonion.pw_audio_output import PwAudioOutput

            legacy_target = os.environ.get("HAPAX_TTS_TARGET") or None
            self._audio_output = PwAudioOutput(sample_rate=24000, channels=1, target=None)
            if legacy_target:
                log.warning(
                    "Ignoring legacy HAPAX_TTS_TARGET=%s; per-utterance semantic routing required",
                    legacy_target,
                )
        except Exception:
            log.exception("Failed to open audio output")

    def _close_audio_output(self) -> None:
        """Close the audio output stream."""
        if self._audio_output:
            try:
                self._audio_output.close()
            except Exception:
                pass
            self._audio_output = None

    def get_session_digest(self) -> dict:
        """Generate a digest of the current conversation for cross-session memory.

        Returns dict with thread summary, turn count, dominant topic,
        conceptual pacts, and unresolved discourse units.
        Used by the daemon to persist session memory via EpisodeStore.
        """
        if not self._conversation_thread:
            return {}

        # Dominant topic: most common significant words across thread entries
        word_counts: dict[str, int] = {}
        for entry in self._conversation_thread:
            text = entry.user_text if isinstance(entry, ThreadEntry) else entry
            for word in text.lower().split():
                if len(word) >= 4 and word.isalpha():
                    word_counts[word] = word_counts.get(word, 0) + 1

        top_words = sorted(word_counts, key=word_counts.get, reverse=True)[:5]  # type: ignore[arg-type]

        # Extract thread text for storage (backward-compatible list[str])
        thread_texts = []
        for entry in self._conversation_thread[-10:]:
            if isinstance(entry, ThreadEntry):
                thread_texts.append(f"{entry.user_text} → {entry.response_summary}")
            else:
                thread_texts.append(entry)

        # Unresolved DUs: entries still in-repair or ungrounded at session end
        unresolved = []
        for entry in self._conversation_thread:
            if isinstance(entry, ThreadEntry) and entry.grounding_state in (
                "in-repair",
                "ungrounded",
            ):
                unresolved.append(f"T{entry.turn}: {entry.user_text[:60]}")

        return {
            "thread": thread_texts,
            "turn_count": self.turn_count,
            "topic_words": top_words,
            "session_id": self._session_id,
            "start_ts": getattr(self, "_session_start_ts", time.time()),
            "unresolved": unresolved,
        }

    def check_sentinel_retrieval(self, response: str) -> float | None:
        """Check if a response correctly uses the sentinel fact.

        Returns score (1.0 = correct, 0.0 = wrong number, None = not a probe).
        """
        sentinel = getattr(self, "_sentinel_number", None)
        if sentinel is None:
            return None

        import re as _re

        numbers = _re.findall(r"\b\d{2}\b", response)
        if not numbers:
            return None

        score = 1.0 if str(sentinel) in numbers else 0.0
        try:
            from agents._telemetry import hapax_event

            hapax_event(
                "voice",
                "sentinel_retrieval",
                metadata={
                    "sentinel": sentinel,
                    "response_numbers": numbers,
                    "correct": score == 1.0,
                    "session_id": self._session_id,
                },
            )
        except Exception:
            pass
        return score

    def _emit(self, event_type: str, **kwargs) -> None:
        if self.event_log:
            try:
                self.event_log.emit(event_type, **kwargs)
            except Exception:
                pass
