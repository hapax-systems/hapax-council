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
    "You have full access to {name}'s system: briefings, calendar, meeting prep, "
    "notifications, and infrastructure status. "
    "You can search documents, emails, and notes. "
    "You can check the calendar and look up real-time events. "
    "You can send SMS messages (always confirm before sending). "
    "You can see through cameras and the screen when asked. "
    "You can generate and edit images — take photos and transform them, "
    "create artwork, make memes. Results appear on screen. "
    "When {name} asks how they look or anything about appearance, "
    "respond naturally and honestly like a friend would — not clinical. "
    "If {name} says just your name without a clear request, "
    "make a brief contextual offer based on what you know — "
    "upcoming calendar, time of day, workspace state, pending notifications. "
    "Frame it as a gentle possibility, not an assumption. One sentence. "
    "Keep responses spoken-natural and brief. "
    "When reading data, summarize — don't dump raw output. "
    "If asked to go deeper, elaborate. "
    "You know {name} well — use first name, skip formalities. "
    "Before calling a tool, say a brief natural bridge — "
    "'Let me check', 'One moment', 'Looking into that', 'On it', or similar. "
    "Vary your phrasing naturally — never start two responses the same way. "
    "For simple questions you can answer directly, skip the bridge."
)

_GUEST_PROMPT = (
    "You are Hapax, a voice assistant. "
    "You're chatting with someone who isn't your primary operator. "
    "Be friendly and helpful for general conversation, but you cannot access "
    "system information, briefings, or personal data. "
    "If asked about those, explain that you'll need the operator for that."
)

_NOTIFICATION_TEMPLATE = "Hey {name} — {summary}"


def system_prompt(guest_mode: bool = False) -> str:
    """Return the system prompt for the current session mode."""
    if guest_mode:
        return _GUEST_PROMPT
    return _SYSTEM_PROMPT.format(name=operator_name())


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
