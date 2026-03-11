"""Tests for the demo evaluation agent."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.demo_models import DemoEvalDimension, DemoEvalReport


class TestEvaluateDemoOutput:
    @pytest.mark.asyncio
    async def test_combines_all_categories(self, tmp_path):
        """Verify evaluate_demo_output combines structural, text, and visual results."""
        script = {"title": "Test", "audience": "family", "scenes": []}
        (tmp_path / "script.json").write_text(json.dumps(script))

        struct_dims = [
            DemoEvalDimension(name="files_present", category="structural", passed=True, score=1.0),
            DemoEvalDimension(
                name="metadata_correctness", category="structural", passed=True, score=1.0
            ),
            DemoEvalDimension(name="html_integrity", category="structural", passed=True, score=1.0),
        ]
        text_dims = [
            DemoEvalDimension(name="voice_consistency", category="text", passed=True, score=0.9),
            DemoEvalDimension(
                name="audience_calibration", category="text", passed=True, score=0.85
            ),
            DemoEvalDimension(name="duration_feasibility", category="text", passed=True, score=0.8),
            DemoEvalDimension(name="key_points_quality", category="text", passed=True, score=0.8),
            DemoEvalDimension(name="narrative_coherence", category="text", passed=True, score=0.9),
        ]
        visual_dims = [
            DemoEvalDimension(name="visual_clarity", category="visual", passed=True, score=0.85),
            DemoEvalDimension(name="visual_variety", category="visual", passed=True, score=0.8),
            DemoEvalDimension(name="theme_compliance", category="visual", passed=True, score=0.9),
            DemoEvalDimension(
                name="visual_narration_alignment", category="visual", passed=True, score=0.85
            ),
        ]

        with (
            patch(
                "agents.demo_pipeline.eval_rubrics.run_structural_checks", return_value=struct_dims
            ),
            patch(
                "agents.demo_pipeline.eval_rubrics.run_text_evaluation",
                new_callable=AsyncMock,
                return_value=text_dims,
            ),
            patch(
                "agents.demo_pipeline.eval_rubrics.run_visual_evaluation",
                new_callable=AsyncMock,
                return_value=visual_dims,
            ),
            patch("agents.demo_pipeline.narrative.load_style_guide", return_value={}),
            patch("agents.demo_pipeline.narrative.load_voice_examples", return_value={}),
        ):
            from agents.demo_eval import evaluate_demo_output

            report = await evaluate_demo_output(tmp_path, expected_audience="family")

        assert len(report.dimensions) == 12
        assert report.overall_pass is True
        assert report.overall_score > 0.8

    @pytest.mark.asyncio
    async def test_fails_on_structural_failure(self, tmp_path):
        """Even high text/visual scores fail if structural checks fail."""
        script = {"title": "Test", "audience": "family", "scenes": []}
        (tmp_path / "script.json").write_text(json.dumps(script))

        struct_dims = [
            DemoEvalDimension(
                name="files_present",
                category="structural",
                passed=False,
                score=0.0,
                issues=["Missing script.json"],
            ),
        ]
        text_dims = [
            DemoEvalDimension(name="voice_consistency", category="text", passed=True, score=0.95),
        ]
        visual_dims = [
            DemoEvalDimension(name="visual_clarity", category="visual", passed=True, score=0.95),
        ]

        with (
            patch(
                "agents.demo_pipeline.eval_rubrics.run_structural_checks", return_value=struct_dims
            ),
            patch(
                "agents.demo_pipeline.eval_rubrics.run_text_evaluation",
                new_callable=AsyncMock,
                return_value=text_dims,
            ),
            patch(
                "agents.demo_pipeline.eval_rubrics.run_visual_evaluation",
                new_callable=AsyncMock,
                return_value=visual_dims,
            ),
            patch("agents.demo_pipeline.narrative.load_style_guide", return_value={}),
            patch("agents.demo_pipeline.narrative.load_voice_examples", return_value={}),
        ):
            from agents.demo_eval import evaluate_demo_output

            report = await evaluate_demo_output(tmp_path)

        assert report.overall_pass is False


class TestRunEvalLoop:
    @pytest.mark.asyncio
    async def test_passes_on_first_iteration(self, tmp_path):
        """If evaluation passes immediately, no healing needed."""
        passing_report = DemoEvalReport(
            dimensions=[
                DemoEvalDimension(
                    name="files_present", category="structural", passed=True, score=1.0
                ),
            ],
            overall_pass=True,
            overall_score=0.9,
        )

        fake_demo_dir = tmp_path / "demo"
        fake_demo_dir.mkdir()
        (fake_demo_dir / "script.json").write_text('{"scenes":[]}')

        with (
            patch("agents.demo.generate_demo", new_callable=AsyncMock, return_value=fake_demo_dir),
            patch(
                "agents.demo_eval.evaluate_demo_output",
                new_callable=AsyncMock,
                return_value=passing_report,
            ),
            patch("agents.demo.parse_request", return_value=("the system", "my partner")),
            patch("agents.demo.resolve_audience", return_value=("family", "")),
            patch("agents.demo_models.load_personas", return_value={"family": MagicMock()}),
            patch("agents.demo.parse_duration", return_value=180),
            patch("agents.demo_pipeline.narrative.load_style_guide", return_value={}),
            patch("agents.demo_pipeline.lessons.load_lessons_for_archetype", return_value=[]),
            patch("agents.demo_pipeline.lessons.format_lessons_block", return_value=""),
        ):
            from agents.demo_eval import run_eval_loop

            result = await run_eval_loop(max_iterations=3)

        assert result.passed is True
        assert result.iterations == 1

    @pytest.mark.asyncio
    async def test_heals_on_second_iteration(self, tmp_path):
        """Fail first, diagnose, pass second."""
        failing_report = DemoEvalReport(
            dimensions=[
                DemoEvalDimension(
                    name="style",
                    category="text",
                    passed=False,
                    score=0.4,
                    issues=["Uses corporate jargon"],
                ),
            ],
            overall_pass=False,
            overall_score=0.4,
        )
        passing_report = DemoEvalReport(
            dimensions=[
                DemoEvalDimension(name="style", category="text", passed=True, score=0.9),
            ],
            overall_pass=True,
            overall_score=0.9,
        )

        eval_call_count = 0

        async def mock_evaluate(*args, **kwargs):
            nonlocal eval_call_count
            eval_call_count += 1
            return failing_report if eval_call_count == 1 else passing_report

        mock_diagnosis = MagicMock()
        mock_diagnosis.root_causes = ["Corporate jargon"]
        mock_diagnosis.planning_overrides = "AVOID: leverage, synergize"
        mock_diagnosis.adjustments_summary = ["Removed jargon"]

        fake_demo_dir = tmp_path / "demo"
        fake_demo_dir.mkdir()
        (fake_demo_dir / "script.json").write_text('{"scenes":[]}')

        with (
            patch("agents.demo.generate_demo", new_callable=AsyncMock, return_value=fake_demo_dir),
            patch("agents.demo_eval.evaluate_demo_output", side_effect=mock_evaluate),
            patch(
                "agents.demo_pipeline.eval_rubrics.diagnose_failures",
                new_callable=AsyncMock,
                return_value=mock_diagnosis,
            ),
            patch("agents.demo.parse_request", return_value=("the system", "my partner")),
            patch("agents.demo.resolve_audience", return_value=("family", "")),
            patch("agents.demo_models.load_personas", return_value={"family": MagicMock()}),
            patch("agents.demo.parse_duration", return_value=180),
            patch("agents.demo_pipeline.narrative.load_style_guide", return_value={}),
            patch("agents.demo_pipeline.lessons.load_lessons_for_archetype", return_value=[]),
            patch("agents.demo_pipeline.lessons.format_lessons_block", return_value=""),
            patch("agents.demo_pipeline.lessons.load_lessons", return_value={}),
            patch("agents.demo_pipeline.lessons.save_lessons"),
            patch(
                "agents.demo_pipeline.lessons.extract_lessons", return_value=["Use simple language"]
            ),
            patch("agents.demo_pipeline.lessons.accumulate_lessons", return_value={"family": []}),
        ):
            from agents.demo_eval import run_eval_loop

            result = await run_eval_loop(max_iterations=3)

        assert result.passed is True
        assert result.iterations == 2
        assert len(result.history) == 2
