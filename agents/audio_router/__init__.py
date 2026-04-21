"""Audio router agent (Phase B3 of evilpet-s4-dynamic-dual-processor-plan).

The arbiter. Reads runtime state (stimmung, programme, impingement,
broadcaster, intelligibility budget, hardware), applies a three-layer
policy (safety clamps / context lookup / salience modulation), and
emits routing intent: Evil Pet preset + S-4 scene + software gains.

Spec: docs/superpowers/specs/2026-04-21-evilpet-s4-dynamic-dual-processor-design.md §6
Plan: docs/superpowers/plans/2026-04-21-evilpet-s4-dynamic-dual-processor-plan.md B3

This package ships the policy layers as pure functions (no hardware,
no MIDI, no side effects). The tick loop / MIDI emission / state
watchers are in ``dynamic_router.py`` (to be wired when S-4 plugs in).
"""

from agents.audio_router.policy import (
    apply_context_lookup,
    apply_safety_clamps,
    apply_salience_modulation,
    arbitrate,
    compute_ramp_seconds,
)
from agents.audio_router.state import (
    AudioRouterState,
    BroadcasterState,
    HardwareState,
    ImpingementDelta,
    IntelligibilityBudget,
    ProgrammeState,
    RoutingIntent,
    Stance,
    StimmungState,
)
from agents.audio_router.sticky import DEFAULT_STICK_WINDOW_S, StickyTracker

__all__ = [
    # State models
    "AudioRouterState",
    "BroadcasterState",
    "HardwareState",
    "ImpingementDelta",
    "IntelligibilityBudget",
    "ProgrammeState",
    "RoutingIntent",
    "Stance",
    "StimmungState",
    # Policy functions
    "apply_context_lookup",
    "apply_safety_clamps",
    "apply_salience_modulation",
    "arbitrate",
    "compute_ramp_seconds",
    # Sticky (utterance-boundary) tracker
    "StickyTracker",
    "DEFAULT_STICK_WINDOW_S",
]
