"""Tests for system release auto-arm — dispatch resilience to lane-death.

Reform improve (CASE-CAPACITY-ROUTING-001): a lane that dies after creating its
PR but before flipping ``release_authorized: true`` strands a CLEAN, green,
mergeable PR at ``pr_open`` forever. The autoqueue (running as the system,
unclaimed — FM-20) must auto-arm such a task — but only when its release was
already authorized-in-principle by its ISAP and every applicable sensitivity
class has machine-verified mitigation evidence.

Release auto-arm blocker reason codes are part of the reconciler/ledger
contract: ``risk_flag:{name}`` means no PR check evidence was supplied,
``needs_mitigation:{name}:{check}`` is emitted once per missing mitigation
check, and ``unmitigable_risk_flag:{name}`` means no automated mitigation gate
exists for that sensitive class.
"""

from __future__ import annotations

from shared.sdlc_lifecycle import (
    RELEASE_MITIGATION_CHECKS,
    apply_release_auto_arm,
    assess_release_auto_arm,
    release_auto_arm_waivers,
)


def _eligible_frontmatter(**overrides: object) -> dict[str, object]:
    """A pr_open, implementation-authorized, non-sensitive source task."""
    base: dict[str, object] = {
        "type": "cc-task",
        "task_id": "reform-improve-dispatch-resilience-20260601",
        "title": "Reform improve — make dispatch resilient to lane-death",
        "status": "pr_open",
        "stage": "S6_IMPLEMENTATION",
        "authority_case": "CASE-CAPACITY-ROUTING-001",
        "parent_spec": "~/Documents/Personal/30-areas/hapax/master-design.md",
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "risk_tier": "T2",
        "implementation_authorized": True,
        "release_authorized": False,
        "public_current": False,
        "tags": ["cc-task", "sdlc", "reform", "dispatch"],
    }
    base.update(overrides)
    return base


# ── subject / needs_arming gating ─────────────────────────────────────


def test_eligible_pr_open_unauthorized_nonsensitive_task_is_auto_armable() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter())
    assert assessment.subject is True
    assert assessment.armed is False
    assert assessment.needs_arming is True
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_task_without_release_authorized_field_is_not_subject() -> None:
    fm = _eligible_frontmatter()
    del fm["release_authorized"]
    assessment = assess_release_auto_arm(fm)
    assert assessment.subject is False
    assert assessment.needs_arming is False
    assert assessment.eligible is False


def test_already_release_authorized_task_does_not_need_arming() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(release_authorized=True))
    assert assessment.subject is True
    assert assessment.armed is True
    assert assessment.needs_arming is False
    assert assessment.eligible is False


# ── governance / sensitivity veto (AC2: sensitive stays manual) ────────


def test_ineligible_when_explicit_governance_risk_flag_set() -> None:
    fm = _eligible_frontmatter(risk_flags={"governance_sensitive": True})
    assessment = assess_release_auto_arm(fm)
    assert assessment.needs_arming is True
    assert assessment.eligible is False
    assert "risk_flag:governance_sensitive" in assessment.blockers


def test_ineligible_when_governance_keyword_in_title_without_explicit_flags() -> None:
    fm = _eligible_frontmatter(
        title="Tighten governance policy enforcement on authority cases",
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert any("governance" in blocker for blocker in assessment.blockers)


def test_ineligible_when_audio_or_live_egress_sensitive() -> None:
    fm = _eligible_frontmatter(
        title="Adjust broadcast audio loudnorm egress chain",
        tags=["cc-task", "audio", "egress"],
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert any("audio_or_live_egress" in blocker for blocker in assessment.blockers)


def test_ineligible_when_public_claim_sensitive() -> None:
    fm = _eligible_frontmatter(
        title="Publish public claim to external surface",
        tags=["cc-task", "publication", "public"],
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert any("public_claim" in blocker for blocker in assessment.blockers)


def test_pass_backed_runtime_secret_subscription_task_is_auto_armable() -> None:
    fm = _eligible_frontmatter(
        title="Activate GLMCP GLM-5.2 lane with pass-backed secret",
        pass_backed_secret_only=True,
        no_secret_value_storage=True,
        secret_entry="glmcp/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.needs_arming is True
    assert assessment.eligible is True
    assert assessment.blockers == ()
    assert release_auto_arm_waivers(fm) == ("pass_backed_runtime_secret_waiver",)


def test_pass_backed_runtime_secret_requires_no_secret_value_storage() -> None:
    fm = _eligible_frontmatter(
        title="Activate GLMCP GLM-5.2 lane with pass-backed secret",
        pass_backed_secret_only=True,
        secret_entry="glmcp/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert "risk_flag:privacy_or_secret_sensitive" in assessment.blockers


def test_pass_backed_runtime_secret_rejects_traversing_pass_entry() -> None:
    fm = _eligible_frontmatter(
        title="Activate GLMCP GLM-5.2 lane with pass-backed secret",
        pass_backed_secret_only=True,
        no_secret_value_storage=True,
        secret_entry="glmcp/../other/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert "risk_flag:privacy_or_secret_sensitive" in assessment.blockers


def test_pass_backed_runtime_secret_rejects_non_glmcp_pass_entry() -> None:
    fm = _eligible_frontmatter(
        title="Activate GLMCP GLM-5.2 lane with pass-backed secret",
        pass_backed_secret_only=True,
        no_secret_value_storage=True,
        secret_entry="other/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert "risk_flag:privacy_or_secret_sensitive" in assessment.blockers


def test_pass_backed_runtime_secret_does_not_waive_explicit_privacy_flag() -> None:
    fm = _eligible_frontmatter(
        title="Activate GLMCP GLM-5.2 lane with pass-backed secret",
        pass_backed_secret_only=True,
        no_secret_value_storage=True,
        secret_entry="glmcp/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
        risk_flags={"privacy_or_secret_sensitive": True},
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert "risk_flag:privacy_or_secret_sensitive" in assessment.blockers


def test_pass_backed_runtime_secret_does_not_waive_governance() -> None:
    fm = _eligible_frontmatter(
        title="Governance GLMCP pass-backed secret lane",
        pass_backed_secret_only=True,
        no_secret_value_storage=True,
        secret_entry="glmcp/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert "risk_flag:governance_sensitive" in assessment.blockers


def test_pass_backed_runtime_secret_does_not_waive_provider_billing() -> None:
    fm = _eligible_frontmatter(
        title="Provider billing GLMCP pass-backed secret lane",
        pass_backed_secret_only=True,
        no_secret_value_storage=True,
        secret_entry="glmcp/api-key",
        subscription_quota_only=True,
        supported_tools_only=True,
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert "risk_flag:provider_billing_sensitive" in assessment.blockers
    assert "risk_flag:privacy_or_secret_sensitive" not in assessment.blockers


def test_ineligible_when_mutation_surface_is_public() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(mutation_surface="public"))
    assert assessment.eligible is False
    assert any("mutation_surface" in blocker for blocker in assessment.blockers)


def test_ineligible_when_mutation_surface_is_provider_spend() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(mutation_surface="provider_spend"))
    assert assessment.eligible is False
    assert any("mutation_surface" in blocker for blocker in assessment.blockers)


def test_ineligible_when_governance_protected_path_in_scope() -> None:
    fm = _eligible_frontmatter(
        mutation_scope_refs=["axioms/registry.yaml", "shared/foo.py"],
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert any("sensitive_path" in blocker for blocker in assessment.blockers)


def test_sensitive_path_does_not_false_match_substring_in_segment() -> None:
    # 'codeowners' is a marker, but 'scripts/sync-codeowners.py' only CONTAINS
    # it as a substring of a filename — it does not modify CODEOWNERS. The raw
    # substring match false-vetoed such tasks from system auto-arm.
    fm = _eligible_frontmatter(mutation_scope_refs=["scripts/sync-codeowners.py"])
    assessment = assess_release_auto_arm(fm)
    assert not any("sensitive_path" in blocker for blocker in assessment.blockers)
    assert assessment.eligible is True


def test_sensitive_path_does_not_false_match_dir_marker_substring() -> None:
    # Marker 'axioms/' must match the governed axioms/ directory, not a
    # segment that merely ends in '...axioms'.
    fm = _eligible_frontmatter(mutation_scope_refs=["research/meta-axioms/notes.md"])
    assessment = assess_release_auto_arm(fm)
    assert not any("sensitive_path" in blocker for blocker in assessment.blockers)
    assert assessment.eligible is True


def test_sensitive_path_matches_codeowners_as_path_segment() -> None:
    fm = _eligible_frontmatter(mutation_scope_refs=[".github/CODEOWNERS"])
    assessment = assess_release_auto_arm(fm)
    assert any("sensitive_path" in blocker for blocker in assessment.blockers)


def test_sensitive_path_matches_claude_md_file_segment() -> None:
    fm = _eligible_frontmatter(mutation_scope_refs=["hapax-council/CLAUDE.md"])
    assessment = assess_release_auto_arm(fm)
    assert any("sensitive_path" in blocker for blocker in assessment.blockers)


def test_ineligible_when_public_current_already_true() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(public_current=True))
    assert assessment.eligible is False
    assert any("public_current" in blocker for blocker in assessment.blockers)


def test_ineligible_when_risk_tier_is_t3() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(risk_tier="T3"))
    assert assessment.eligible is False
    assert any("risk_tier" in blocker for blocker in assessment.blockers)


# ── ISAP authorization-in-principle precondition ──────────────────────


def test_ineligible_when_not_implementation_authorized() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(implementation_authorized=False))
    assert assessment.eligible is False
    assert any("implementation_authorized" in blocker for blocker in assessment.blockers)


def test_ineligible_when_implementation_authorized_field_absent() -> None:
    fm = _eligible_frontmatter()
    del fm["implementation_authorized"]
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert any("implementation_authorized" in blocker for blocker in assessment.blockers)


# ── AVSDLC axes evidence gate (axes must permit) ──────────────────────


def test_ineligible_when_avsdlc_axis_evidence_missing() -> None:
    fm = _eligible_frontmatter(avsdlc_axes=["visual"])
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is False
    assert any(blocker.startswith("avsdlc:") for blocker in assessment.blockers)


def test_eligible_when_avsdlc_axes_declared_none() -> None:
    fm = _eligible_frontmatter(avsdlc_axes=[])
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is True


# ── note-text arming transform ────────────────────────────────────────

_NOTE = """---
type: cc-task
task_id: reform-improve-dispatch-resilience-20260601
status: pr_open
stage: S6_IMPLEMENTATION
implementation_authorized: true
release_authorized: false
updated_at: 2026-06-01T00:00:00Z
authority_case: CASE-CAPACITY-ROUTING-001
---

# task

## Session log
- prior line
"""


def test_apply_release_auto_arm_sets_release_authorized_true() -> None:
    out = apply_release_auto_arm(_NOTE, now_iso="2026-06-01T03:00:00Z")
    assert "release_authorized: true" in out
    assert "release_authorized: false" not in out


def test_apply_release_auto_arm_advances_stage_to_s7() -> None:
    out = apply_release_auto_arm(_NOTE, now_iso="2026-06-01T03:00:00Z")
    assert "stage: S7_RELEASE" in out
    assert "stage: S6_IMPLEMENTATION" not in out


def test_apply_release_auto_arm_keeps_existing_s7_stage() -> None:
    note = _NOTE.replace("stage: S6_IMPLEMENTATION", "stage: S7_RELEASE")
    out = apply_release_auto_arm(note, now_iso="2026-06-01T03:00:00Z")
    assert out.count("stage: S7_RELEASE") == 1


def test_apply_release_auto_arm_updates_timestamp_and_logs() -> None:
    out = apply_release_auto_arm(_NOTE, now_iso="2026-06-01T03:00:00Z")
    assert "updated_at: 2026-06-01T03:00:00Z" in out
    assert "- prior line" in out  # body preserved
    assert "release auto-arm" in out.lower()  # audit line appended to body


# ── evidence-gated auto-arm (no manual arming; operator directive 2026-06-22) ──


def test_sensitivity_is_hard_veto_without_verified_checks_backward_compat() -> None:
    # Pure-frontmatter assessment (no verified_checks) preserves the historical
    # hard veto so legacy callers are unaffected.
    fm = _eligible_frontmatter(risk_flags={"privacy_or_secret_sensitive": True})
    assessment = assess_release_auto_arm(fm)
    assert not assessment.eligible
    assert "risk_flag:privacy_or_secret_sensitive" in assessment.blockers


def test_privacy_secret_auto_arms_when_mitigation_evidence_present() -> None:
    # With the dedicated secret scanner passing, a privacy/secret-sensitive change
    # auto-arms on its evidence — the #4256 proof case. No human arm.
    fm = _eligible_frontmatter(risk_flags={"privacy_or_secret_sensitive": True})
    assessment = assess_release_auto_arm(fm, verified_checks={"secrets-scan", "test", "review"})
    assert assessment.eligible
    assert assessment.blockers == ()


def test_privacy_secret_held_when_mitigation_evidence_missing() -> None:
    # Evidence absent → held with a "needs_mitigation" reason; resolved by PRODUCING
    # the mitigation (running secrets-scan), never by a manual override.
    fm = _eligible_frontmatter(risk_flags={"privacy_or_secret_sensitive": True})
    assessment = assess_release_auto_arm(fm, verified_checks={"test", "review"})
    assert not assessment.eligible
    assert "needs_mitigation:privacy_or_secret_sensitive:secrets-scan" in assessment.blockers


def test_governance_sensitive_auto_arms_when_mitigation_evidence_present() -> None:
    fm = _eligible_frontmatter(risk_flags={"governance_sensitive": True})
    verified_checks = set(RELEASE_MITIGATION_CHECKS["governance_sensitive"])

    assessment = assess_release_auto_arm(fm, verified_checks=verified_checks)

    assert assessment.eligible
    assert assessment.blockers == ()


def test_governance_sensitive_held_when_mitigation_evidence_missing() -> None:
    fm = _eligible_frontmatter(risk_flags={"governance_sensitive": True})
    assessment = assess_release_auto_arm(fm, verified_checks={"authority-case-check"})

    assert not assessment.eligible
    assert assessment.blockers == ("needs_mitigation:governance_sensitive:review-team-quorum",)


def test_governance_sensitive_still_fails_closed_without_verified_checks() -> None:
    fm = _eligible_frontmatter(risk_flags={"governance_sensitive": True})
    assessment = assess_release_auto_arm(fm)

    assert not assessment.eligible
    assert assessment.blockers == ("risk_flag:governance_sensitive",)


def test_public_claim_sensitive_held_when_mitigation_evidence_missing() -> None:
    fm = _eligible_frontmatter(risk_flags={"public_claim_sensitive": True})
    assessment = assess_release_auto_arm(fm, verified_checks={"secrets-scan", "test", "review"})
    assert not assessment.eligible
    assert assessment.blockers == (
        "needs_mitigation:public_claim_sensitive:authority-case-check",
        "needs_mitigation:public_claim_sensitive:review-team-quorum",
    )


def test_public_claim_sensitive_auto_arms_when_mitigation_evidence_present() -> None:
    fm = _eligible_frontmatter(risk_flags={"public_claim_sensitive": True})
    verified_checks = set(RELEASE_MITIGATION_CHECKS["public_claim_sensitive"])

    assessment = assess_release_auto_arm(fm, verified_checks=verified_checks)

    assert assessment.eligible
    assert assessment.blockers == ()


def test_public_claim_mitigation_does_not_grant_public_surface_release() -> None:
    fm = _eligible_frontmatter(
        risk_flags={"public_claim_sensitive": True},
        mutation_surface="public",
    )
    verified_checks = set(RELEASE_MITIGATION_CHECKS["public_claim_sensitive"])

    assessment = assess_release_auto_arm(fm, verified_checks=verified_checks)

    assert not assessment.eligible
    assert "mutation_surface:public" in assessment.blockers


def test_nonsensitive_task_stays_eligible_with_verified_checks() -> None:
    # Supplying verified_checks must not regress the non-sensitive happy path.
    assessment = assess_release_auto_arm(
        _eligible_frontmatter(), verified_checks={"secrets-scan", "test"}
    )
    assert assessment.eligible
