"""Tests for extended demo models and duration parsing."""

import pytest

from agents.demo_models import DemoQualityReport, DemoScene, QualityDimension, ScreenshotSpec


class TestDemoSceneExtended:
    def test_visual_type_default(self):
        scene = DemoScene(
            title="Test",
            narration="test",
            duration_hint=5.0,
            screenshot=ScreenshotSpec(url="http://localhost"),
        )
        assert scene.visual_type == "screenshot"
        assert scene.diagram_spec is None
        assert scene.research_notes is None

    def test_visual_type_diagram(self):
        scene = DemoScene(
            title="Architecture",
            narration="test",
            duration_hint=8.0,
            screenshot=ScreenshotSpec(url="http://localhost"),
            visual_type="diagram",
            diagram_spec="direction: right\nA -> B -> C",
        )
        assert scene.visual_type == "diagram"
        assert scene.diagram_spec is not None

    def test_backward_compatible_serialization(self):
        """Old scripts without new fields still parse."""
        data = {
            "title": "Test",
            "narration": "test",
            "duration_hint": 5.0,
            "screenshot": {"url": "http://localhost"},
        }
        scene = DemoScene.model_validate(data)
        assert scene.visual_type == "screenshot"


class TestQualityReport:
    def test_all_pass(self):
        report = DemoQualityReport(
            dimensions=[QualityDimension(name="narrative", passed=True)],
            overall_pass=True,
        )
        assert report.overall_pass

    def test_failure(self):
        report = DemoQualityReport(
            dimensions=[
                QualityDimension(
                    name="style", passed=False, severity="critical", issues=["Corporatism detected"]
                ),
            ],
            overall_pass=False,
            revision_notes="Fix corporate language",
        )
        assert not report.overall_pass


class TestIllustrationSpec:
    def test_illustration_spec_defaults(self):
        from agents.demo_models import IllustrationSpec

        spec = IllustrationSpec(prompt="A warm sunrise over connected systems")
        assert spec.aspect_ratio == "16:9"
        assert "text" in spec.negative_prompt
        assert spec.style == ""

    def test_illustration_spec_with_style(self):
        from agents.demo_models import IllustrationSpec

        spec = IllustrationSpec(
            prompt="Neural pathways forming a network",
            style="warm minimal illustration, soft colors",
        )
        assert spec.style == "warm minimal illustration, soft colors"

    def test_scene_with_illustration_type(self):
        from agents.demo_models import DemoScene, IllustrationSpec

        scene = DemoScene(
            title="Why I Built This",
            narration="x " * 60,
            duration_hint=30.0,
            visual_type="illustration",
            illustration=IllustrationSpec(
                prompt="A person surrounded by helpful autonomous agents"
            ),
        )
        assert scene.visual_type == "illustration"
        assert scene.illustration is not None

    def test_skeleton_accepts_illustration_type(self):
        from agents.demo_models import IllustrationSpec, SceneSkeleton

        skel = SceneSkeleton(
            title="Motivation",
            facts=["Built for personal productivity"],
            visual_type="illustration",
            visual_brief="Conceptual image of cognitive support",
            illustration=IllustrationSpec(prompt="Abstract cognitive support"),
        )
        assert skel.visual_type == "illustration"


_has_playwright = True
try:
    import playwright  # noqa: F401
except ImportError:
    _has_playwright = False


@pytest.mark.skipif(not _has_playwright, reason="playwright not installed")
class TestParseDuration:
    def test_minutes(self):
        from agents.demo import parse_duration

        assert parse_duration("5m", "family") == 300

    def test_seconds(self):
        from agents.demo import parse_duration

        assert parse_duration("90s", "family") == 90

    def test_audience_default_family(self):
        from agents.demo import parse_duration

        assert parse_duration(None, "family") == 180

    def test_audience_default_peers(self):
        from agents.demo import parse_duration

        assert parse_duration(None, "technical-peer") == 720

    def test_bare_number(self):
        from agents.demo import parse_duration

        assert parse_duration("300", "family") == 300
