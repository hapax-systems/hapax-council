"""Tests for demo evaluation data models."""
import pytest
from agents.demo_models import DemoEvalDimension, DemoEvalReport, DemoEvalResult


class TestDemoEvalDimension:
    def test_basic_creation(self):
        dim = DemoEvalDimension(
            name="voice_consistency", category="text", passed=True, score=0.9
        )
        assert dim.name == "voice_consistency"
        assert dim.category == "text"
        assert dim.passed is True

    def test_with_issues(self):
        dim = DemoEvalDimension(
            name="visual_clarity",
            category="visual",
            passed=False,
            score=0.3,
            issues=["Screenshot shows loading spinner", "Text too small to read"],
            evidence="Scene 2 screenshot captured during page load",
        )
        assert len(dim.issues) == 2
        assert dim.evidence is not None

    def test_score_bounds(self):
        with pytest.raises(Exception):
            DemoEvalDimension(name="x", category="text", passed=True, score=1.5)


class TestDemoEvalReport:
    def test_passing_report(self):
        dims = [
            DemoEvalDimension(name="style", category="text", passed=True, score=0.9),
            DemoEvalDimension(
                name="clarity", category="visual", passed=True, score=0.8
            ),
        ]
        report = DemoEvalReport(
            dimensions=dims,
            overall_pass=True,
            overall_score=0.85,
            iteration=1,
        )
        assert report.overall_pass is True
        assert report.iteration == 1

    def test_with_adjustments(self):
        report = DemoEvalReport(
            dimensions=[],
            overall_pass=False,
            overall_score=0.4,
            iteration=2,
            adjustments_applied=["Added explicit style avoidance list"],
        )
        assert len(report.adjustments_applied) == 1


class TestDemoEvalResult:
    def test_successful_result(self):
        report = DemoEvalReport(
            dimensions=[],
            overall_pass=True,
            overall_score=0.9,
            iteration=1,
        )
        result = DemoEvalResult(
            scenario="the system for my wife",
            passed=True,
            iterations=1,
            final_report=report,
            demo_dir="/tmp/demo",
            total_duration_seconds=45.0,
        )
        assert result.passed is True
        assert result.iterations == 1

    def test_with_history(self):
        r1 = DemoEvalReport(
            dimensions=[], overall_pass=False, overall_score=0.4, iteration=1
        )
        r2 = DemoEvalReport(
            dimensions=[], overall_pass=True, overall_score=0.85, iteration=2
        )
        result = DemoEvalResult(
            scenario="test",
            passed=True,
            iterations=2,
            final_report=r2,
            history=[r1, r2],
            demo_dir="/tmp/demo",
        )
        assert len(result.history) == 2
