"""DMN Ollama inference — two paths: fast (no-think) and thinking (async).

Sensory ticks use _ollama_fast (chat API, /no_think, ~2-6s).
Evaluative/consolidation use start_thinking/collect_thinking (fire-and-forget,
result collected on next tick cycle).
"""

from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger("dmn.ollama")

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
DMN_MODEL_FAST = "qwen3:4b"
DMN_MODEL_THINK = "qwen3.5:4b"

SENSORY_SYSTEM = (
    "You are a continuous situation monitor. Report WHAT is happening in one sentence. "
    "Never explain WHY. Never evaluate quality. Never use abstract language. "
    "Format: one concrete sentence describing the current state."
)
EVALUATIVE_SYSTEM = (
    "You are a value trajectory assessor. Given the current state and what changed, "
    "report whether the situation is IMPROVING, DEGRADING, or STABLE. "
    "If degrading, state the specific concern in concrete terms (what is wrong, not why). "
    'Format: "Trajectory: [improving|degrading|stable]. Concern: [specific issue or none]" '
    "Never evaluate your own performance. Never use abstract language."
)
CONSOLIDATION_SYSTEM = (
    "Compress the following observations into one paragraph. "
    "Preserve: specific numbers, state changes, trends, anomalies. "
    "Discard: redundant stable readings, repeated values. "
    "Never interpret or evaluate. Just compress the facts."
)


async def _ollama_fast(prompt: str, system: str) -> str:
    """Fast path: non-thinking model, returns in ~1-3s warm."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                OLLAMA_CHAT_URL,
                json={
                    "model": DMN_MODEL_FAST,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "keep_alive": "10m",
                    "options": {"temperature": 0.3},
                },
            )
            if resp.status_code == 200:
                msg = resp.json().get("message", {})
                return msg.get("content", "").strip()
            log.warning("Ollama fast returned %d", resp.status_code)
            return ""
    except Exception as exc:
        log.warning("Ollama fast failed: %s: %s", type(exc).__name__, exc)
        return ""


async def _ollama_think(prompt: str, system: str) -> str:
    """Thinking path: lets the model reason fully. May take 30-120s."""
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                OLLAMA_CHAT_URL,
                json={
                    "model": DMN_MODEL_THINK,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "keep_alive": "10m",
                    "options": {"temperature": 0.3},
                },
            )
            if resp.status_code == 200:
                msg = resp.json().get("message", {})
                text = msg.get("content", "").strip()
                if not text:
                    text = msg.get("thinking", "").strip()
                return text
            log.warning("Ollama think returned %d", resp.status_code)
            return ""
    except Exception as exc:
        log.warning("Ollama think failed: %s: %s", type(exc).__name__, exc)
        return ""


_pending: dict[str, asyncio.Task[str]] = {}


def start_thinking(key: str, prompt: str, system: str) -> None:
    """Fire a thinking request in background. Retrieve with collect_thinking()."""
    if key in _pending and not _pending[key].done():
        return
    _pending[key] = asyncio.ensure_future(_ollama_think(prompt, system))


def collect_thinking(key: str) -> str | None:
    """Collect a completed thinking result. Returns None if still in flight."""
    task = _pending.get(key)
    if task is None or not task.done():
        return None
    _pending.pop(key)
    try:
        return task.result()
    except Exception as exc:
        log.warning("Thinking task '%s' failed: %s", key, exc)
        return ""


def _format_sensor_prompt(snapshot: dict, deltas: list[str]) -> str:
    parts = []
    p = snapshot.get("perception", {})
    parts.append(f"Activity: {p.get('activity', '?')}. Flow: {p.get('flow_score', 0):.1f}.")
    s = snapshot.get("stimmung", {})
    parts.append(f"Stimmung: {s.get('stance', '?')}. Stress: {s.get('operator_stress', 0):.2f}.")
    f = snapshot.get("fortress")
    if f:
        parts.append(
            f"Fortress {f.get('fortress_name', '?')}: pop={f.get('population')}, "
            f"food={f.get('food')}, drink={f.get('drink')}, "
            f"threats={f.get('threats')}, idle={f.get('idle')}."
        )
    w = snapshot.get("watch", {})
    if w.get("heart_rate", 0) > 0:
        parts.append(f"Heart rate: {w['heart_rate']} bpm.")
    if deltas:
        parts.append("Changes: " + "; ".join(deltas) + ".")
    return " ".join(parts)
