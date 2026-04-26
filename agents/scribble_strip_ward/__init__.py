"""L-12 channel-strip diagnostic ward — data model + invariants (Phase 1).

Per ``feedback-prevention-scribble-strip-ward``: a ward in the studio
compositor that renders a diagrammatic L-12 channel strip (12 input
strips + AUX A through E + EFX). Each strip carries a *routing
assertion* — a short structured invariant statement, not narrative
prose. Ward-as-checklist, NOT ward-as-narration.

Phase 1 (this module) ships the data model + invariant validation:
- ``StripAssertion`` — one input-channel routing fact
- ``AuxAssertion`` — one AUX-bus routing fact
- ``ScribbleStripState`` — the full 12-input + 5-AUX + EFX model
- Validation pins per the operator's L-12 routing-discipline directives
  (e.g., AUX B's "SEND-B-MUST-BE-ZERO" on the Evil-Pet return)

Phase 2 will ship the Cairo overlay rendering on top of this model;
the data model is the source of truth, the renderer reads it and
draws.

Spec: ``feedback_show_dont_tell_director``,
``feedback_no_blinking_homage_wards``, ``feedback_gem_aesthetic_bar``,
``feedback_features_on_by_default``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PhantomState = Literal["+48V", "phantom-bank-1-4", "phantom-safe", "phantom-OFF", "n/a"]
"""Per-channel phantom-power posture. ``+48V`` = phantom on this strip;
``phantom-bank-1-4`` = strip is in the 1-4 bank that the L-12 ganged-
phantom switch covers; ``phantom-safe`` = strip carries a +48-tolerant
input (DI / line); ``phantom-OFF`` = phantom must be off here;
``n/a`` = not applicable (digital return, etc.)."""


class StripAssertion(BaseModel):
    """One input-channel routing assertion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: int = Field(ge=1, le=12)
    label: str = Field(max_length=24)
    """Short human-readable name, e.g. 'Cortado contact mic'."""
    phantom: PhantomState = "n/a"
    notes: str = ""
    """Free-form short note, e.g. 'reserve' or 'phantom-bank 1-4'."""

    @field_validator("label", "notes")
    @classmethod
    def _no_narrative(cls, v: str) -> str:
        """Show-don't-tell pin: reject narrative-shape strings.

        The strip is a checklist, not a narration. Strings like 'is
        listening' / 'will route' / 'currently active' contradict the
        ``feedback_show_dont_tell_director`` directive.
        """
        forbidden_phrases = ("listening", "currently", "is active", "will route")
        lower = v.lower()
        for phrase in forbidden_phrases:
            if phrase in lower:
                raise ValueError(f"narrative-shape phrase forbidden in scribble-strip: {phrase!r}")
        return v


AuxBus = Literal["A", "B", "C", "D", "E", "EFX"]
"""L-12's 5 AUX buses + EFX (effects send/return)."""


class AuxAssertion(BaseModel):
    """One AUX-bus routing assertion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bus: AuxBus
    label: str = Field(max_length=32)
    invariant: str = ""
    """Optional invariant statement, e.g. 'CH 6 SEND-B-MUST-BE-ZERO'.
    Kept short — the strip is a checklist, not documentation."""


class ScribbleStripState(BaseModel):
    """Full L-12 channel-strip state for the diagnostic ward."""

    model_config = ConfigDict(extra="forbid")

    strips: list[StripAssertion]
    aux: list[AuxAssertion]

    @field_validator("strips")
    @classmethod
    def _exactly_12_strips(cls, v: list[StripAssertion]) -> list[StripAssertion]:
        if len(v) != 12:
            raise ValueError(f"L-12 has 12 input channels; got {len(v)}")
        channels = sorted(s.channel for s in v)
        if channels != list(range(1, 13)):
            raise ValueError(f"strips must cover channels 1-12 exactly; got {channels}")
        return v

    @field_validator("aux")
    @classmethod
    def _aux_subset(cls, v: list[AuxAssertion]) -> list[AuxAssertion]:
        # Bus values are constrained by AuxBus Literal; no duplicates.
        seen: set[AuxBus] = set()
        for entry in v:
            if entry.bus in seen:
                raise ValueError(f"duplicate AUX bus: {entry.bus}")
            seen.add(entry.bus)
        return v


# ── Operator-curated routing invariants ────────────────────────────


def evilpet_send_b_invariant_present(state: ScribbleStripState) -> bool:
    """Pin per project memory: AUX B carries the Evil-Pet return; the
    operator's directive is that the Evil-Pet return channel's SEND-B
    must be zero (otherwise feedback loop). This validator returns True
    iff the AUX B assertion explicitly carries that invariant.
    """
    return any(entry.bus == "B" and "SEND-B-MUST-BE-ZERO" in entry.invariant for entry in state.aux)


__all__ = [
    "AuxAssertion",
    "AuxBus",
    "PhantomState",
    "ScribbleStripState",
    "StripAssertion",
    "evilpet_send_b_invariant_present",
]
