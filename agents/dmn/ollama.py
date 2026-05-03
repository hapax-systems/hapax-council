"""DMN inference — two paths: fast (no-think) and thinking (async).

Sensory ticks use _tabby_fast (OpenAI-compatible, ~1-3s).
Evaluative/consolidation use start_thinking/collect_thinking (fire-and-forget,
result collected on next tick cycle).

Backend: TabbyAPI (EXL3) on :5000. No Ollama fallback — loading a second model
causes VRAM exhaustion when TabbyAPI is already resident.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import nullcontext

import httpx

try:
    from agents.telemetry.llm_call_span import llm_call_span
except ImportError:  # telemetry optional
    llm_call_span = None  # type: ignore[assignment]

log = logging.getLogger("dmn.ollama")

TABBY_CHAT_URL = "http://localhost:5000/v1/chat/completions"
DMN_MODEL = "Qwen3.5-9B-exl3-5.00bpw"

SENSORY_SYSTEM = (
    "You are a continuous situation monitor. Report WHAT is happening in one sentence. "
    "Never explain WHY. Never evaluate quality. Never use abstract language. "
    "Format: one concrete sentence describing the current state."
)
EVALUATIVE_SYSTEM = (
    "You are a situation assessor. You receive sensor data and may also receive an image "
    "of a visual surface. First, if an image is present, describe what you see in one "
    "sentence (colors, shapes, patterns, spatial arrangement). Then assess whether the "
    "overall situation is IMPROVING, DEGRADING, or STABLE. If degrading, state the "
    "specific concern in concrete terms. "
    'Format: "Visual: [one sentence description or none]. '
    'Trajectory: [improving|degrading|stable]. Concern: [specific issue or none]" '
    "Never evaluate your own performance. Never use abstract language."
)
CONSOLIDATION_SYSTEM = (
    "Compress the following observations into one paragraph. "
    "Preserve: specific numbers, state changes, trends, anomalies. "
    "Discard: redundant stable readings, repeated values. "
    "Never interpret or evaluate. Just compress the facts."
)


async def _tabby_fast(prompt: str, system: str) -> str:
    """Fast path via TabbyAPI (OpenAI-compatible). Falls back to Ollama."""
    metrics_ctx = (
        llm_call_span(model=DMN_MODEL, route="dmn-sensory")
        if llm_call_span is not None
        else nullcontext(None)
    )
    try:
        with metrics_ctx as metrics_span:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    TABBY_CHAT_URL,
                    json={
                        "model": DMN_MODEL,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 256,
                        "temperature": 0.3,
                        "stream": False,
                        "chat_template_kwargs": {"enable_thinking": False},
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                if metrics_span is not None:
                    metrics_span.set_outcome("refused")
                log.warning("TabbyAPI fast returned %d, skipping tick", resp.status_code)
    except Exception as exc:
        log.warning("TabbyAPI fast unavailable (%s), skipping tick", exc)

    return ""


async def _tabby_think(prompt: str, system: str) -> str:
    """Thinking path via TabbyAPI (with reasoning enabled). Falls back to Ollama."""
    metrics_ctx = (
        llm_call_span(model=DMN_MODEL, route="dmn-thinking")
        if llm_call_span is not None
        else nullcontext(None)
    )
    try:
        with metrics_ctx as metrics_span:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    TABBY_CHAT_URL,
                    json={
                        "model": DMN_MODEL,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 1024,
                        "temperature": 0.3,
                        "stream": False,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                if metrics_span is not None:
                    metrics_span.set_outcome("refused")
                log.warning("TabbyAPI think returned %d, skipping tick", resp.status_code)
    except Exception as exc:
        log.warning("TabbyAPI think unavailable (%s), skipping tick", exc)

    return ""


_pending: dict[str, asyncio.Task[str]] = {}


def _extract_litellm_response_cost(resp: object) -> float | None:
    """Pull `_response_cost` from a LiteLLM Proxy response object.

    LiteLLM Proxy attaches per-call cost via `_hidden_params._response_cost`
    on the OpenAI-compatible response. Non-LiteLLM proxies + responses
    without cost return None — caller treats None as "no cost data" and
    the span emission is a no-op.

    Defensive: any exception in attribute walk returns None (telemetry
    must never raise).
    """
    try:
        hidden = getattr(resp, "_hidden_params", None)
        if hidden is None:
            return None
        cost = (
            hidden.get("_response_cost")
            if isinstance(hidden, dict)
            else getattr(hidden, "_response_cost", None)
        )
        if cost is None:
            return None
        return float(cost)
    except (TypeError, ValueError, AttributeError):
        return None


async def _gemini_multimodal(prompt: str, system: str, frame_b64: str) -> str:
    """Multimodal evaluative call via gemini-flash — sees the visual surface directly."""
    import os

    # cc-task jr-gemini-3-flash-vision-router-update: route DMN per-tick
    # vision through `vision-fast` (= gemini-3-flash-preview) with
    # `media_resolution="low"` for the price-performance leader on 10fps
    # vision (~$0.00014/frame). MODELS resolution import-local to avoid a
    # circular import (shared.config doesn't import this module).
    from shared.config import MODELS

    vision_model = MODELS["vision-fast"]
    metrics_ctx = (
        llm_call_span(model=vision_model, route="dmn-multimodal")
        if llm_call_span is not None
        else nullcontext(None)
    )
    try:
        with metrics_ctx as span:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                base_url=os.environ.get("LITELLM_BASE", "http://localhost:4000"),
                api_key=os.environ.get("LITELLM_API_KEY", ""),
            )
            user_content: list[dict] = [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame_b64}"}},
                {"type": "text", "text": prompt},
            ]
            resp = await client.chat.completions.create(
                model=vision_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                max_tokens=256,
                extra_body={
                    "thinking": {"type": "disabled", "budget_tokens": 0},
                    "media_resolution": "low",
                },
            )
            # cc-task vision-cost-guard-prometheus-emitter: capture LiteLLM
            # response cost when present. LiteLLM Proxy attaches cost via
            # `_hidden_params._response_cost` on the response object; non-
            # LiteLLM proxies + responses without cost return None and the
            # span emission is a no-op.
            if span is not None and hasattr(span, "set_cost"):
                cost = _extract_litellm_response_cost(resp)
                if cost is not None:
                    span.set_cost(cost)
            return resp.choices[0].message.content.strip()
    except Exception as exc:
        log.warning("Gemini multimodal failed (%s), falling back to text-only", exc)
        return await _tabby_think(prompt, system)


def start_thinking(key: str, prompt: str, system: str, *, frame_b64: str = "") -> None:
    """Fire a thinking request in background. Retrieve with collect_thinking()."""
    if key in _pending and not _pending[key].done():
        return
    if frame_b64:
        _pending[key] = asyncio.ensure_future(_gemini_multimodal(prompt, system, frame_b64))
    else:
        _pending[key] = asyncio.ensure_future(_tabby_think(prompt, system))


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
