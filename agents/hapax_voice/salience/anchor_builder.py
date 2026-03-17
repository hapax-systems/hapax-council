"""Build concern anchors from existing infrastructure.

Gathers keywords/phrases from workspace analysis, calendar, goals,
notifications, profile dimensions, and conversation history, then
returns them as ConcernAnchor objects ready for embedding.
"""

from __future__ import annotations

import logging

from agents.hapax_voice.salience.concern_graph import ConcernAnchor

log = logging.getLogger(__name__)

# Consent-related terms always get highest weight
_CONSENT_TERMS = [
    "consent",
    "permission",
    "recording",
    "privacy",
    "guest",
    "visitor",
    "who is here",
    "someone else",
    "another person",
]


def build_anchors(
    env_state: object | None = None,
    calendar_items: list[str] | None = None,
    goals: list[str] | None = None,
    notifications: list[str] | None = None,
    profile_keywords: list[str] | None = None,
    recent_topics: list[str] | None = None,
) -> list[ConcernAnchor]:
    """Build concern anchors from available infrastructure data.

    All inputs are optional — the system degrades gracefully when
    sources are unavailable.
    """
    anchors: list[ConcernAnchor] = []

    # Consent anchors — permanent, high weight (governance)
    for term in _CONSENT_TERMS:
        anchors.append(ConcernAnchor(text=term, source="consent", weight=2.0))

    # Workspace analysis keywords
    if env_state is not None:
        try:
            # EnvironmentState has workspace_summary, active_window, etc.
            ws = getattr(env_state, "workspace_summary", None)
            if ws and isinstance(ws, str):
                # Extract key phrases from workspace summary
                for phrase in _extract_phrases(ws):
                    anchors.append(ConcernAnchor(text=phrase, source="workspace", weight=1.0))

            # Active window title
            active = getattr(env_state, "active_window", None)
            if active and isinstance(active, str):
                anchors.append(ConcernAnchor(text=active, source="workspace", weight=0.8))

            # Activity mode
            activity = getattr(env_state, "activity_mode", None)
            if activity and isinstance(activity, str) and activity != "idle":
                anchors.append(ConcernAnchor(text=activity, source="workspace", weight=0.6))
        except Exception:
            log.debug("Failed to extract workspace anchors", exc_info=True)

    # Calendar items (next 24h)
    if calendar_items:
        for item in calendar_items[:10]:
            anchors.append(ConcernAnchor(text=item, source="calendar", weight=1.2))

    # Active goals
    if goals:
        for goal in goals[:10]:
            anchors.append(ConcernAnchor(text=goal, source="goal", weight=1.0))

    # Pending notifications
    if notifications:
        for notif in notifications[:5]:
            anchors.append(ConcernAnchor(text=notif, source="notification", weight=0.9))

    # Profile dimension keywords (stable, refresh daily)
    if profile_keywords:
        for kw in profile_keywords[:15]:
            anchors.append(ConcernAnchor(text=kw, source="profile", weight=0.7))

    # Recent conversation topics (sliding window)
    if recent_topics:
        for topic in recent_topics[-5:]:
            anchors.append(ConcernAnchor(text=topic, source="conversation", weight=0.5))

    log.debug(
        "Built %d concern anchors: %s",
        len(anchors),
        {a.source for a in anchors},
    )
    return anchors


def _extract_phrases(text: str, max_phrases: int = 10) -> list[str]:
    """Extract key phrases from a text block.

    Simple heuristic: split on sentences/lines, take significant ones.
    """
    phrases: list[str] = []
    for line in text.replace(". ", "\n").split("\n"):
        line = line.strip()
        if len(line) >= 5 and len(line.split()) >= 2:
            phrases.append(line[:100])  # cap length
            if len(phrases) >= max_phrases:
                break
    return phrases


def build_context_distillation(
    env_state: object | None = None,
    calendar_items: list[str] | None = None,
    notification_count: int = 0,
    drift_count: int = 0,
) -> str:
    """Generate a 2-3 sentence context distillation for LOCAL tier prompts.

    This replaces the stripped LOCAL prompt with grounded context so the
    local model doesn't sound vapid.
    """
    parts: list[str] = []

    # What the operator is doing
    if env_state is not None:
        activity = getattr(env_state, "activity_mode", "idle")
        ws = getattr(env_state, "workspace_summary", None)
        if ws and isinstance(ws, str):
            # Take first sentence
            first = ws.split(".")[0].strip()
            if first:
                parts.append(f"Ryan is {first.lower()}" if not first[0].isupper() else first)
        elif activity != "idle":
            parts.append(f"Ryan is {activity}")

    # Time context
    import time

    hour = time.localtime().tm_hour
    if 5 <= hour < 12:
        parts.append("Morning")
    elif 12 <= hour < 18:
        parts.append("Afternoon")
    elif 18 <= hour < 23:
        parts.append("Evening")
    else:
        parts.append("Late night")

    # Calendar
    if calendar_items:
        next_meeting = calendar_items[0]
        parts.append(f"Next: {next_meeting}")
    else:
        parts.append("No meetings today")

    # System state
    status_parts = []
    if drift_count > 0:
        status_parts.append(f"{drift_count} drift items")
    if notification_count > 0:
        status_parts.append(f"{notification_count} notifications")
    if status_parts:
        parts.append(", ".join(status_parts))

    return ". ".join(parts) + "." if parts else ""
