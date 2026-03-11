"""Activity mode classification from fused workspace signals."""

from __future__ import annotations

from agents.hapax_voice.screen_models import WorkspaceAnalysis

# Apps that suggest coding/development
_CODE_APPS = {"foot", "code", "com.visualstudio.code", "neovim", "vim"}
# Apps that suggest browsing/research
_BROWSER_APPS = {"firefox", "chromium", "chrome", "com.google.Chrome"}
# Keywords in context suggesting video calls
_MEETING_KEYWORDS = {"video call", "meeting", "zoom", "teams", "google meet"}


def classify_activity_mode(
    analysis: WorkspaceAnalysis | None,
    audio_music: bool = False,
    audio_speech: bool = False,
) -> str:
    """Classify operator activity mode from workspace analysis + audio signals.

    Returns one of: coding, production, research, meeting, away, idle, unknown.
    """
    if analysis is None:
        return "unknown"

    if analysis.operator_present is False or analysis.operator_activity == "away":
        return "away"

    has_gear = any(g.powered for g in analysis.gear_state)
    context_lower = (analysis.context or "").lower()

    # Meeting detection: video call app + speech
    if audio_speech and any(kw in context_lower for kw in _MEETING_KEYWORDS):
        return "meeting"

    # Production: hardware active + music or hardware attention
    if has_gear and (audio_music or analysis.operator_attention == "hardware"):
        return "production"

    # Coding: terminal/IDE + typing
    if analysis.app in _CODE_APPS and analysis.operator_activity in ("typing", "unknown"):
        return "coding"

    # Research: browser + reading
    if analysis.app in _BROWSER_APPS:
        return "research"

    return "idle" if analysis.operator_present else "unknown"
