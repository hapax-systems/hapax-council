"""Release/ops gates for Authority-Case SDLC.

Release candidate record, ORR-lite gate, rollback validator,
public-currentness witness, and publication surface gates.

ISAP: SLICE-006-RELEASE-OPS (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

RiskTier = Literal["T0", "T1", "T2", "T3"]
ReleaseMethod = Literal["merge_pr", "service_restart", "hot_reload", "rebuild", "uv_publish"]
RollbackMethod = Literal["revert_commit", "service_restart", "config_restore", "yank_package"]
PublicSurfaceTier = Literal["FULL_AUTO", "CONDITIONAL_ENGAGE", "REFUSED", "INTERNAL"]


class ReleaseCandidateRecord(BaseModel):
    """Structured record for a release candidate."""

    case_id: str
    slice_id: str = ""
    pr_number: int | None = None
    branch: str = ""
    commit_sha: str = ""
    risk_tier: RiskTier = "T0"
    release_method: ReleaseMethod = "merge_pr"
    deploy_scope: list[str] = Field(
        default_factory=list,
        description="Paths/services affected by this release",
    )
    rollback_method: RollbackMethod = "revert_commit"
    rollback_trigger: str = (
        "CI failure, service crash, or >10% false positives on legitimate operations"
    )
    readback_plan: str = Field(
        default="",
        description="What runtime signal confirms successful deployment",
    )
    orr_lite_passed: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    created_utc: float = Field(default_factory=time.time)
    notes: str = ""


class OrrLiteResult(BaseModel):
    """Result of an ORR-lite (Operational Readiness Review lite) check."""

    case_id: str
    checks: dict[str, bool] = Field(default_factory=dict)
    passed: bool = False
    blockers: list[str] = Field(default_factory=list)
    timestamp_utc: float = Field(default_factory=time.time)
    reviewer: str = ""


class RollbackPlan(BaseModel):
    """Validated rollback plan for a release."""

    case_id: str
    trigger: str
    method: RollbackMethod
    affected_services: list[str] = Field(default_factory=list)
    emergency_env_var: str = ""
    pre_release_snapshot: str = Field(
        default="",
        description="Commit SHA or state snapshot to revert to",
    )
    non_git_surfaces: list[str] = Field(
        default_factory=list,
        description="Vault, PyPI, ledger entries that need special rollback",
    )
    validated: bool = False
    validation_notes: str = ""


class PublicCurrentnessWitness(BaseModel):
    """Witness record for public-currentness gate."""

    case_id: str
    public_surfaces_touched: list[str] = Field(default_factory=list)
    no_public_surfaces: bool = False
    publication_tier: PublicSurfaceTier = "INTERNAL"
    claim_safe: bool = False
    notes: str = ""


# ── ORR-lite check logic ──────────────────────────────────────────────


def run_orr_lite(
    case_id: str,
    pr_number: int | None = None,
    risk_tier: RiskTier = "T0",
    has_tests: bool = False,
    ci_green: bool = False,
    has_readback_plan: bool = False,
    has_rollback_plan: bool = False,
    has_evidence: bool = False,
    has_review: bool = False,
    has_axiom_scan: bool = False,
    reviewer: str = "",
) -> OrrLiteResult:
    checks: dict[str, bool] = {}
    blockers: list[str] = []

    checks["tests_pass"] = has_tests
    if not has_tests:
        blockers.append("Tests not passing or not run")

    checks["ci_green"] = ci_green
    if not ci_green:
        blockers.append("CI not green")

    checks["readback_plan_exists"] = has_readback_plan
    if not has_readback_plan and risk_tier in ("T1", "T2", "T3"):
        blockers.append(f"Readback plan required for {risk_tier}")

    checks["rollback_plan_exists"] = has_rollback_plan
    if not has_rollback_plan:
        blockers.append("No rollback plan")

    checks["evidence_sufficient"] = has_evidence
    if not has_evidence:
        blockers.append("Evidence ledger incomplete for tier")

    if risk_tier in ("T2", "T3"):
        checks["review_complete"] = has_review
        if not has_review:
            blockers.append(f"Independent review required for {risk_tier}")
        checks["axiom_scan_passed"] = has_axiom_scan
        if not has_axiom_scan:
            blockers.append(f"Axiom scan required for {risk_tier}")

    return OrrLiteResult(
        case_id=case_id,
        checks=checks,
        passed=len(blockers) == 0,
        blockers=blockers,
        reviewer=reviewer,
    )


def validate_rollback_plan(plan: RollbackPlan) -> list[str]:
    """Return list of validation issues. Empty = valid."""
    issues: list[str] = []
    if not plan.trigger:
        issues.append("Rollback trigger not defined")
    if not plan.pre_release_snapshot:
        issues.append("No pre-release snapshot SHA defined")
    if plan.non_git_surfaces and not plan.validation_notes:
        issues.append(f"Non-git surfaces ({', '.join(plan.non_git_surfaces)}) need rollback notes")
    return issues


def check_public_currentness(witness: PublicCurrentnessWitness) -> list[str]:
    """Return list of gate violations. Empty = gate passes."""
    issues: list[str] = []
    if witness.no_public_surfaces:
        return []
    if not witness.public_surfaces_touched:
        issues.append("Public surfaces not enumerated")
    if witness.publication_tier == "REFUSED":
        issues.append("Publication tier is REFUSED — cannot release to public")
    if not witness.claim_safe:
        issues.append("Public claims not verified as safe")
    return issues
