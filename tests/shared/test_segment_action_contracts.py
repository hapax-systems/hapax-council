from __future__ import annotations

from shared.segment_action_contracts import (
    ActionContract,
    InterviewActionContract,
    InterviewActionKind,
    TierListActionKind,
    validate_interview_actions,
    validate_tier_list_actions,
)


class TestTierListActions:
    def test_valid_tier_list(self) -> None:
        actions = [
            ActionContract(
                action_id="t1",
                kind=TierListActionKind.TIER_VISUAL_DISPLAY,
                object_ref="source:ranking.json",
                operation="display tier chart",
                evidence_refs=("source:ranking.json",),
                fallback="announce verbally",
            ),
        ]
        result = validate_tier_list_actions(actions)
        assert result["ok"]

    def test_missing_evidence_flagged(self) -> None:
        actions = [
            ActionContract(
                action_id="t1",
                kind=TierListActionKind.TIER_COMPARISON,
                object_ref="source:data",
                operation="compare tiers",
                evidence_refs=(),
                fallback="skip",
            ),
        ]
        result = validate_tier_list_actions(actions)
        assert not result["ok"]
        assert any("evidence_refs" in v for v in result["violations"])

    def test_no_tier_kinds_flagged(self) -> None:
        actions = [
            ActionContract(
                action_id="t1",
                kind="generic_action",
                object_ref="x",
                operation="y",
                fallback="z",
            ),
        ]
        result = validate_tier_list_actions(actions)
        assert not result["ok"]


class TestInterviewActions:
    def test_valid_interview_with_consent_and_question(self) -> None:
        actions = [
            InterviewActionContract(
                action_id="i1",
                kind=InterviewActionKind.CONSENT_CHECK,
                object_ref="topic:zram-pressure",
                operation="check operator consent for topic",
                fallback="skip topic",
                consent_receipt_ref="receipt:consent:001",
            ),
            InterviewActionContract(
                action_id="i2",
                kind=InterviewActionKind.QUESTION_ASK,
                object_ref="question:q1",
                operation="ask operator about zram swap",
                evidence_refs=("source:system-metrics/zram.json",),
                fallback="move to next question",
                question_ladder_position=0,
            ),
        ]
        result = validate_interview_actions(actions)
        assert result["ok"]

    def test_missing_consent_flagged(self) -> None:
        actions = [
            ActionContract(
                action_id="i2",
                kind=InterviewActionKind.QUESTION_ASK,
                object_ref="q1",
                operation="ask",
                evidence_refs=("source:test",),
                fallback="skip",
            ),
        ]
        result = validate_interview_actions(actions)
        assert not result["ok"]
        assert any("consent_check" in v for v in result["violations"])

    def test_question_without_evidence_flagged(self) -> None:
        actions = [
            ActionContract(
                action_id="i1",
                kind=InterviewActionKind.CONSENT_CHECK,
                object_ref="topic",
                operation="check consent",
                fallback="skip",
            ),
            ActionContract(
                action_id="i2",
                kind=InterviewActionKind.QUESTION_ASK,
                object_ref="q1",
                operation="ask",
                evidence_refs=(),
                fallback="skip",
            ),
        ]
        result = validate_interview_actions(actions)
        assert not result["ok"]
        assert any("source-grounded" in v for v in result["violations"])

    def test_interview_contract_has_consent_fields(self) -> None:
        contract = InterviewActionContract(
            action_id="i1",
            kind=InterviewActionKind.CONSENT_CHECK,
            object_ref="topic",
            operation="check consent",
            fallback="skip",
            consent_receipt_ref="receipt:001",
            answer_authority_ref="auth:operator",
            release_scope_ref="scope:public",
            question_ladder_position=0,
        )
        assert contract.consent_receipt_ref == "receipt:001"
        assert contract.question_ladder_position == 0
