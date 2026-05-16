from __future__ import annotations

from unittest.mock import patch

from agents.deliberative_council.models import ConvergenceStatus, CouncilVerdict
from shared.segment_disconfirmation import (
    apply_council_verdicts,
    extract_claims,
    run_council_disconfirmation,
)


class TestExtractClaims:
    def test_extracts_from_claim_map(self) -> None:
        claim_map = [
            {
                "claim_id": "claim:seg1:001",
                "claim_text": "zram swap pressure exceeds 50% during compositor peak",
                "grounds": ["source:system-metrics/zram-usage.json"],
                "source_consequence": "ranking changes if swap is below threshold",
            },
            {
                "claim_id": "claim:seg1:002",
                "claim_text": "Command-R handles all interview routing locally",
                "grounds": ["source:config/litellm-config.yaml"],
                "source_consequence": "routing claim invalid if cloud fallback exists",
            },
        ]
        source_consequence_map = [
            {
                "source_ref": "source:system-metrics/zram-usage.json",
                "claim_ids": ["claim:seg1:001"],
                "consequence_kind": "ranking_or_order_changed",
            },
        ]

        inputs = extract_claims(
            claim_map=claim_map,
            source_consequence_map=source_consequence_map,
        )

        assert len(inputs) == 2
        assert inputs[0].text == "zram swap pressure exceeds 50% during compositor peak"
        assert inputs[0].source_ref == "source:system-metrics/zram-usage.json"
        assert inputs[0].metadata["claim_id"] == "claim:seg1:001"

    def test_skips_claims_without_grounds(self) -> None:
        claim_map = [
            {
                "claim_id": "claim:seg1:001",
                "claim_text": "this claim has no evidence",
                "grounds": [],
                "source_consequence": "none",
            },
        ]
        inputs = extract_claims(claim_map=claim_map, source_consequence_map=[])
        assert len(inputs) == 0

    def test_empty_claim_map_returns_empty(self) -> None:
        inputs = extract_claims(claim_map=[], source_consequence_map=[])
        assert inputs == []

    def test_deduplicates_same_claim_text(self) -> None:
        claim_map = [
            {
                "claim_id": "claim:seg1:001",
                "claim_text": "same claim repeated",
                "grounds": ["source:a.md"],
                "source_consequence": "scope changes",
            },
            {
                "claim_id": "claim:seg1:002",
                "claim_text": "same claim repeated",
                "grounds": ["source:b.md"],
                "source_consequence": "scope changes",
            },
        ]
        inputs = extract_claims(claim_map=claim_map, source_consequence_map=[])
        assert len(inputs) == 1

    def test_metadata_includes_consequence_kind(self) -> None:
        claim_map = [
            {
                "claim_id": "claim:seg1:001",
                "claim_text": "test claim",
                "grounds": ["source:test.md"],
                "source_consequence": "scope narrowed",
            },
        ]
        source_consequence_map = [
            {
                "source_ref": "source:test.md",
                "claim_ids": ["claim:seg1:001"],
                "consequence_kind": "scope_confidence_or_action_delta",
            },
        ]
        inputs = extract_claims(
            claim_map=claim_map,
            source_consequence_map=source_consequence_map,
        )
        assert inputs[0].metadata["consequence_kind"] == "scope_confidence_or_action_delta"


def _mock_verdict(
    status: ConvergenceStatus, scores: dict[str, int | None] | None = None
) -> CouncilVerdict:
    return CouncilVerdict(
        scores=scores or {"evidence_adequacy": 4, "counter_evidence_resilience": 4},
        confidence_bands={"evidence_adequacy": (3, 5)},
        convergence_status=status,
        disagreement_log=[],
        research_findings=["checked source"],
        evidence_matrix=None,
        receipt={"input_hash": "test"},
    )


def _mock_claim(claim_id: str = "claim:seg1:001", text: str = "test claim") -> tuple:
    from agents.deliberative_council.models import CouncilInput

    return CouncilInput(
        text=text,
        source_ref="source:test.md",
        metadata={"claim_id": claim_id, "source_consequence": "scope"},
    )


class TestRunCouncilDisconfirmation:
    def test_bypass_when_disabled(self) -> None:
        with patch.dict("os.environ", {"HAPAX_COUNCIL_DISCONFIRMATION_ENABLED": "0"}):
            result = run_council_disconfirmation([_mock_claim()])
        assert result == []

    def test_empty_claims_returns_empty(self) -> None:
        result = run_council_disconfirmation([])
        assert result == []


class TestApplyCouncilVerdicts:
    def test_survived_claim_gets_receipt(self) -> None:
        claim = _mock_claim()
        verdict = _mock_verdict(ConvergenceStatus.CONVERGED, {"a": 4, "b": 5})
        result = apply_council_verdicts(
            [(claim, verdict)],
            source_consequence_map=[],
            claim_map=[{"claim_id": "claim:seg1:001", "grounds": ["source:test.md"]}],
        )
        assert "claim:seg1:001" in result["survived_claims"]
        assert result["council_disconfirmation_passed"] is True

    def test_contested_claim_updates_map(self) -> None:
        claim = _mock_claim()
        verdict = _mock_verdict(ConvergenceStatus.CONTESTED)
        result = apply_council_verdicts(
            [(claim, verdict)],
            source_consequence_map=[],
            claim_map=[{"claim_id": "claim:seg1:001", "grounds": ["source:test.md"]}],
        )
        assert "claim:seg1:001" in result["contested_claims"]
        assert len(result["updated_source_consequence_map"]) == 1
        assert (
            result["updated_source_consequence_map"][0]["consequence_kind"] == "council_contested"
        )

    def test_refuted_structural_triggers_no_candidate(self) -> None:
        claim = _mock_claim()
        verdict = _mock_verdict(ConvergenceStatus.CONVERGED, {"a": 1, "b": 1})
        result = apply_council_verdicts(
            [(claim, verdict)],
            source_consequence_map=[],
            claim_map=[{"claim_id": "claim:seg1:001", "grounds": ["source:a.md", "source:b.md"]}],
        )
        assert "claim:seg1:001" in result["refuted_claims"]
        assert result["no_candidate_triggered"] is True
        assert result["council_disconfirmation_passed"] is False

    def test_refuted_nonstructural_does_not_trigger_no_candidate(self) -> None:
        claim = _mock_claim()
        verdict = _mock_verdict(ConvergenceStatus.CONVERGED, {"a": 1, "b": 2})
        result = apply_council_verdicts(
            [(claim, verdict)],
            source_consequence_map=[],
            claim_map=[{"claim_id": "claim:seg1:001", "grounds": ["source:a.md"]}],
        )
        assert "claim:seg1:001" in result["refuted_claims"]
        assert result["no_candidate_triggered"] is False

    def test_source_consequence_map_additive(self) -> None:
        existing = [{"source_ref": "existing:ref", "claim_ids": ["old"]}]
        claim = _mock_claim()
        verdict = _mock_verdict(ConvergenceStatus.CONTESTED)
        result = apply_council_verdicts(
            [(claim, verdict)],
            source_consequence_map=existing,
            claim_map=[{"claim_id": "claim:seg1:001", "grounds": ["source:test.md"]}],
        )
        assert len(result["updated_source_consequence_map"]) == 2
        assert result["updated_source_consequence_map"][0]["source_ref"] == "existing:ref"
