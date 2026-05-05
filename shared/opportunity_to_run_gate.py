"""Opportunity-to-run WCS gate.

Per cc-task ``opportunity-to-run-wcs-gate`` (WSJF 8.8). The Bayesian
``ContentOpportunity`` selector surfaces candidate programmes ranked
by trend / audience / revenue posterior. Without a gate, those
candidates would launch as live programme runs regardless of whether
the world-capability surface (WCS) actually supports them today —
operator nomination by another name. This module is the **fail-CLOSED
gate** that converts each opportunity decision into a runnable / dry-
run / refused / archive-only / held / blocked run envelope.

Phase 0 (this PR) ships the gate as a reusable predicate library;
Phase 1 wires it into the content-programme runner +
programme-wcs-runner-readiness-tests.

Operating law (cc-task §"Best-Version Synthesis"):

* Bayesian opportunity selects candidates; **WCS gates what can
  truthfully be done** with them.
* Trend / audience / revenue reward never overrides evidence,
  rights, privacy, or no-expert-system constraints.
* Public-live requires WCS public readiness AND a
  ``ResearchVehiclePublicEvent`` path; otherwise dry-run / refusal /
  held / archive-only.
* Opportunity SELECTION and run AUTHORIZATION are **separate
  decisions** — this gate does the latter only.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

#: Minimum Bayesian posterior an opportunity needs to be eligible for
#: any non-DIAGNOSTIC mode. Below this the gate REFUSES regardless of
#: WCS evidence (low-confidence opportunities should not ship).
MIN_OPPORTUNITY_POSTERIOR: float = 0.30


class RunMode(enum.StrEnum):
    """The 6-mode run envelope the gate emits."""

    RUNNABLE = "runnable"
    """Public-live ready: all evidence axes satisfied, run may go
    live with full claim authority."""

    DRY_RUN = "dry_run"
    """Run inside the director loop with no public-event emission;
    used to exercise the format on this opportunity without
    audience-facing exposure."""

    PRIVATE = "private"
    """Run for operator-private context only (e.g., dossier feed,
    operator-only dashboard); never audience-facing."""

    ARCHIVE_ONLY = "archive_only"
    """May write to the public VOD archive but cannot ship as
    public-live (e.g., live broadcast egress is offline but the
    archive path is healthy)."""

    HELD = "held"
    """All evidence checks pass but a higher-priority run is
    occupying the office; the gate parks the opportunity for retry."""

    REFUSED = "refused"
    """Opportunity is not actionable in any mode (rights, privacy,
    or no-expert-system constraint hit)."""

    BLOCKED = "blocked"
    """A required surface is structurally blocked; the opportunity
    can return when the blocker clears."""


class BlockerKind(enum.StrEnum):
    """Concrete reason the gate blocked / refused a run.

    Surface-side consumers consult this to construct refusal /
    correction articulations rather than silently dropping the
    opportunity.
    """

    NONE = "none"
    LOW_POSTERIOR = "low_posterior"
    MISSING_CLAIM_SHAPE = "missing_claim_shape"
    MISSING_EVIDENCE = "missing_evidence"
    MISSING_WITNESS = "missing_witness"
    MISSING_RIGHTS = "missing_rights"
    MISSING_PRIVACY = "missing_privacy"
    MISSING_PUBLIC_EVENT_PATH = "missing_public_event_path"
    MISSING_MONETIZATION = "missing_monetization"
    NO_EXPERT_SYSTEM_OVERRIDE = "no_expert_system_override"
    HARDWARE_BLOCKED = "hardware_blocked"
    HIGHER_PRIORITY_OCCUPYING = "higher_priority_occupying"


@dataclass(frozen=True)
class ContentOpportunity:
    """Bayesian-surfaced candidate the gate evaluates.

    The opportunity carries the posterior + format ID + a public-claim
    shape declaration. The gate consults the format WCS matrix + WCS
    snapshot to decide which mode the run can take.
    """

    opportunity_id: str
    format_id: str
    """The content format ID (react / watchalong / tier_list /
    audit / explainer / refusal_breakdown / etc) — looked up in the
    format WCS matrix to determine required evidence axes."""

    posterior: float
    """Bayesian posterior in [0.0, 1.0] from the opportunity
    selector. Below MIN_OPPORTUNITY_POSTERIOR the gate refuses
    regardless of WCS evidence."""

    public_claim_intended: bool = False
    """True when the opportunity wants to land as public-live.
    False routes through PRIVATE / DRY_RUN regardless of WCS."""

    monetization_intended: bool = False
    """True when the opportunity intends to surface conversion cues.
    Requires monetization_ready=True on the WCS snapshot."""


@dataclass(frozen=True)
class FormatWcsRequirement:
    """A row from the format WCS requirement matrix.

    Phase 0 hardcodes a minimal in-memory shape; Phase 1 follow-on
    wires this to the live ``shared.format_wcs_requirement_matrix``
    loader (already in tree as the upstream cc-task).
    """

    format_id: str
    requires_egress: bool = False
    requires_audio_safe: bool = False
    requires_rights_clear: bool = False
    requires_privacy_clear: bool = False
    requires_public_event_path: bool = False
    requires_archive_path: bool = False
    requires_claim_shape: bool = True
    """Every format must declare a claim shape (the cc-task contract)."""


@dataclass(frozen=True)
class WcsSnapshot:
    """Runtime WCS evidence the gate consults.

    Defaults are the safest values (no surface available, no
    witnesses, blocked) so missing-evidence configurations
    fail-CLOSED.
    """

    egress_active: bool = False
    audio_safe: bool = False
    rights_clear: bool = False
    privacy_clear: bool = False
    public_event_path_ready: bool = False
    archive_path_ready: bool = False
    monetization_ready: bool = False
    claim_shape_declared: bool = False
    hardware_blocked: bool = False
    higher_priority_run_occupying: bool = False


@dataclass(frozen=True)
class GateResult:
    """The gate's verdict on one opportunity."""

    mode: RunMode
    blockers: tuple[BlockerKind, ...] = field(default_factory=tuple)
    """Names of every blocker that fired. Surface consumers iterate
    this to produce a refusal articulation listing each constraint
    rather than collapsing all causes into one reason."""

    reason: str = ""
    """Short human-readable summary; complements ``blockers`` for
    log lines / dashboards."""

    camera_salience: dict[str, Any] | None = None
    """WCS-shaped camera-salience projection from the broker (see
    ``shared.bayesian_camera_salience_world_surface``). Populated by
    ``evaluate_opportunity`` from a ``broker().query(consumer=
    'content_opportunity', ...)`` call so downstream surfaces can
    inspect which camera apertures were salient at gate time without
    re-querying. ``None`` when the broker is unavailable or the query
    failed-closed; the gate verdict itself is unaffected."""


def _required_evidence_blockers(
    requirement: FormatWcsRequirement, snapshot: WcsSnapshot
) -> tuple[BlockerKind, ...]:
    """Compute the blockers triggered by missing WCS evidence."""
    blockers: list[BlockerKind] = []
    if requirement.requires_claim_shape and not snapshot.claim_shape_declared:
        blockers.append(BlockerKind.MISSING_CLAIM_SHAPE)
    if requirement.requires_egress and not snapshot.egress_active:
        blockers.append(BlockerKind.MISSING_EVIDENCE)
    if requirement.requires_audio_safe and not snapshot.audio_safe:
        blockers.append(BlockerKind.MISSING_EVIDENCE)
    if requirement.requires_rights_clear and not snapshot.rights_clear:
        blockers.append(BlockerKind.MISSING_RIGHTS)
    if requirement.requires_privacy_clear and not snapshot.privacy_clear:
        blockers.append(BlockerKind.MISSING_PRIVACY)
    if requirement.requires_public_event_path and not snapshot.public_event_path_ready:
        blockers.append(BlockerKind.MISSING_PUBLIC_EVENT_PATH)
    return tuple(blockers)


def _query_camera_salience_for_opportunity(
    opportunity: ContentOpportunity,
) -> dict[str, Any] | None:
    """Query the camera-salience broker for this opportunity's gate decision.

    Mirrors the inline pattern used by ``director_loop`` and
    ``affordance_pipeline``. Fails closed (returns ``None``) on any
    broker error so the gate's verdict is never blocked by a salience
    lookup failure.
    """
    try:
        from shared.camera_salience_singleton import broker as _camera_broker

        bundle = _camera_broker().query(
            consumer="content_opportunity",
            decision_context=f"opportunity_gate:{opportunity.opportunity_id}",
            candidate_action=f"format:{opportunity.format_id}",
        )
        if bundle is None:
            return None
        return bundle.to_wcs_projection_payload()
    except Exception:
        log.debug("camera salience content_opportunity query failed", exc_info=True)
        return None


def evaluate_opportunity(
    opportunity: ContentOpportunity,
    requirement: FormatWcsRequirement,
    snapshot: WcsSnapshot,
    *,
    min_posterior: float = MIN_OPPORTUNITY_POSTERIOR,
) -> GateResult:
    """Decide which run mode the opportunity may take.

    Decision order (each pre-empts the modes below):

      1. Posterior below ``min_posterior`` → REFUSED.
      2. Hardware blocked → BLOCKED.
      3. Higher-priority run occupying the office → HELD.
      4. Required claim shape missing → REFUSED.
      5. Public-claim intended + monetization intended + monetization
         not ready → REFUSED (no-expert-system: monetization can't be
         laundered through a high-posterior opportunity).
      6. Public-claim intended + missing evidence → ARCHIVE_ONLY when
         archive path is ready, BLOCKED otherwise.
      7. Public-claim intended + all evidence satisfied → RUNNABLE.
      8. NOT public-claim intended → DRY_RUN (default for non-public
         opportunities; PRIVATE chosen explicitly by the caller via
         a separate path, not promoted by the gate).

    Camera-salience attachment: every returned ``GateResult`` carries
    the broker's WCS projection on ``camera_salience`` (``None`` when
    the broker is unavailable). Surface consumers can inspect which
    camera apertures were salient at gate time without re-querying.
    """
    base_verdict = _decide_opportunity(opportunity, requirement, snapshot, min_posterior)
    salience = _query_camera_salience_for_opportunity(opportunity)
    if salience is None:
        return base_verdict
    from dataclasses import replace

    return replace(base_verdict, camera_salience=salience)


def _decide_opportunity(
    opportunity: ContentOpportunity,
    requirement: FormatWcsRequirement,
    snapshot: WcsSnapshot,
    min_posterior: float,
) -> GateResult:
    """Pure decision function — see ``evaluate_opportunity`` for contract."""
    # Step 1: posterior floor.
    if opportunity.posterior < min_posterior:
        return GateResult(
            mode=RunMode.REFUSED,
            blockers=(BlockerKind.LOW_POSTERIOR,),
            reason=(f"posterior {opportunity.posterior:.2f} below floor {min_posterior:.2f}"),
        )

    # Step 2: hardware-blocked surface.
    if snapshot.hardware_blocked:
        return GateResult(
            mode=RunMode.BLOCKED,
            blockers=(BlockerKind.HARDWARE_BLOCKED,),
            reason="surface hardware blocked; opportunity can return when blocker clears",
        )

    # Step 3: higher-priority run occupying the office.
    if snapshot.higher_priority_run_occupying:
        return GateResult(
            mode=RunMode.HELD,
            blockers=(BlockerKind.HIGHER_PRIORITY_OCCUPYING,),
            reason="higher-priority run occupying the office; opportunity parked",
        )

    # Step 4: missing claim shape always refuses.
    if requirement.requires_claim_shape and not snapshot.claim_shape_declared:
        return GateResult(
            mode=RunMode.REFUSED,
            blockers=(BlockerKind.MISSING_CLAIM_SHAPE,),
            reason="format requires a declared claim shape; none in WCS snapshot",
        )

    # Step 5: monetization-cue overreach (no-expert-system override).
    if (
        opportunity.monetization_intended
        and opportunity.public_claim_intended
        and not snapshot.monetization_ready
    ):
        return GateResult(
            mode=RunMode.REFUSED,
            blockers=(
                BlockerKind.MISSING_MONETIZATION,
                BlockerKind.NO_EXPERT_SYSTEM_OVERRIDE,
            ),
            reason=(
                "monetization intended for public-live but monetization_ready=False; "
                "trend/audience reward cannot override readiness"
            ),
        )

    # Step 6: public-claim path with missing evidence.
    if opportunity.public_claim_intended:
        evidence_blockers = _required_evidence_blockers(requirement, snapshot)
        if evidence_blockers:
            if requirement.requires_archive_path and snapshot.archive_path_ready:
                return GateResult(
                    mode=RunMode.ARCHIVE_ONLY,
                    blockers=evidence_blockers,
                    reason=(
                        "public-live evidence missing but archive path ready; "
                        "downgraded to archive_only"
                    ),
                )
            return GateResult(
                mode=RunMode.BLOCKED,
                blockers=evidence_blockers,
                reason=(
                    f"public-claim run requires evidence "
                    f"({', '.join(b.value for b in evidence_blockers)}); blocked"
                ),
            )
        # All evidence satisfied.
        return GateResult(
            mode=RunMode.RUNNABLE,
            reason="public-claim run; all required evidence axes satisfied",
        )

    # Step 7: not public-claim → dry_run by default.
    return GateResult(
        mode=RunMode.DRY_RUN,
        reason="not public-claim intended; default dry_run",
    )


__all__ = [
    "MIN_OPPORTUNITY_POSTERIOR",
    "BlockerKind",
    "ContentOpportunity",
    "FormatWcsRequirement",
    "GateResult",
    "RunMode",
    "WcsSnapshot",
    "evaluate_opportunity",
]
