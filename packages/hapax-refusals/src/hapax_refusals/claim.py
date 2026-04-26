"""Lightweight claim model for the refusal gate.

The full Hapax ``Claim`` model (in ``shared.claim`` upstream) carries
the full Bayesian provenance trail — temporal profile, prior
provenance, signal weights, evidence references. Most downstream
users of ``hapax-refusals`` do not need that depth; they need a
calibrated posterior, a name, and a proposition.

:class:`ClaimSpec` is the minimal shape the gate needs. Callers can
upcast their fuller domain ``Claim`` model into a ``ClaimSpec`` with
a one-line adapter, and the upstream Hapax monorepo's full
``shared.claim.Claim`` is structurally compatible (same three field
names: ``name``, ``proposition``, ``posterior``) so a Hapax-internal
caller can pass a ``shared.claim.Claim`` directly without conversion
because Pydantic v2 duck-types on shape.

The claim model does NOT include the temporal profile, evidence
sources, or prior provenance. Those are the responsibility of the
sensor pipeline; here we only need the calibrated posterior.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ClaimSpec(BaseModel):
    """One calibrated assertion the LLM may or may not narrate.

    Attributes:
        name: Stable identifier (snake_case). Token overlap against
            the LLM's emitted propositions decides whether a sentence
            is asserting *this* claim. Choose names that include the
            content tokens you expect the LLM to produce — e.g.
            ``vinyl_is_playing`` not ``c1`` — because the matcher
            scans for every token of length ≥ 3 in lowercased form.
        posterior: Calibrated probability in [0, 1]. The gate's
            per-surface floor is compared against this number.
        proposition: Human-readable rendering, used in re-roll
            prompt addenda so the LLM sees a clear restatement of
            what it was asked to retract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    posterior: float = Field(ge=0.0, le=1.0)
    proposition: str = Field(min_length=1)


__all__ = ["ClaimSpec"]
