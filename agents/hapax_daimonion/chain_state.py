"""Cross-role state types and Behavior factory for multi-role composition.

GovernanceChainState and ConversationState enums define the possible states
for governance chains and conversation tracking. The factory function creates
sentinel-initialized Behaviors for cross-role publication.
"""

from __future__ import annotations

from enum import Enum

from agents.hapax_daimonion.primitives import Behavior


class GovernanceChainState(Enum):
    """State of a governance chain (MC, OBS, etc.)."""

    IDLE = "idle"
    ACTIVE = "active"
    SUPPRESSED = "suppressed"
    FIRING = "firing"


class ConversationState(Enum):
    """State of the voice conversation pipeline."""

    IDLE = "idle"
    LISTENING = "listening"
    SPEAKING = "speaking"
    PROCESSING = "processing"


def create_cross_role_behaviors(watermark: float = 0.0) -> dict[str, Behavior]:
    """Create sentinel-initialized Behaviors for cross-role state publication.

    Returns a dict of named Behaviors that governance chains can read to
    coordinate across roles. All are immediately sampleable.

    Keys:
        mc_state: GovernanceChainState — current MC governance state
        conversation_state: ConversationState — voice pipeline state
        current_scene: str — current OBS scene name
        conversation_suppression: float — suppression level from conversation
        mc_activity: float — suppression level from MC activity
        monitoring_alert: float — suppression level from monitoring alerts
    """
    return {
        "mc_state": Behavior(GovernanceChainState.IDLE, watermark=watermark),
        "conversation_state": Behavior(ConversationState.IDLE, watermark=watermark),
        "current_scene": Behavior("wide_ambient", watermark=watermark),
        "conversation_suppression": Behavior(0.0, watermark=watermark),
        "mc_activity": Behavior(0.0, watermark=watermark),
        "monitoring_alert": Behavior(0.0, watermark=watermark),
    }
