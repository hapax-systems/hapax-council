"""Tests for CCTV rubric v2 calibration probe structure and scoring logic."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agents.deliberative_council.models import CouncilConfig, CouncilInput
from agents.deliberative_council.rubrics import DisconfirmationRubric
from scripts.cctv_rubric_v2_validation import (
    PROBES,
    _band_range,
    _score_in_band,
    _selected_probes,
    run_validation,
)


class TestProbeStructure:
    def test_ten_probes_defined(self) -> None:
        assert len(PROBES) == 10

    def test_band_distribution(self) -> None:
        bands = [p.expected_band for p in PROBES]
        assert bands.count("floor") == 5
        assert bands.count("weak") == 3
        assert bands.count("boundary") == 1
        assert bands.count("strong") == 1

    def test_all_probes_have_source_refs(self) -> None:
        for probe in PROBES:
            assert probe.source_ref, f"{probe.id} missing source_ref"

    def test_all_probes_have_expected_axis_notes(self) -> None:
        rubric = DisconfirmationRubric()
        axis_names = {a.name for a in rubric.axes}
        for probe in PROBES:
            assert probe.expected_axis_notes, f"{probe.id} missing notes"
            for axis in probe.expected_axis_notes:
                assert axis in axis_names, f"{probe.id}: unknown axis {axis}"

    def test_unique_probe_ids(self) -> None:
        ids = [p.id for p in PROBES]
        assert len(ids) == len(set(ids))

    def test_recalibrated_probe_band_decisions_are_recorded(self) -> None:
        recalibrated = {
            "weak_tangential_evidence": "floor",
            "weak_single_source_circular": "floor",
            "strong_multi_source_bounded": "boundary",
            "strong_counter_evidence_addressed": "weak",
        }
        probes = {probe.id: probe for probe in PROBES}
        for probe_id, expected_band in recalibrated.items():
            assert probes[probe_id].expected_band == expected_band
            assert "2026-05-18 focused rerun" in probes[probe_id].calibration_decision


class TestBandLogic:
    def test_floor_range(self) -> None:
        lo, hi = _band_range("floor")
        assert lo == 1.0
        assert hi == 2.4

    def test_weak_range(self) -> None:
        lo, hi = _band_range("weak")
        assert lo == 2.0
        assert hi == 3.4

    def test_boundary_range(self) -> None:
        lo, hi = _band_range("boundary")
        assert lo == 3.0
        assert hi == 3.9

    def test_strong_range(self) -> None:
        lo, hi = _band_range("strong")
        assert lo == 3.6
        assert hi == 5.0

    def test_score_in_floor_band(self) -> None:
        assert _score_in_band(1.5, "floor")
        assert not _score_in_band(3.0, "floor")

    def test_score_in_strong_band(self) -> None:
        assert _score_in_band(4.5, "strong")
        assert not _score_in_band(2.0, "strong")


class TestDisconfirmationRubricV2:
    def test_floor_examples_present(self) -> None:
        rubric = DisconfirmationRubric()
        axes_with_floor = [a for a in rubric.axes if a.floor_example]
        assert len(axes_with_floor) == 4, "Rubric v2 must anchor floor/mid boundaries on every axis"

    def test_version_marks_calibration_update(self) -> None:
        rubric = DisconfirmationRubric()
        assert rubric.version == 2
        assert "Use the full 1-5 scale" in rubric.instructions

    def test_four_axes(self) -> None:
        rubric = DisconfirmationRubric()
        assert len(rubric.axes) == 4
        names = {a.name for a in rubric.axes}
        assert names == {
            "evidence_adequacy",
            "counter_evidence_resilience",
            "scope_honesty",
            "falsifiability",
        }


class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_returns_all_probes(self) -> None:
        summary = await run_validation(dry_run=True)
        assert summary["probes_run"] == 10
        assert summary["probes_requested"] == [probe.id for probe in PROBES]
        assert all("calibration_decision" in r for r in summary["results"])
        assert all(r["dry_run"] for r in summary["results"])

    @pytest.mark.asyncio
    async def test_dry_run_can_filter_to_one_probe(self) -> None:
        summary = await run_validation(dry_run=True, probe_ids={"weak_tangential_evidence"})
        assert summary["probes_requested"] == ["weak_tangential_evidence"]
        assert summary["probes_run"] == 1

    def test_selected_probes_rejects_unknown_ids(self) -> None:
        with pytest.raises(ValueError, match="unknown probe id"):
            _selected_probes({"missing_probe"})


class TestScoringIntegration:
    @pytest.mark.asyncio
    async def test_floor_probe_scores_low_with_mock(self) -> None:
        # Phase 1 scoring is now provider-enforced structured output: the engine
        # expects a Phase1Output from the scoring call (output_type set) and text
        # from the investigate call. cc-task cctv-council-perfect-health-faillloud.
        from agents.deliberative_council.models import Phase1Output

        low_scores = Phase1Output(
            scores={
                "evidence_adequacy": 1,
                "counter_evidence_resilience": 1,
                "scope_honesty": 2,
                "falsifiability": 1,
            },
            rationale={
                "evidence_adequacy": "No evidence cited",
                "counter_evidence_resilience": "No counter-evidence addressed",
                "scope_honesty": "Unbounded claim",
                "falsifiability": "Unfalsifiable",
            },
            research_findings=["file not found"],
        )

        async def _mock_call(member, prompt, *, output_type=None, usage_limits=None):
            if output_type is None:  # investigate (research) call
                return "researched the claim", ["read_source(path) → File not found"], ""
            return low_scores, ["read_source(path) → File not found"], ""

        with patch("agents.deliberative_council.engine._call_member", _mock_call):
            from agents.deliberative_council.engine import run_phase1
            from agents.deliberative_council.rubrics import DisconfirmationRubric

            rubric = DisconfirmationRubric()
            config = CouncilConfig(phases=(1,), model_aliases=("opus", "balanced"))
            inp = CouncilInput(
                text=PROBES[0].text,
                source_ref=PROBES[0].source_ref,
            )
            results = await run_phase1(inp, rubric, config)
            assert len(results) == 2
            for r in results:
                assert r.scores["evidence_adequacy"] <= 2
