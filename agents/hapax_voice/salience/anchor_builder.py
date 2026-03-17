"""Build concern anchors from existing infrastructure.

Gathers keywords/phrases from workspace analysis, calendar, goals,
notifications, profile dimensions, conversation history, and temporal
bands (Husserlian retention/impression/protention/surprise) to build
the operator's concern graph for salience-based routing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agents.hapax_voice.salience.concern_graph import ConcernAnchor

log = logging.getLogger(__name__)

_TEMPORAL_PATH = Path("/dev/shm/hapax-temporal/bands.json")

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

    # Temporal bands (Husserlian retention/impression/protention/surprise)
    anchors.extend(_read_temporal_anchors())

    # Self-band: apperception self-observations with pending actions
    anchors.extend(_read_apperception_anchors())

    log.debug(
        "Built %d concern anchors: %s",
        len(anchors),
        {a.source for a in anchors},
    )
    return anchors


def _read_temporal_anchors() -> list[ConcernAnchor]:
    """Extract concern anchors from Husserlian temporal bands.

    Reads /dev/shm/hapax-temporal/bands.json (written by visual_layer_aggregator
    every perception tick). Extracts anchors from:
      - Impression: current activity, flow state, music genre
      - Retention: recent activities (what operator was doing)
      - Protention: predicted states (what's coming next)
      - Surprises: prediction mismatches (inherently salient)

    Staleness check: >30s → skip. Graceful degradation if file missing.
    """
    import time

    try:
        raw = json.loads(_TEMPORAL_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    except Exception:
        log.debug("Failed to read temporal bands", exc_info=True)
        return []

    # Staleness check
    ts = raw.get("timestamp", 0)
    if ts > 0 and (time.time() - ts) > 30:
        return []

    anchors: list[ConcernAnchor] = []

    # Parse the XML temporal context to extract structured data.
    # The raw JSON also has metadata fields we can use directly.
    xml = raw.get("xml", "")
    if not xml:
        return []

    # Extract from XML using simple string parsing (no XML library needed
    # for these predictable formats — avoids import overhead on hot path)

    # Impression: current activity and flow state
    activity = _xml_tag_content(xml, "activity")
    if activity and activity != "idle":
        anchors.append(ConcernAnchor(text=activity, source="temporal", weight=1.2))

    flow_state = _xml_tag_content(xml, "flow_state")
    if flow_state and flow_state != "idle":
        anchors.append(
            ConcernAnchor(text=f"{flow_state} flow state", source="temporal", weight=0.8)
        )

    music_genre = _xml_tag_content(xml, "music_genre")
    if music_genre:
        anchors.append(ConcernAnchor(text=music_genre, source="temporal", weight=0.4))

    # Retention: recent activities from memory tags
    # Format: <memory age_s="5" flow="active" activity="coding">coding, 78bpm</memory>
    for activity_attr in _xml_attr_values(xml, "memory", "activity"):
        if activity_attr and activity_attr != "idle":
            anchors.append(ConcernAnchor(text=activity_attr, source="temporal", weight=0.7))

    # Protention: predicted states
    # Format: <prediction state="entering_deep_work" confidence="0.72">basis</prediction>
    for state in _xml_attr_values(xml, "prediction", "state"):
        if state:
            # Convert snake_case to readable: "entering_deep_work" → "entering deep work"
            readable = state.replace("_", " ")
            anchors.append(ConcernAnchor(text=readable, source="protention", weight=0.9))

    # Surprises: prediction mismatches are inherently salient
    max_surprise = raw.get("max_surprise", 0.0)
    if max_surprise > 0.3:
        # Extract surprise observations from XML
        for observed in _xml_attr_values(xml, "surprise", "observed"):
            if observed:
                anchors.append(ConcernAnchor(text=observed, source="surprise", weight=1.5))

    # Deduplicate by text (temporal data repeats across bands)
    seen: set[str] = set()
    unique: list[ConcernAnchor] = []
    for a in anchors:
        if a.text not in seen:
            seen.add(a.text)
            unique.append(a)

    return unique


def _xml_tag_content(xml: str, tag: str) -> str:
    """Extract text content of a simple XML tag. Returns '' if not found."""
    import re

    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml)
    return m.group(1).strip() if m else ""


def _xml_attr_values(xml: str, tag: str, attr: str) -> list[str]:
    """Extract all values of an attribute from matching XML tags."""
    import re

    return re.findall(rf'<{tag}\b[^>]*\b{attr}="([^"]*)"', xml)


_APPERCEPTION_PATH = Path("/dev/shm/hapax-apperception/self-band.json")


def _read_apperception_anchors() -> list[ConcernAnchor]:
    """Extract concern anchors from self-band apperception state.

    Self-observations with pending actions become concern anchors (source="self").
    Dimensions with low confidence (< 0.3) also become anchors — the system
    is uncertain about an aspect of itself, which is relevant to routing.

    Staleness check: >30s → skip. Graceful degradation if file missing.
    """
    import time

    try:
        raw = json.loads(_APPERCEPTION_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    except Exception:
        log.debug("Failed to read apperception state", exc_info=True)
        return []

    # Staleness check
    ts = raw.get("timestamp", 0)
    if ts > 0 and (time.time() - ts) > 30:
        return []

    anchors: list[ConcernAnchor] = []
    model = raw.get("self_model", {})

    # Pending actions from cascade — high weight (actionable self-observations)
    for action in raw.get("pending_actions", [])[:5]:
        anchors.append(ConcernAnchor(text=action, source="self", weight=1.3))

    # Low-confidence dimensions — system is uncertain about itself
    for name, dim in model.get("dimensions", {}).items():
        confidence = dim.get("confidence", 0.5)
        if confidence < 0.3:
            anchors.append(
                ConcernAnchor(
                    text=f"uncertain about {name}",
                    source="self",
                    weight=0.8,
                )
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

    # Flow state from temporal bands
    try:
        raw = json.loads(_TEMPORAL_PATH.read_text(encoding="utf-8"))
        xml = raw.get("xml", "")
        if xml:
            flow = _xml_tag_content(xml, "flow_state")
            if flow and flow != "idle":
                parts.append(f"Flow: {flow}")
            flow_score = _xml_tag_content(xml, "flow_score")
            if flow_score:
                try:
                    fs = float(flow_score)
                    if fs > 0.6:
                        parts.append("Deep focus")
                except ValueError:
                    pass
    except Exception:
        pass  # graceful degradation

    # System state
    status_parts = []
    if drift_count > 0:
        status_parts.append(f"{drift_count} drift items")
    if notification_count > 0:
        status_parts.append(f"{notification_count} notifications")
    if status_parts:
        parts.append(", ".join(status_parts))

    return ". ".join(parts) + "." if parts else ""
