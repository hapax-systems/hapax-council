"""Hapax persona — system prompts, greetings, notification formatting.

LRR Phase 7 §4.4 integration: prompts are now driven by the description-of-being
document (axioms/persona/hapax-description-of-being.prompt.md) via
shared.persona_prompt_composer, not hard-coded personification strings.

Tool descriptions, voice-mode operational instructions, and the current-partner
declaration are kept inline here — they're infrastructure + task-level
constraints, not description-of-being. Those compose on top of the persona.

Operators can opt out via HAPAX_PERSONA_LEGACY=1 to revert to pre-Phase-7
hard-coded prompts; default is document-driven.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from logos.voice import greeting, operator_name
from shared.persona_prompt_composer import compose_persona_prompt

if TYPE_CHECKING:
    from agents.hapax_daimonion.screen_models import ScreenAnalysis

log = logging.getLogger(__name__)

# ── Legacy opt-out env var ─────────────────────────────────────────────────

_LEGACY_ENV = "HAPAX_PERSONA_LEGACY"


def _legacy_mode() -> bool:
    """True when HAPAX_PERSONA_LEGACY is set to a truthy value."""
    value = os.environ.get(_LEGACY_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


# ── Voice-mode operational instructions ────────────────────────────────────
#
# These are task-level constraints for voice conversation, not personification.
# "Keep responses brief" is a mode constraint (the output is spoken, short is
# right); "warm but concise" is personification (drops under Phase 7 reframe).

_VOICE_MODE_INSTRUCTIONS = (
    "## Voice mode\n"
    "You are in a voice conversation. Responses are spoken, not read. "
    "Keep each reply to one to three sentences. Vary phrasing; do not start "
    "two consecutive replies the same way. Before a tool call, say a short "
    "natural bridge ('let me check', 'one moment'). Only state facts you "
    "actually know or can look up. Never invent meetings, events, "
    "notifications, or other specifics.\n"
    "\n"
    "## Hard grounding fences (operator directive 2026-04-24)\n"
    "- NEVER narrate vinyl / platter / turntable / spinning / RPM / record "
    "playback, or claim a specific track or album is 'playing' / 'sounding' / "
    "'on now', unless a tool result or explicit factual context you just "
    "looked up names that track as currently playing. A visible album cover "
    "or album ward on screen is a DECORATIVE display, not a now-playing "
    "indicator.\n"
    "- NEVER mention CBIP / chess-boxing / interpretive plane / album-ward "
    "enhancements / intensity router / Ring-2 gate. These are internal "
    "compositor infrastructure and MUST NOT surface in conversation."
)

# ── Tool descriptions (unchanged infrastructure) ───────────────────────────

_TOOLS_BLOCK = (
    "## Tools\n\n"
    "Search (pick the right one):\n"
    "- get_calendar_today: LIVE calendar from Google. Use for schedule questions.\n"
    "- search_emails: email search. recent_only=true for freshest via Gmail API.\n"
    "- search_drive: Drive files (includes legacy data).\n"
    "- search_documents: semantic search across ALL indexed sources. "
    "Use source_filter to narrow: gmail, gcalendar, gdrive, obsidian, chrome, "
    "claude-code, weather, git, langfuse, ambient-audio, health_connect, youtube.\n\n"
    "Quick lookups (no arguments):\n"
    "- get_current_time, get_weather, get_briefing\n\n"
    "Actions:\n"
    "- send_sms → confirm_send_sms: two-step. send_sms returns a confirmation_id; "
    "read it back to the operator, then confirm_send_sms after approval. Expires in 2 min.\n"
    "- open_app → confirm_open_app: two-step app launch. Also expires in 2 min.\n"
    "- focus_window, switch_workspace, get_desktop_state: desktop control.\n"
    "- generate_image: create images from text prompts.\n\n"
    "Vision:\n"
    "- analyze_scene: capture cameras and/or screen. "
    "Cameras: 'operator' (face), 'hardware' (desk/gear), 'screen' (desktop). "
    "Default captures all available.\n\n"
    "Phone (Pixel 10 via KDE Connect):\n"
    "- find_phone: ring it when {name} can't find it.\n"
    "- lock_phone: lock the phone.\n"
    "- send_to_phone: share text or URLs to the phone.\n"
    "- media_control: play/pause/next/previous/stop phone media.\n\n"
    "System:\n"
    "- get_system_status: health checks (docker, gpu, services, network, voice).\n"
    "- check_consent_status, describe_consent_flow, check_governance_health.\n\n"
    "Use tools proactively — don't guess when you can look it up."
)


# ── Legacy prompts (preserved for HAPAX_PERSONA_LEGACY=1 opt-out) ──────────

_LEGACY_SYSTEM_PROMPT = (
    "You are Hapax, a voice assistant for {name}. "
    "You are warm but concise — friendly without being chatty. "
    "Keep responses spoken-natural and brief — one to three sentences. "
    "You know {name} well — use first name, skip formalities. "
    "Vary your phrasing naturally — never start two responses the same way. "
    "IMPORTANT: Only state facts you actually know or can look up via tools. "
    "Never invent meetings, events, notifications, or other specifics. "
    "If {name} says just your name without a clear request, "
    "acknowledge warmly and ask what they need. One sentence. "
    "If you have tools available, say a brief natural bridge before calling them — "
    "'Let me check', 'One moment', or similar. "
    "If you don't have tools for something, say so honestly.\n\n"
    "Your tools:\n\n"
    "Search (pick the right one):\n"
    "- get_calendar_today: LIVE calendar from Google. Use for schedule questions.\n"
    "- search_emails: email search. recent_only=true for freshest via Gmail API.\n"
    "- search_drive: Drive files (includes legacy data).\n"
    "- search_documents: semantic search across ALL indexed sources. "
    "Use source_filter to narrow: gmail, gcalendar, gdrive, obsidian, chrome, "
    "claude-code, weather, git, langfuse, ambient-audio, health_connect, youtube.\n\n"
    "Quick lookups (no arguments):\n"
    "- get_current_time, get_weather, get_briefing\n\n"
    "Actions:\n"
    "- send_sms → confirm_send_sms: two-step. send_sms returns a confirmation_id; "
    "read it back to {name}, then confirm_send_sms after approval. Expires in 2 min.\n"
    "- open_app → confirm_open_app: two-step app launch. Also expires in 2 min.\n"
    "- focus_window, switch_workspace, get_desktop_state: desktop control.\n"
    "- generate_image: create images from text prompts.\n\n"
    "Vision:\n"
    "- analyze_scene: capture cameras and/or screen. "
    "Cameras: 'operator' (face), 'hardware' (desk/gear), 'screen' (desktop). "
    "Default captures all available.\n\n"
    "Phone (Pixel 10 via KDE Connect):\n"
    "- find_phone: ring it when {name} can't find it.\n"
    "- lock_phone: lock the phone.\n"
    "- send_to_phone: share text or URLs to the phone.\n"
    "- media_control: play/pause/next/previous/stop phone media.\n\n"
    "System:\n"
    "- get_system_status: health checks (docker, gpu, services, network, voice).\n"
    "- check_consent_status, describe_consent_flow, check_governance_health.\n\n"
    "You can search documents, emails, calendar, and Drive. "
    "Use tools proactively — don't guess when you can look it up."
)

_LEGACY_SYSTEM_PROMPT_MINIMAL = (
    "You are Hapax, a voice assistant for {name}. "
    "You are warm but concise — friendly without being chatty. "
    "Keep responses spoken-natural and brief — one to three sentences. "
    "You know {name} well — use first name, skip formalities. "
    "Vary your phrasing naturally — never start two responses the same way. "
    "IMPORTANT: Only state facts you actually know or can look up via tools. "
    "Never invent meetings, events, notifications, or other specifics. "
    "If {name} says just your name without a clear request, "
    "acknowledge warmly and ask what they need. One sentence. "
    "If you have tools available, say a brief natural bridge before calling them — "
    "'Let me check', 'One moment', or similar. "
    "If you don't have tools for something, say so honestly."
)

_LEGACY_GUEST_PROMPT = (
    "You are Hapax, a voice assistant. "
    "You're chatting with someone who isn't your primary operator. "
    "Be friendly and helpful for general conversation, but you cannot access "
    "system information, briefings, or personal data. "
    "If asked about those, explain that you'll need the operator for that."
)

_LEGACY_EXPERIMENT_PROMPT = (
    "You are Hapax, a voice assistant for {name}. "
    "Warm but concise — friendly without being chatty. "
    "Keep responses spoken-natural and brief. "
    "You know {name} well — use first name, skip formalities. "
    "Vary your phrasing naturally — never start two responses the same way. "
    "Only state facts you actually know. Never invent specifics. "
    "If {name} says just your name, acknowledge warmly and ask what they need."
)

_NOTIFICATION_TEMPLATE = "Hey {name} — {summary}"


# ── Partner declarations (new Phase 7 path) ────────────────────────────────


def _operator_partner_block() -> str:
    name = operator_name()
    return (
        f"## Current partner\n"
        f"The partner in conversation is {name}, the operator. This is the "
        f"partner-in-conversation relational role per axioms/roles/registry.yaml. "
        f"Grounding proceeds via turn-taking and re-inscription to the chronicle "
        f"+ grounding ledger, not via performance. Address them by first name. "
        f"If they say just your name without a clear request, acknowledge and "
        f"ask what they need in one sentence."
    )


def _guest_partner_block() -> str:
    return (
        "## Current partner\n"
        "The partner in conversation is a guest — not the operator. This is still "
        "the partner-in-conversation relational role, but operator-private tools "
        "(briefing, goals, personal notes, profile) are out of scope. If asked "
        "about operator-private information, explain that you'll need the "
        "operator for that. Engage helpfully on general topics within the "
        "guest's consent scope."
    )


# ── Assembly ───────────────────────────────────────────────────────────────


def _compose_prompt(
    guest_mode: bool,
    experiment_mode: bool,
    tool_recruitment_active: bool,
    policy_block: str,
) -> str:
    """LRR Phase 7 §4.4 composed prompt: persona document + mode + partner + tools."""
    persona = compose_persona_prompt(role_id="partner-in-conversation")

    parts: list[str] = [persona, "", _VOICE_MODE_INSTRUCTIONS]

    if guest_mode:
        parts.extend(["", _guest_partner_block()])
        # Guest path: no tool descriptions (limited access)
        if policy_block:
            parts.extend(["", policy_block.strip()])
        return "\n".join(parts)

    parts.extend(["", _operator_partner_block()])

    # Tools — skip for experiment mode or when recruitment injects them
    if not experiment_mode and not tool_recruitment_active:
        parts.extend(["", _TOOLS_BLOCK])

    if policy_block:
        parts.extend(["", policy_block.strip()])

    return "\n".join(parts)


def _legacy_system_prompt(
    guest_mode: bool,
    policy_block: str,
    experiment_mode: bool,
    tool_recruitment_active: bool,
) -> str:
    """Pre-Phase-7 hard-coded prompt path, selected by HAPAX_PERSONA_LEGACY=1."""
    if guest_mode:
        return _LEGACY_GUEST_PROMPT + policy_block
    if experiment_mode:
        base = _LEGACY_EXPERIMENT_PROMPT
    elif tool_recruitment_active:
        base = _LEGACY_SYSTEM_PROMPT_MINIMAL
    else:
        base = _LEGACY_SYSTEM_PROMPT
    return base.format(name=operator_name()) + policy_block


def system_prompt(
    guest_mode: bool = False,
    policy_block: str = "",
    experiment_mode: bool = False,
    tool_recruitment_active: bool = False,
) -> str:
    """Return the system prompt for the current session mode.

    Default path (LRR Phase 7): composes the persona document (description-
    of-being) + voice-mode operational instructions + current-partner
    declaration + tool descriptions + policy block.

    Legacy path (HAPAX_PERSONA_LEGACY=1): returns the pre-Phase-7 hard-coded
    prompt (NOT a personality — it is the deprecated revert target).

    Args:
        guest_mode: Partner is not the operator. Limits tool scope.
        policy_block: Optional conversational policy block from get_policy().
        experiment_mode: Strip tool descriptions for experimental / benchmark
            prompts (prompt-compression benchmark uses this).
        tool_recruitment_active: Tools are injected via schemas; don't
            duplicate them in the prompt.
    """
    if _legacy_mode():
        return _legacy_system_prompt(
            guest_mode, policy_block, experiment_mode, tool_recruitment_active
        )
    return _compose_prompt(guest_mode, experiment_mode, tool_recruitment_active, policy_block)


def voice_greeting() -> str:
    """Return a time-of-day greeting from the logos voice module."""
    return greeting()


def format_notification(title: str, message: str) -> str:
    """Combine title and message into a spoken notification."""
    summary = f"{title}: {message}" if message else title
    return _NOTIFICATION_TEMPLATE.format(name=operator_name(), summary=summary)


def session_end_message(queued_count: int = 0) -> str:
    """Return an appropriate session-ending message."""
    if queued_count > 0:
        return f"Before you go — I have {queued_count} notifications queued. Want to hear them?"
    return "Catch you later."


def screen_context_block(analysis: ScreenAnalysis | None) -> str:
    """Format screen/workspace analysis for injection into LLM system prompt."""
    if analysis is None:
        return ""
    lines = [
        "\n## Current Screen Context",
        f"App: {analysis.app}",
        f"Context: {analysis.context}",
        f"Summary: {analysis.summary}",
    ]
    if analysis.issues:
        lines.append("Issues:")
        for issue in analysis.issues:
            lines.append(
                f"  - [{issue.severity}] {issue.description} (confidence: {issue.confidence:.2f})"
            )

    # WorkspaceAnalysis extensions (duck-type check)
    if hasattr(analysis, "operator_present") and analysis.operator_present is not None:
        lines.append(
            f"Operator: {analysis.operator_activity}, attention on {analysis.operator_attention}"
        )
    if hasattr(analysis, "gear_state") and analysis.gear_state:
        lines.append("Hardware:")
        for g in analysis.gear_state:
            powered = "on" if g.powered else ("off" if g.powered is False else "unknown")
            lines.append(f"  - {g.device}: {powered}")
            if g.display_content:
                lines.append(f"    Display: {g.display_content}")

    return "\n".join(lines)
