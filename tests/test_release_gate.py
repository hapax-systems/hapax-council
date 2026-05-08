"""Tests for release gate module (SDLC Reform Slice 6).

ISAP: SLICE-006-RELEASE-OPS (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

from shared.release_gate import (
    PublicCurrentnessWitness,
    ReleaseCandidateRecord,
    RollbackPlan,
    check_public_currentness,
    run_orr_lite,
    validate_rollback_plan,
)

# ── Release candidate record ────────────────────────────────────────


def test_release_candidate_record_defaults() -> None:
    rc = ReleaseCandidateRecord(case_id="CASE-001", slice_id="SLICE-001")
    assert rc.risk_tier == "T0"
    assert rc.release_method == "merge_pr"
    assert rc.rollback_method == "revert_commit"
    assert not rc.orr_lite_passed


# ── ORR-lite gate ────────────────────────────────────────────────────


def test_orr_lite_t0_passes_with_tests_and_ci() -> None:
    result = run_orr_lite(
        case_id="CASE-001",
        risk_tier="T0",
        has_tests=True,
        ci_green=True,
        has_rollback_plan=True,
        has_evidence=True,
    )
    assert result.passed
    assert not result.blockers


def test_orr_lite_t0_fails_without_tests() -> None:
    result = run_orr_lite(
        case_id="CASE-001",
        risk_tier="T0",
        has_tests=False,
        ci_green=True,
        has_rollback_plan=True,
        has_evidence=True,
    )
    assert not result.passed
    assert any("Tests" in b for b in result.blockers)


def test_orr_lite_t2_requires_review_and_axiom_scan() -> None:
    result = run_orr_lite(
        case_id="CASE-001",
        risk_tier="T2",
        has_tests=True,
        ci_green=True,
        has_readback_plan=True,
        has_rollback_plan=True,
        has_evidence=True,
        has_review=False,
        has_axiom_scan=False,
    )
    assert not result.passed
    assert any("review" in b.lower() for b in result.blockers)
    assert any("axiom" in b.lower() for b in result.blockers)


def test_orr_lite_t2_passes_with_all_checks() -> None:
    result = run_orr_lite(
        case_id="CASE-001",
        risk_tier="T2",
        has_tests=True,
        ci_green=True,
        has_readback_plan=True,
        has_rollback_plan=True,
        has_evidence=True,
        has_review=True,
        has_axiom_scan=True,
    )
    assert result.passed


def test_orr_lite_t1_requires_readback_plan() -> None:
    result = run_orr_lite(
        case_id="CASE-001",
        risk_tier="T1",
        has_tests=True,
        ci_green=True,
        has_readback_plan=False,
        has_rollback_plan=True,
        has_evidence=True,
    )
    assert not result.passed
    assert any("Readback" in b for b in result.blockers)


# ── Rollback validator ───────────────────────────────────────────────


def test_rollback_plan_valid() -> None:
    plan = RollbackPlan(
        case_id="CASE-001",
        trigger="CI failure",
        method="revert_commit",
        pre_release_snapshot="abc123",
    )
    issues = validate_rollback_plan(plan)
    assert issues == []


def test_rollback_plan_missing_trigger() -> None:
    plan = RollbackPlan(
        case_id="CASE-001",
        trigger="",
        method="revert_commit",
        pre_release_snapshot="abc123",
    )
    issues = validate_rollback_plan(plan)
    assert any("trigger" in i.lower() for i in issues)


def test_rollback_plan_missing_snapshot() -> None:
    plan = RollbackPlan(
        case_id="CASE-001",
        trigger="CI failure",
        method="revert_commit",
        pre_release_snapshot="",
    )
    issues = validate_rollback_plan(plan)
    assert any("snapshot" in i.lower() for i in issues)


def test_rollback_plan_non_git_surfaces_need_notes() -> None:
    plan = RollbackPlan(
        case_id="CASE-001",
        trigger="CI failure",
        method="revert_commit",
        pre_release_snapshot="abc123",
        non_git_surfaces=["PyPI", "vault"],
        validation_notes="",
    )
    issues = validate_rollback_plan(plan)
    assert any("non-git" in i.lower() or "Non-git" in i for i in issues)


def test_rollback_plan_non_git_with_notes_ok() -> None:
    plan = RollbackPlan(
        case_id="CASE-001",
        trigger="CI failure",
        method="revert_commit",
        pre_release_snapshot="abc123",
        non_git_surfaces=["PyPI"],
        validation_notes="Yank package, republish with bumped version",
    )
    assert validate_rollback_plan(plan) == []


# ── Public-currentness gate ──────────────────────────────────────────


def test_public_currentness_no_surfaces_passes() -> None:
    w = PublicCurrentnessWitness(case_id="CASE-001", no_public_surfaces=True)
    assert check_public_currentness(w) == []


def test_public_currentness_refused_tier_fails() -> None:
    w = PublicCurrentnessWitness(
        case_id="CASE-001",
        public_surfaces_touched=["pypi"],
        publication_tier="REFUSED",
    )
    issues = check_public_currentness(w)
    assert any("REFUSED" in i for i in issues)


def test_public_currentness_missing_claim_safety() -> None:
    w = PublicCurrentnessWitness(
        case_id="CASE-001",
        public_surfaces_touched=["weblog"],
        publication_tier="FULL_AUTO",
        claim_safe=False,
    )
    issues = check_public_currentness(w)
    assert any("claim" in i.lower() for i in issues)


def test_public_currentness_all_ok() -> None:
    w = PublicCurrentnessWitness(
        case_id="CASE-001",
        public_surfaces_touched=["weblog"],
        publication_tier="FULL_AUTO",
        claim_safe=True,
    )
    assert check_public_currentness(w) == []
