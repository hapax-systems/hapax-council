"""Tests for demo evaluation structural rubrics."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image
from pydantic_ai.messages import BinaryContent

from agents.demo_models import DemoEvalDimension
from agents.demo_pipeline.eval_rubrics import (
    DiagnosisOutput,
    DimScore,
    TextEvalOutput,
    VisualEvalOutput,
    _build_diagnosis_prompt,
    _build_text_eval_prompt,
    _build_visual_eval_prompt,
    _load_screenshots_as_content,
    check_files_present,
    check_html_integrity,
    check_metadata_correctness,
    diagnose_failures,
    run_structural_checks,
    run_text_evaluation,
    run_visual_evaluation,
)


def _make_demo_dir(tmp_path: Path, scenes: int = 3) -> Path:
    """Create a minimal demo output directory for testing."""
    demo_dir = tmp_path / "demo"
    demo_dir.mkdir()
    screenshots_dir = demo_dir / "screenshots"
    screenshots_dir.mkdir()

    script = {
        "title": "Test Demo",
        "audience": "family",
        "scenes": [
            {
                "title": f"Scene {i}",
                "narration": f"Narration {i}",
                "duration_hint": 10.0,
                "key_points": [f"Point {i}"],
                "screenshot": {"url": "http://localhost:5173"},
            }
            for i in range(1, scenes + 1)
        ],
        "intro_narration": "Welcome.",
        "outro_narration": "Done.",
    }
    (demo_dir / "script.json").write_text(json.dumps(script))

    metadata = {
        "title": "Test Demo",
        "audience": "family",
        "scope": "the system",
        "scenes": scenes,
        "format": "slides",
        "duration": 30.0,
        "timestamp": "20260305-120000",
        "output_dir": str(demo_dir),
        "primary_file": "demo.html",
        "has_video": False,
        "has_audio": False,
        "target_duration": 180,
        "quality_pass": True,
        "narrative_framework": "guided-tour",
    }
    (demo_dir / "metadata.json").write_text(json.dumps(metadata))

    for i in range(1, scenes + 1):
        img = Image.new("RGB", (1920, 1080), color=(40, 40, 40))
        img.save(screenshots_dir / f"{i:02d}-scene-{i}.png")

    html = f"""<!DOCTYPE html>
<html><body style="background:#282828;color:#ebdbb2">
<div id="app">{"".join(f'<div class="slide">{s["title"]}</div>' for s in script["scenes"])}
<img src="data:image/png;base64,iVBOR"/>
<button>play</button>
</div></body></html>"""
    (demo_dir / "demo.html").write_text(html)

    return demo_dir


class TestCheckFilesPresent:
    def test_all_present(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path)
        result = check_files_present(demo_dir)
        assert result.passed is True
        assert result.score == 1.0

    def test_missing_script(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path)
        (demo_dir / "script.json").unlink()
        result = check_files_present(demo_dir)
        assert result.passed is False
        assert "script.json" in result.issues[0]

    def test_missing_screenshots(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path)
        for p in (demo_dir / "screenshots").glob("*.png"):
            p.unlink()
        result = check_files_present(demo_dir)
        assert result.passed is False

    def test_insufficient_screenshots(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path, scenes=5)
        pngs = sorted((demo_dir / "screenshots").glob("*.png"))
        for p in pngs[2:]:
            p.unlink()
        result = check_files_present(demo_dir)
        assert result.passed is False
        assert "Only 2 screenshots for 5 scenes" in result.issues[0]


class TestCheckMetadataCorrectness:
    def test_correct_metadata(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path)
        result = check_metadata_correctness(demo_dir, expected_audience="family")
        assert result.passed is True

    def test_audience_mismatch(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path)
        result = check_metadata_correctness(demo_dir, expected_audience="leadership")
        assert result.passed is False
        assert "Audience mismatch" in result.issues[0]

    def test_missing_metadata_file(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path)
        (demo_dir / "metadata.json").unlink()
        result = check_metadata_correctness(demo_dir)
        assert result.passed is False

    def test_quality_pass_false_not_penalized(self, tmp_path):
        """quality_pass is pipeline-internal, should not penalize eval."""
        demo_dir = _make_demo_dir(tmp_path)
        meta = json.loads((demo_dir / "metadata.json").read_text())
        meta["quality_pass"] = False
        (demo_dir / "metadata.json").write_text(json.dumps(meta))
        result = check_metadata_correctness(demo_dir)
        assert result.passed is True  # Not penalized


class TestCheckHtmlIntegrity:
    def test_valid_html(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path)
        result = check_html_integrity(demo_dir)
        assert result.passed is True

    def test_missing_base64_images(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path)
        (demo_dir / "demo.html").write_text("<html><body>#282828</body></html>")
        result = check_html_integrity(demo_dir)
        assert result.passed is False
        assert any("base64" in i for i in result.issues)

    def test_missing_html(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path)
        (demo_dir / "demo.html").unlink()
        result = check_html_integrity(demo_dir)
        assert result.passed is False


class TestRunStructuralChecks:
    def test_all_pass(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path)
        results = run_structural_checks(demo_dir, expected_audience="family")
        assert len(results) == 3
        assert all(r.passed for r in results)
        assert all(r.category == "structural" for r in results)


class TestBuildTextEvalPrompt:
    def test_includes_narration(self):
        script_data = {
            "audience": "family",
            "intro_narration": "Welcome to the system.",
            "outro_narration": "That's how it works.",
            "scenes": [
                {"title": "Scene 1", "narration": "This is scene one.", "key_points": ["Point A"]},
            ],
        }
        style_guide = {
            "voice": "first-person",
            "avoid": ["leverage"],
            "embrace": ["concrete numbers"],
        }
        prompt = _build_text_eval_prompt(script_data, style_guide, 180)
        assert "Welcome to the system" in prompt
        assert "scene one" in prompt
        assert "leverage" in prompt
        assert "180 seconds" in prompt

    def test_word_count_calculation(self):
        script_data = {
            "audience": "family",
            "intro_narration": "One two three",
            "outro_narration": "Four five",
            "scenes": [{"title": "S1", "narration": "Six seven eight nine ten", "key_points": []}],
        }
        prompt = _build_text_eval_prompt(script_data, {}, 60)
        assert "Total word count: 10" in prompt


class TestRunTextEvaluation:
    @pytest.mark.asyncio
    async def test_returns_five_dimensions(self):
        mock_output = TextEvalOutput(
            voice_consistency=DimScore(score=0.9, passed=True),
            audience_calibration=DimScore(score=0.85, passed=True),
            duration_feasibility=DimScore(score=0.7, passed=False, issues=["Too short"]),
            key_points_quality=DimScore(score=0.8, passed=True),
            narrative_coherence=DimScore(score=0.9, passed=True),
        )
        mock_result = MagicMock()
        mock_result.output = mock_output

        with patch("agents.demo_pipeline.eval_rubrics.text_eval_agent") as mock_agent:
            mock_agent.run = AsyncMock(return_value=mock_result)
            dims = await run_text_evaluation(
                {"audience": "family", "scenes": [], "intro_narration": "", "outro_narration": ""},
                {},
                180,
            )

        assert len(dims) == 5
        assert all(d.category == "text" for d in dims)
        names = {d.name for d in dims}
        assert "voice_consistency" in names
        assert "duration_feasibility" in names
        dur = next(d for d in dims if d.name == "duration_feasibility")
        assert dur.passed is False
        assert "Too short" in dur.issues


class TestLoadScreenshotsAsContent:
    def test_loads_screenshots(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path, scenes=2)
        script_data = json.loads((demo_dir / "script.json").read_text())
        content = _load_screenshots_as_content(demo_dir, script_data)
        images = [c for c in content if isinstance(c, BinaryContent)]
        texts = [c for c in content if isinstance(c, str)]
        assert len(images) == 2
        assert len(texts) == 2

    def test_handles_missing_screenshot(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path, scenes=2)
        pngs = sorted((demo_dir / "screenshots").glob("*.png"))
        pngs[0].unlink()
        script_data = json.loads((demo_dir / "script.json").read_text())
        content = _load_screenshots_as_content(demo_dir, script_data)
        images = [c for c in content if isinstance(c, BinaryContent)]
        assert len(images) == 1


class TestBuildVisualEvalPrompt:
    def test_includes_audience(self):
        prompt = _build_visual_eval_prompt({"title": "My Demo", "audience": "family"})
        assert "family" in prompt
        assert "visual_clarity" in prompt


class TestRunVisualEvaluation:
    @pytest.mark.asyncio
    async def test_no_screenshots_returns_failing(self, tmp_path):
        demo_dir = tmp_path / "empty"
        demo_dir.mkdir()
        (demo_dir / "screenshots").mkdir()
        dims = await run_visual_evaluation(demo_dir, {"scenes": []})
        assert len(dims) == 4
        assert all(d.passed is False for d in dims)

    @pytest.mark.asyncio
    async def test_returns_four_dimensions(self, tmp_path):
        demo_dir = _make_demo_dir(tmp_path, scenes=2)
        script_data = json.loads((demo_dir / "script.json").read_text())

        mock_output = VisualEvalOutput(
            visual_clarity=DimScore(score=0.9, passed=True),
            visual_variety=DimScore(score=0.7, passed=False, issues=["Screenshots look similar"]),
            theme_compliance=DimScore(score=0.85, passed=True),
            visual_narration_alignment=DimScore(score=0.8, passed=True),
        )
        mock_result = MagicMock()
        mock_result.output = mock_output

        with patch("agents.demo_pipeline.eval_rubrics.visual_eval_agent") as mock_agent:
            mock_agent.run = AsyncMock(return_value=mock_result)
            dims = await run_visual_evaluation(demo_dir, script_data)

        assert len(dims) == 4
        assert all(d.category == "visual" for d in dims)
        variety = next(d for d in dims if d.name == "visual_variety")
        assert variety.passed is False


class TestBuildDiagnosisPrompt:
    def test_includes_failing_dimensions(self):
        dims = [
            DemoEvalDimension(
                name="style",
                category="text",
                passed=False,
                score=0.3,
                issues=["Uses 'leverage'", "Passive voice"],
                evidence="Scene 2: 'leverage the system'",
            ),
            DemoEvalDimension(name="clarity", category="visual", passed=True, score=0.9),
        ]
        prompt = _build_diagnosis_prompt(dims, {"title": "Demo", "scenes": []}, {}, 1)
        assert "style" in prompt
        assert "leverage" in prompt
        # Passing dimensions should NOT be in the failing section
        failing_section = prompt.split("Failing Dimensions")[1].split("Current Script")[0]
        assert "clarity" not in failing_section

    def test_includes_iteration_number(self):
        prompt = _build_diagnosis_prompt([], {}, {}, 3)
        assert "iteration 3" in prompt

    def test_includes_scene_details_and_jargon(self):
        """Diagnosis prompt should include per-scene word counts, narration excerpts, and jargon detection."""
        dims = [
            DemoEvalDimension(
                name="audience_calibration",
                category="text",
                passed=False,
                score=0.5,
                issues=["Technical jargon found for family audience"],
            )
        ]
        script = {
            "audience": "family",
            "title": "Test Demo",
            "scenes": [
                {
                    "title": "Scene 1",
                    "narration": "The API endpoint uses Docker containers",
                    "visual_type": "diagram",
                },
                {
                    "title": "Scene 2",
                    "narration": "A warm welcome to the system",
                    "visual_type": "screenshot",
                },
            ],
            "intro_narration": "Welcome to the system",
            "outro_narration": "Thanks for watching",
        }
        style = {"voice": "first-person", "avoid": ["jargon"]}

        forbidden = ["API", "Docker", "container"]
        prompt = _build_diagnosis_prompt(
            dims, script, style, iteration=1, forbidden_terms=forbidden
        )

        # Per-scene analysis present
        assert "Per-Scene Analysis" in prompt
        assert "Scene 1" in prompt
        assert "Scene 2" in prompt
        # Word counts included
        assert "Total narration:" in prompt
        # Jargon detected for family audience
        assert "JARGON DETECTED" in prompt
        assert "API" in prompt
        assert "Docker" in prompt
        # Scene 2 should NOT trigger jargon (no tech terms)
        jargon_section = prompt.split("JARGON DETECTED")[1].split("## Style Guide")[0]
        assert "Scene 1:" in jargon_section
        assert "Scene 2:" not in jargon_section

    def test_no_jargon_section_for_leadership_audience(self):
        """Jargon detection only triggers for non-technical audiences."""
        script = {
            "audience": "leadership",
            "title": "Tech Demo",
            "scenes": [{"title": "S1", "narration": "The API uses Docker containers"}],
            "intro_narration": "",
            "outro_narration": "",
        }
        prompt = _build_diagnosis_prompt([], script, {}, 1)
        assert "JARGON DETECTED" not in prompt

    def test_word_count_includes_intro_outro(self):
        """Total word count should include intro and outro narration."""
        script = {
            "audience": "family",
            "title": "Demo",
            "scenes": [{"title": "S1", "narration": "one two three"}],
            "intro_narration": "four five",
            "outro_narration": "six seven eight",
        }
        prompt = _build_diagnosis_prompt([], script, {}, 1)
        assert "Total narration: 8 words" in prompt


class TestDiagnoseFailures:
    @pytest.mark.asyncio
    async def test_returns_diagnosis(self):
        mock_output = DiagnosisOutput(
            root_causes=["Narration uses corporate jargon for family audience"],
            planning_overrides="CRITICAL: Replace all technical terms with plain language.",
            adjustments_summary=["Simplified vocabulary for family audience"],
        )
        mock_result = MagicMock()
        mock_result.output = mock_output

        with patch("agents.demo_pipeline.eval_rubrics.diagnosis_agent") as mock_agent:
            mock_agent.run = AsyncMock(return_value=mock_result)
            diagnosis = await diagnose_failures(
                [
                    DemoEvalDimension(
                        name="style", category="text", passed=False, score=0.3, issues=["jargon"]
                    )
                ],
                {"title": "Demo", "scenes": []},
                {},
                1,
            )

        assert len(diagnosis.root_causes) == 1
        assert "CRITICAL" in diagnosis.planning_overrides
