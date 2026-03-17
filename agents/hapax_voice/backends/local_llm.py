"""Local LLM perception backend — fast activity/flow classification.

WS5 Tier 2: uses a small local model (qwen2.5:3b via Ollama) for
perception classification. ~200ms on RTX 3090, ~2-3GB VRAM, coexists
with everything else.

Provides:
  - llm_activity: str — LLM-classified activity (coding, writing, browsing, etc.)
  - llm_flow_hint: str — LLM assessment of flow state (deep, light, none)
  - llm_confidence: float — model's self-assessed confidence (0.0-1.0)

Runs on the SLOW tier (every slow tick, ~12s). Falls back gracefully
when Ollama is unavailable.
"""

from __future__ import annotations

import json
import logging
import time

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)

_MODEL = "qwen2.5:3b"
_OLLAMA_TIMEOUT = 5.0  # seconds — hard cap for classification latency

_SYSTEM_PROMPT = """\
You are a perception classifier for an ambient computing system. \
Given a snapshot of the operator's current state, classify their activity and flow.

Respond with ONLY a JSON object, no other text:
{"activity": "<activity>", "flow": "<deep|light|none>", "confidence": <0.0-1.0>}

Activities: coding, writing, browsing, reading, making_music, gaming, \
meeting, presenting, idle, break, exercising, sleeping

Rules:
- "deep" flow = sustained focus, minimal task-switching
- "light" flow = engaged but interruptible
- "none" = idle, between tasks, or distracted
- confidence reflects how certain you are (0.3 = guessing, 0.9 = obvious)
"""


class LocalLLMBackend:
    """PerceptionBackend that classifies activity/flow via local LLM.

    Uses qwen2.5:3b via Ollama for fast (~200ms) structured classification.
    Falls back to no-op when Ollama is unavailable.
    """

    def __init__(self, model: str = _MODEL, timeout: float = _OLLAMA_TIMEOUT) -> None:
        self._model = model
        self._timeout = timeout
        self._b_activity = Behavior[str]("")
        self._b_flow_hint = Behavior[str]("none")
        self._b_confidence = Behavior[float](0.0)
        self._available = False
        self._last_check: float = 0.0
        self._check_interval = 60.0  # re-check availability every 60s
        self._consecutive_errors = 0

        # Context for classification
        self._last_snapshot: dict = {}

    @property
    def name(self) -> str:
        return "local_llm"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"llm_activity", "llm_flow_hint", "llm_confidence"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.SLOW

    def available(self) -> bool:
        return self._check_available()

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()

        # Build context from other behaviors
        snapshot = self._gather_context(behaviors)
        if not snapshot:
            return

        # Classify
        result = self._classify(snapshot)
        if result is not None:
            self._b_activity.update(result["activity"], now)
            self._b_flow_hint.update(result["flow"], now)
            self._b_confidence.update(result["confidence"], now)
            self._consecutive_errors = 0

        behaviors["llm_activity"] = self._b_activity
        behaviors["llm_flow_hint"] = self._b_flow_hint
        behaviors["llm_confidence"] = self._b_confidence

    def start(self) -> None:
        self._available = self._check_available()
        log.info(
            "Local LLM backend started (model=%s, available=%s)",
            self._model,
            self._available,
        )

    def stop(self) -> None:
        log.info("Local LLM backend stopped")

    def set_perception_snapshot(self, snapshot: dict) -> None:
        """Set the latest perception snapshot for context.

        Called by the daemon before each slow tick with the current
        perception state dict.
        """
        self._last_snapshot = snapshot

    def _check_available(self) -> bool:
        """Check if Ollama is reachable and the model is available."""
        now = time.monotonic()
        if now - self._last_check < self._check_interval:
            return self._available
        self._last_check = now

        try:
            import ollama

            client = ollama.Client(timeout=3)
            models = client.list()
            model_names = [m.get("name", m.get("model", "")) for m in models.get("models", [])]
            # Check for model name with or without tag
            self._available = any(
                self._model in name or name.startswith(self._model.split(":")[0])
                for name in model_names
            )
            if not self._available:
                log.debug("Model %s not found in Ollama (available: %s)", self._model, model_names)
        except Exception:
            self._available = False
            log.debug("Ollama not reachable", exc_info=True)

        return self._available

    def _gather_context(self, behaviors: dict[str, Behavior]) -> dict | None:
        """Build a minimal context dict for classification."""
        # Prefer the full perception snapshot if available
        if self._last_snapshot:
            return {
                "activity": self._last_snapshot.get("production_activity", ""),
                "flow_score": self._last_snapshot.get("flow_score", 0.0),
                "audio_energy": self._last_snapshot.get("audio_energy_rms", 0.0),
                "music_genre": self._last_snapshot.get("music_genre", ""),
                "heart_rate": self._last_snapshot.get("heart_rate_bpm", 0),
                "hour": self._last_snapshot.get("hour", 0),
            }

        # Fall back to behavior values
        ctx = {}
        for key in ("production_activity", "flow_state_score", "audio_energy_rms"):
            b = behaviors.get(key)
            if b is not None:
                ctx[key] = b.value
        return ctx if ctx else None

    def _classify(self, snapshot: dict) -> dict | None:
        """Run classification via Ollama. Returns parsed result or None."""
        if not self._available:
            return None

        # Back off after repeated errors
        if self._consecutive_errors >= 3:
            now = time.monotonic()
            if now - self._last_check < 30.0:
                return None
            self._consecutive_errors = 0  # reset and retry

        prompt = f"Current state: {json.dumps(snapshot, default=str)}"

        try:
            import ollama

            client = ollama.Client(timeout=self._timeout)
            start = time.monotonic()
            response = client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": 0.1, "num_predict": 64},
            )
            elapsed_ms = (time.monotonic() - start) * 1000

            content = response.get("message", {}).get("content", "")
            result = self._parse_response(content)

            if result is not None:
                log.debug(
                    "LLM classify: %s (flow=%s, conf=%.2f) in %.0fms",
                    result["activity"],
                    result["flow"],
                    result["confidence"],
                    elapsed_ms,
                )
            return result

        except Exception:
            self._consecutive_errors += 1
            log.debug("LLM classification failed", exc_info=True)
            return None

    @staticmethod
    def _parse_response(content: str) -> dict | None:
        """Parse LLM JSON response. Tolerant of markdown fences."""
        # Strip markdown code fences if present
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    data = json.loads(text[start:end])
                except json.JSONDecodeError:
                    return None
            else:
                return None

        activity = data.get("activity", "")
        flow = data.get("flow", "none")
        confidence = float(data.get("confidence", 0.5))

        # Validate
        valid_activities = {
            "coding", "writing", "browsing", "reading", "making_music",
            "gaming", "meeting", "presenting", "idle", "break",
            "exercising", "sleeping",
        }
        if activity not in valid_activities:
            activity = "idle"
            confidence *= 0.5

        if flow not in ("deep", "light", "none"):
            flow = "none"

        confidence = max(0.0, min(1.0, confidence))

        return {"activity": activity, "flow": flow, "confidence": confidence}
