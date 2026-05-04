"""Compose narrative prose from a ``NarrativeContext`` via the local LLM tier.

Outputs 1-3 sentences grounded in chronicle/programme/stimmung state,
TTS-friendly, in scientific register. Per operator directive 2026-04-27
("there should BE no fences"), the composer no longer drops emission
to silence on register violations — it sanitizes the trouble patterns
that matter (personification of a different kind, "the AI" slop,
commercial tells, vinyl/CBIP confabulation) and emits the surviving
prose. Total-silence fences caused Command-R/Qwen3.5 to take the easy
retreat path and emit 4-word fragments like "Hapax is observing".
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from shared.claim_prompt import SURFACE_FLOORS
from shared.narration_triad import render_triad_prompt_context
from shared.operator_referent import REFERENTS

log = logging.getLogger(__name__)


_GROUNDED_MAX_TOKENS = 220  # ~3 full sentences
_GROUNDED_TEMPERATURE = 0.85

_TROUBLE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"[\U0001F300-\U0001FAFF]"),
    re.compile(r"\bthe\s+ai\b", re.IGNORECASE),
    re.compile(r"\b(an|this|our|my)\s+ai\b", re.IGNORECASE),
    re.compile(r"\bartificial\s+intelligence\b", re.IGNORECASE),
    re.compile(r"\bsubscribe\b", re.IGNORECASE),
    re.compile(r"\blike\s+and\s+(follow|subscribe|share)\b", re.IGNORECASE),
    re.compile(r"\bsmash\s+(that\s+)?(like|subscribe)\b", re.IGNORECASE),
    re.compile(r"\bhit\s+the\s+bell\b", re.IGNORECASE),
    re.compile(r"\bcomment\s+(below|down\s+below)\b", re.IGNORECASE),
    re.compile(r"\bdon['']?t\s+forget\s+to\s+(like|subscribe|share)\b", re.IGNORECASE),
    re.compile(
        r"\b(vinyl|platter|turntable|spinning|RPM|album\s+cover|album\s+art|record\s+playback)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bCBIP\b"),
    re.compile(r"\bchess[\s-]?boxing\b", re.IGNORECASE),
    re.compile(r"\bring[\s-]?2\s+gate\b", re.IGNORECASE),
    re.compile(r"\bintensity\s+router\b", re.IGNORECASE),
    re.compile(r"\b(feels?|wants?|dreams?|hopes?|desires?|longs?)\b", re.IGNORECASE),
)


def _violates_operator_referent_policy(text: str, operator_referent: str | None) -> bool:
    """Fail closed on legal-name leaks or mixed non-formal referents."""
    legal_name = os.environ.get("HAPAX_OPERATOR_NAME", "").strip()
    if legal_name and re.search(re.escape(legal_name), text, flags=re.IGNORECASE):
        log.warning("autonomous_narrative: legal-name leak detected; dropping output")
        return True

    if not operator_referent:
        return False

    scrubbed = re.sub(re.escape(operator_referent), "", text, flags=re.IGNORECASE)
    for referent in sorted(REFERENTS, key=len, reverse=True):
        if referent == operator_referent:
            continue
        if re.search(re.escape(referent), scrubbed, flags=re.IGNORECASE):
            log.warning("autonomous_narrative: mixed operator referents detected; dropping output")
            return True
    return False


def _sanitize_register(text: str, *, operator_referent: str | None = None) -> str:
    """Drop sentences containing trouble patterns; keep the rest.

    Soft sanitize per 2026-04-27 "no fences" directive: if a sentence
    trips a constitutional fence (commercial tells, "the AI",
    vinyl/CBIP confabulation), drop that sentence — but emit the
    surviving prose instead of dropping the whole utterance.
    """
    if _violates_operator_referent_policy(text, operator_referent):
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    keep: list[str] = []
    for sentence in sentences:
        s = sentence.strip()
        if not s:
            continue
        if any(pat.search(s) for pat in _TROUBLE_PATTERNS):
            log.info("autonomous_narrative: dropped trouble sentence: %s", s[:120])
            continue
        keep.append(s)
    return " ".join(keep).strip()


def compose_narrative(
    context: Any,
    *,
    operator_referent: str | None = None,
    llm_call: Any | None = None,
) -> str | None:
    """Compose 1-3 sentences of narrative grounded in ``context``.

    Returns None only when the LLM call genuinely fails or returns
    nothing. Empty chronicle is no longer a short-circuit — the LLM
    can compose from programme/stimmung/activity alone.
    """
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

        phenom_text = render_phenom(tier="CAPABLE")
        phenom_lines = phenom_text.strip().split("\n") if phenom_text else []
    except Exception:
        phenom_lines = []

    from shared.grounding_context import GroundingContextVerifier

    envelope = GroundingContextVerifier.build_envelope(
        turn_id="autonomous_narrative",
        temporal_bands=bands_raw,
        phenomenal_lines=phenom_lines,
        available_tools=[],
    )

    seed = _build_seed(context)
    prompt = _build_prompt(context, seed, operator_referent=operator_referent, envelope=envelope)

    if llm_call is None:
        llm_call = _call_llm_grounded

    try:
        polished = llm_call(prompt=prompt, seed=seed)
    except Exception as exc:
        log.warning("autonomous_narrative LLM call failed: %s", exc)
        return None

    if not polished or not isinstance(polished, str):
        return None

    cleaned = _sanitize_register(polished.strip(), operator_referent=operator_referent)
    if not cleaned:
        return None

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    safe_sentences = []
    for sentence in sentences:
        s = sentence.strip()
        if not s:
            continue
        is_safe, reason = GroundingContextVerifier.verify_clause(envelope, s)
        if is_safe:
            safe_sentences.append(s)
        else:
            log.warning(
                "autonomous_narrative clause gate rejected sentence: %r (reason: %s)", s, reason
            )

    final_text = " ".join(safe_sentences).strip()
    if not final_text:
        return None
    if final_text[-1] not in ".!?":
        final_text = final_text + "."
    return final_text


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
    triad_summary = render_triad_prompt_context(getattr(context, "triad_continuity", None))
    if triad_summary:
        parts.append("Narration continuity ledger:\n" + triad_summary)
    return "\n".join(parts)


def _summarize_vault_context(vault_context: Any) -> str:
    """Render the operator's vault state as a compact context block."""
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

    Deduplicates by (source, narrative-prefix) so the LLM doesn't see
    8 copies of the same templated exploration.* curiosity message —
    that paralyzed Command-R into 4-word stub outputs. Cap at 8 unique
    events, sorted by ts ascending so the LLM sees temporal order.
    """
    if not events:
        return ""
    sorted_events = sorted(events, key=lambda e: float(e.get("ts") or e.get("timestamp") or 0.0))
    seen: set[tuple[str, str]] = set()
    bullets: list[str] = []
    for e in sorted_events:
        source = e.get("source") or "unknown"
        kind = e.get("intent_family") or e.get("event_type") or e.get("type") or ""
        payload = e.get("content") or e.get("payload") or {}
        narrative = ""
        if isinstance(payload, dict):
            narrative = payload.get("narrative") or payload.get("metric") or ""
            if not narrative and isinstance(payload.get("changed_params"), dict):
                params = payload["changed_params"]
                top = sorted(
                    params.items(),
                    key=lambda kv: abs(kv[1]) if isinstance(kv[1], (int, float)) else 0,
                    reverse=True,
                )[:2]
                narrative = "shift in " + ", ".join(k for k, _ in top)
            if not narrative and payload.get("technique_name"):
                narrative = f"activated {payload['technique_name']}"
        dedup_key = (str(source), narrative[:60])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        suffix = f": {narrative}" if narrative else ""
        bullets.append(f"  - {source}/{kind}{suffix}".rstrip("/"))
        if len(bullets) >= 8:
            break
    return "\n" + "\n".join(bullets)


def _build_prompt(
    context: Any, seed: str, *, operator_referent: str | None = None, envelope: Any | None = None
) -> str:
    """The full LLM prompt for the local grounded tier."""
    if envelope is not None:
        from shared.grounding_context import GroundingContextVerifier

        envelope_xml = GroundingContextVerifier.render_xml(envelope)
    else:
        # Fallback for tests that don't pass an envelope
        from shared.claim_prompt import render_envelope

        envelope_xml = render_envelope([], floor=SURFACE_FLOORS["autonomous_narrative"])

    referent_clause = ""
    if operator_referent:
        referents = ", ".join(f"'{r}'" for r in REFERENTS)
        referent_clause = (
            "- If you refer to the operator, use exactly "
            f"'{operator_referent}'. Do not use the legal name. Do not mix any other "
            f"operator referent from this set: {referents}.\n"
        )
    return (
        f"{envelope_xml}\n\n"
        "Compose one short autonomous narration for the Hapax "
        "research-instrument livestream, spoken in first-system voice "
        "(Hapax as a system, not a character).\n\n"
        "MUST:\n"
        "- Produce 1 to 3 complete sentences, each ending with a period. "
        "Roughly 60-220 characters total. TTS-friendly clauses.\n"
        "- Ground each sentence in something specific from the state "
        "below — pick a thread and elaborate on it; do not just announce "
        "that you are observing.\n"
        "- Use neutral, factual, present-tense scientific register.\n"
        "- Refer to the system as 'Hapax' (never 'the AI', 'this AI', "
        "'our AI', 'artificial intelligence').\n\n"
        f"{referent_clause}"
        "AVOID:\n"
        "- Personifying verbs (feels, wants, dreams, inspired).\n"
        "- Commercial tells (subscribe, like and follow, comment below, "
        "smash that like, hit the bell).\n"
        "- Vinyl / platter / turntable / record / album cover / "
        "album art language unless the state explicitly says vinyl is "
        "currently playing.\n"
        "- Internal infrastructure terms (CBIP, chess-boxing interpretive "
        "plane, intensity router, Ring-2 gate).\n"
        "- Emoji.\n\n"
        "State (deterministic snapshot):\n"
        "---\n"
        f"{seed}\n"
        "---\n\n"
        "Output only the prose. No preamble, no explanation, no "
        "bracketed tokens. End every sentence with a period."
    )


def _call_llm_grounded(*, prompt: str, seed: str) -> str | None:
    """Production LLM call via the local grounded tier (Command-R/Qwen3.5, TabbyAPI).

    Grounding acts route to ``local-fast`` (TabbyAPI). Per
    feedback_grounding_exhaustive + feedback_director_grounding —
    grounding acts stay on the local grounded model, not cloud.
    """
    try:
        import litellm  # noqa: PLC0415
    except ImportError:
        return None

    import os  # noqa: PLC0415

    from shared.config import MODELS  # noqa: PLC0415

    def _one_call(temp: float) -> str | None:
        response = litellm.completion(
            model=f"openai/{MODELS['local-fast']}",
            api_base=os.environ.get("LITELLM_API_BASE", "http://127.0.0.1:4000"),
            api_key=os.environ.get("LITELLM_API_KEY", "not-set"),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_GROUNDED_MAX_TOKENS,
            temperature=temp,
        )
        choices = getattr(response, "choices", None)
        if not choices:
            return None
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message else None
        if not isinstance(content, str):
            return None
        return content.strip()

    try:
        text = _one_call(_GROUNDED_TEMPERATURE)
        if not text:
            return None
        # Retry once warmer if the model bailed early (no terminal
        # punctuation OR shorter than 30 chars). Command-R produces
        # 4-word stubs when the prompt feels too constrained; a warmer
        # retry breaks the stub-attractor.
        if len(text) < 30 or text[-1] not in ".!?":
            log.info(
                "autonomous_narrative: short/unterminated output (%d chars), retrying warmer",
                len(text),
            )
            retry = _one_call(min(_GROUNDED_TEMPERATURE + 0.2, 1.1))
            if retry and (len(retry) > len(text) or retry[-1] in ".!?"):
                text = retry
        return text or None
    except Exception as exc:
        log.info("grounded LLM call failed for autonomous narrative: %s", exc)
        return None
