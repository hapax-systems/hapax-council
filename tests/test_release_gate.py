"""Tests for release gate module (SDLC Reform Slice 6).

ISAP: SLICE-006-RELEASE-OPS (CASE-SDLC-REFORM-001)
"""

from __future__ import annotations

from shared.release_gate import (
    AVSDLC_EVIDENCE_FRESHNESS_SECONDS,
    PublicCurrentnessWitness,
    ReleaseCandidateRecord,
    RollbackPlan,
    check_public_currentness,
    evaluate_avsdlc_release_gate,
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


# -- AVSDLC release evidence gate --------------------------------------


def test_avsdlc_gate_passes_when_no_impacted_axes_or_surface() -> None:
    result = evaluate_avsdlc_release_gate({"mutation_surface": "source"})

    assert result.passed
    assert not result.required
    assert not result.blockers


def test_avsdlc_gate_blocks_obvious_visual_surface_without_axis_classification() -> None:
    result = evaluate_avsdlc_release_gate(
        {"mutation_scope_refs": ["agents/studio_compositor/layout.py"]}
    )

    assert not result.passed
    assert result.required
    assert "avsdlc_axes_missing:visual" in result.blockers


def test_avsdlc_gate_blocks_runtime_media_without_axis_classification() -> None:
    result = evaluate_avsdlc_release_gate({"runtime_media_impact": True})

    assert not result.passed
    assert "avsdlc_axes_missing:audiovisual" in result.blockers


def test_avsdlc_gate_does_not_treat_required_as_visual_ui_marker() -> None:
    result = evaluate_avsdlc_release_gate(
        {"mutation_scope_refs": ["tests/test_ci_required_coverage_claims.py"]}
    )

    assert result.passed
    assert result.inferred_axes == []


def test_avsdlc_gate_allows_explicit_no_axis_classification() -> None:
    result = evaluate_avsdlc_release_gate(
        {
            "avsdlc_axes": "none",
            "tags": ["audio"],
            "mutation_scope_refs": ["tests/shared/test_audio_routing_policy.py"],
        }
    )

    assert result.passed
    assert result.inferred_axes == ["audio"]


def test_avsdlc_gate_blocks_visual_axis_missing_dossier_witness_and_freshness() -> None:
    result = evaluate_avsdlc_release_gate({"avsdlc_axes": ["visual"]})

    assert not result.passed
    assert "missing:avsdlc_dossier" in result.blockers
    assert "missing:visual_witness" in result.blockers
    assert "missing:avsdlc_evidence_collected_at" in result.blockers


def test_avsdlc_gate_passes_with_fresh_visual_evidence() -> None:
    now = 1_800_000_000.0

    result = evaluate_avsdlc_release_gate(
        {
            "avsdlc_axes": ["visual"],
            "avsdlc_dossier": "docs/evidence/visual.md",
            "visual_witness": "artifacts/frame.png",
            "avsdlc_evidence_collected_at": now - 60,
        },
        now=now,
    )

    assert result.passed
    assert not result.blockers


def test_avsdlc_gate_blocks_stale_audio_evidence() -> None:
    now = 1_800_000_000.0

    result = evaluate_avsdlc_release_gate(
        {
            "avsdlc_axes": ["audio"],
            "avsdlc_dossier": "docs/evidence/audio.md",
            "audio_witness": "artifacts/lufs.json",
            "avsdlc_evidence_collected_at": now - AVSDLC_EVIDENCE_FRESHNESS_SECONDS - 1,
        },
        now=now,
    )

    assert not result.passed
    assert "stale:avsdlc_evidence_collected_at" in result.blockers


def test_avsdlc_gate_requires_audiovisual_and_runtime_media_witnesses() -> None:
    now = 1_800_000_000.0

    result = evaluate_avsdlc_release_gate(
        {
            "avsdlc_axes": ["audiovisual"],
            "avsdlc_dossier": "docs/evidence/av.md",
            "avsdlc_evidence_collected_at": now,
            "runtime_media_impact": True,
        },
        now=now,
    )

    assert not result.passed
    assert "missing:audiovisual_witness" in result.blockers
    assert "missing:runtime_media_witness" in result.blockers
