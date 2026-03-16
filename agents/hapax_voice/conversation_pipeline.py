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

log = logging.getLogger(__name__)

_tts_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")

# Sentence boundary pattern for TTS chunking
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+|(?<=\n)")
_MIN_SENTENCE_WORDS = 4
_MAX_ACCUMULATION_S = 2.0
_MAX_RESPONSE_TOKENS = 256
_MAX_TURNS = 20
_SILENCE_TIMEOUT_S = 30.0


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

        self.state = ConvState.IDLE
        self.messages: list[dict] = []
        self.turn_count = 0
        self._running = False
        self._task: asyncio.Task | None = None
        self._audio_output = None
        self._last_env_hash: int = 0

        # Observation signal tracking (Batch 4: revealed preferences)
        self._last_assistant_end: float = 0.0  # monotonic time when last response finished
        self._last_user_topic: str = ""  # rough topic tracking for abandonment detection

    @property
    def is_active(self) -> bool:
        return self._running and self.state != ConvState.IDLE

    async def start(self) -> None:
        """Start the conversation pipeline."""
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.turn_count = 0
        self._running = True
        self.state = ConvState.LISTENING

        # Refresh consent contracts to pick up any new ones
        if self._consent_reader:
            self._consent_reader.reload_contracts()

        if self.buffer:
            self.buffer.activate()

        self._open_audio_output()
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

    def _update_system_context(self) -> None:
        """Refresh system message with current environment and policy blocks."""
        if not self.messages:
            return

        updated = self.system_prompt

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

        # STT
        self.state = ConvState.TRANSCRIBING
        transcript = await self.stt.transcribe(audio_bytes)
        if not transcript:
            self.state = ConvState.LISTENING
            return

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

        # Refresh environment context before LLM call
        self._update_system_context()

        # LLM → TTS
        self.state = ConvState.THINKING
        await self._generate_and_speak()

        # Check limits
        if self.turn_count >= _MAX_TURNS:
            log.info("Max turns reached, ending conversation")
            await self.stop()
            return

        self.state = ConvState.LISTENING

    async def _generate_and_speak(self) -> None:
        """Stream LLM response, accumulate sentences, synthesize and play."""
        try:
            import os

            import litellm

            # Compress history if it's grown long enough
            if self.turn_count > 6:
                try:
                    from shared.context_compression import compress_history

                    self.messages = compress_history(self.messages, keep_recent=4)
                except Exception:
                    log.debug("History compression failed (non-fatal)", exc_info=True)

            kwargs = {
                "model": f"openai/{self.llm_model}",
                "messages": self.messages,
                "stream": True,
                "max_tokens": _MAX_RESPONSE_TOKENS,
                "temperature": 0.7,
                "api_base": os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000"),
                "api_key": os.environ.get("LITELLM_API_KEY", "not-set"),
            }
            if self.tools:
                kwargs["tools"] = self.tools

            response = await litellm.acompletion(**kwargs)

            full_text = ""
            accumulated = ""
            tool_calls_data: list[dict] = []
            accumulation_start = time.monotonic()

            self.state = ConvState.SPEAKING
            if self.buffer:
                self.buffer.set_speaking(True)

            async for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
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

                full_text += content
                accumulated += content

                # Check for sentence boundary
                parts = _SENTENCE_END.split(accumulated)
                if len(parts) > 1:
                    for sentence in parts[:-1]:
                        sentence = sentence.strip()
                        if sentence and len(sentence.split()) >= _MIN_SENTENCE_WORDS:
                            await self._speak_sentence(sentence)
                            # Barge-in: operator spoke over us — stop and yield
                            if self.buffer and self.buffer.barge_in_detected:
                                log.info("Barge-in: cutting response short")
                                break
                    accumulated = parts[-1]
                    accumulation_start = time.monotonic()
                elif (time.monotonic() - accumulation_start) > _MAX_ACCUMULATION_S:
                    if accumulated.strip():
                        await self._speak_sentence(accumulated.strip())
                        accumulated = ""
                        accumulation_start = time.monotonic()

                # Barge-in: break out of LLM stream
                if self.buffer and self.buffer.barge_in_detected:
                    break

            # Flush remaining text (skip if barge-in — operator is talking)
            if accumulated.strip() and not (self.buffer and self.buffer.barge_in_detected):
                await self._speak_sentence(accumulated.strip())

            # Record assistant message (even partial on barge-in)
            if full_text:
                self.messages.append({"role": "assistant", "content": full_text})
                if self.buffer and self.buffer.barge_in_detected:
                    self._emit("assistant_interrupted", text=full_text)
                    self._emit("user_interrupted", turn=self.turn_count)
                else:
                    self._emit("assistant_response", text=full_text)
                self._last_assistant_end = time.monotonic()

            # Handle tool calls
            if tool_calls_data:
                await self._handle_tool_calls(tool_calls_data, full_text)

        except TimeoutError:
            log.warning("LLM timeout — no response")
            await self._speak_sentence("I'm having trouble connecting right now.")
        except Exception:
            log.exception("LLM generation failed")
            await self._speak_sentence("Sorry, something went wrong.")
        finally:
            if self.buffer:
                self.buffer.set_speaking(False)

    async def _handle_tool_calls(self, tool_calls: list[dict], assistant_text: str) -> None:
        """Execute tool calls and generate follow-up response."""
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

    # ── Bridge Phrases ────────────────────────────────────────────────

    _GREETING_BRIDGES = ("Hey.", "Yep.", "Mm-hmm.", "Yeah.")
    _THINKING_BRIDGES = (
        "Let me think.",
        "One sec.",
        "Hmm.",
        "Give me a moment.",
        "On it.",
        "Thinking.",
        "Let me check.",
    )
    _bridge_idx: int = 0

    async def _speak_bridge(self) -> None:
        """Speak a brief bridge phrase to fill dead air during LLM processing.

        First turn gets a greeting acknowledgment ("Hey.", "Yep.").
        Subsequent turns get a thinking bridge ("Let me think.", "One sec.").
        Skipped when the previous response was very recent (rapid back-and-forth).
        """
        # Skip if last response was < 2s ago (rapid exchange, no dead air)
        if self._last_assistant_end > 0:
            gap = time.monotonic() - self._last_assistant_end
            if gap < 2.0:
                return

        # Pick appropriate phrase
        if self.turn_count <= 1:
            phrases = self._GREETING_BRIDGES
        else:
            phrases = self._THINKING_BRIDGES
        phrase = phrases[self._bridge_idx % len(phrases)]
        self._bridge_idx += 1

        # Suppress mic during bridge phrase
        if self.buffer:
            self.buffer.set_speaking(True)
        await self._speak_sentence(phrase)
        if self.buffer:
            self.buffer.set_speaking(False)

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
        """Synthesize and play a single sentence."""
        if not self._running:
            return

        try:
            loop = asyncio.get_running_loop()
            pcm = await loop.run_in_executor(
                _tts_executor,
                self.tts.synthesize,
                text,
                "conversation",
            )
            if pcm and self._audio_output:
                self._audio_output.write(pcm)
        except Exception:
            log.debug("TTS/playback failed for: %s", text[:50], exc_info=True)

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

    def _emit(self, event_type: str, **kwargs) -> None:
        if self.event_log:
            try:
                self.event_log.emit(event_type, **kwargs)
            except Exception:
                pass
