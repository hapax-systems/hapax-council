"""StructuralDirector — slow-cadence LLM for long-horizon moves.

Phase 5c of the volitional-director epic (PR #1018; spec §3.4).

Cadence: 150 s. Emits StructuralIntent that the narrative director reads
as a context enrichment on its next tick — "Current structural direction:
<long_horizon_direction>". This keeps structural moves slow and coherent
across multiple narrative ticks without forcing the narrative director
to carry long-horizon state itself.

Output lands at /dev/shm/hapax-structural/intent.json (atomic replace).
The narrative director reads it alongside the PerceptualField block.

Under the grounding-exhaustive axiom, structural moves are grounding
moves of the slowest frequency — scene shifts, preset-family
transitions, YouTube direction. They use the grounded model (Command R
via LiteLLM) just like the narrative director, but with a smaller prompt
(no compositional-impingement demand; just scene_mode + family_hint +
long_horizon_direction free text).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

_STRUCTURAL_INTENT_PATH = Path("/dev/shm/hapax-structural/intent.json")
_STRUCTURAL_INTENT_JSONL = Path(
    os.path.expanduser("~/hapax-state/stream-experiment/structural-intent.jsonl")
)

SceneMode = Literal[
    "desk-work",
    "hardware-play",
    "conversation",
    "idle-ambient",
    "mixed",
    "research-foregrounded",
]

PresetFamilyHint = Literal[
    "audio-reactive",
    "calm-textural",
    "glitch-dense",
    "warm-minimal",
]


class StructuralIntent(BaseModel):
    scene_mode: SceneMode
    preset_family_hint: PresetFamilyHint
    long_horizon_direction: str = Field(
        ...,
        description=(
            "1-2 sentence direction the narrative director reads as "
            "context on its next tick. Stays in effect for ~150s until "
            "superseded."
        ),
    )
    emitted_at: float = Field(default_factory=time.time)
    condition_id: str = "none"


def _read_condition_id() -> str:
    try:
        marker = Path("/dev/shm/hapax-compositor/research-marker.json")
        if marker.exists():
            data = json.loads(marker.read_text(encoding="utf-8"))
            return data.get("condition_id") or "none"
    except Exception:
        pass
    return "none"


def _publish(intent: StructuralIntent) -> None:
    """Atomic publish to /dev/shm + append to JSONL for research observability."""
    try:
        _STRUCTURAL_INTENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STRUCTURAL_INTENT_PATH.with_suffix(".json.tmp")
        tmp.write_text(intent.model_dump_json(), encoding="utf-8")
        tmp.replace(_STRUCTURAL_INTENT_PATH)
    except Exception:
        log.warning("structural-intent publish failed", exc_info=True)
    try:
        _STRUCTURAL_INTENT_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with _STRUCTURAL_INTENT_JSONL.open("a", encoding="utf-8") as fh:
            fh.write(intent.model_dump_json() + "\n")
    except Exception:
        log.warning("structural-intent jsonl write failed", exc_info=True)
    try:
        from shared.director_observability import emit_structural_intent

        emit_structural_intent(
            scene_mode=intent.scene_mode,
            preset_family_hint=intent.preset_family_hint,
            condition_id=intent.condition_id,
        )
    except Exception:
        log.debug("prometheus emit_structural_intent failed", exc_info=True)


def parse_structural_intent(raw: str) -> StructuralIntent | None:
    """Best-effort parse of an LLM response into a StructuralIntent.

    Returns None on any failure — the caller can fall back to a stale
    intent or a default.
    """
    text = raw.strip()
    if not text or not text.startswith("{"):
        return None
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    try:
        return StructuralIntent.model_validate(obj)
    except Exception:
        return None


class StructuralDirector:
    """Slow 150-second LLM loop publishing long-horizon directives."""

    DEFAULT_CADENCE_S = 150.0
    STARTUP_OFFSET_S = 10.0  # delay so structural doesn't collide with narrative tick edge

    def __init__(
        self,
        *,
        cadence_s: float = DEFAULT_CADENCE_S,
        sleep_fn=time.sleep,
        llm_fn=None,
    ):
        """llm_fn: callable(prompt: str) -> str. Defaults to the same
        LiteLLM route used by the narrative director. Tests inject a
        deterministic stub."""
        self._cadence_s = cadence_s
        self._sleep = sleep_fn
        self._llm_fn = llm_fn or _default_llm_fn
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="structural-director", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        # Startup offset so structural ticks don't coincide with narrative tick edges
        self._sleep(self.STARTUP_OFFSET_S)
        while self._running:
            try:
                self.tick_once()
            except Exception:  # pragma: no cover
                log.warning("structural tick crashed", exc_info=True)
            self._sleep(self._cadence_s)

    def tick_once(self) -> StructuralIntent | None:
        prompt = self._build_prompt()
        try:
            raw = self._llm_fn(prompt)
        except Exception:
            log.warning("structural LLM call failed", exc_info=True)
            return None
        intent = parse_structural_intent(raw or "")
        if intent is None:
            log.debug("structural LLM response unparseable; keeping prior intent")
            return None
        intent = intent.model_copy(
            update={
                "emitted_at": time.time(),
                "condition_id": _read_condition_id(),
            }
        )
        _publish(intent)
        return intent

    def _build_prompt(self) -> str:
        """Minimal structural prompt. No images, no per-tick compositional demand.

        Reads the same PerceptualField the narrative director sees plus a
        short objectives summary. Shorter than narrative to keep the 150s
        cadence latency-cheap.
        """
        parts: list[str] = []
        parts.append("<structural_context>")
        try:
            from shared.perceptual_field import build_perceptual_field

            field = build_perceptual_field()
            parts.append("## Perceptual Field")
            parts.append(field.model_dump_json(indent=2, exclude_none=True))
        except Exception:
            log.debug("structural: perceptual_field read failed", exc_info=True)
        parts.append("")
        parts.append("## Your Role")
        parts.append(
            "You are Hapax's slow (2-3 min) structural director. Your job "
            "is the long-horizon shape of the livestream: what scene mode "
            "we're in, which effect-preset family feels right, and a "
            "one-or-two-sentence direction the narrative director reads "
            "as its next tick's context."
        )
        parts.append("")
        parts.append("## Response Format")
        parts.append(
            "{\n"
            '  "scene_mode": "<desk-work|hardware-play|conversation|idle-ambient|mixed|research-foregrounded>",\n'
            '  "preset_family_hint": "<audio-reactive|calm-textural|glitch-dense|warm-minimal>",\n'
            '  "long_horizon_direction": "<1-2 sentences>"\n'
            "}"
        )
        parts.append(
            "Ground your scene_mode in what the PerceptualField actually "
            "shows. Ground your family hint in the music/energy profile. "
            "The long_horizon_direction is prose guidance the narrative "
            "director consumes; stay concrete, avoid rhetorical flourish "
            "(axiom ex-prose-001)."
        )
        parts.append("</structural_context>")
        return "\n".join(parts)


def _default_llm_fn(prompt: str) -> str:
    """Fallback LLM call — reuses the narrative director's LiteLLM route.

    Best-effort: imports are lazy so tests can stub this without pulling
    in the heavy director_loop module.
    """
    import subprocess
    import urllib.request

    litellm_url = "http://localhost:4000/v1/chat/completions"
    # Reuse the same key fetch as director_loop._get_litellm_key
    try:
        result = subprocess.run(
            ["pass", "show", "litellm/master-key"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        key = result.stdout.strip()
    except Exception:
        key = ""
    body = json.dumps(
        {
            "model": os.environ.get("HAPAX_STRUCTURAL_MODEL", "local-fast"),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 320,
            "temperature": 0.7,
        }
    ).encode()
    req = urllib.request.Request(
        litellm_url,
        body,
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    started = time.time()
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())
    elapsed = time.time() - started
    try:
        from shared.director_observability import observe_llm_latency

        observe_llm_latency(elapsed, tier="structural", condition_id=_read_condition_id())
    except Exception:
        pass
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


__all__ = [
    "StructuralDirector",
    "StructuralIntent",
    "parse_structural_intent",
]
