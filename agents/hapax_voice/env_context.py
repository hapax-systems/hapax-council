"""Environment context serializer for voice LLM injection.

Serializes current perception state to TOON format for per-turn
context injection into the conversation LLM. Ephemeral — never persisted.

Constraints:
- No mood/emotion/body state — only objective observations
- Ephemeral — exists only in conversation messages, never logged
- Consent-aware — face count but no identity when guests present
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from shared.context_compression import to_toon

if TYPE_CHECKING:
    from agents.hapax_voice.ambient_classifier import AmbientResult
    from agents.hapax_voice.perception import EnvironmentState
    from agents.hapax_voice.screen_models import WorkspaceAnalysis

log = logging.getLogger(__name__)

_last_hash: int = 0


def serialize_environment(
    state: EnvironmentState,
    analysis: WorkspaceAnalysis | None,
    ambient: AmbientResult | None,
    perception_tier: str | None = None,
) -> str:
    """Serialize current environment to TOON for LLM context injection.

    Returns ~25-30 token block. Empty string if nothing changed since last call.
    """
    global _last_hash

    data: dict = {}

    # App context from workspace analysis
    if analysis is not None:
        data["app"] = analysis.app
        data["ctx"] = analysis.context
        if analysis.gear_state:
            data["gear"] = [
                {"id": g.device, "status": "on" if g.powered else "off"}
                for g in analysis.gear_state
                if g.powered is not None
            ]

    # Desktop state
    if state.active_window is not None:
        win_class = getattr(state.active_window, "wm_class", "")
        win_title = getattr(state.active_window, "title", "")
        if win_class and "app" not in data:
            data["app"] = win_class
        if win_title:
            data["title"] = win_title[:60]

    # Operator presence
    if state.operator_present:
        data["op"] = "present"
    else:
        data["op"] = "absent"

    data["faces"] = state.face_count

    # Audio classification (during session)
    if ambient is not None and ambient.top_labels:
        top_label, top_score = ambient.top_labels[0]
        if top_score > 0.1:
            data["audio"] = top_label

    # Activity mode
    if state.activity_mode != "unknown":
        data["mode"] = state.activity_mode

    # Perception tier (so LLM knows its awareness level)
    if perception_tier and perception_tier != "full":
        data["perception"] = perception_tier

    # Change detection
    content_hash = hash(str(sorted(data.items())))
    if content_hash == _last_hash:
        return ""
    _last_hash = content_hash

    return to_toon(data)
