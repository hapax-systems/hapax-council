"""Scientific-register + GEAL framing helpers.

The composer is anchored on neutral, non-personifying prose. These
helpers (a) compose deterministic seed strings from snapshot state, (b)
enforce the scientific-register check on any LLM-polished output, and
(c) build the LLM prompt that asks the model to rewrite a seed in the
target voice.
"""

from __future__ import annotations

import re
from typing import Any

# Forbidden patterns: emoji, performance-register verbs, character
# personification. Matched against any prose before egress.
_FORBIDDEN_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"[\U0001F300-\U0001FAFF]"),  # broad emoji block
    re.compile(r"\bfeels?\b", re.IGNORECASE),
    re.compile(r"\bthinks?\b", re.IGNORECASE),
    re.compile(r"\bwants?\b", re.IGNORECASE),
    re.compile(r"\bremembers?\b", re.IGNORECASE),
    re.compile(r"\bdreams?\b", re.IGNORECASE),
    re.compile(r"\bexploring\s+(creative|new|unknown)", re.IGNORECASE),
    re.compile(r"\binspired\b", re.IGNORECASE),
    re.compile(r"\bcreative\s+journey\b", re.IGNORECASE),
    re.compile(r"!{2,}"),  # multiple exclamation
)


def enforce_register(text: str, *, fallback: str) -> str:
    """Return ``text`` if it passes the scientific-register check, else ``fallback``.

    The fallback is the deterministic seed — it cannot itself violate
    register because it's composed from controlled vocabulary.
    """
    if not text:
        return fallback
    if any(pat.search(text) for pat in _FORBIDDEN_PATTERNS):
        return fallback
    return text


def compose_title_seed(state) -> str:
    """Deterministic short label suitable as an LLM seed for title polish."""
    parts: list[str] = ["Legomena Live"]
    role = _programme_role(state)
    if role:
        parts.append(_humanize(role))
    if state.working_mode and state.working_mode != "research":
        parts.append(f"({state.working_mode})")
    return " — ".join(parts)


def compose_description_seed(state, *, scope: str) -> str:
    """Deterministic prose describing current research-instrument state.

    Scope-specific framing — vod_boundary gets longer scaffolding, live
    updates are tighter.
    """
    lines: list[str] = []
    role = _programme_role(state)
    if role:
        lines.append(f"Active programme role: {_humanize(role)}.")
    lines.append(f"Working mode: {state.working_mode}.")
    if state.director_activity and state.director_activity != "observe":
        lines.append(f"Current activity: {state.director_activity}.")
    if state.stimmung_tone:
        lines.append(f"Stimmung tone: {state.stimmung_tone}.")

    if scope == "vod_boundary":
        lines.append("")
        lines.append(
            "Hapax livestream is a research instrument. The broadcast surfaces "
            "the system's perceptual + compositional state without staging. "
            "Metadata is autonomously composed from current operational signals."
        )
    return "\n".join(lines).strip()


def compose_event_description(state, triggering_event: dict) -> str:
    event_type = triggering_event.get("event_type") or "event"
    salience = triggering_event.get("payload", {}).get("salience")
    intent = triggering_event.get("payload", {}).get("intent_family") or event_type
    parts = [f"Hapax livestream — {intent}."]
    if isinstance(salience, (int, float)):
        parts.append(f"Salience: {salience:.2f}.")
    role = _programme_role(state)
    if role:
        parts.append(f"Programme role: {_humanize(role)}.")
    return " ".join(parts)


def compose_tags(state) -> list[str]:
    tags = ["legomena", "livestream", "hapax", "research-instrument"]
    if state.working_mode:
        tags.append(state.working_mode)
    role = _programme_role(state)
    if role:
        tags.append(role.replace("_", "-"))
    if state.stimmung_tone:
        tags.append(state.stimmung_tone)
    seen = set()
    deduped: list[str] = []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def compose_shorts_caption(state) -> str:
    role = _programme_role(state)
    if role:
        return f"Hapax {_humanize(role)} — Legomena Live"
    return "Hapax livestream — Legomena Live"


def compose_bluesky_post(state, *, scope: str, triggering_event: dict | None = None) -> str:
    role = _programme_role(state)
    if scope == "cross_surface" and triggering_event is not None:
        intent = triggering_event.get("payload", {}).get("intent_family") or "event"
        return f"Hapax livestream: {intent}."
    if scope == "vod_boundary":
        suffix = f" ({_humanize(role)})" if role else ""
        return f"VOD boundary on Legomena Live{suffix}."
    return "Live now: Legomena (Hapax research instrument)."


def compose_discord_embed(
    state, *, scope: str, triggering_event: dict | None = None
) -> tuple[str, str]:
    title = compose_title_seed(state)
    description = compose_description_seed(state, scope=scope)
    if scope == "cross_surface" and triggering_event is not None:
        description = compose_event_description(state, triggering_event)
    return title, description


def compose_mastodon_post(state, *, scope: str, triggering_event: dict | None = None) -> str:
    if scope == "cross_surface" and triggering_event is not None:
        return compose_event_description(state, triggering_event)
    if scope == "vod_boundary":
        return f"VOD boundary — {compose_title_seed(state)}"
    return f"Live: {compose_title_seed(state)}"


def compose_pinned_comment(state, chapter_list) -> str:
    if not chapter_list:
        return ""
    lines = ["Chapters:"]
    for c in chapter_list:
        h, rem = divmod(int(c.timestamp_s), 3600)
        m, s = divmod(rem, 60)
        if h:
            lines.append(f"  {h}:{m:02d}:{s:02d} {c.label}")
        else:
            lines.append(f"  {m:02d}:{s:02d} {c.label}")
    return "\n".join(lines)


def build_llm_prompt(*, seed: str, scope: str, kind: str, referent: str | None = None) -> str:
    """Build the prompt asked of the ``balanced`` tier when polishing seeds.

    ``referent`` is the operator's chosen non-formal referent for this
    composition (per ``shared.operator_referent.OperatorReferentPicker`` —
    `su-non-formal-referent-001`). When provided, the prompt includes a
    style rule that constrains the LLM to that single referent so all
    metadata for one VOD stays internally consistent.
    """
    referent_clause = ""
    if referent:
        referent_clause = (
            "\nOperator-naming rule:\n"
            f'- When the operator must be named, refer to them EXCLUSIVELY as: "{referent}".\n'
            "- Do not use their legal name in this context.\n"
            "- Do not mix other referent forms.\n"
        )
    return (
        "You are composing YouTube metadata for a 24/7 research-instrument "
        "livestream named Hapax.\n\n"
        "Voice constraints:\n"
        "- Scientific register: neutral, factual, present-tense.\n"
        "- Hapax is a system, not a character. Never personify (no 'feels', "
        "'thinks', 'wants', 'remembers', 'dreams', 'inspired', 'creative "
        "journey').\n"
        "- No emoji, no exclamation marks except ending sentences once.\n"
        "- Describe operational state, not commercial performance."
        f"{referent_clause}\n"
        f"\nScope: {scope}\n"
        f"Output kind: {kind}\n\n"
        f"Seed (deterministically composed from current state):\n"
        f"---\n{seed}\n---\n\n"
        "Polish this seed into the target prose. Preserve every fact and "
        "every signal name. Return only the polished prose, no preamble."
    )


# ── internal helpers ───────────────────────────────────────────────────────


def _programme_role(state) -> str | None:
    if state.programme is None:
        return None
    role: Any = getattr(state.programme, "role", None)
    if role is None:
        return None
    if hasattr(role, "value"):
        return str(role.value)
    return str(role)


def _humanize(role: str) -> str:
    return role.replace("_", " ").title()
