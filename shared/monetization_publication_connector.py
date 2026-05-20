"""Wire value braid readiness into the publication pipeline.

Bridges `monetization_readiness_ledger` to the publish orchestrator so
revenue-bearing surfaces check readiness before dispatch. Non-monetized
surfaces (weblog, Mastodon, Bluesky, Are.na) pass through unconditionally.

Authority case: CASE-VISIBILITY-ENGINE-001 item 6 —
"keep the monetization decision agent out of HN readiness while giving it a
real backlog WSJF path."
"""

from __future__ import annotations

import logging
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from shared.monetization_readiness_ledger import (
    MonetizationReadinessLedger,
    TargetFamilyLedgerEntry,
)

log = logging.getLogger(__name__)

REVENUE_BEARING_SURFACES: frozenset[str] = frozenset(
    {
        "youtube-monetized",
        "github-sponsors",
        "ko-fi",
        "patreon",
        "buy-me-a-coffee",
        "gumroad",
        "lemon-squeezy",
    }
)


class MonetizationDecision(StrEnum):
    PROCEED = "proceed"
    NOT_READY = "not_ready"
    FLAGGED_FOR_REVIEW = "flagged_for_review"


class MonetizationCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    surface: str
    decision: MonetizationDecision
    reason: str
    missing_dimensions: tuple[str, ...] = Field(default_factory=tuple)
    revenue_bearing: bool = False


def check_surface_monetization_readiness(
    surface_slug: str,
    *,
    ledger: MonetizationReadinessLedger | None = None,
) -> MonetizationCheckResult:
    """Check if a surface is cleared for dispatch given monetization readiness.

    Non-revenue surfaces always return PROCEED. Revenue-bearing surfaces
    consult the monetization readiness ledger.
    """
    if surface_slug not in REVENUE_BEARING_SURFACES:
        return MonetizationCheckResult(
            surface=surface_slug,
            decision=MonetizationDecision.PROCEED,
            reason="non-revenue surface; no monetization gate",
            revenue_bearing=False,
        )

    if ledger is None:
        return MonetizationCheckResult(
            surface=surface_slug,
            decision=MonetizationDecision.NOT_READY,
            reason="no monetization readiness ledger provided",
            revenue_bearing=True,
        )

    family_id = _surface_to_target_family(surface_slug)
    try:
        entry: TargetFamilyLedgerEntry = ledger.for_target_family(family_id)
    except KeyError:
        return MonetizationCheckResult(
            surface=surface_slug,
            decision=MonetizationDecision.NOT_READY,
            reason=f"no readiness entry for target family '{family_id}'",
            revenue_bearing=True,
        )

    if entry.decision.allowed:
        return MonetizationCheckResult(
            surface=surface_slug,
            decision=MonetizationDecision.PROCEED,
            reason=f"readiness confirmed: {entry.decision.effective_state}",
            revenue_bearing=True,
        )

    missing = tuple(
        str(d) for d in entry.relevant_dimensions if d not in entry.satisfied_dimensions
    )
    reasons = "; ".join(entry.operator_visible_reasons) if entry.operator_visible_reasons else ""

    return MonetizationCheckResult(
        surface=surface_slug,
        decision=MonetizationDecision.NOT_READY,
        reason=reasons or f"not ready for {family_id}",
        missing_dimensions=missing,
        revenue_bearing=True,
    )


def _surface_to_target_family(surface_slug: str) -> str:
    mapping: dict[str, str] = {
        "youtube-monetized": "youtube_vod_packaging",
        "github-sponsors": "support_prompt",
        "ko-fi": "support_prompt",
        "patreon": "support_prompt",
        "buy-me-a-coffee": "support_prompt",
        "gumroad": "artifact_edition_release",
        "lemon-squeezy": "artifact_edition_release",
    }
    return mapping.get(surface_slug, surface_slug)


__all__ = [
    "REVENUE_BEARING_SURFACES",
    "MonetizationCheckResult",
    "MonetizationDecision",
    "check_surface_monetization_readiness",
]
