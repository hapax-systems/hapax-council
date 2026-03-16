"""Hapax persona — system prompts, greetings, notification formatting."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cockpit.voice import greeting, operator_name

if TYPE_CHECKING:
    from agents.hapax_voice.screen_models import ScreenAnalysis

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
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
    "System:\n"
    "- get_system_status: health checks (docker, gpu, services, network, voice).\n"
    "- check_consent_status, describe_consent_flow, check_governance_health.\n\n"
    "You can search documents, emails, calendar, and Drive — but you do NOT have "
    "access to the operator profile, conversation memory, or governance precedents.\n"
    "Use tools proactively — don't guess when you can look it up."
)

_GUEST_PROMPT = (
    "You are Hapax, a voice assistant. "
    "You're chatting with someone who isn't your primary operator. "
    "Be friendly and helpful for general conversation, but you cannot access "
    "system information, briefings, or personal data. "
    "If asked about those, explain that you'll need the operator for that."
)

_NOTIFICATION_TEMPLATE = "Hey {name} — {summary}"


def system_prompt(guest_mode: bool = False, policy_block: str = "") -> str:
    """Return the system prompt for the current session mode.

    Args:
        guest_mode: Whether in guest mode (non-operator primary speaker).
        policy_block: Optional conversational policy block from get_policy().
    """
    if guest_mode:
        return _GUEST_PROMPT + policy_block
    return _SYSTEM_PROMPT.format(name=operator_name()) + policy_block


def voice_greeting() -> str:
    """Return a time-of-day greeting from the cockpit voice module."""
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
