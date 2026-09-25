from __future__ import annotations

from unittest.mock import patch

import pytest

from agents.deliberative_council.models import ConvergenceStatus, CouncilInput, CouncilVerdict
from agents.deliberative_council.modes.disconfirmation import (
    DisconfirmationRecommendation,
    DisconfirmationVerdict,
    derive_recommendation,
    derive_verdict,
)
from agents.deliberative_council.rubrics import DisconfirmationRubric
from shared.segment_disconfirmation import (
    apply_council_verdicts,
    build_substance_gap_report,
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
        scores=scores
        if scores is not None
        else {"evidence_adequacy": 4, "counter_evidence_resilience": 4},
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
    @staticmethod
    def _assert_mode_and_segment_agree(
        verdict: CouncilVerdict,
        expected: DisconfirmationVerdict,
        claim: CouncilInput | None = None,
    ) -> dict:
        assert derive_verdict(verdict) == expected
        claim = claim if claim is not None else _mock_claim()
        claim_id = claim.metadata["claim_id"]
        result = apply_council_verdicts(
            [(claim, verdict)],
            source_consequence_map=[],
            claim_map=[{"claim_id": claim_id, "grounds": [claim.source_ref]}],
        )
        for disposition, key in (
            (DisconfirmationVerdict.SURVIVED, "survived_claims"),
            (DisconfirmationVerdict.CONTESTED, "contested_claims"),
            (DisconfirmationVerdict.REFUTED, "refuted_claims"),
            (DisconfirmationVerdict.INSUFFICIENT_EVIDENCE, "degraded_claims"),
        ):
            assert result[key] == ([claim_id] if expected == disposition else [])
        assert result["council_disconfirmation_passed"] is (
            expected in (DisconfirmationVerdict.SURVIVED, DisconfirmationVerdict.CONTESTED)
        )
        assert result["council_degraded"] is (
            expected == DisconfirmationVerdict.INSUFFICIENT_EVIDENCE
        )
        assert result["no_candidate_triggered"] is False
        return result

    @pytest.mark.parametrize(
        ("scores", "expected"),
        [
            pytest.param([1, 5, 5, 5], DisconfirmationVerdict.REFUTED, id="one_low"),
            pytest.param([3, 3, 3, 3], DisconfirmationVerdict.CONTESTED, id="all_middle"),
            pytest.param([1, 1, 1, 1], DisconfirmationVerdict.REFUTED, id="all_low"),
            pytest.param([5, 5, 5, 5], DisconfirmationVerdict.SURVIVED, id="all_high"),
        ],
    )
    def test_finite_counterexample_consumers_agree(
        self, scores: list[int], expected: DisconfirmationVerdict
    ) -> None:
        """Root's four controlled score cases exercise both actual consumers.

        The finite counterexample is checked locally; these synthetic scores
        make no claim about calibration, live incidence, or model ability.
        """
        domain = [1, 2, 3]
        counterexample = 1
        assert counterexample in domain and counterexample % 2 != 0
        claim = CouncilInput(
            text="Every integer in the finite set {1, 2, 3} is even.",
            source_ref="synthetic:finite-set",
            metadata={"claim_id": "synthetic:claim"},
        )
        axes = [axis.name for axis in DisconfirmationRubric().axes]
        verdict = CouncilVerdict(
            scores=dict(zip(axes, scores, strict=True)),
            confidence_bands={
                axis: (score, score) for axis, score in zip(axes, scores, strict=True)
            },
            convergence_status=ConvergenceStatus.CONVERGED,
            disagreement_log=[],
            research_findings=["Counterexample certificate: 1 is in the set and 1 modulo 2 is 1."],
            evidence_matrix=None,
        )
        result = self._assert_mode_and_segment_agree(verdict, expected, claim)
        if expected == DisconfirmationVerdict.CONTESTED:
            assert derive_recommendation(expected) == DisconfirmationRecommendation.NARROW
            assert result["updated_source_consequence_map"] == [
                {
                    "source_ref": claim.source_ref,
                    "claim_ids": ["synthetic:claim"],
                    "consequence_kind": "council_contested",
                    "changed_field": "qualifier_narrowed",
                    "failure_if_missing": "council found disagreement on this claim",
                    "council_disagreement_log": verdict.disagreement_log,
                    "council_research_findings": verdict.research_findings,
                }
            ]
        else:
            assert result["updated_source_consequence_map"] == []

    @pytest.mark.parametrize(
        ("scores", "expected"),
        [
            pytest.param({"a": None, "b": 1, "c": 5}, DisconfirmationVerdict.REFUTED, id="low"),
            pytest.param(
                {"a": None, "b": 3, "c": 5}, DisconfirmationVerdict.CONTESTED, id="neutral"
            ),
            pytest.param({"a": None, "b": 4, "c": 5}, DisconfirmationVerdict.SURVIVED, id="high"),
        ],
    )
    def test_none_axis_is_ignored_among_valid_scores(
        self, scores: dict[str, int | None], expected: DisconfirmationVerdict
    ) -> None:
        """The mode ignores None axes and classifies only the remaining scores."""
        self._assert_mode_and_segment_agree(
            _mock_verdict(ConvergenceStatus.CONVERGED, scores), expected
        )

    @pytest.mark.parametrize("scores", [{}, {"a": None, "b": None}], ids=["empty", "all_none"])
    def test_no_valid_scores_is_insufficient(self, scores: dict[str, int | None]) -> None:
        """Even execution convergence cannot supply missing evidence."""
        self._assert_mode_and_segment_agree(
            _mock_verdict(ConvergenceStatus.CONVERGED, scores),
            DisconfirmationVerdict.INSUFFICIENT_EVIDENCE,
        )

    @pytest.mark.parametrize("status", [ConvergenceStatus.REFUSED, ConvergenceStatus.HUNG])
    @pytest.mark.parametrize("scores", [{"a": 1, "b": 5}, {"a": 5, "b": 5}], ids=["mixed", "high"])
    def test_refused_or_hung_with_scores_is_insufficient(
        self, status: ConvergenceStatus, scores: dict[str, int]
    ) -> None:
        """HUNG with real scores previously meant contested-pass; now it degrades.

        REFUSED panels also remain insufficient regardless of partial scores.
        """
        self._assert_mode_and_segment_agree(
            _mock_verdict(status, scores), DisconfirmationVerdict.INSUFFICIENT_EVIDENCE
        )

    @pytest.mark.parametrize(
        ("scores", "expected"),
        [
            pytest.param({"a": 2, "b": 5}, DisconfirmationVerdict.REFUTED, id="low"),
            pytest.param({"a": 3, "b": 5}, DisconfirmationVerdict.CONTESTED, id="neutral"),
            pytest.param({"a": 4, "b": 5}, DisconfirmationVerdict.SURVIVED, id="high"),
        ],
    )
    def test_contested_execution_uses_mode_disposition(
        self, scores: dict[str, int], expected: DisconfirmationVerdict
    ) -> None:
        """Execution disagreement does not prescribe evidentiary disposition."""
        self._assert_mode_and_segment_agree(
            _mock_verdict(ConvergenceStatus.CONTESTED, scores), expected
        )

    def test_council_unavailable_overrides_mode_disposition(self) -> None:
        """R-A4: unavailable takes precedence even over otherwise surviving scores."""
        claim = _mock_claim()
        verdict = _mock_verdict(ConvergenceStatus.CONVERGED, {"a": 5, "b": 5})
        self._assert_mode_and_segment_agree(verdict, DisconfirmationVerdict.SURVIVED, claim)
        unavailable = verdict.model_copy(update={"receipt": {"council_unavailable": True}})
        assert derive_verdict(unavailable) == DisconfirmationVerdict.SURVIVED
        with patch("shared.segment_disconfirmation.derive_verdict") as derive:
            result = apply_council_verdicts(
                [(claim, unavailable)],
                source_consequence_map=[],
                claim_map=[{"claim_id": "claim:seg1:001", "grounds": ["source:test.md"]}],
            )
        derive.assert_not_called()
        assert result["degraded_claims"] == ["claim:seg1:001"]
        assert result["survived_claims"] == []
        assert result["contested_claims"] == []
        assert result["refuted_claims"] == []
        assert result["council_degraded"] is True
        assert result["council_disconfirmation_passed"] is False
        assert result["no_candidate_triggered"] is False
        assert result["updated_source_consequence_map"] == []

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
        """Previously pinned contested execution with high scores as contested.

        Neutral evidence now supplies the contested disposition from the mode.
        """
        claim = _mock_claim()
        verdict = _mock_verdict(ConvergenceStatus.CONTESTED, {"a": 3, "b": 3})
        verdict.disagreement_log.append("Source coverage remains disputed")
        assert derive_verdict(verdict) == DisconfirmationVerdict.CONTESTED
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
        entry = result["updated_source_consequence_map"][0]
        assert entry["council_disagreement_log"] == verdict.disagreement_log
        assert entry["council_research_findings"] == verdict.research_findings

    def test_refuted_structural_triggers_no_candidate(self) -> None:
        """Previously exercised only the all-low rule; one low axis now refutes."""
        claim = _mock_claim()
        verdict = _mock_verdict(ConvergenceStatus.CONVERGED, {"a": 1, "b": 5})
        assert derive_verdict(verdict) == DisconfirmationVerdict.REFUTED
        result = apply_council_verdicts(
            [(claim, verdict)],
            source_consequence_map=[],
            claim_map=[{"claim_id": "claim:seg1:001", "grounds": ["source:a.md", "source:b.md"]}],
        )
        assert "claim:seg1:001" in result["refuted_claims"]
        assert result["no_candidate_triggered"] is True
        assert result["council_disconfirmation_passed"] is False

    def test_refuted_nonstructural_does_not_trigger_no_candidate(self) -> None:
        """Previously exercised only the all-low rule; the ceiling is per axis."""
        claim = _mock_claim()
        verdict = _mock_verdict(ConvergenceStatus.CONVERGED, {"a": 5, "b": 2})
        assert derive_verdict(verdict) == DisconfirmationVerdict.REFUTED
        result = apply_council_verdicts(
            [(claim, verdict)],
            source_consequence_map=[],
            claim_map=[{"claim_id": "claim:seg1:001", "grounds": ["source:a.md"]}],
        )
        assert "claim:seg1:001" in result["refuted_claims"]
        assert result["no_candidate_triggered"] is False
        assert result["council_disconfirmation_passed"] is False

    def test_source_consequence_map_additive(self) -> None:
        """Previously pinned high scores as contested from execution status alone."""
        existing = [{"source_ref": "existing:ref", "claim_ids": ["old"]}]
        claim = _mock_claim()
        verdict = _mock_verdict(ConvergenceStatus.CONTESTED, {"a": 3, "b": 3})
        assert derive_verdict(verdict) == DisconfirmationVerdict.CONTESTED
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


class TestSubstanceGapReport:
    @pytest.mark.parametrize(
        ("status", "scores", "expected"),
        [
            pytest.param(
                ConvergenceStatus.CONVERGED,
                [1, 5, 5, 5],
                DisconfirmationVerdict.REFUTED,
                id="mixed",
            ),
            pytest.param(
                ConvergenceStatus.CONVERGED,
                [],
                DisconfirmationVerdict.INSUFFICIENT_EVIDENCE,
                id="empty",
            ),
            pytest.param(
                ConvergenceStatus.CONVERGED,
                [None, None, None, None],
                DisconfirmationVerdict.INSUFFICIENT_EVIDENCE,
                id="all_none",
            ),
            pytest.param(
                ConvergenceStatus.CONVERGED,
                [5, None, None],
                DisconfirmationVerdict.SURVIVED,
                id="partial_high",
            ),
            pytest.param(
                ConvergenceStatus.HUNG,
                [1, 1, 1, 1],
                DisconfirmationVerdict.INSUFFICIENT_EVIDENCE,
                id="hung_low",
            ),
            pytest.param(
                ConvergenceStatus.REFUSED,
                [1, 1, 1, 1],
                DisconfirmationVerdict.INSUFFICIENT_EVIDENCE,
                id="refused_low",
            ),
            pytest.param(
                ConvergenceStatus.CONVERGED,
                [1, 1, 1, 1],
                DisconfirmationVerdict.REFUTED,
                id="all_low",
            ),
            pytest.param(
                ConvergenceStatus.CONVERGED,
                [1, None, None],
                DisconfirmationVerdict.REFUTED,
                id="partial_low",
            ),
            pytest.param(
                ConvergenceStatus.CONVERGED,
                [3, 3, 3, 3],
                DisconfirmationVerdict.CONTESTED,
                id="neutral",
            ),
        ],
    )
    def test_disposition_and_report_agree(
        self,
        status: ConvergenceStatus,
        scores: list[int | None],
        expected: DisconfirmationVerdict,
    ) -> None:
        claim = _mock_claim("synthetic:claim", "A synthetic structural claim.")
        grounds = ["synthetic:source", "synthetic:other"]
        claim_map = [{"claim_id": "synthetic:claim", "grounds": grounds}]
        axes = [axis.name for axis in DisconfirmationRubric().axes][: len(scores)]
        verdict = _mock_verdict(status, dict(zip(axes, scores, strict=True)))
        verdict.disagreement_log.append("Counterexample found in the cited source.")
        verdicts = [(claim, verdict)]

        assert derive_verdict(verdict) == expected
        result = apply_council_verdicts(verdicts, [], claim_map)
        for disposition, key in (
            (DisconfirmationVerdict.SURVIVED, "survived_claims"),
            (DisconfirmationVerdict.CONTESTED, "contested_claims"),
            (DisconfirmationVerdict.REFUTED, "refuted_claims"),
            (DisconfirmationVerdict.INSUFFICIENT_EVIDENCE, "degraded_claims"),
        ):
            assert result[key] == (["synthetic:claim"] if expected == disposition else [])
        assert result["no_candidate_triggered"] is (expected == DisconfirmationVerdict.REFUTED)
        assert result["council_degraded"] is (
            expected == DisconfirmationVerdict.INSUFFICIENT_EVIDENCE
        )
        assert result["council_disconfirmation_passed"] is (
            expected in (DisconfirmationVerdict.SURVIVED, DisconfirmationVerdict.CONTESTED)
        )

        report = build_substance_gap_report(verdicts, claim_map)
        lines = report.splitlines()
        assert [line for line in lines if line.startswith("### REFUTED:")] == [
            f"### REFUTED: {claim_id}" for claim_id in result["refuted_claims"]
        ]
        assert lines[0] == "## Substance Gap Report (Council Disconfirmation)"
        assert lines[-1] == "The composer should find stronger evidence or reframe these claims."
        if expected == DisconfirmationVerdict.REFUTED:
            assert f"Claim: {claim.text}" in lines
            assert f"Scores: {verdict.scores}" in lines
            assert f"Council notes: {verdict.disagreement_log[0]}" in lines
            assert f"Research: {verdict.research_findings[0]}" in lines
            weak_sources = next(line for line in lines if line.startswith("### Weak sources:"))
            assert set(weak_sources.removeprefix("### Weak sources: ").split(", ")) == set(grounds)
            assert "### Summary: 1 claims refuted." in lines
        else:
            assert "synthetic:claim" not in report
            assert "Claim:" not in report
            assert "Scores:" not in report
            assert "Council notes:" not in report
            assert "Research:" not in report
            assert "### Weak sources:" not in report
            assert "### Summary: 0 claims refuted." in lines

    @pytest.mark.parametrize("refuted_count", [1, 3], ids=["structural_feedback", "repair"])
    @pytest.mark.parametrize(
        ("status", "scores"),
        [(ConvergenceStatus.CONVERGED, {}), (ConvergenceStatus.HUNG, {"a": 1})],
        ids=["empty", "hung_low"],
    )
    def test_triggered_report_excludes_insufficient_claim(
        self, refuted_count: int, status: ConvergenceStatus, scores: dict[str, int]
    ) -> None:
        """Both caller triggers consume the report built from ALL verdicts."""
        verdicts = []
        claim_map = []
        refuted_ids = [f"synthetic:refuted:{i}" for i in range(refuted_count)]
        for claim_id in refuted_ids:
            claim = _mock_claim(claim_id, f"Refuted claim {claim_id}.")
            verdicts.append((claim, _mock_verdict(ConvergenceStatus.CONVERGED, {"a": 1})))
            grounds = [f"synthetic:source:{claim_id}"]
            if refuted_count == 1:
                grounds.append("synthetic:structural-source")
            claim_map.append({"claim_id": claim_id, "grounds": grounds})
        insufficient = _mock_claim("synthetic:insufficient", "Undetermined claim text.")
        verdict = _mock_verdict(status, scores)
        verdict.disagreement_log.append("Undetermined council note.")
        verdict.research_findings[:] = ["Undetermined research finding."]
        verdicts.append((insufficient, verdict))
        claim_map.append(
            {"claim_id": "synthetic:insufficient", "grounds": ["synthetic:undetermined-source"]}
        )

        result = apply_council_verdicts(verdicts, [], claim_map)
        assert result["refuted_claims"] == refuted_ids
        assert result["degraded_claims"] == ["synthetic:insufficient"]
        assert result["survived_claims"] == []
        assert result["contested_claims"] == []
        assert result["council_disconfirmation_passed"] is False
        assert result["council_degraded"] is True
        assert result["no_candidate_triggered"] is (refuted_count == 1)
        assert result["no_candidate_triggered"] or len(result["refuted_claims"]) > 2

        report = build_substance_gap_report(verdicts, claim_map)
        lines = report.splitlines()
        assert [line for line in lines if line.startswith("### REFUTED:")] == [
            f"### REFUTED: {claim_id}" for claim_id in refuted_ids
        ]
        assert f"### Summary: {refuted_count} claims refuted." in lines
        assert "synthetic:insufficient" not in report
        assert insufficient.text not in report
        assert verdict.disagreement_log[0] not in report
        assert verdict.research_findings[0] not in report
        assert "synthetic:undetermined-source" not in report

    @pytest.mark.parametrize(
        ("status", "scores"),
        [(ConvergenceStatus.CONVERGED, {"a": 1}), (ConvergenceStatus.HUNG, {})],
        ids=["otherwise_refuted", "otherwise_insufficient"],
    )
    def test_unavailable_precedes_report_disposition(
        self, status: ConvergenceStatus, scores: dict[str, int]
    ) -> None:
        claim = _mock_claim("synthetic:unavailable", "Unavailable claim text.")
        verdict = _mock_verdict(status, scores)
        verdict.receipt["council_unavailable"] = True
        claim_map = [
            {"claim_id": "synthetic:unavailable", "grounds": ["synthetic:a", "synthetic:b"]}
        ]
        with patch("shared.segment_disconfirmation.derive_verdict", wraps=derive_verdict) as derive:
            result = apply_council_verdicts([(claim, verdict)], [], claim_map)
            report = build_substance_gap_report([(claim, verdict)], claim_map)
        derive.assert_not_called()
        assert result["degraded_claims"] == ["synthetic:unavailable"]
        assert result["refuted_claims"] == []
        assert result["survived_claims"] == []
        assert result["contested_claims"] == []
        assert result["council_disconfirmation_passed"] is False
        assert result["council_degraded"] is True
        assert result["no_candidate_triggered"] is False
        assert report == (
            "## Substance Gap Report (Council Disconfirmation)\n\n"
            "### Summary: 0 claims refuted.\n"
            "The composer should find stronger evidence or reframe these claims."
        )
