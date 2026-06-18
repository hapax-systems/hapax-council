"""Tests for system release auto-arm — dispatch resilience to lane-death.

Reform improve (CASE-CAPACITY-ROUTING-001): a lane that dies after creating its
PR but before flipping ``release_authorized: true`` strands a CLEAN, green,
mergeable PR at ``pr_open`` forever. The autoqueue (running as the system,
unclaimed — FM-20) must auto-arm such a task when its release was already
authorized-in-principle by its ISAP and the automated quality gates pass. There
is no separate human release authorization stop.
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


# ── sensitivity is handled by automated gates, not manual release ───────


def test_explicit_governance_risk_flag_does_not_block_auto_arm() -> None:
    fm = _eligible_frontmatter(risk_flags={"governance_sensitive": True})
    assessment = assess_release_auto_arm(fm)
    assert assessment.needs_arming is True
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_governance_keyword_in_title_does_not_block_auto_arm() -> None:
    fm = _eligible_frontmatter(
        title="Tighten governance policy enforcement on authority cases",
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_audio_or_live_egress_sensitive_metadata_does_not_block_auto_arm() -> None:
    fm = _eligible_frontmatter(
        title="Adjust broadcast audio loudnorm egress chain",
        tags=["cc-task", "audio", "egress"],
        avsdlc_axes=[],
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_public_claim_sensitive_metadata_does_not_block_auto_arm() -> None:
    fm = _eligible_frontmatter(
        title="Publish public claim to external surface",
        tags=["cc-task", "publication", "public"],
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_public_mutation_surface_does_not_create_manual_release_gate() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(mutation_surface="public"))
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_provider_spend_mutation_surface_does_not_create_manual_release_gate() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(mutation_surface="provider_spend"))
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_governance_protected_path_does_not_create_manual_release_gate() -> None:
    fm = _eligible_frontmatter(
        mutation_scope_refs=["axioms/registry.yaml", "shared/foo.py"],
    )
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_sensitive_path_substring_does_not_block_auto_arm() -> None:
    fm = _eligible_frontmatter(mutation_scope_refs=["scripts/sync-codeowners.py"])
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_sensitive_path_dir_marker_substring_does_not_block_auto_arm() -> None:
    fm = _eligible_frontmatter(mutation_scope_refs=["research/meta-axioms/notes.md"])
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_codeowners_path_segment_does_not_create_manual_release_gate() -> None:
    fm = _eligible_frontmatter(mutation_scope_refs=[".github/CODEOWNERS"])
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_claude_md_path_segment_does_not_create_manual_release_gate() -> None:
    fm = _eligible_frontmatter(mutation_scope_refs=["hapax-council/CLAUDE.md"])
    assessment = assess_release_auto_arm(fm)
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_public_current_does_not_create_manual_release_gate() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(public_current=True))
    assert assessment.eligible is True
    assert assessment.blockers == ()


def test_risk_tier_t3_does_not_create_manual_release_gate() -> None:
    assessment = assess_release_auto_arm(_eligible_frontmatter(risk_tier="T3"))
    assert assessment.eligible is True
    assert assessment.blockers == ()


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
