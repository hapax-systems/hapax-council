"""Refusal-brief annex helper for receive-rail surfaces.

When a rail's API path requires operator-physical interaction
(Alby OAuth flow, Liberapay KYC threshold, etc.), the rail emits one
``RefusalEvent`` to the canonical refusal log and disables itself.
Other rails continue running so the PR ships partial coverage rather
than failing closed.

Constitutional fit: refusal-as-data per
``feedback_full_automation_or_no_engagement``. The annex is one
line of structured data, not a narrative — the operator's omg.lol
fanout surfaces refusals individually and the operator can react
(swap rail config, accept the kyc step, demote rail to
CONDITIONAL_ENGAGE).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from agents.refusal_brief import RefusalEvent, append

log = logging.getLogger(__name__)

# Axiom name is shared across all three rails — the same constitutional
# directive applies to every payment surface (full-automation-or-none).
RAIL_REFUSAL_AXIOM = "full_auto_or_nothing"


def emit_rail_refusal(
    *,
    rail: str,
    surface: str,
    reason: str,
    refusal_brief_link: str | None = None,
) -> bool:
    """Emit one refusal event for a rail that cannot run full-auto.

    Returns True iff the refusal was appended. The caller should
    disable its polling loop after this call so the rail does not
    re-trigger every tick.
    """
    event = RefusalEvent(
        timestamp=datetime.now(UTC),
        axiom=RAIL_REFUSAL_AXIOM,
        surface=f"payment-rail:{rail}:{surface}",
        reason=reason[:160],  # writer enforces max_length=160
        refusal_brief_link=refusal_brief_link,
    )
    ok = append(event)
    if ok:
        log.info("rail refusal emitted: rail=%s surface=%s", rail, surface)
    return ok


__all__ = ["RAIL_REFUSAL_AXIOM", "emit_rail_refusal"]
