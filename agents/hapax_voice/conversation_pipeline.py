"""Conversation pipeline — lightweight async voice interaction.

Replaces Pipecat with a simple state machine:
IDLE → LISTENING → TRANSCRIBING → THINKING → SPEAKING → LISTENING

The mic stays shared. Models stay resident. No framework.
~250 lines replacing ~600 lines of Pipecat integration.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents.hapax_voice.config import LITELLM_BASE as _voice_litellm_base

log = logging.getLogger(__name__)

_tts_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")
_audio_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio-out")

# Emoji pattern: matches most emoji ranges (emoticons, symbols, flags, etc.)
_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f1e0-\U0001f1ff"  # flags
    "\U00002702-\U000027b0"  # dingbats
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"  # chess symbols
    "\U0001fa70-\U0001faff"  # symbols extended-A
    "\U00002600-\U000026ff"  # misc symbols
    "\U0000200d"  # zero width joiner
    "\U0000231a-\U0000231b"  # watch/hourglass
    "\U00002934-\U00002935"  # arrows
    "\U000025aa-\U000025ab"  # squares
    "\U000025fb-\U000025fe"  # squares
    "\U00002b05-\U00002b07"  # arrows
    "\U00002b1b-\U00002b1c"  # squares
    "\U00002b50\U00002b55"  # star/circle
    "\U00003030\U0000303d"  # wavy dash
    "\U00003297\U00003299"  # ideographs
    "]+",
    flags=re.UNICODE,
)


def _strip_emoji(text: str) -> str:
    """Remove emoji from text, preserving surrounding words."""
    return _EMOJI_RE.sub("", text).strip()


_GREETING_PREFIX_RE = re.compile(
    r"^(?:hey|hi|hello|yo)\s+hapax[,;:\s]*",
    flags=re.IGNORECASE,
)


def _extract_substance(text: str) -> str:
    """Strip greeting prefixes before extracting the first clause.

    "Hey hapax, what's the weather" → "what's the weather"
    """
    stripped = _GREETING_PREFIX_RE.sub("", text).strip()
    if not stripped:
        stripped = text
    return stripped.split(",")[0].split(".")[0][:60]


def _lcs_word_length(a: list[str], b: list[str]) -> int:
    """Longest common subsequence length between two word lists.

    O(n*m) but lists are short (voice utterances < 30 words).
    """
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return 0
    # Space-optimized: two rows
    prev = [0] * (n + 1)
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, [0] * (n + 1)
    return prev[n]


# Clause boundary pattern for TTS chunking (Phase 3a: clause-level for earlier first audio)
_CLAUSE_END = re.compile(r"(?<=[.!?;:])\s+|(?<=\n)|(?<=,)\s+|(?<=—)\s*")
_MIN_CLAUSE_WORDS = 2
_MIN_FIRST_CLAUSE_WORDS = 3  # First audio: enough words to avoid false turn-boundary pauses
_MAX_ACCUMULATION_S = 0.3
# Response length per tier — the ramp IS the length. Short casual
# responses at LOCAL feel like warmup; longer responses at CAPABLE
# feel like deep engagement. This shapes conversational cadence.
# Voice responses must be SHORT. Nobody wants to listen to a 30-second
# monologue. 1-3 sentences at most tiers, up to 4-5 for deep questions.
# Calibrated from live conversation: operator barged in on every response
# because they were too long.
# Voice response token budget — hard ceiling. 150 tokens ≈ 2-3 spoken
# sentences. Enough for substance, not enough for monologue. Opus will
# self-regulate shorter via system prompt; this prevents runaway responses
# that blow past TTS pipeline capacity and trigger 20s timeouts.
_TIER_MAX_TOKENS: dict[str, int] = {
    "CANNED": 0,
    "LOCAL": 80,
    "FAST": 150,
    "STRONG": 150,
    "CAPABLE": 150,
}
_MAX_RESPONSE_TOKENS = 150
_MAX_SPOKEN_WORDS = 35  # Default cutoff (overridden by density-driven limit)

# Bayesian Tier 1: density-driven word limits from visual layer display_density
_DENSITY_WORD_LIMITS: dict[str, int] = {
    "presenting": 15,  # meetings: absolute minimum
    "focused": 20,  # deep work: brief
    "ambient": 35,  # baseline: current value
    "receptive": 50,  # between tasks: can elaborate
}
_MAX_TURNS = 20
_SILENCE_TIMEOUT_S = 30.0

_VLS_PATH = "/dev/shm/hapax-compositor/visual-layer-state.json"


def _density_word_limit() -> int:
    """Read display density from visual layer state and return word limit."""
    try:
        vls = json.loads(Path(_VLS_PATH).read_text())
        density = vls.get("display_density", "ambient")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        density = "ambient"
    return _DENSITY_WORD_LIMITS.get(density, _MAX_SPOKEN_WORDS)


def _stimmung_downgrade(model: str, tier: ModelTier) -> tuple[str, ModelTier]:
    """Apply stimmung-aware downgrade to voice model selection.

    Reads live stimmung from /dev/shm. Under resource/cost pressure or
    critical stance, downgrades the selected model to a cheaper tier.
    This is allostatic regulation — the voice pipeline participates in
    system self-preservation instead of being disconnected from stimmung.

    Returns (model, tier) — unchanged if nominal or stimmung unavailable.
    """
    from pathlib import Path

    from agents.hapax_voice.model_router import TIER_ROUTES, ModelTier

    try:
        raw = json.loads(Path("/dev/shm/hapax-stimmung/state.json").read_text(encoding="utf-8"))
    except Exception:
        return model, tier

    stance = raw.get("overall_stance", "nominal")
    resource = raw.get("resource_pressure", {}).get("value", 0.0)
    cost = raw.get("llm_cost_pressure", {}).get("value", 0.0)

    # Critical stance: check what's driving it
    # Health/resource critical → slam to LOCAL (infrastructure at risk)
    # Cost critical alone → downgrade one tier (budget, not safety)
    if stance == "critical":
        health = raw.get("health", {}).get("value", 0.0)
        if health >= 0.85 or resource >= 0.85:
            log.info("Stimmung critical (health/resource) → voice downgrade to LOCAL")
            return TIER_ROUTES[ModelTier.LOCAL], ModelTier.LOCAL
        if tier.value > ModelTier.LOCAL.value:
            new_tier = ModelTier(tier.value - 1)
            log.info("Stimmung critical (cost) → voice %s → %s", tier.name, new_tier.name)
            return TIER_ROUTES[new_tier], new_tier
        return model, tier

    # Resource pressure > 0.7: drop one tier
    if resource > 0.7 and tier.value > ModelTier.LOCAL.value:
        new_tier = ModelTier(tier.value - 1)
        log.info(
            "Stimmung resource pressure %.2f → voice %s → %s",
            resource,
            tier.name,
            new_tier.name,
        )
        return TIER_ROUTES[new_tier], new_tier

    # Cost pressure > 0.6: CAPABLE → STRONG, STRONG → FAST
    if cost > 0.6 and tier.value >= ModelTier.STRONG.value:
        new_tier = ModelTier(tier.value - 1)
        log.info(
            "Stimmung cost pressure %.2f → voice %s → %s",
            cost,
            tier.name,
            new_tier.name,
        )
        return TIER_ROUTES[new_tier], new_tier

    return model, tier


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
        self._screen_capturer = screen_capturer
        self._echo_canceller = echo_canceller
        self._bridge_engine = bridge_engine
        self._experiment_flags = experiment_flags or {}

        self.state = ConvState.IDLE
        self.messages: list[dict] = []
        self.turn_count = 0
        self._running = False
        self._task: asyncio.Task | None = None
        self._audio_output = None
        self._last_env_hash: int = 0
        self._session_id: str = ""
        self._activity_mode: str = "idle"
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
        self._conversation_thread: list[str] = []

        # Frustration detection (Batch 4)
        self._frustration_detector = None

    @property
    def is_active(self) -> bool:
        return self._running and self.state != ConvState.IDLE

    async def start(self) -> None:
        """Start the conversation pipeline."""
        import random
        import uuid

        self._session_id = uuid.uuid4().hex[:12]
        self._session_start_ts = time.time()
        self._conversation_thread = []

        # Generate sentinel fact for probe question testing
        self._sentinel_number = random.randint(10, 99)
        self._sentinel_line = (
            f"\n\nInternal test fact: The operator's favorite number this session is "
            f"{self._sentinel_number}. If asked about their favorite number, use this."
        )
        # Sentinel injected by _update_system_context, not here — survives rebuilds
        self.messages = [{"role": "system", "content": self.system_prompt}]

        # Create frustration detector for this session
        from agents.hapax_voice.frustration_detector import FrustrationDetector

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
        """Stop the conversation pipeline."""
        self._running = False
        self.state = ConvState.IDLE

        if self.buffer:
            self.buffer.deactivate()

        self._close_audio_output()
        self._emit("conversation_end", turns=self.turn_count)
        log.info("Conversation pipeline stopped (%d turns)", self.turn_count)

    # Compressed prompt for LOCAL tier — gemma3:4b can't follow complex instructions.
    # ~200 tokens instead of ~1300. Just enough personality to not be generic.
    _LOCAL_SYSTEM_PROMPT = (
        "You are Hapax, a voice assistant for Ryan (system architect, hip-hop producer). "
        "Be brief (1-2 sentences), warm, direct, genuinely helpful. Dry wit welcome. "
        "Never condescend. Answer first, then reasoning if needed. "
        "Don't say 'I'm just an AI' or hedge unnecessarily."
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

        # Conversation thread: accumulated topic summaries (~15 tokens each)
        if self._conversation_thread and self._experiment_flags.get("stable_frame", True):
            thread_text = "\n".join(f"- {entry}" for entry in self._conversation_thread)
            updated += f"\n\n## Conversation So Far\n{thread_text}"

        # Sentinel fact: injected here so it survives system prompt rebuilds
        if self._experiment_flags.get("sentinel", True) and hasattr(self, "_sentinel_line"):
            updated += self._sentinel_line

        # ── VOLATILE band: environment + policy + salience ─────────────
        # Refresh conversational policy (adapts to environment changes)
        if self._policy_fn is not None:
            try:
                policy = self._policy_fn()
                if policy:
                    updated += policy
            except Exception:
                log.debug("policy_fn failed (non-fatal)", exc_info=True)

        # Append environment TOON block
        if self._env_context_fn is not None:
            try:
                env_toon = self._env_context_fn()
                if env_toon:
                    updated += "\n\n## Current Environment\n" + env_toon
            except Exception:
                log.debug("env_context_fn failed (non-fatal)", exc_info=True)

        # Phenomenal context: temporal bands + self-band — always full fidelity
        try:
            from agents.hapax_voice.phenomenal_context import render as render_phenomenal

            phenom = render_phenomenal(tier="CAPABLE")
            if phenom:
                updated += "\n\n" + phenom
        except Exception:
            log.debug("phenomenal context render failed (non-fatal)", exc_info=True)

        # Salience context: activation signals from the concern graph,
        # injected as orientation so the model can self-modulate response
        # depth and investment. Replaces tier-based gating.
        try:
            salience_ctx = self._build_salience_context()
            if salience_ctx:
                updated += "\n\n## Conversational Salience\n" + salience_ctx
        except Exception:
            log.debug("salience context build failed (non-fatal)", exc_info=True)

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

        from shared.telemetry import hapax_bool_score, hapax_event, hapax_score, hapax_trace

        _t_start = time.monotonic()
        _utt_trace_cm = hapax_trace(
            "voice",
            "utterance",
            session_id=getattr(self, "_session_id", None),
            metadata={"turn": self.turn_count, "audio_bytes": len(audio_bytes)},
        )
        _utt_trace = _utt_trace_cm.__enter__()

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
            from shared.governance.consent_context import maybe_principal
            from shared.governance.says import Says

            speaker_principal = maybe_principal()
            if speaker_principal is not None:
                self._last_says = Says.unit(speaker_principal, transcript)
            else:
                self._last_says = None
        except Exception:
            self._last_says = None

        self._emit("user_utterance", text=transcript)

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

        # ── Model routing: intelligence-first ────────────────────────
        # Always CAPABLE (claude-opus) except CANNED for pure phatic.
        # The salience router still computes activation/novelty/concern
        # signals — these are injected into the model's context (Batch 2)
        # rather than used to select a tier.
        from agents.hapax_voice.model_router import TIER_ROUTES, ModelTier

        if self._salience_router is not None:
            routing = self._salience_router.route(
                transcript,
                turn_count=self.turn_count,
                activity_mode=self._activity_mode,
                consent_phase=self._consent_phase,
                guest_mode=self._guest_mode,
                face_count=self._face_count,
                has_tools=bool(self.tools),
            )
            # Keep CANNED for zero-latency phatic, upgrade everything else
            if routing.tier != ModelTier.CANNED:
                routing = routing.__class__(
                    tier=ModelTier.CAPABLE,
                    model=TIER_ROUTES[ModelTier.CAPABLE],
                    reason=f"intelligence_first:{routing.reason}",
                    canned_response="",
                )
        else:
            # No salience router — default to CAPABLE
            from agents.hapax_voice.model_router import RoutingDecision

            routing = RoutingDecision(
                tier=ModelTier.CAPABLE,
                model=TIER_ROUTES[ModelTier.CAPABLE],
                reason="intelligence_first:default",
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
                if self._echo_canceller:
                    self._echo_canceller.feed_reference(pcm)
                self._audio_output.write(pcm)
                if self.buffer:
                    self.buffer.set_speaking(False)
            else:
                await self._speak_sentence(routing.canned_response)
            self.messages.append({"role": "assistant", "content": routing.canned_response})
            self._emit("assistant_response", text=routing.canned_response)
            self._last_assistant_end = time.monotonic()
            self.state = ConvState.LISTENING
            return

        # Intelligence is the LAST thing to shed under stimmung pressure.
        # Stimmung state is fed into model context (Batch 3) instead of
        # downgrading the model. Vision, perception cadence, workspace
        # analysis get shed first.
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
            await asyncio.wait_for(llm_task, timeout=20.0)
        except TimeoutError:
            log.warning("LLM task timed out after 20s")
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
            from agents.hapax_voice.grounding_evaluator import evaluate_turn

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
                evaluate_turn(
                    response=_last_response,
                    messages=self.messages,
                    conversation_thread=self._conversation_thread,
                    user_utterance=transcript,
                    langfuse_trace=_utt_trace,
                )

                # Probe question: check sentinel retrieval
                sentinel_score = self.check_sentinel_retrieval(_last_response)
                if sentinel_score is not None:
                    hapax_score(_utt_trace, "sentinel_retrieval", sentinel_score)

                # Update conversation thread with this turn's summary
                _user_clause = _extract_substance(transcript)
                _resp_clause = _last_response.split(",")[0].split(".")[0][:60]
                self._conversation_thread.append(f"{_user_clause} → {_resp_clause}")
                if len(self._conversation_thread) > 15:
                    self._conversation_thread = self._conversation_thread[-15:]
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
        try:
            _utt_trace_cm.__exit__(None, None, None)
        except Exception:
            pass

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
            if self._experiment_flags.get("message_drop", True) and len(self.messages) > 12:
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

            # LOCAL tier: phenomenal context replaces the old context_distillation.
            # Identity + orientation in ~60 tokens. The phenomenal renderer
            # returns layers 1-3 for LOCAL (stimmung + situation + impression),
            # which is a directionally faithful rendering of the same temporal
            # structure that CAPABLE gets in full — just at lower fidelity.
            _messages = self.messages
            if _tier_name == "LOCAL" and _messages and _messages[0].get("role") == "system":
                try:
                    from agents.hapax_voice.phenomenal_context import render as render_phenom

                    phenom = render_phenom(tier="LOCAL")
                except Exception:
                    phenom = self._context_distillation  # fallback to old distillation
                _messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are Hapax, a voice assistant. Be warm, brief, and casual. "
                            "1-2 short sentences max. Match the operator's energy — if they're "
                            "just checking in, keep it light. Don't volunteer system status "
                            "or technical details unless specifically asked."
                            + (f"\n\n{phenom}" if phenom else "")
                        ),
                    },
                    *_messages[1:],
                ]

            kwargs = {
                "model": f"openai/{_model}",
                "messages": _messages,
                "stream": True,
                "max_tokens": _TIER_MAX_TOKENS.get(
                    getattr(self, "_turn_model_tier", ""), _MAX_RESPONSE_TOKENS
                ),
                "temperature": 0.7,
                "api_base": _voice_litellm_base,
                "api_key": os.environ.get("LITELLM_API_KEY", "not-set"),
            }
            # Tools disabled for voice pacing — tool execution + second LLM
            # round-trip adds 10-15s latency that destroys conversation flow.
            # The model answers from system prompt context instead.
            # if self.tools:
            #     kwargs["tools"] = self.tools

            kwargs["timeout"] = 15  # seconds — fail fast, don't block conversation
            _t_llm_start = time.monotonic()
            response = await litellm.acompletion(**kwargs)

            full_text = ""
            accumulated = ""
            tool_calls_data: list[dict] = []
            accumulation_start = time.monotonic()
            _t_first_token = 0.0
            _t_first_audio = 0.0
            _first_clause_spoken = False
            _spoken_words = 0  # Track words sent to TTS for cutoff
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
                        await self._speak_sentence(cut)
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
                            await self._speak_sentence(to_speak)
                            _first_clause_spoken = True
                            # Speak any complete middle clauses too (don't drop them)
                            for mid in parts[1:-1]:
                                mid = mid.strip()
                                if mid and len(mid.split()) >= _MIN_CLAUSE_WORDS:
                                    await self._speak_sentence(mid)
                            accumulated = parts[-1]
                            accumulation_start = time.monotonic()
                    elif _elapsed > _MAX_ACCUMULATION_S and _words >= _MIN_FIRST_CLAUSE_WORDS:
                        await self._speak_sentence(accumulated.strip())
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
                                await self._speak_sentence(sentence)
                                _spoke = True
                                if self.buffer and self.buffer.barge_in_detected:
                                    log.info("Barge-in: cutting response short")
                                    break
                        accumulated = parts[-1]
                        if _spoke:
                            accumulation_start = time.monotonic()
                    elif _elapsed > _MAX_ACCUMULATION_S:
                        if accumulated.strip() and _words >= _MIN_CLAUSE_WORDS:
                            await self._speak_sentence(accumulated.strip())
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
                    await self._speak_sentence(accumulated.strip())

            # Log full response for debugging truncation
            if full_text:
                log.info("LLM full response (%d chars): %r", len(full_text), full_text[:200])

            # Record assistant message (even partial on barge-in)
            # Only append here if there are NO tool calls — _handle_tool_calls
            # appends its own assistant message with the tool_calls structure.
            if full_text and not tool_calls_data:
                self.messages.append({"role": "assistant", "content": full_text})
                if self.buffer and self.buffer.barge_in_detected:
                    self._emit("assistant_interrupted", text=full_text)
                    self._emit("user_interrupted", turn=self.turn_count)
                else:
                    self._emit("assistant_response", text=full_text)
                self._last_assistant_end = time.monotonic()

            # Tool calls: skip in voice turns to avoid 10-15s latency penalty.
            # Tool execution + second LLM round-trip eats the 20s timeout budget.
            # The model already has workspace context via system prompt injection;
            # tools add precision but destroy conversational pacing.
            # TODO: re-enable with tight per-tool timeouts (3s cap) once latency
            # is under control.
            if tool_calls_data:
                log.info(
                    "Skipping %d tool call(s) for voice pacing: %s",
                    len(tool_calls_data),
                    [tc["name"] for tc in tool_calls_data],
                )
                # Record as assistant message without executing tools
                if full_text:
                    self.messages.append({"role": "assistant", "content": full_text})

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
            from agents.hapax_voice.bridge_engine import BridgeContext

            ctx = BridgeContext(
                turn_position=self.turn_count,
                response_type="tool-running",
                session_id=self._session_id,
            )
            phrase, pcm = self._bridge_engine.select(ctx)
            if pcm and self._audio_output:
                try:
                    self._audio_output.write(pcm)
                    if self._echo_canceller:
                        self._echo_canceller.feed_reference(pcm)
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
                    result = (
                        await handler(args)
                        if asyncio.iscoroutinefunction(handler)
                        else handler(args)
                    )
                    if not isinstance(result, str):
                        result = json.dumps(result)
                except Exception as e:
                    result = json.dumps({"error": str(e)})

            # Consent gate: filter tool results before they reach the LLM
            if self._consent_reader:
                result = self._consent_reader.filter_tool_result(tc["name"], result)

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

        from agents.hapax_voice.bridge_engine import BridgeContext

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
                self._audio_output.write(pcm)
                if self._echo_canceller:
                    self._echo_canceller.feed_reference(pcm)
            except Exception:
                log.debug("Bridge playback failed", exc_info=True)
        elif phrase:
            await self._speak_sentence(phrase)

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
        # long responses. Base 12s covers 5s cooldown + propagation.
        _ECHO_TTL_S = 12.0

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

            # 3. High-confidence LCS match (≥3 words, ≥70% overlap)
            if word_count >= 3 and len(tts_words) >= 3:
                lcs_len = _lcs_word_length(norm_words, tts_words)
                shorter = min(word_count, len(tts_words))
                if lcs_len / shorter >= 0.70:
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

    async def _speak_sentence(self, text: str) -> None:
        """Synthesize and play a single sentence/clause.

        TTS runs in _tts_executor, audio write runs in _audio_executor.
        Both are single-threaded so clauses play in order, but the async
        loop resumes immediately after synthesis — tokens keep streaming
        from the LLM while audio plays.
        """
        if not self._running:
            return

        # Track for echo detection — store with timestamp for TTL pruning
        self._recent_tts_texts.append((time.monotonic(), text.lower().strip().rstrip(".,!?")))
        if len(self._recent_tts_texts) > self._max_tts_history:
            self._recent_tts_texts.pop(0)

        try:
            _t0 = time.monotonic()
            # Strip emoji before TTS — Kokoro synthesizes them as
            # "smiling face with..." or silence. Keep original in
            # echo detection history (already appended above).
            tts_text = _strip_emoji(text)
            if not tts_text.strip():
                return  # text was only emoji

            loop = asyncio.get_running_loop()
            pcm = await loop.run_in_executor(
                _tts_executor,
                self.tts.synthesize,
                tts_text,
                "conversation",
            )
            _t_synth = time.monotonic()
            _tts_ms = (_t_synth - _t0) * 1000
            if pcm and self._audio_output:
                log.info(
                    "TIMING tts_synth=%.0fms play=%db text=%r",
                    _tts_ms,
                    len(pcm),
                    text[:40],
                )
                from shared.telemetry import hapax_event

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
                )
        except Exception:
            log.debug("TTS/playback failed for: %s", text[:50], exc_info=True)

    @staticmethod
    def _write_audio(audio_output, echo_canceller, pcm: bytes) -> None:
        """Write PCM to audio output and feed AEC reference. Runs in _audio_executor.

        Reference is fed BEFORE playback so the canceller has the expected
        signal queued when the echo arrives at the microphone (~5-20ms later).
        """
        try:
            if echo_canceller:
                echo_canceller.feed_reference(pcm)
            else:
                log.debug("_write_audio: echo_canceller is None!")
            audio_output.write(pcm)
        except Exception:
            pass

    async def _prewarm_llm(self) -> None:
        """Phase 3b: Pre-warm LLM connection at session start.

        Sends a minimal request to warm TCP + LiteLLM route cache +
        upstream provider connection. Saves 200-500ms on first LLM call.
        """
        if self._llm_prewarmed:
            return
        try:
            import os

            import litellm

            await litellm.acompletion(
                model=f"openai/{self.llm_model}",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
                api_base=_voice_litellm_base,
                api_key=os.environ.get("LITELLM_API_KEY", "not-set"),
                timeout=5,
            )
            self._llm_prewarmed = True
            log.debug("LLM connection pre-warmed")
        except Exception:
            log.debug("LLM prewarm failed (non-fatal)", exc_info=True)

    def _open_audio_output(self) -> None:
        """Open PyAudio output stream for TTS playback."""
        try:
            import pyaudio

            pa = pyaudio.PyAudio()
            self._audio_output = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=24000,  # Kokoro output rate
                output=True,
            )
            self._pa = pa
        except Exception:
            log.exception("Failed to open audio output")

    def _close_audio_output(self) -> None:
        """Close the audio output stream."""
        if self._audio_output:
            try:
                self._audio_output.stop_stream()
                self._audio_output.close()
            except Exception:
                pass
            self._audio_output = None
        if hasattr(self, "_pa") and self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass

    def get_session_digest(self) -> dict:
        """Generate a digest of the current conversation for cross-session memory.

        Returns dict with thread summary, turn count, and dominant topic.
        Used by the daemon to persist session memory via EpisodeStore.
        """
        if not self._conversation_thread:
            return {}

        # Dominant topic: most common significant words across thread entries
        word_counts: dict[str, int] = {}
        for entry in self._conversation_thread:
            for word in entry.lower().split():
                if len(word) >= 4 and word.isalpha():
                    word_counts[word] = word_counts.get(word, 0) + 1

        top_words = sorted(word_counts, key=word_counts.get, reverse=True)[:5]  # type: ignore[arg-type]

        return {
            "thread": self._conversation_thread[-10:],
            "turn_count": self.turn_count,
            "topic_words": top_words,
            "session_id": self._session_id,
            "start_ts": getattr(self, "_session_start_ts", time.time()),
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
            from shared.telemetry import hapax_event

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
