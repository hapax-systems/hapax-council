"""Public claim gate — evidence-bound classifier for metadata claims.

Per cc-task ``metadata-public-claim-gate`` (WSJF 9.4). YouTube + cross-
surface metadata routinely composes claims that look like statements of
fact ("live now", "current programme role", "monetization ready",
"archive available"). Without an evidence gate, those claims drift
into hallucination — the composer asserts what the operator wishes
were true rather than what is currently witnessed by the world-
capability surface (WCS) and chronicle public-event log.

This module ships the **gate model** consumers use to validate each
claim before it lands in metadata output. ``compose_metadata`` records
its scope-level gate result in ``grounding_provenance`` and emits
refusal/correction copy when a required public claim lacks evidence.
The same predicate library is reusable by the ``github-public-claim-
evidence-gate`` cc-task surface.

Design surface
--------------

* :class:`ClaimKind` — enumerates the public-claim taxonomy.
* :class:`ClaimEvidence` — frozen dataclass carrying the per-kind
  evidence the gate needs (broadcast id, egress state, programme role,
  rights status, monetization readiness, etc.).
* :class:`PublicClaimGateDecision` — gate verdict (``ALLOW`` / ``REFUSE``
  / ``CORRECT``) plus correction copy to swap into metadata when the
  raw claim is unsupported.
* :func:`evaluate_public_claim` — pure function from (kind, claim_text,
  evidence) to :class:`PublicClaimGateDecision`.

Authority floor
---------------

The gate is **fail-CLOSED**: when evidence is missing or stale,
:class:`Decision.REFUSE` (with corrected copy) is returned rather than
silently allowing the claim through. This mirrors the constitutional
posture in ``hapax-research/audits/2026-04-29-expert-system-rule-style-
grounding-violations.md`` — public surfaces cannot claim what the
runtime cannot witness.

Reusability
-----------

The gate is consumed by the metadata composer and by
``github-public-claim-evidence-gate`` (README/profile/repo metadata/
package/release surfaces). Both call ``evaluate_public_claim`` with the
same evidence fixture; only the per-claim wiring differs.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

# ── Constants ────────────────────────────────────────────────────────

#: Match the `PRIVATE_SENTINEL_DO_NOT_PUBLISH_*` token introduced in
#: PR #2526. Any text-bearing public-claim evidence carrying this token
#: is fail-CLOSED at the gate so cross-surface private text never lands
#: in public metadata.
_PRIVATE_SENTINEL_PATTERN = re.compile(r"PRIVATE_SENTINEL_DO_NOT_PUBLISH_[A-Z0-9_]+")

#: Maximum age (seconds) for a broadcast id to count as "current". A
#: broadcast id older than this is treated as a stale pointer; the
#: live-now claim REFUSES even if the id is otherwise well-formed.
DEFAULT_BROADCAST_FRESHNESS_S: float = 30.0

#: Maximum age for a programme role to count as "current". The
#: programme role is updated by the run-store every few seconds during
#: a programme; ten seconds is generous enough to absorb tick jitter
#: without granting a stale role to the public surface.
DEFAULT_PROGRAMME_FRESHNESS_S: float = 10.0


class ClaimKind(enum.StrEnum):
    """The taxonomy of public claims the gate validates."""

    LIVE_NOW = "live_now"
    """The surface asserts that broadcast is currently live."""

    CURRENT_ACTIVITY = "current_activity"
    """The surface asserts a current activity (coding, mixing, etc.)."""

    PROGRAMME_ROLE = "programme_role"
    """The surface asserts the operator's current programme role."""

    ARCHIVE = "archive"
    """The surface asserts the existence of a public VOD archive."""

    REPLAY = "replay"
    """The surface asserts a public replay/replay-ready URL."""

    SUPPORT = "support"
    """The surface asserts support readiness (Patreon, GH Sponsors, etc.)."""

    MONETIZATION = "monetization"
    """The surface asserts monetization readiness (ads, memberships)."""

    LICENSE_CLASS = "license_class"
    """The surface asserts a redistribution license class."""

    PUBLICATION_STATE = "publication_state"
    """The surface asserts a publication state (e.g., 'released',
    'preprint available') for an artifact."""

    DISABLED_ISSUES = "disabled_issues"
    """The surface asserts that issues / discussions are disabled."""


class Decision(enum.StrEnum):
    """The gate's verdict on a single claim."""

    ALLOW = "allow"
    """Claim passes; metadata may emit it as-is."""

    REFUSE = "refuse"
    """Claim is not evidence-backed; metadata must drop it (or use the
    correction copy in the decision)."""

    CORRECT = "correct"
    """Claim is partially supported but the surface text overclaims; the
    decision's ``correction`` field carries replacement copy that
    states what the evidence actually supports."""


@dataclass(frozen=True)
class ClaimEvidence:
    """Per-kind evidence the gate consults.

    All fields are optional; the gate's per-kind logic decides which
    combination of fields is required for ALLOW. Missing evidence
    fail-CLOSES to REFUSE.

    Constraints by kind:

    * ``live_now`` — requires ``broadcast_id``, ``broadcast_age_s`` <=
      :data:`DEFAULT_BROADCAST_FRESHNESS_S`, and ``egress_active=True``.
    * ``current_activity`` — requires ``current_activity`` non-empty.
    * ``programme_role`` — requires ``programme_role`` non-empty AND
      ``programme_role_age_s`` <= :data:`DEFAULT_PROGRAMME_FRESHNESS_S`.
    * ``archive`` / ``replay`` — requires ``archive_url`` non-empty AND
      ``rights_clear=True``.
    * ``support`` — requires ``support_surface_active=True``.
    * ``monetization`` — requires ``monetization_active=True``.
    * ``license_class`` — requires ``declared_license`` non-empty AND
      ``license_consistent=True`` (the canonical surfaces — NOTICE,
      CITATION, codemeta — agree among themselves).
    * ``publication_state`` — requires ``publication_state`` non-empty
      AND ``publication_evidence_url`` non-empty (a deposit DOI or
      release URL).
    * ``disabled_issues`` — requires ``issues_disabled=True``.
    """

    # Broadcast / live evidence
    broadcast_id: str = ""
    broadcast_age_s: float | None = None
    egress_active: bool = False

    # Activity / programme evidence
    current_activity: str = ""
    programme_role: str = ""
    programme_role_age_s: float | None = None

    # Archive / replay evidence
    archive_url: str = ""
    rights_clear: bool = False

    # Support / monetization evidence
    support_surface_active: bool = False
    monetization_active: bool = False

    # License / publication / repo evidence
    declared_license: str = ""
    license_consistent: bool = False
    publication_state: str = ""
    publication_evidence_url: str = ""
    issues_disabled: bool = False


@dataclass(frozen=True)
class PublicClaimGateDecision:
    """Verdict for one claim evaluation."""

    decision: Decision
    kind: ClaimKind
    reason: str
    """Short human-readable rationale for the verdict."""
    correction: str = ""
    """Replacement copy to use when ``decision == Decision.CORRECT``
    (or when the consumer chooses to publish a correction in place of
    a refused claim)."""

    @property
    def allows_emission(self) -> bool:
        """``True`` iff the consumer may emit the original claim copy."""
        return self.decision is Decision.ALLOW


# ── Per-kind evaluators ──────────────────────────────────────────────


def _eval_live_now(
    evidence: ClaimEvidence,
    *,
    broadcast_freshness_s: float,
    programme_freshness_s: float = DEFAULT_PROGRAMME_FRESHNESS_S,
) -> PublicClaimGateDecision:
    del programme_freshness_s  # unused for live_now; accepted for dispatch uniformity
    if not evidence.broadcast_id:
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.LIVE_NOW,
            reason="no broadcast_id in evidence",
            correction="not currently broadcasting",
        )
    if evidence.broadcast_age_s is None or evidence.broadcast_age_s > broadcast_freshness_s:
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.LIVE_NOW,
            reason=(
                "broadcast_id stale "
                f"(age={evidence.broadcast_age_s}s, ceiling={broadcast_freshness_s}s)"
            ),
            correction="not currently broadcasting",
        )
    if not evidence.egress_active:
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.LIVE_NOW,
            reason="egress_active=False (broadcast pipeline not emitting)",
            correction="not currently broadcasting",
        )
    return PublicClaimGateDecision(
        decision=Decision.ALLOW,
        kind=ClaimKind.LIVE_NOW,
        reason="broadcast id fresh and egress active",
    )


def _eval_current_activity(evidence: ClaimEvidence) -> PublicClaimGateDecision:
    if not evidence.current_activity:
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.CURRENT_ACTIVITY,
            reason="no current_activity in evidence",
            correction="activity not currently witnessed",
        )
    if _PRIVATE_SENTINEL_PATTERN.search(evidence.current_activity):
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.CURRENT_ACTIVITY,
            reason="current_activity carries a PRIVATE_SENTINEL_DO_NOT_PUBLISH token",
            correction="activity not currently witnessed",
        )
    return PublicClaimGateDecision(
        decision=Decision.ALLOW,
        kind=ClaimKind.CURRENT_ACTIVITY,
        reason=f"current_activity={evidence.current_activity!r}",
    )


def _eval_programme_role(
    evidence: ClaimEvidence,
    *,
    programme_freshness_s: float,
    broadcast_freshness_s: float = DEFAULT_BROADCAST_FRESHNESS_S,
) -> PublicClaimGateDecision:
    del broadcast_freshness_s  # unused for programme_role; accepted for dispatch uniformity
    if not evidence.programme_role:
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.PROGRAMME_ROLE,
            reason="no programme_role in evidence",
            correction="programme role not currently witnessed",
        )
    if _PRIVATE_SENTINEL_PATTERN.search(evidence.programme_role):
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.PROGRAMME_ROLE,
            reason="programme_role carries a PRIVATE_SENTINEL_DO_NOT_PUBLISH token",
            correction="programme role not currently witnessed",
        )
    if (
        evidence.programme_role_age_s is None
        or evidence.programme_role_age_s > programme_freshness_s
    ):
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.PROGRAMME_ROLE,
            reason=(
                "programme_role stale "
                f"(age={evidence.programme_role_age_s}s, ceiling={programme_freshness_s}s)"
            ),
            correction="programme role not currently witnessed",
        )
    return PublicClaimGateDecision(
        decision=Decision.ALLOW,
        kind=ClaimKind.PROGRAMME_ROLE,
        reason=f"programme_role={evidence.programme_role!r} fresh",
    )


def _eval_archive_or_replay(evidence: ClaimEvidence, kind: ClaimKind) -> PublicClaimGateDecision:
    if not evidence.archive_url:
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=kind,
            reason="no archive_url in evidence",
            correction="archive not yet available",
        )
    if not evidence.rights_clear:
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=kind,
            reason="rights_clear=False (rights status not witnessed)",
            correction="archive not yet available (rights pending)",
        )
    return PublicClaimGateDecision(
        decision=Decision.ALLOW,
        kind=kind,
        reason=f"archive_url={evidence.archive_url!r} with cleared rights",
    )


def _eval_support(evidence: ClaimEvidence) -> PublicClaimGateDecision:
    if not evidence.support_surface_active:
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.SUPPORT,
            reason="support_surface_active=False (no live support rail)",
            correction="no public support surface currently active",
        )
    return PublicClaimGateDecision(
        decision=Decision.ALLOW,
        kind=ClaimKind.SUPPORT,
        reason="support surface active",
    )


def _eval_monetization(evidence: ClaimEvidence) -> PublicClaimGateDecision:
    if not evidence.monetization_active:
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.MONETIZATION,
            reason="monetization_active=False (no monetization readiness witness)",
            correction="not currently monetized",
        )
    return PublicClaimGateDecision(
        decision=Decision.ALLOW,
        kind=ClaimKind.MONETIZATION,
        reason="monetization readiness witnessed",
    )


def _eval_license_class(evidence: ClaimEvidence) -> PublicClaimGateDecision:
    if not evidence.declared_license:
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.LICENSE_CLASS,
            reason="no declared_license in evidence",
            correction="license class not currently declared",
        )
    if not evidence.license_consistent:
        return PublicClaimGateDecision(
            decision=Decision.CORRECT,
            kind=ClaimKind.LICENSE_CLASS,
            reason=(
                f"declared_license={evidence.declared_license!r} but "
                "license_consistent=False (canonical surfaces disagree)"
            ),
            correction=(
                "license posture in transition; see "
                "docs/governance/license-reconciliation-status.md"
            ),
        )
    return PublicClaimGateDecision(
        decision=Decision.ALLOW,
        kind=ClaimKind.LICENSE_CLASS,
        reason=f"declared_license={evidence.declared_license!r} consistent",
    )


def _eval_publication_state(evidence: ClaimEvidence) -> PublicClaimGateDecision:
    if not evidence.publication_state:
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.PUBLICATION_STATE,
            reason="no publication_state in evidence",
            correction="publication state not currently witnessed",
        )
    if not evidence.publication_evidence_url:
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.PUBLICATION_STATE,
            reason=(
                f"publication_state={evidence.publication_state!r} but "
                "no publication_evidence_url (deposit DOI / release URL)"
            ),
            correction=f"publication state {evidence.publication_state!r} pending evidence",
        )
    return PublicClaimGateDecision(
        decision=Decision.ALLOW,
        kind=ClaimKind.PUBLICATION_STATE,
        reason=(
            f"publication_state={evidence.publication_state!r} backed by "
            f"{evidence.publication_evidence_url!r}"
        ),
    )


def _eval_disabled_issues(evidence: ClaimEvidence) -> PublicClaimGateDecision:
    if not evidence.issues_disabled:
        return PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.DISABLED_ISSUES,
            reason=(
                "issues_disabled=False (cannot claim issues are disabled "
                "without GitHub-API witness)"
            ),
            correction="repository discussion surfaces in default state",
        )
    return PublicClaimGateDecision(
        decision=Decision.ALLOW,
        kind=ClaimKind.DISABLED_ISSUES,
        reason="issues confirmed disabled",
    )


_EVALUATORS = {
    ClaimKind.LIVE_NOW: _eval_live_now,
    ClaimKind.CURRENT_ACTIVITY: lambda e, **_: _eval_current_activity(e),
    ClaimKind.PROGRAMME_ROLE: _eval_programme_role,
    ClaimKind.ARCHIVE: lambda e, **_: _eval_archive_or_replay(e, ClaimKind.ARCHIVE),
    ClaimKind.REPLAY: lambda e, **_: _eval_archive_or_replay(e, ClaimKind.REPLAY),
    ClaimKind.SUPPORT: lambda e, **_: _eval_support(e),
    ClaimKind.MONETIZATION: lambda e, **_: _eval_monetization(e),
    ClaimKind.LICENSE_CLASS: lambda e, **_: _eval_license_class(e),
    ClaimKind.PUBLICATION_STATE: lambda e, **_: _eval_publication_state(e),
    ClaimKind.DISABLED_ISSUES: lambda e, **_: _eval_disabled_issues(e),
}


def evaluate_public_claim(
    kind: ClaimKind,
    evidence: ClaimEvidence,
    *,
    broadcast_freshness_s: float = DEFAULT_BROADCAST_FRESHNESS_S,
    programme_freshness_s: float = DEFAULT_PROGRAMME_FRESHNESS_S,
) -> PublicClaimGateDecision:
    """Evaluate one public claim against the supplied evidence.

    The freshness ceilings are arguments rather than module constants
    so the consumer (composer / github-claim-gate) can tune per-surface
    tolerance — e.g., a YouTube cross-surface post might tolerate a
    slightly older broadcast id than a live-update emission.
    """
    evaluator = _EVALUATORS[kind]
    return evaluator(
        evidence,
        broadcast_freshness_s=broadcast_freshness_s,
        programme_freshness_s=programme_freshness_s,
    )


__all__ = [
    "DEFAULT_BROADCAST_FRESHNESS_S",
    "DEFAULT_PROGRAMME_FRESHNESS_S",
    "ClaimEvidence",
    "ClaimKind",
    "Decision",
    "PublicClaimGateDecision",
    "evaluate_public_claim",
]
