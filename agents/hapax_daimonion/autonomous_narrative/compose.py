"""Compose narrative prose from a ``NarrativeContext`` via the balanced LLM tier.

Per design draft + spec: prose is grounded in ≥1 specific observed
chronicle event, scientific register, GEAL-aligned framing (Hapax as
system not character), 1-3 sentences, TTS-friendly. Output passes
through ``agents.metadata_composer.framing.enforce_register`` to catch
LLM drift into personification / commercial register / hollow
affirmations.

If the LLM call fails (network, quota, missing key), or if the LLM
output fails the register check after one re-prompt, the composer
returns None — better silence than slop.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.metadata_composer.framing import enforce_register

log = logging.getLogger(__name__)


_BALANCED_MAX_TOKENS = 160  # ~2-3 sentences
_BALANCED_TEMPERATURE = 0.7


def compose_narrative(
    context: Any,
    *,
    llm_call: Any | None = None,
) -> str | None:
    """Compose 1-3 sentences of narrative grounded in ``context``.

    ``llm_call`` is a test injection hook; production callers leave
    None and the function dispatches to ``_call_llm_balanced``.

    Returns None when the chronicle window is empty (no concrete event
    to ground in), the LLM fails, or the output fails the register
    check. Silence is the safe default.
    """
    if not getattr(context, "chronicle_events", None):
        log.debug("autonomous_narrative compose: chronicle empty; skipping")
        return None

    seed = _build_seed(context)
    prompt = _build_prompt(context, seed)

    if llm_call is None:
        llm_call = _call_llm_balanced

    try:
        polished = llm_call(prompt=prompt, seed=seed)
    except Exception as exc:
        log.warning("autonomous_narrative LLM call failed: %s", exc)
        return None

    if not polished or not isinstance(polished, str):
        return None

    # Scientific-register check; on violation, drop to silence (no
    # fallback prose for autonomous narrative — prefer silence).
    cleaned = enforce_register(polished.strip(), fallback="")
    if not cleaned:
        log.info("autonomous_narrative output failed register check; emitting silence")
        return None
    return cleaned


def _build_seed(context: Any) -> str:
    """Deterministic state summary used as the LLM grounding."""
    parts: list[str] = []
    prog = getattr(context, "programme", None)
    if prog is not None:
        role = getattr(prog, "role", None)
        if role is not None:
            parts.append(f"Active programme role: {getattr(role, 'value', role)}")
        beat = getattr(getattr(prog, "narrative", None), "narrative_beat", None) or getattr(
            prog, "narrative_beat", None
        )
        if isinstance(beat, str) and beat:
            parts.append(f"Programme narrative beat: {beat}")
    tone = getattr(context, "stimmung_tone", "")
    if tone:
        parts.append(f"Stimmung tone: {tone}")
    activity = getattr(context, "director_activity", "")
    if activity:
        parts.append(f"Current activity: {activity}")
    events_summary = _summarize_events(context.chronicle_events)
    if events_summary:
        parts.append(f"Recent events: {events_summary}")
    return "\n".join(parts)


def _summarize_events(events: tuple[dict, ...]) -> str:
    """Render the chronicle events as a compact bullet list for the prompt.

    Cap at 8 events; sort by ts ascending so the LLM sees temporal order.
    Each event yields "{source} {intent_family or event_type}: {narrative}"
    where present.
    """
    if not events:
        return ""
    sorted_events = sorted(events, key=lambda e: float(e.get("ts") or e.get("timestamp") or 0.0))[
        -8:
    ]
    bullets: list[str] = []
    for e in sorted_events:
        source = e.get("source") or "unknown"
        kind = e.get("intent_family") or e.get("event_type") or e.get("type") or ""
        payload = e.get("content") or e.get("payload") or {}
        narrative = ""
        if isinstance(payload, dict):
            narrative = payload.get("narrative") or payload.get("metric") or ""
        suffix = f": {narrative}" if narrative else ""
        bullets.append(f"  - {source}/{kind}{suffix}".rstrip("/"))
    return "\n" + "\n".join(bullets)


def _build_prompt(context: Any, seed: str) -> str:
    """The full LLM prompt asked of the balanced tier."""
    return (
        "You are composing one short autonomous narration for the Hapax "
        "research-instrument livestream. The narration is spoken in "
        "first-system voice (Hapax as a system, never as a character).\n\n"
        "Voice constraints:\n"
        "- Scientific register: neutral, factual, present-tense.\n"
        "- Hapax is a system, not a character. Never personify (no "
        "'feels', 'thinks', 'wants', 'remembers', 'dreams', 'inspired').\n"
        "- 1 to 3 sentences, total under 220 characters. TTS-friendly: "
        "short clauses, simple syntax.\n"
        "- Ground each sentence in a specific observed event from the "
        "state below — do not generate generic 'I notice the stream is "
        "running' filler.\n"
        "- No emoji, no exclamation marks except ending sentences once.\n"
        "- No commercial tells (no 'subscribe', 'like and follow', "
        "'comment below'). No hollow affirmations ('amazing', "
        "'incredible'). No creator-opener clichés ('So,', 'Today we're', "
        "'Welcome back').\n"
        "- Diegetic consistency: refer to the system as 'Hapax'. Never "
        "'the AI', 'this AI', 'our AI'.\n"
        "- If no event in the state below is substantive enough to "
        "narrate, return the literal token [silence] and nothing else.\n\n"
        "State (deterministic snapshot):\n"
        "---\n"
        f"{seed}\n"
        "---\n\n"
        "Compose the narration. Return only the prose (or [silence]); "
        "no preamble, no explanation."
    )


def _call_llm_balanced(*, prompt: str, seed: str) -> str | None:
    """Production LLM call via the balanced tier (Claude Sonnet)."""
    try:
        import litellm  # noqa: PLC0415
    except ImportError:
        return None

    from shared.config import MODELS  # noqa: PLC0415

    try:
        response = litellm.completion(
            model=MODELS["balanced"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_BALANCED_MAX_TOKENS,
            temperature=_BALANCED_TEMPERATURE,
        )
        choices = getattr(response, "choices", None)
        if not choices:
            return None
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message else None
        if not isinstance(content, str):
            return None
        text = content.strip()
        if text == "[silence]" or not text:
            return None
        return text
    except Exception as exc:
        log.info("balanced LLM call failed for autonomous narrative: %s", exc)
        return None
