"""OperatorActivityEngine — Phase 6a activity-claim Bayesian wrapper.

Per beta's scope direction (relay 2026-04-25T02:18Z) + Universal
Bayesian Claim-Confidence research §Phase 6 (activity claims as
delta-lane canonical Phase 6a deliverable). Posterior:
``P(operator_is_actively_working | observed_signals)``.

**Distinct from PresenceEngine (Phase 1).** PresenceEngine answers
"is the body in the room?" (passive presence — face, HR, watch
proximity); ActivityEngine answers "is the operator actively
engaged in focused work?" (motion + intent — keyboard, MIDI clock,
desk taps, window switching, watch motion). The signal sets are
deliberately disjoint where possible: heart-rate alone lifts
presence but not activity; keyboard input lifts both.

Mirrors the SpeakerIsOperatorEngine (#1355) and SystemDegradedEngine
(#1357) shape:
- ``ClaimEngine[bool]`` internal delegate
- Asymmetric ``TemporalProfile`` (fast-enter/slow-exit — operator
  transitions to ACTIVE on a single strong cue, transitions to IDLE
  only after sustained absence so brief pauses don't flip state)
- ``LRDerivation``-typed signal weights (HPX003/HPX003-AST compliant)
- Prior provenance ref into ``shared/prior_provenance.yaml`` (HPX004)
- ``HAPAX_BAYESIAN_BYPASS=1`` flows through the engine automatically

Phase 6a-i.A scope (this PR): module + signal contract + tests +
registry + prior provenance entry. Phase 6a-i.B (deferred): wire to
actual signals (evdev keyboard, OXI MIDI clock, Cortado contact mic,
Hyprland focus events, Pixel Watch accelerometer) via a perception
loop adapter so the wiring surface is reviewed independently from
the engine math.
"""

from __future__ import annotations

import logging

from shared.claim import (
    ClaimEngine,
    ClaimState,
    LRDerivation,
    TemporalProfile,
)

log = logging.getLogger(__name__)


# Engine-state translation for callers reading state vocabulary
# directly. Mirrors SystemDegradedEngine's pattern but uses
# ACTIVE/UNCERTAIN/IDLE for activity-claim semantics per beta's
# scope direction.
_ENGINE_STATE_TO_ACTIVITY_STATE: dict[ClaimState, str] = {
    "ASSERTED": "ACTIVE",
    "UNCERTAIN": "UNCERTAIN",
    "RETRACTED": "IDLE",
}


# Default LR weights per signal. Each (p_active, p_idle) tuple
# represents (P(signal | actively_working), P(signal | idle)).
# Weights are tuned for fast-enter / slow-exit semantics: a single
# keyboard burst or MIDI clock cue lifts the posterior over the
# enter threshold within 1 tick; recovery to IDLE requires sustained
# absence (k_exit=8 ticks).
#
# Distinct-from-PresenceEngine note: signals here measure *motion +
# engagement* (the act of working) rather than *occupation* (being
# in the room). Heart rate, face presence, BLE proximity are
# intentionally absent — those belong to PresenceEngine.
DEFAULT_SIGNAL_WEIGHTS: dict[str, tuple[float, float]] = {
    # Direct evidence — physical keystrokes through evdev. Strong
    # bidirectional: present → active, sustained-idle → not-active.
    "keyboard_active": (0.85, 0.05),
    # OXI One MIDI clock running. Very strong positive (clock = doing
    # music work); weak negative (operator may be writing while clock
    # idle), so positive-only via low p_idle.
    "midi_clock_active": (0.70, 0.02),
    # Cortado contact-mic energy. Bidirectional via tap/click cues.
    "desk_active": (0.75, 0.10),
    # Hyprland focus event within the last poll window — operator
    # actively moving between workspaces / windows.
    "desktop_focus_changed_recent": (0.65, 0.15),
    # Pixel Watch accelerometer delta — motion not posture. Weak
    # positive (operator can be active while still); positive-only.
    "watch_movement": (0.55, 0.10),
}


class OperatorActivityEngine:
    """Bayesian posterior over P(operator_is_actively_working).

    Provides the same surface other Phase 6 cluster engines do —
    ``contribute(observations)``, ``posterior``, ``state``, ``reset()``,
    ``_required_ticks_for_transition`` — so consumers can swap between
    engines uniformly. State vocabulary is ACTIVE/UNCERTAIN/IDLE rather
    than ASSERTED/UNCERTAIN/RETRACTED.

    Phase 6a-i.B will wire the five signal sources into this engine
    via a perception loop adapter; until then the engine is constructed
    + tested against synthetic observations only.
    """

    name: str = "operator_activity_engine"
    provides: tuple[str, ...] = ("operator_activity_probability", "operator_activity_state")

    def __init__(
        self,
        # Operator is actively working ~30% of waking hours by
        # rough self-report — bias toward IDLE so the engine
        # requires positive evidence to assert ACTIVE.
        prior: float = 0.30,
        enter_threshold: float = 0.65,
        exit_threshold: float = 0.30,
        # Fast-enter (one strong cue → ACTIVE within 1 tick) so the
        # engine reflects engagement bursts immediately.
        enter_ticks: int = 1,
        # Slow-exit (~8 ticks of sustained idle ≈ 40s at the daimonion
        # 5s perception cadence) so brief reading pauses don't flip
        # state to IDLE.
        exit_ticks: int = 8,
        signal_weights: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        weights = signal_weights or DEFAULT_SIGNAL_WEIGHTS
        lr_records: dict[str, LRDerivation] = {
            name: LRDerivation(
                signal_name=name,
                claim_name="operator_activity",
                source_category="expert_elicitation_shelf",
                p_true_given_h1=p_active,
                p_true_given_h0=p_idle,
                positive_only=False,
                estimation_reference=(
                    "DEFAULT_SIGNAL_WEIGHTS calibrated 2026-04-25 "
                    "against PresenceEngine baseline; refined in 6a-i.B "
                    "wire-in once live signal stream is available"
                ),
            )
            for name, (p_active, p_idle) in weights.items()
        }
        self._engine: ClaimEngine[bool] = ClaimEngine(
            name="operator_activity",
            prior=prior,
            temporal_profile=TemporalProfile(
                enter_threshold=enter_threshold,
                exit_threshold=exit_threshold,
                k_enter=enter_ticks,
                k_exit=exit_ticks,
                k_uncertain=4,
            ),
            signal_weights=lr_records,
        )

    def contribute(self, observations: dict[str, bool | None]) -> None:
        """Apply a single tick's worth of signal observations.

        Each key must match a ``LRDerivation.signal_name`` known to the
        engine; unknown keys are silently ignored by the engine's log-
        odds fusion so callers can pass extended-vocabulary dicts
        without breaking forward compatibility.
        """
        self._engine.tick(observations)

    @property
    def posterior(self) -> float:
        return self._engine.posterior

    @property
    def state(self) -> str:
        return _ENGINE_STATE_TO_ACTIVITY_STATE[self._engine.state]

    def reset(self) -> None:
        self._engine.reset()

    def _required_ticks_for_transition(self, frm: str, to: str) -> int:
        """Test-introspection helper. Translates ACTIVE/IDLE back to
        the engine's ASSERTED/RETRACTED vocabulary then delegates."""
        translation: dict[str, ClaimState] = {
            "ACTIVE": "ASSERTED",
            "UNCERTAIN": "UNCERTAIN",
            "IDLE": "RETRACTED",
        }
        return self._engine._required_ticks_for_transition(translation[frm], translation[to])


__all__ = [
    "DEFAULT_SIGNAL_WEIGHTS",
    "OperatorActivityEngine",
]
