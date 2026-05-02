"""Tests for ``shared.rights_safe_media_reference_gate``.

Per cc-task ``rights-safe-media-reference-gate`` (WSJF 9.0). The gate
is the load-bearing predicate every react / review / comparison /
watch-along media reference consults before emission. These tests pin
the fail-CLOSED contract for every cc-task acceptance factor.

Coverage maps directly to the cc-task acceptance criteria:

  - fail closed on unknown rights / stream ripping / rebroadcast /
    sparse commentary / substitution risk → TestFailClosed
  - excerpt plan / transformation evidence / commentary density /
    non-substitution / monetization fields → TestExcerptValidation
  - link-along + metadata-first modes → TestSaferModes
  - fair-use memo as evidence prep → TestFairUseMemo
  - Content ID / advertiser suitability / disclosure / kill-switch →
    TestPlatformIntegration
"""

from __future__ import annotations

import pytest

from shared.rights_safe_media_reference_gate import (
    MAX_EXCERPT_FRACTION,
    MIN_COMMENTARY_DENSITY,
    Decision,
    FairUseMemo,
    MediaReferenceProposal,
    ReferenceMode,
    RightsClass,
    evaluate_media_reference,
)

# ── Module surface ───────────────────────────────────────────────────


class TestModuleSurface:
    def test_default_thresholds_are_documented_values(self) -> None:
        # Pin the documented defaults; downstream callers tune via
        # kwargs but the module-level constants must stay stable.
        assert MAX_EXCERPT_FRACTION == 0.20
        assert MIN_COMMENTARY_DENSITY == 1.0

    def test_decision_taxonomy(self) -> None:
        assert {d.value for d in Decision} == {"allow", "refuse", "downgrade"}

    def test_reference_mode_taxonomy(self) -> None:
        assert {m.value for m in ReferenceMode} == {
            "excerpt",
            "link_along",
            "metadata_first",
        }

    def test_rights_class_taxonomy(self) -> None:
        assert {c.value for c in RightsClass} == {
            "unknown",
            "explicit_license",
            "fair_use_prep",
            "platform_provided",
            "refused",
        }


# ── Fixture builders ─────────────────────────────────────────────────


def _good_excerpt_proposal(**overrides) -> MediaReferenceProposal:
    """Build a proposal that should ALLOW under excerpt mode by default.
    Tests override fields to exercise specific failure paths."""
    base = {
        "upstream_id": "https://youtu.be/abc",
        "upstream_total_seconds": 600.0,
        "rights_class": RightsClass.FAIR_USE_PREP,
        "proposed_mode": ReferenceMode.EXCERPT,
        "excerpt_seconds": 60.0,  # 10% of total
        "commentary_seconds": 120.0,  # density 2.0
        "transformation_evidence": "voice commentary + frame overlay",
        "non_substitution_rationale": "viewer would still want full work",
        "disclosure_text": "fair-use commentary; original at <url>",
    }
    base.update(overrides)
    return MediaReferenceProposal(**base)


# ── Fail-closed (cc-task §"Acceptance Criteria" item 1) ─────────────


class TestFailClosed:
    def test_unknown_source_refuses(self) -> None:
        result = evaluate_media_reference(_good_excerpt_proposal(upstream_id=""))
        assert result.decision is Decision.REFUSE
        assert "unknown_source" in result.refused_factors

    def test_unknown_duration_refuses(self) -> None:
        result = evaluate_media_reference(_good_excerpt_proposal(upstream_total_seconds=0.0))
        assert result.decision is Decision.REFUSE
        assert "unknown_duration" in result.refused_factors

    def test_unknown_rights_class_refuses(self) -> None:
        result = evaluate_media_reference(_good_excerpt_proposal(rights_class=RightsClass.UNKNOWN))
        assert result.decision is Decision.REFUSE
        assert "rights_unknown" in result.refused_factors

    def test_explicitly_refused_rights_refuses(self) -> None:
        result = evaluate_media_reference(_good_excerpt_proposal(rights_class=RightsClass.REFUSED))
        assert result.decision is Decision.REFUSE
        assert "rights_refused" in result.refused_factors

    def test_kill_switch_refuses_regardless_of_rights(self) -> None:
        result = evaluate_media_reference(
            _good_excerpt_proposal(
                rights_class=RightsClass.EXPLICIT_LICENSE,
                live_rights_kill_switch_active=True,
            )
        )
        assert result.decision is Decision.REFUSE
        assert "kill_switch" in result.refused_factors


# ── Excerpt validation (cc-task §"Acceptance Criteria" item 2) ──────


class TestExcerptValidation:
    def test_zero_excerpt_seconds_refuses(self) -> None:
        result = evaluate_media_reference(_good_excerpt_proposal(excerpt_seconds=0.0))
        assert result.decision is Decision.REFUSE
        assert "missing_excerpt_plan" in result.refused_factors

    def test_excerpt_at_max_fraction_allows(self) -> None:
        # 20% of 600 = 120s — exactly at the ceiling.
        result = evaluate_media_reference(
            _good_excerpt_proposal(
                excerpt_seconds=120.0,
                commentary_seconds=240.0,  # density 2.0
            )
        )
        assert result.decision is Decision.ALLOW

    def test_excerpt_above_max_fraction_downgrades(self) -> None:
        # 25% of 600 = 150s — above the rebroadcast ceiling.
        result = evaluate_media_reference(_good_excerpt_proposal(excerpt_seconds=150.0))
        assert result.decision is Decision.DOWNGRADE
        assert result.downgrade_to is ReferenceMode.LINK_ALONG
        assert "rebroadcast_risk" in result.refused_factors

    def test_missing_transformation_refuses(self) -> None:
        result = evaluate_media_reference(_good_excerpt_proposal(transformation_evidence=""))
        assert result.decision is Decision.REFUSE
        assert "no_transformation" in result.refused_factors

    def test_missing_non_substitution_refuses(self) -> None:
        result = evaluate_media_reference(_good_excerpt_proposal(non_substitution_rationale=""))
        assert result.decision is Decision.REFUSE
        assert "substitution_risk" in result.refused_factors

    def test_sparse_commentary_refuses(self) -> None:
        # commentary_density = 30 / 60 = 0.5 < 1.0 floor
        result = evaluate_media_reference(_good_excerpt_proposal(commentary_seconds=30.0))
        assert result.decision is Decision.REFUSE
        assert "sparse_commentary" in result.refused_factors

    def test_commentary_density_at_floor_allows(self) -> None:
        # density exactly 1.0 — passes the >= floor.
        result = evaluate_media_reference(
            _good_excerpt_proposal(commentary_seconds=60.0)  # density = 1.0
        )
        assert result.decision is Decision.ALLOW

    def test_excerpt_kwarg_override_tightens_ceiling(self) -> None:
        # 10% of 600 = 60s — under default 20% but over a strict 5%.
        result = evaluate_media_reference(
            _good_excerpt_proposal(),
            max_excerpt_fraction=0.05,
        )
        assert result.decision is Decision.DOWNGRADE


# ── Safer modes (cc-task §"Acceptance Criteria" item 3) ─────────────


class TestSaferModes:
    def test_link_along_allows(self) -> None:
        # Even with no excerpt fields populated, link-along is rights-
        # safe by construction.
        result = evaluate_media_reference(
            MediaReferenceProposal(
                upstream_id="https://youtu.be/abc",
                upstream_total_seconds=600.0,
                rights_class=RightsClass.FAIR_USE_PREP,
                proposed_mode=ReferenceMode.LINK_ALONG,
            )
        )
        assert result.decision is Decision.ALLOW

    def test_metadata_first_allows(self) -> None:
        result = evaluate_media_reference(
            MediaReferenceProposal(
                upstream_id="https://youtu.be/abc",
                upstream_total_seconds=600.0,
                rights_class=RightsClass.PLATFORM_PROVIDED,
                proposed_mode=ReferenceMode.METADATA_FIRST,
            )
        )
        assert result.decision is Decision.ALLOW

    def test_safer_modes_still_refuse_unknown_rights(self) -> None:
        # Safer modes don't bypass rights pre-check.
        result = evaluate_media_reference(
            MediaReferenceProposal(
                upstream_id="https://youtu.be/abc",
                upstream_total_seconds=600.0,
                rights_class=RightsClass.UNKNOWN,
                proposed_mode=ReferenceMode.LINK_ALONG,
            )
        )
        assert result.decision is Decision.REFUSE


# ── Fair-use memo (cc-task §"Acceptance Criteria" item 4) ──────────


class TestFairUseMemo:
    def test_memo_attached_on_allow(self) -> None:
        result = evaluate_media_reference(_good_excerpt_proposal())
        assert result.fair_use_memo is not None
        assert isinstance(result.fair_use_memo, FairUseMemo)

    def test_memo_attached_on_refuse(self) -> None:
        # Memo emitted regardless of decision so operator can take it
        # to a rights review even after a refusal.
        result = evaluate_media_reference(_good_excerpt_proposal(rights_class=RightsClass.UNKNOWN))
        assert result.fair_use_memo is not None

    def test_memo_carries_four_factors(self) -> None:
        memo = evaluate_media_reference(_good_excerpt_proposal()).fair_use_memo
        assert memo is not None
        # Each factor populated.
        assert memo.purpose_and_character != ""
        assert memo.nature_of_work != ""
        assert memo.amount_and_substantiality != ""
        assert memo.market_effect != ""

    def test_memo_includes_excerpt_fraction(self) -> None:
        # Factor 3 (amount/substantiality) should reflect the actual
        # excerpt fraction so a rights reviewer sees the material
        # number, not just a flag.
        memo = evaluate_media_reference(_good_excerpt_proposal(excerpt_seconds=60.0)).fair_use_memo
        assert memo is not None
        assert "10.0%" in memo.amount_and_substantiality

    def test_memo_records_missing_evidence(self) -> None:
        # When evidence is missing, the memo says so explicitly rather
        # than silently dropping the factor.
        result = evaluate_media_reference(_good_excerpt_proposal(transformation_evidence=""))
        # Decision is REFUSE but the memo still emits.
        assert result.decision is Decision.REFUSE
        assert result.fair_use_memo is not None
        assert "no transformation evidence supplied" in result.fair_use_memo.purpose_and_character


# ── Platform integration (cc-task §"Acceptance Criteria" item 5) ────


class TestPlatformIntegration:
    def test_disclosure_required_for_monetization(self) -> None:
        # Monetization request without disclosure_text is an
        # advertiser-suitability fail.
        result = evaluate_media_reference(
            _good_excerpt_proposal(
                monetization_requested=True,
                disclosure_text="",
            )
        )
        assert result.decision is Decision.REFUSE
        assert "no_disclosure_for_monetization" in result.refused_factors

    def test_monetization_with_disclosure_allows(self) -> None:
        result = evaluate_media_reference(
            _good_excerpt_proposal(
                monetization_requested=True,
                disclosure_text="fair-use commentary; original at <url>",
            )
        )
        assert result.decision is Decision.ALLOW

    def test_platform_provided_rights_class_allowed(self) -> None:
        result = evaluate_media_reference(
            _good_excerpt_proposal(
                rights_class=RightsClass.PLATFORM_PROVIDED,
            )
        )
        assert result.decision is Decision.ALLOW

    def test_kill_switch_overrides_explicit_license(self) -> None:
        # Operator can REFUSE even an explicit license via kill-switch.
        result = evaluate_media_reference(
            _good_excerpt_proposal(
                rights_class=RightsClass.EXPLICIT_LICENSE,
                live_rights_kill_switch_active=True,
            )
        )
        assert result.decision is Decision.REFUSE


# ── Result structure (consumer contract) ─────────────────────────────


class TestResultStructure:
    def test_allow_result_has_no_downgrade_target(self) -> None:
        result = evaluate_media_reference(_good_excerpt_proposal())
        assert result.decision is Decision.ALLOW
        assert result.downgrade_to is None
        assert result.refused_factors == ()

    def test_downgrade_result_carries_target_mode(self) -> None:
        result = evaluate_media_reference(
            _good_excerpt_proposal(excerpt_seconds=300.0)  # 50% of 600
        )
        assert result.decision is Decision.DOWNGRADE
        assert result.downgrade_to is ReferenceMode.LINK_ALONG

    def test_refuse_result_lists_factors(self) -> None:
        result = evaluate_media_reference(
            MediaReferenceProposal(
                upstream_id="",
                upstream_total_seconds=0.0,
            )
        )
        assert result.decision is Decision.REFUSE
        # First failing precheck wins; either unknown_source or
        # unknown_duration depending on order.
        assert len(result.refused_factors) >= 1


# ── Sanity: standard-mode fixture is healthy ────────────────────────


@pytest.mark.parametrize(
    "rights_class",
    [
        RightsClass.EXPLICIT_LICENSE,
        RightsClass.FAIR_USE_PREP,
        RightsClass.PLATFORM_PROVIDED,
    ],
)
def test_each_passing_rights_class_allows_default_excerpt(
    rights_class: RightsClass,
) -> None:
    """Three of the five rights classes are 'pass through to ALLOW' as
    long as the excerpt-mode invariants hold. Pin that contract."""
    result = evaluate_media_reference(_good_excerpt_proposal(rights_class=rights_class))
    assert result.decision is Decision.ALLOW
