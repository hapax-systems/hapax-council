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
    from agents.hapax_daimonion.ambient_classifier import AmbientResult
    from agents.hapax_daimonion.perception import EnvironmentState
    from agents.hapax_daimonion.screen_models import WorkspaceAnalysis

log = logging.getLogger(__name__)

_last_hash: int = 0


def serialize_environment(
    state: EnvironmentState,
    analysis: WorkspaceAnalysis | None,
    ambient: AmbientResult | None,
    perception_tier: str | None = None,
    experiment_mode: bool = False,
) -> str:
    """Serialize current environment to TOON for LLM context injection.

    Returns ~25-30 token block. Empty string if nothing changed since last call.

    When experiment_mode is True, returns only operator presence — strips all
    non-grounding-justified context to minimize prompt noise for research.
    """
    global _last_hash

    data: dict = {}

    if experiment_mode:
        # Experiment mode: presence only (Clark medium constraint #1: copresence)
        data["op"] = "present" if state.operator_present else "absent"
    else:
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
        data["op"] = "present" if state.operator_present else "absent"
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

        # Visual layer state (what's currently on the Corpora screen)
        corpora = _read_corpora_state()
        if corpora:
            data["corpora"] = corpora

    # Change detection
    content_hash = hash(str(sorted(data.items())))
    if content_hash == _last_hash:
        return ""
    _last_hash = content_hash

    return to_toon(data)


def _read_corpora_state() -> dict | None:
    """Read current visual layer state for voice context injection.

    Lets Hapax voice reference what's currently on the Corpora screen:
    signals, activity label, voice content, etc.
    """
    import json
    from pathlib import Path

    vl_path = Path("/dev/shm/hapax-compositor/visual-layer-state.json")
    try:
        data = json.loads(vl_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    result: dict = {}

    # Current display state
    display_state = data.get("display_state", "ambient")
    if display_state != "ambient":
        result["state"] = display_state

    # What Hapax thinks operator is doing
    activity = data.get("activity_label", "")
    if activity:
        result["activity"] = activity
        detail = data.get("activity_detail", "")
        if detail:
            result["activity_detail"] = detail

    # Active signals (what's showing on screen)
    signals = data.get("signals", {})
    visible = []
    for entries in signals.values():
        for sig in entries:
            title = sig.get("title", "")
            if title:
                visible.append(title)
    if visible:
        result["showing"] = visible[:5]

    # Ambient text fragment currently displayed
    ambient_text = data.get("ambient_text", "")
    if ambient_text:
        result["fragment"] = ambient_text

    return result if result else None
