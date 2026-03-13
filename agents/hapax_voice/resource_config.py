"""Static resource mappings and priority configuration for the ResourceArbiter.

Maps action names to physical resources and defines per-(resource, chain) priorities.
"""

from __future__ import annotations

# Action name → physical resource
RESOURCE_MAP: dict[str, str] = {
    "vocal_throw": "audio_output",
    "ad_lib": "audio_output",
    "tts_announce": "audio_output",
    "wide_ambient": "obs_scene",
    "gear_closeup": "obs_scene",
    "face_cam": "obs_scene",
    "rapid_cut": "obs_scene",
}

# (resource, chain) → priority (higher = wins)
# Chain names must match the trigger_source field in Command objects
# produced by each governance pipeline.
DEFAULT_PRIORITIES: dict[tuple[str, str], int] = {
    # Audio output: conversation > MC > TTS
    ("audio_output", "conversation"): 100,
    ("audio_output", "mc_governance"): 50,
    ("audio_output", "tts"): 30,
    # OBS scene: conversation > OBS governance > MC
    ("obs_scene", "conversation"): 100,
    ("obs_scene", "obs_governance"): 70,
    ("obs_scene", "mc_governance"): 40,
}


def resource_for(action: str) -> str:
    """Look up the physical resource for an action. Raises KeyError if unmapped."""
    try:
        return RESOURCE_MAP[action]
    except KeyError:
        raise KeyError(f"No resource mapping for action: {action}") from None
