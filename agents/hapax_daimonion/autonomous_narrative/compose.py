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
from shared.claim_prompt import SURFACE_FLOORS, render_envelope

log = logging.getLogger(__name__)


_GROUNDED_MAX_TOKENS = 160  # ~2-3 sentences
_GROUNDED_TEMPERATURE = 0.7


def compose_narrative(
    context: Any,
    *,
    llm_call: Any | None = None,
) -> str | None:
    """Compose 1-3 sentences of narrative grounded in ``context``.

    ``llm_call`` is a test injection hook; production callers leave
    None and the function dispatches to ``_call_llm_grounded`` which
    routes to the local Command-R tier (TabbyAPI ``local-fast``) per
    feedback_grounding_exhaustive + feedback_director_grounding — every
    grounding act is performed by the local grounded model, not by a
    cloud tier.

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
        llm_call = _call_llm_grounded

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
    vault_summary = _summarize_vault_context(getattr(context, "vault_context", None))
    if vault_summary:
        parts.append(vault_summary)
    return "\n".join(parts)


def _summarize_vault_context(vault_context: Any) -> str:
    """Render the operator's vault state as a compact context block.

    SS2 cycle 1 (ytb-SS2 §4): provides the LLM with the operator's
    "current focus" — recent daily notes + active goals — as
    informational context rather than as a directive about what to
    talk about. The compose-prompt frames it as such.

    Returns an empty string when the vault context is None or empty
    so the seed cleanly omits the block; downstream prompt assembly
    drops empty parts.
    """
    if vault_context is None:
        return ""
    excerpts = getattr(vault_context, "daily_note_excerpts", ()) or ()
    goals = getattr(vault_context, "active_goals", ()) or ()
    if not excerpts and not goals:
        return ""

    sections: list[str] = []
    if goals:
        goal_lines = [f"  - [{prio}] {title} ({status})" for title, prio, status in goals]
        sections.append("Operator's active goals:\n" + "\n".join(goal_lines))
    if excerpts:
        note_lines: list[str] = []
        for date_label, body in excerpts:
            indented_body = body.replace("\n", "\n    ")
            note_lines.append(f"  [{date_label}]\n    {indented_body}")
        sections.append("Operator's recent daily notes (oldest first):\n" + "\n".join(note_lines))

    return "Operator focus context:\n" + "\n\n".join(sections)


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
    envelope = render_envelope([], floor=SURFACE_FLOORS["autonomous_narrative"])
    return (
        f"{envelope}\n\n"
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
        "narrate, return the literal token [silence] and nothing else.\n"
        "- Operator focus context (when present in the state below) is "
        "informational scaffolding, NOT a directive about what to talk "
        "about. Use it to ground references to operator concerns when "
        "naturally relevant; do NOT recite it, summarise it, or treat "
        "its presence as license to narrate goals or daily notes "
        "directly. The chronicle events remain the primary grounding "
        "source.\n"
        "- HARD GROUNDING FENCES (never confabulate these):\n"
        "  * Vinyl / platter / turntable / spinning / RPM / album cover "
        "/ album art / record playback — NEVER mention unless the state "
        "below explicitly contains a line stating vinyl is currently "
        "playing (look for 'spinning vinyl' / 'vinyl_playing: true' / a "
        "track title with a playback marker). Absent such a line, assume "
        "no vinyl is playing and do not reference it.\n"
        "  * CBIP / chess-boxing interpretive plane / album-ward "
        "enhancements / intensity router / Ring-2 gate — NEVER mention. "
        "CBIP is internal compositor infrastructure and must not surface "
        "in narration under any circumstance.\n\n"
        "State (deterministic snapshot):\n"
        "---\n"
        f"{seed}\n"
        "---\n\n"
        "Compose the narration. Return only the prose (or [silence]); "
        "no preamble, no explanation."
    )


def _call_llm_grounded(*, prompt: str, seed: str) -> str | None:
    """Production LLM call via the local grounded tier (Command-R, TabbyAPI).

    Grounding acts are performed by the local Command-R route (``local-fast``),
    which is already what the director_loop uses (``HAPAX_DIRECTOR_MODEL``
    default). Autonomous narrative is a grounding act over chronicle events
    and operator focus context, so it must not route to a cloud tier — see
    feedback_director_grounding + feedback_grounding_exhaustive.
    """
    try:
        import litellm  # noqa: PLC0415
    except ImportError:
        return None

    import os  # noqa: PLC0415

    from shared.config import MODELS  # noqa: PLC0415

    # Raw litellm.completion needs an explicit provider prefix +
    # api_base / api_key; the bare model alias hits the gateway with
    # "LLM Provider NOT provided" 400. The local-fast route lives
    # behind the LiteLLM proxy at :4000, which is OpenAI-compatible.
    try:
        response = litellm.completion(
            model=f"openai/{MODELS['local-fast']}",
            api_base=os.environ.get("LITELLM_API_BASE", "http://127.0.0.1:4000"),
            api_key=os.environ.get("LITELLM_API_KEY", "not-set"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_GROUNDED_MAX_TOKENS,
            temperature=_GROUNDED_TEMPERATURE,
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
        log.info("grounded LLM call failed for autonomous narrative: %s", exc)
        return None
