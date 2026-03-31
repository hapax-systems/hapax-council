"""Visual layer signal aggregator package.

Re-exports for backward compatibility with existing imports.
"""

from .aggregator import VisualLayerAggregator
from .constants import (
    FAST_INTERVAL_S,
    HEALTH_HISTORY_PATH,
    HEALTH_POLL_S,
    INFRA_SNAPSHOT_PATH,
    LANGFUSE_STATE_PATH,
    SLOW_INTERVAL_S,
    SLOW_POLL_S,
    STATE_TICK_BASE_S,
    WATCH_STATE_DIR,
)
from .signal_mappers import (
    _map_scene_inventory,
    map_biometrics,
    map_briefing,
    map_copilot,
    map_drift,
    map_goals,
    map_gpu,
    map_health,
    map_nudges,
    map_perception,
    map_phone,
    map_stimmung,
    map_voice_content,
    map_voice_session,
    time_of_day_warmth_offset,
)

__all__ = [
    "FAST_INTERVAL_S",
    "HEALTH_HISTORY_PATH",
    "HEALTH_POLL_S",
    "INFRA_SNAPSHOT_PATH",
    "LANGFUSE_STATE_PATH",
    "SLOW_INTERVAL_S",
    "SLOW_POLL_S",
    "STATE_TICK_BASE_S",
    "WATCH_STATE_DIR",
    "VisualLayerAggregator",
    "_map_scene_inventory",
    "map_biometrics",
    "map_briefing",
    "map_copilot",
    "map_drift",
    "map_goals",
    "map_gpu",
    "map_health",
    "map_nudges",
    "map_perception",
    "map_phone",
    "map_stimmung",
    "map_voice_content",
    "map_voice_session",
    "time_of_day_warmth_offset",
]
