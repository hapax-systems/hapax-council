"""Tests for system release auto-arm — dispatch resilience to lane-death.

Reform improve (CASE-CAPACITY-ROUTING-001): a lane that dies after creating its
PR but before flipping ``release_authorized: true`` strands a CLEAN, green,
mergeable PR at ``pr_open`` forever. The autoqueue (running as the system,
unclaimed — FM-20) must auto-arm such a task — but only when its release was
already authorized-in-principle by its ISAP and its risk profile carries no
governance/public/audio-egress veto. Sensitive tasks stay manual.
"""

from __future__ import annotations

from shared.sdlc_lifecycle import (
    apply_release_auto_arm,
    assess_release_auto_arm,
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
    assert any("governance" in blocker for blocker in assessment.blockers)


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
