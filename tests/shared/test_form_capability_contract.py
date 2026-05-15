"""Tests for shared.form_capability_contract.

Three fixture categories per the spec:
- valid_weird_form: non-standard form that passes all gates
- rubric_recitation: framework vocabulary without source consequence
- regex_theater: exact trigger phrases without structured action intent
"""

from __future__ import annotations

import pytest

from shared.form_capability_contract import (
    ActionPrimitive,
    AuthorityHypothesis,
    ClaimShape,
    FormCapabilityContract,
    FormOrigin,
    LiveEventObject,
    PublicPrivateCeiling,
    ReadbackRequirement,
    RefusalMode,
    form_capability_contract_sha256,
    validate_form_capability_contract,
)


def _valid_weird_form() -> FormCapabilityContract:
    """Short, non-standard, source-bound form that passes authority gates."""
    return FormCapabilityContract(
        form_id="zram-swap-pressure-argument-20260515",
        form_label="three-minute-zram-swap-pressure-argument",
        form_origin=FormOrigin.GENERATED,
        exemplar_refs=(),
        grounding_question=(
            "Is the current 18G/32G zram swap utilization evidence that the "
            "128GB RAM policy is under-provisioned for peak compositor load?"
        ),
        claim_shape=ClaimShape(
            allowed_claim_verbs=("demonstrates", "contrasts", "argues"),
            authority_ceiling="eligible_candidate",
            scope="system memory pressure during compositor peak (2026-05-14 incident)",
            uncertainty_posture="bounded_confidence",
            correction_path="operator overrides via zram-policy.yaml re-tuning",
        ),
        authority_hypothesis=AuthorityHypothesis(
            requested_transition="eligible_candidate",
            evidence_needed=(
                "source:system-metrics/zram-usage-2026-05-14.json",
                "source:config/128gb-ram-policy.yaml",
            ),
            falsification_criterion=(
                "swap utilization below 50% during compositor peak would "
                "falsify under-provisioning claim"
            ),
            current_state="scratch",
        ),
        source_classes=("source:system_metrics", "source:config_yaml"),
        evidence_requirements=(
            "If zram metrics show <50% usage during peak, claim narrows to non-issue",
            "If ram-policy already accounts for compositor burst, argument blocks",
        ),
        live_event_object=LiveEventObject(
            object_id="swap-pressure-comparison",
            object_kind="comparison_view",
            visible_payload="side-by-side zram utilization vs policy allocation",
            source_binding="source:system-metrics/zram-usage-2026-05-14.json",
        ),
        action_primitives=(
            ActionPrimitive(
                action_id="compare-peak-vs-policy",
                kind="compare",
                object_ref="source:system-metrics/zram-usage-2026-05-14.json",
                operation="contrast peak swap usage against 128GB policy headroom target",
                evidence_refs=("source:system-metrics/zram-usage-2026-05-14.json",),
                fallback="narrate comparison without visual if compositor unavailable",
            ),
            ActionPrimitive(
                action_id="cite-policy-gap",
                kind="cite_source",
                object_ref="source:config/128gb-ram-policy.yaml",
                operation="show the specific allocation line that may be insufficient",
                evidence_refs=("source:config/128gb-ram-policy.yaml",),
                fallback="read policy values aloud without visual overlay",
            ),
        ),
        layout_need_classes=("comparison_view", "source_visible"),
        readback_requirements=(
            ReadbackRequirement(
                readback_id="swap-comparison-visible",
                must_show="swap pressure chart rendered with both metrics visible",
                must_not_claim="static default layout as success",
                timeout_s=10.0,
                failure_mode="fall back to spoken-only comparison",
            ),
        ),
        public_private_ceiling=PublicPrivateCeiling.PUBLIC_LIVE,
        refusal_mode=RefusalMode.NARROW_SCOPE,
    )


def _rubric_recitation_form() -> FormCapabilityContract:
    """Recites framework vocabulary without source consequence."""
    return FormCapabilityContract(
        form_id="rubric-recitation-fixture-001",
        form_label="quality-budget-excellence-gate-review",
        form_origin=FormOrigin.GENERATED,
        grounding_question=(
            "Does the source consequence contract meet the quality budget principle "
            "as defined by the eligibility gate?"
        ),
        claim_shape=ClaimShape(
            allowed_claim_verbs=("evaluates", "assesses"),
            authority_ceiling="eligible_candidate",
            scope="excellence selection detector trigger theater review scope",
            uncertainty_posture="quality range receipt bounded",
            correction_path="consultation manifest role contract refs update cycle",
        ),
        authority_hypothesis=AuthorityHypothesis(
            requested_transition="eligible_candidate",
            evidence_needed=("quality range receipt", "positive excellence receipt"),
            falsification_criterion=(
                "non-anthropomorphic force runtime readback doctrine violation"
            ),
            current_state="scratch",
        ),
        source_classes=("source:quality_rubric",),
        evidence_requirements=(
            "quality range receipt must exist",
            "positive excellence receipt must be present",
        ),
        live_event_object=None,
        action_primitives=(),
        public_private_ceiling=PublicPrivateCeiling.PRIVATE,
        refusal_mode=RefusalMode.EMIT_NO_CANDIDATE,
    )


def _regex_theater_form() -> FormCapabilityContract:
    """Uses exact trigger phrases and bracket templates."""
    return FormCapabilityContract(
        form_id="regex-theater-fixture-001",
        form_label="generic-tier-list-template",
        form_origin=FormOrigin.GENERATED,
        grounding_question="Which [item] belongs in [S/A/B/C/D]-tier?",
        claim_shape=ClaimShape(
            allowed_claim_verbs=("ranks", "places"),
            authority_ceiling="eligible_candidate",
            scope="generic ranking of unspecified items",
            uncertainty_posture="bounded_confidence",
            correction_path="re-rank on new evidence",
        ),
        authority_hypothesis=AuthorityHypothesis(
            requested_transition="eligible_candidate",
            evidence_needed=("source:ranking_criteria",),
            falsification_criterion="criteria change would alter rankings",
            current_state="scratch",
        ),
        source_classes=("source:ranking_data",),
        evidence_requirements=(
            "If ranking criteria change, all placements must be re-evaluated",
        ),
        live_event_object=LiveEventObject(
            object_id="tier-chart-display",
            object_kind="tier_chart",
            visible_payload="[item] placement in [S/A/B/C/D] tiers",
            source_binding="source:ranking_data",
        ),
        action_primitives=(
            ActionPrimitive(
                action_id="place-item-in-tier",
                kind="rank",
                object_ref="[item]",
                operation="Place [item] in [S/A/B/C/D]-tier",
                evidence_refs=(),
                fallback="skip item placement",
            ),
            ActionPrimitive(
                action_id="reveal-ranking",
                kind="reveal",
                object_ref="[ranking]",
                operation="#N is... or Number N:",
                evidence_refs=(),
                fallback="announce verbally",
            ),
        ),
        layout_need_classes=("tier_visual",),
        readback_requirements=(
            ReadbackRequirement(
                readback_id="tier-chart-visible",
                must_show="tier chart rendered",
                must_not_claim="default layout",
                timeout_s=10.0,
                failure_mode="spoken-only ranking",
            ),
        ),
        public_private_ceiling=PublicPrivateCeiling.PUBLIC_LIVE,
        refusal_mode=RefusalMode.NARROW_SCOPE,
    )


class TestValidWeirdForm:
    def test_passes_structural_validation(self) -> None:
        contract = _valid_weird_form()
        assert contract.form_id == "zram-swap-pressure-argument-20260515"

    def test_passes_negative_control_checks(self) -> None:
        contract = _valid_weird_form()
        result = validate_form_capability_contract(contract)
        assert result["ok"] is True
        assert result["violations"] == []

    def test_hash_is_stable(self) -> None:
        contract = _valid_weird_form()
        h1 = form_capability_contract_sha256(contract)
        h2 = form_capability_contract_sha256(contract)
        assert h1 == h2
        assert len(h1) == 64

    def test_no_exemplar_refs_is_valid(self) -> None:
        contract = _valid_weird_form()
        assert contract.exemplar_refs == ()


class TestRubricRecitation:
    def test_detected_as_rubric_recitation(self) -> None:
        contract = _rubric_recitation_form()
        result = validate_form_capability_contract(contract)
        assert result["ok"] is False
        reasons = [v["reason"] for v in result["violations"]]
        assert "rubric_recitation" in reasons

    def test_framework_vocabulary_flagged(self) -> None:
        contract = _rubric_recitation_form()
        result = validate_form_capability_contract(contract)
        recitation_violations = [
            v for v in result["violations"] if v["reason"] == "rubric_recitation"
        ]
        assert len(recitation_violations) >= 1
        assert "framework vocabulary" in recitation_violations[0]["detail"]


class TestRegexTheater:
    def test_detected_as_regex_theater(self) -> None:
        contract = _regex_theater_form()
        result = validate_form_capability_contract(contract)
        assert result["ok"] is False
        reasons = [v["reason"] for v in result["violations"]]
        assert "regex_theater" in reasons

    def test_bracket_templates_flagged(self) -> None:
        contract = _regex_theater_form()
        result = validate_form_capability_contract(contract)
        theater_violations = [
            v for v in result["violations"] if v["reason"] == "regex_theater"
        ]
        assert any("bracket-template" in v["detail"] for v in theater_violations)

    def test_exact_phrases_flagged(self) -> None:
        contract = _regex_theater_form()
        result = validate_form_capability_contract(contract)
        theater_violations = [
            v for v in result["violations"] if v["reason"] == "regex_theater"
        ]
        assert any("trigger phrase" in v["detail"] for v in theater_violations)


class TestModelInvariants:
    def test_refusal_form_cannot_claim_public(self) -> None:
        with pytest.raises(Exception, match="refusal.*must not claim public"):
            FormCapabilityContract(
                form_id="bad-refusal",
                form_label="bad",
                form_origin=FormOrigin.REFUSAL_NO_CANDIDATE,
                grounding_question="Why refuse?",
                claim_shape=ClaimShape(
                    allowed_claim_verbs=("refuses",),
                    authority_ceiling="scratch",
                    scope="n/a",
                    uncertainty_posture="certain",
                    correction_path="n/a",
                ),
                authority_hypothesis=AuthorityHypothesis(
                    requested_transition="no_candidate",
                    evidence_needed=("none",),
                    falsification_criterion="n/a",
                ),
                source_classes=("source:none",),
                evidence_requirements=("no evidence changes outcome",),
                public_private_ceiling=PublicPrivateCeiling.PUBLIC_LIVE,
                refusal_mode=RefusalMode.EMIT_NO_CANDIDATE,
            )

    def test_public_form_requires_live_event(self) -> None:
        with pytest.raises(Exception, match="must declare a live_event_object"):
            FormCapabilityContract(
                form_id="bad-public",
                form_label="bad",
                form_origin=FormOrigin.GENERATED,
                grounding_question="What does this demonstrate?",
                claim_shape=ClaimShape(
                    allowed_claim_verbs=("demonstrates",),
                    authority_ceiling="eligible_candidate",
                    scope="test",
                    uncertainty_posture="bounded",
                    correction_path="revert",
                ),
                authority_hypothesis=AuthorityHypothesis(
                    requested_transition="eligible_candidate",
                    evidence_needed=("source:test",),
                    falsification_criterion="test fails",
                ),
                source_classes=("source:test",),
                evidence_requirements=("If test data changes, claim narrows",),
                public_private_ceiling=PublicPrivateCeiling.PUBLIC_LIVE,
                refusal_mode=RefusalMode.NARROW_SCOPE,
            )

    def test_contract_is_frozen(self) -> None:
        contract = _valid_weird_form()
        with pytest.raises(Exception):
            contract.form_id = "hacked"  # type: ignore[misc]

    def test_duplicate_action_ids_rejected(self) -> None:
        with pytest.raises(Exception, match="unique action_ids"):
            FormCapabilityContract(
                form_id="dup-actions",
                form_label="dup",
                form_origin=FormOrigin.GENERATED,
                grounding_question="What does this demonstrate?",
                claim_shape=ClaimShape(
                    allowed_claim_verbs=("demonstrates",),
                    authority_ceiling="eligible_candidate",
                    scope="test",
                    uncertainty_posture="bounded",
                    correction_path="revert",
                ),
                authority_hypothesis=AuthorityHypothesis(
                    requested_transition="eligible_candidate",
                    evidence_needed=("source:test",),
                    falsification_criterion="test fails",
                ),
                source_classes=("source:test",),
                evidence_requirements=("If data changes, claim narrows",),
                live_event_object=LiveEventObject(
                    object_id="obj-1",
                    object_kind="comparison_view",
                    visible_payload="test",
                    source_binding="source:test",
                ),
                action_primitives=(
                    ActionPrimitive(
                        action_id="same-id",
                        kind="compare",
                        object_ref="source:test",
                        operation="compare things",
                        evidence_refs=("source:test",),
                        fallback="skip",
                    ),
                    ActionPrimitive(
                        action_id="same-id",
                        kind="cite",
                        object_ref="source:other",
                        operation="cite other",
                        evidence_refs=("source:other",),
                        fallback="skip",
                    ),
                ),
                layout_need_classes=("comparison_view",),
                readback_requirements=(
                    ReadbackRequirement(
                        readback_id="rb-1",
                        must_show="chart",
                        must_not_claim="default",
                        timeout_s=10.0,
                        failure_mode="skip",
                    ),
                ),
                public_private_ceiling=PublicPrivateCeiling.PUBLIC_LIVE,
                refusal_mode=RefusalMode.NARROW_SCOPE,
            )
