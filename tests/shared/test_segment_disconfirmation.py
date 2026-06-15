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

    def test_resolves_src_handles_to_real_refs_and_surfaces_context(self) -> None:
        # src:N handles are Hapax-internal and the council cannot dereference them
        # (read_source("src:0") -> File not found -> research-timeout cascade).
        # extract_claims must resolve them to real refs AND surface the recruited
        # source TEXT as source_context (verified diagnosis 2026-06-14).
        claim_map = [
            {
                "claim_id": "claim:seg1:001",
                "claim_text": "the launch claim changes once the source is visible",
                "grounds": ["src:0", "src:1"],
                "source_consequence": "ranking changes",
            },
        ]
        source_handles = {
            "src:0": ("qdrant:documents:launch-receipts.md", "Receipt body A."),
            "src:1": ("qdrant:documents:source-policy.md", "Policy body B."),
        }
        inputs = extract_claims(
            claim_map=claim_map,
            source_consequence_map=[],
            source_handles=source_handles,
        )
        assert len(inputs) == 1
        inp = inputs[0]
        # primary ground resolved to the real ref (not the bare handle)
        assert inp.source_ref == "qdrant:documents:launch-receipts.md"
        assert "src:0" not in inp.source_ref
        # the actual source TEXT is surfaced so the council judges real material
        assert "Receipt body A." in inp.source_context
        assert "Policy body B." in inp.source_context
        # all_grounds are resolved too — no handle leaks into the council
        assert inp.metadata["all_grounds"] == [
            "qdrant:documents:launch-receipts.md",
            "qdrant:documents:source-policy.md",
        ]

    def test_unmapped_handle_passes_through_without_context(self) -> None:
        claim_map = [
            {
                "claim_id": "claim:seg1:001",
                "claim_text": "a claim citing an unknown handle",
                "grounds": ["src:99"],
                "source_consequence": "scope changes",
            },
        ]
        inputs = extract_claims(
            claim_map=claim_map, source_consequence_map=[], source_handles={"src:0": ("r", "t")}
        )
        assert len(inputs) == 1
        assert inputs[0].source_ref == "src:99"  # unchanged when unmapped
        assert inputs[0].source_context == ""  # no snippet available

    def test_backward_compatible_without_source_handles(self) -> None:
        claim_map = [
            {
                "claim_id": "claim:seg1:001",
                "claim_text": "a grounded claim",
                "grounds": ["source:real/path.md"],
                "source_consequence": "scope changes",
            },
        ]
        inputs = extract_claims(claim_map=claim_map, source_consequence_map=[])
        assert inputs[0].source_ref == "source:real/path.md"
        assert inputs[0].source_context == ""
        assert inputs[0].metadata["all_grounds"] == ["source:real/path.md"]

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

    def test_council_unavailable_marks_degraded_not_passed(self) -> None:
        """R-A4: a fallback (council_unavailable) verdict must NOT be counted as
        a survival and must NOT report council_disconfirmation_passed=True. A
        degraded council is recorded, never silently passed open."""
        claim = _mock_claim()
        fallback = CouncilVerdict(
            scores={},
            confidence_bands={},
            convergence_status=ConvergenceStatus.HUNG,
            disagreement_log=["Council unavailable: boom"],
            research_findings=[],
            evidence_matrix=None,
            receipt={"council_unavailable": True, "error": "boom"},
        )
        result = apply_council_verdicts(
            [(claim, fallback)],
            source_consequence_map=[],
            claim_map=[{"claim_id": "claim:seg1:001", "grounds": ["source:test.md"]}],
        )
        assert result["council_disconfirmation_passed"] is False
        assert result["council_degraded"] is True
        assert "claim:seg1:001" not in result["survived_claims"]
        assert "claim:seg1:001" in result["degraded_claims"]

    def test_real_survival_is_not_degraded(self) -> None:
        """R-A4: a genuine converged survival still passes and is not degraded."""
        claim = _mock_claim()
        verdict = _mock_verdict(ConvergenceStatus.CONVERGED, {"a": 4, "b": 5})
        result = apply_council_verdicts(
            [(claim, verdict)],
            source_consequence_map=[],
            claim_map=[{"claim_id": "claim:seg1:001", "grounds": ["source:test.md"]}],
        )
        assert result["council_disconfirmation_passed"] is True
        assert result["council_degraded"] is False
        assert result["degraded_claims"] == []
