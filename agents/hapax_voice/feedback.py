"""Feedback loop wiring — accumulates ActuationEvents into Behaviors.

Subscribes to the actuation_event Event and updates Behaviors that governance
chains can read. Closes the perception → governance → actuation → feedback loop.
"""

from __future__ import annotations

from agents.hapax_voice.actuation_event import ActuationEvent
from agents.hapax_voice.primitives import Behavior, Event

# Actions that map to specific feedback Behaviors
_MC_ACTIONS = frozenset({"vocal_throw", "ad_lib"})
_OBS_ACTIONS = frozenset({"wide_ambient", "gear_closeup", "face_cam", "rapid_cut"})
_TTS_ACTIONS = frozenset({"tts_announce"})


def wire_feedback_behaviors(
    actuation_event: Event[ActuationEvent],
    watermark: float = 0.0,
) -> dict[str, Behavior]:
    """Create feedback Behaviors and wire them to actuation events.

    Returns:
        dict with keys: last_mc_fire, mc_fire_count, last_obs_switch, last_tts_end
    """
    last_mc_fire: Behavior[float] = Behavior(0.0, watermark=watermark)
    mc_fire_count: Behavior[int] = Behavior(0, watermark=watermark)
    last_obs_switch: Behavior[float] = Behavior(0.0, watermark=watermark)
    last_tts_end: Behavior[float] = Behavior(0.0, watermark=watermark)

    def _on_actuation(timestamp: float, event: ActuationEvent) -> None:
        if event.action in _MC_ACTIONS:
            last_mc_fire.update(event.wall_time, timestamp, consent_label=event.consent_label)
            mc_fire_count.update(
                mc_fire_count.value + 1, timestamp, consent_label=event.consent_label
            )
        elif event.action in _OBS_ACTIONS:
            last_obs_switch.update(event.wall_time, timestamp, consent_label=event.consent_label)
        elif event.action in _TTS_ACTIONS:
            last_tts_end.update(event.wall_time, timestamp, consent_label=event.consent_label)

    actuation_event.subscribe(_on_actuation)

    return {
        "last_mc_fire": last_mc_fire,
        "mc_fire_count": mc_fire_count,
        "last_obs_switch": last_obs_switch,
        "last_tts_end": last_tts_end,
    }
