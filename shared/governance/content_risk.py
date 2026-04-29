"""ContentRiskGate — broadcast-provenance filter (content-source-registry Phase 1).

Parallel axis to MonetizationRiskGate. Where monetization_safety classifies
SEMANTIC content risk (profanity, reaction-content), this gate classifies
BROADCAST PROVENANCE risk: where the audio/visual came from and whether
playing it on YouTube can trigger Content ID claims.

Risk tiers (`shared.affordance.ContentRisk`):

  unknown                  — missing/stale metadata; blocks public-capable
                              broadcast payloads
  tier_0_owned             — operator-owned, generated, hardware-captured
  tier_1_platform_cleared  — Storyblocks, Streambeats, YT Audio Library
  tier_2_provenance_known  — verified CC0, Internet Archive raw PD uploads
  tier_3_uncertain         — Bandcamp direct license per release, CC-BY
  tier_4_risky             — vinyl, commercial, raw type-beats, stream-ripped

Gate policy:

  unknown → block when public-capable/monetizable; allow only internal-only
            candidates that explicitly declare public_capable=False
  tier_4 → unconditional block
  tier_3 → permitted only when HAPAX_CONTENT_RISK_UNLOCK_TIER env contains
           the tier slug (operator session unlock, never auto-recruit)
  tier_2 → permitted only when programme.content_opt_ins includes the tier
  tier_0 / tier_1 → always permitted

Per `docs/superpowers/research/2026-04-23-content-source-registry-research.md`
§6 and `docs/superpowers/plans/2026-04-23-content-source-registry-plan.md`
Phase 1.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol, cast, runtime_checkable

from shared.affordance import ContentRisk

__all__ = [
    "GATE",
    "ContentRiskAssessment",
    "ContentRiskGate",
    "candidate_filter",
    "is_unlocked",
]

_log = logging.getLogger(__name__)

# Programme opt-ins are strings (the tier slug) so the protocol stays
# decoupled from the ContentRisk Literal at the type level. Programmes
# that haven't been migrated to opt into TIER 2+ default to tier_0/tier_1
# only — the safest posture.
_AUTO_PERMITTED: frozenset[str] = frozenset({"tier_0_owned", "tier_1_platform_cleared"})
_VALID_TIERS: frozenset[str] = frozenset(
    {
        "unknown",
        "tier_0_owned",
        "tier_1_platform_cleared",
        "tier_2_provenance_known",
        "tier_3_uncertain",
        "tier_4_risky",
    }
)
_PUBLIC_MEDIA: frozenset[str] = frozenset({"visual", "auditory", "speech", "textual"})

# tier_4 is the bottom of the broadcast scale. No path through; the only
# way TIER 4 content reaches broadcast is hardware-side (operator opens
# AUX-B for vinyl on the L-12) — which is exactly what the audio-safety
# detector watches for in PR #1238.
_NEVER_PERMITTED: frozenset[str] = frozenset({"tier_4_risky"})

# Operator session unlock — env-driven so the unlock state is visible to
# every consumer and does not require a separate persistent file or
# socket. Set to a comma-separated list of tier slugs (e.g.
# "tier_3_uncertain,tier_2_provenance_known") to permit those tiers for
# the duration of the session. Cleared by unsetting the env var.
_UNLOCK_ENV = "HAPAX_CONTENT_RISK_UNLOCK_TIER"


def is_unlocked(tier: ContentRisk) -> bool:
    """True when ``tier`` is permitted by the current session unlock env."""
    raw = os.environ.get(_UNLOCK_ENV, "")
    if not raw:
        return False
    return tier in {chunk.strip() for chunk in raw.split(",") if chunk.strip()}


def _coerce_tier(raw: Any) -> ContentRisk:
    """Normalize missing/stale payload tiers to ``unknown``."""
    if raw in _VALID_TIERS:
        return cast("ContentRisk", raw)
    return "unknown"


def _public_or_monetizable(payload: dict[str, Any]) -> bool:
    """Whether missing content-risk metadata must fail closed."""
    if payload.get("monetizable") is True:
        return True
    public_capable = payload.get("public_capable")
    if public_capable is True:
        return True
    if public_capable is False:
        return False
    medium = payload.get("medium")
    return isinstance(medium, str) and medium in _PUBLIC_MEDIA


@runtime_checkable
class _CandidateLike(Protocol):
    capability_name: str
    payload: dict[str, Any]


@runtime_checkable
class _ProgrammeLike(Protocol):
    @property
    def content_opt_ins(self) -> set[str] | frozenset[str]:
        """Tier slugs the active programme permits (e.g. tier_2_provenance_known)."""
        ...


class ContentRiskAssessment:
    """Per-candidate gate verdict. Pure value; no I/O."""

    __slots__ = ("allowed", "reason", "tier")

    def __init__(self, *, allowed: bool, tier: ContentRisk, reason: str) -> None:
        self.allowed = allowed
        self.tier = tier
        self.reason = reason

    def __repr__(self) -> str:
        return (
            f"ContentRiskAssessment(allowed={self.allowed!r}, "
            f"tier={self.tier!r}, reason={self.reason!r})"
        )


class ContentRiskGate:
    """Pure filter — never raises, never logs in the hot path.

    Stateless. The module-level singleton ``GATE`` is the canonical
    instance; callers should prefer ``candidate_filter()`` over
    instantiating their own gate.
    """

    def assess(
        self,
        candidate: _CandidateLike,
        programme: _ProgrammeLike | None = None,
    ) -> ContentRiskAssessment:
        """Verdict for a single candidate. Reads tier from ``payload``."""
        raw_tier = candidate.payload.get("content_risk")
        tier = _coerce_tier(raw_tier)
        name = candidate.capability_name
        if tier == "unknown":
            if _public_or_monetizable(candidate.payload):
                reason = "missing" if raw_tier is None else f"unknown value {raw_tier!r}"
                return ContentRiskAssessment(
                    allowed=False,
                    tier=tier,
                    reason=f"{name}: content_risk {reason}; public-capable broadcast fails closed",
                )
            return ContentRiskAssessment(
                allowed=True,
                tier=tier,
                reason=f"{name}: unknown content_risk on non-public capability — passed",
            )
        if tier in _AUTO_PERMITTED:
            return ContentRiskAssessment(
                allowed=True, tier=tier, reason=f"{name}: {tier} auto-permitted"
            )
        if tier in _NEVER_PERMITTED:
            return ContentRiskAssessment(
                allowed=False,
                tier=tier,
                reason=f"{name}: {tier} unconditionally blocked from broadcast",
            )
        # tier_2 and tier_3 are the gated middle. tier_3 is unlock-only
        # (operator session decision); tier_2 is programme-opt-in.
        if tier == "tier_3_uncertain":
            if is_unlocked(tier):
                return ContentRiskAssessment(
                    allowed=True,
                    tier=tier,
                    reason=f"{name}: {tier} permitted by session unlock",
                )
            return ContentRiskAssessment(
                allowed=False,
                tier=tier,
                reason=(f"{name}: {tier} requires session unlock (set {_UNLOCK_ENV}={tier})"),
            )
        if tier == "tier_2_provenance_known":
            opt_ins: set[str] | frozenset[str] = (
                set(getattr(programme, "content_opt_ins", set()) or set()) if programme else set()
            )
            if tier in opt_ins or is_unlocked(tier):
                return ContentRiskAssessment(
                    allowed=True,
                    tier=tier,
                    reason=f"{name}: {tier} permitted by programme opt-in or unlock",
                )
            return ContentRiskAssessment(
                allowed=False,
                tier=tier,
                reason=(
                    f"{name}: {tier} requires programme opt-in "
                    f"(add {tier!r} to programme.content_opt_ins)"
                ),
            )
        # Unknown tier — fail-closed. Should be impossible at runtime
        # because ContentRisk is a Literal; defensive branch for stale
        # payload data from a future schema.
        return ContentRiskAssessment(
            allowed=False,
            tier=tier,
            reason=f"{name}: unknown content_risk tier {tier!r} — failing closed",
        )

    def candidate_filter(
        self,
        candidates: list[_CandidateLike],
        programme: _ProgrammeLike | None = None,
    ) -> list[_CandidateLike]:
        """Return only candidates whose content_risk passes the gate."""
        return [c for c in candidates if self.assess(c, programme).allowed]


# Module singleton — stateless, prevents accidental drift if multiple
# ContentRiskGate instances were instantiated with divergent futures.
GATE = ContentRiskGate()


def candidate_filter(
    candidates: list[_CandidateLike],
    programme: _ProgrammeLike | None = None,
) -> list[_CandidateLike]:
    """Module-level convenience for the shared singleton."""
    return GATE.candidate_filter(candidates, programme)
