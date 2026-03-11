"""Tests for self-critique and revision loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from agents.demo_models import (
    DemoQualityReport,
    DemoScene,
    DemoScript,
    IllustrationSpec,
    QualityDimension,
    ScreenshotSpec,
)
from agents.demo_pipeline.critique import (
    MAX_ITERATIONS,
    QUALITY_DIMENSIONS,
    _build_critique_prompt,
    critique_and_revise,
)

# Use short target_seconds in tests so deterministic word count checks don't interfere
# with LLM-agent-focused test logic
TEST_TARGET_SECONDS = 7  # ~17 words target (85% = 14), met by test scripts (~15 words)


def _make_script(title="Test Demo", scenes=2):
    return DemoScript(
        title=title,
        audience="technical-peer",
        intro_narration="Welcome to this demo.",
        outro_narration="Thanks for watching.",
        scenes=[
            DemoScene(
                title=f"Scene {i}",
                narration=f"Narration for scene {i}",
                duration_hint=10.0,
                screenshot=ScreenshotSpec(url=f"http://localhost:5173/page{i}"),
            )
            for i in range(1, scenes + 1)
        ],
    )


def _make_passing_report():
    return DemoQualityReport(
        dimensions=[QualityDimension(name=d, passed=True) for d in QUALITY_DIMENSIONS],
        overall_pass=True,
    )


def _make_failing_report(critical=1, important=0):
    dims = []
    for i, d in enumerate(QUALITY_DIMENSIONS):
        if i < critical:
            dims.append(
                QualityDimension(name=d, passed=False, severity="critical", issues=["Fix this"])
            )
        elif i < critical + important:
            dims.append(
                QualityDimension(
                    name=d, passed=False, severity="important", issues=["Improve this"]
                )
            )
        else:
            dims.append(QualityDimension(name=d, passed=True))
    return DemoQualityReport(dimensions=dims, overall_pass=False, revision_notes="Fix issues")


class TestCritiquePrompt:
    def test_includes_all_dimensions(self):
        script = _make_script()
        prompt = _build_critique_prompt(
            script, "research", {"avoid": ["jargon"]}, {"name": "Test"}, TEST_TARGET_SECONDS
        )
        for dim in QUALITY_DIMENSIONS:
            assert dim in prompt

    def test_includes_style_avoid(self):
        script = _make_script()
        prompt = _build_critique_prompt(
            script,
            "research",
            {"avoid": ["jargon", "buzzwords"]},
            {"name": "Test"},
            TEST_TARGET_SECONDS,
        )
        assert "jargon" in prompt

    def test_includes_target_duration(self):
        script = _make_script()
        prompt = _build_critique_prompt(
            script, "research", {}, {"name": "Test"}, TEST_TARGET_SECONDS
        )
        assert f"{TEST_TARGET_SECONDS} seconds" in prompt

    def test_includes_framework_name(self):
        script = _make_script()
        prompt = _build_critique_prompt(script, "research", {}, {"name": "problem-solution"}, 300)
        assert "problem-solution" in prompt

    def test_no_avoid_when_empty(self):
        script = _make_script()
        prompt = _build_critique_prompt(
            script, "research", {}, {"name": "Test"}, TEST_TARGET_SECONDS
        )
        assert "Style AVOID list" not in prompt


class TestCritiqueAndRevise:
    async def test_all_pass_no_revision(self):
        """Script passes on first try — no revision needed."""
        script = _make_script()
        mock_critique_result = MagicMock()
        mock_critique_result.output = _make_passing_report()

        with patch("agents.demo_pipeline.critique.critique_agent") as mock_agent:
            mock_agent.run = AsyncMock(return_value=mock_critique_result)

            result_script, result_report = await critique_and_revise(
                script,
                "research context",
                {},
                {"name": "Test"},
                TEST_TARGET_SECONDS,
            )
            assert result_report.overall_pass
            assert result_script == script
            # Revision agent should NOT have been called
            mock_agent.run.assert_called_once()

    async def test_critique_triggers_revision(self):
        """Critical issue — revision — passes."""
        script = _make_script()
        revised_script = _make_script(title="Revised Demo")

        failing_report = _make_failing_report(critical=1)
        passing_report = _make_passing_report()

        mock_critique_fail = MagicMock()
        mock_critique_fail.output = failing_report
        mock_critique_pass = MagicMock()
        mock_critique_pass.output = passing_report
        mock_revision = MagicMock()
        mock_revision.output = revised_script

        with (
            patch("agents.demo_pipeline.critique.critique_agent") as mock_crit,
            patch("agents.demo_pipeline.critique.revision_agent") as mock_rev,
        ):
            mock_crit.run = AsyncMock(side_effect=[mock_critique_fail, mock_critique_pass])
            mock_rev.run = AsyncMock(return_value=mock_revision)

            result_script, result_report = await critique_and_revise(
                script,
                "research",
                {},
                {"name": "Test"},
                TEST_TARGET_SECONDS,
            )
            assert result_script.title == "Revised Demo"
            assert mock_rev.run.call_count == 1

    async def test_max_iterations_reached(self):
        """Always failing — stops at MAX_ITERATIONS."""
        script = _make_script()
        failing_report = _make_failing_report(critical=2)

        mock_critique = MagicMock()
        mock_critique.output = failing_report
        mock_revision = MagicMock()
        mock_revision.output = _make_script(title="Still bad")

        with (
            patch("agents.demo_pipeline.critique.critique_agent") as mock_crit,
            patch("agents.demo_pipeline.critique.revision_agent") as mock_rev,
        ):
            # All critiques fail, all revisions produce new versions
            mock_crit.run = AsyncMock(return_value=mock_critique)
            mock_rev.run = AsyncMock(return_value=mock_revision)

            result_script, result_report = await critique_and_revise(
                script,
                "research",
                {},
                {"name": "Test"},
                TEST_TARGET_SECONDS,
            )
            # Should have MAX_ITERATIONS critique calls in the loop + 1 final
            assert mock_crit.run.call_count == MAX_ITERATIONS + 1

    async def test_important_only_passes(self):
        """One important issue (no critical) passes quality gate."""
        script = _make_script()
        report = _make_failing_report(critical=0, important=1)
        mock_result = MagicMock()
        mock_result.output = report

        with patch("agents.demo_pipeline.critique.critique_agent") as mock_crit:
            mock_crit.run = AsyncMock(return_value=mock_result)

            result_script, result_report = await critique_and_revise(
                script,
                "research",
                {},
                {"name": "Test"},
                TEST_TARGET_SECONDS,
            )
            # 0 critical + 1 important = pass
            assert result_script == script
            mock_crit.run.assert_called_once()

    async def test_progress_callback(self):
        """Progress callback is invoked during loop."""
        script = _make_script()
        mock_result = MagicMock()
        mock_result.output = _make_passing_report()

        messages = []
        with patch("agents.demo_pipeline.critique.critique_agent") as mock_crit:
            mock_crit.run = AsyncMock(return_value=mock_result)

            await critique_and_revise(
                script,
                "research",
                {},
                {"name": "Test"},
                TEST_TARGET_SECONDS,
                on_progress=messages.append,
            )
            assert len(messages) >= 2  # at least evaluation + passed messages
            assert any("iteration" in m for m in messages)


class TestDeterministicChecks:
    def test_word_count_passes_when_sufficient(self):
        from agents.demo_pipeline.critique import _check_word_count

        script = _make_script()
        # With 10 second target, need ~25 words; test script has enough
        result = _check_word_count(script, TEST_TARGET_SECONDS)
        assert result is None  # None means passed

    def test_word_count_fails_when_too_short(self):
        from agents.demo_pipeline.critique import _check_word_count

        script = _make_script()
        # With 600 second target, need ~1500 words; test script has ~20
        result = _check_word_count(script, 600)
        assert result is not None
        assert result.severity == "critical"
        assert not result.passed

    def test_word_count_fails_when_too_long(self):
        from agents.demo_pipeline.critique import _check_word_count

        # Build a script with way too many words for a 5-second target
        long_narration = " ".join(["word"] * 200)
        script = DemoScript(
            title="Overlong",
            audience="family",
            intro_narration=long_narration,
            outro_narration=long_narration,
            scenes=[
                DemoScene(
                    title="Scene 1",
                    narration=long_narration,
                    duration_hint=10.0,
                    screenshot=ScreenshotSpec(url="http://localhost:5173/"),
                )
            ],
        )
        # 5 second target = ~12 target words, max = ~13. Script has 600 words.
        result = _check_word_count(script, 5)
        assert result is not None
        assert result.severity == "critical"
        assert "maximum" in result.issues[0].lower() or "Excess" in result.issues[1]

    def test_visual_variety_passes_with_few_screenshots(self):
        from agents.demo_pipeline.critique import _check_visual_variety

        script = _make_script(scenes=2)
        result = _check_visual_variety(script)
        # 2 screenshots with unique URLs is fine (<=3, no dupes)
        assert result is None

    async def test_max_iterations_reapplies_deterministic_checks(self):
        """Final iteration re-applies word count check even if LLM says pass."""
        # Script with very little narration + high target = deterministic word count fail
        script = _make_script()  # ~20 words
        target_seconds = 600  # needs ~1500 words

        # LLM always says "pass" (optimistic)
        optimistic_report = _make_passing_report()
        # But first iterations fail to trigger the revision loop
        failing_report = _make_failing_report(critical=2)

        call_count = 0

        def make_critique_result():
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            # First MAX_ITERATIONS calls fail, final call is optimistic
            if call_count <= MAX_ITERATIONS:
                mock.output = failing_report
            else:
                mock.output = optimistic_report
            return mock

        mock_revision = MagicMock()
        mock_revision.output = script  # revision doesn't improve word count

        with (
            patch("agents.demo_pipeline.critique.critique_agent") as mock_crit,
            patch("agents.demo_pipeline.critique.revision_agent") as mock_rev,
        ):
            mock_crit.run = AsyncMock(side_effect=lambda _: make_critique_result())
            mock_rev.run = AsyncMock(return_value=mock_revision)

            _result_script, result_report = await critique_and_revise(
                script,
                "research",
                {},
                {"name": "Test"},
                target_seconds,
            )

            # LLM said pass, but deterministic word count should override
            assert not result_report.overall_pass, (
                "Should fail: LLM was optimistic but word count is still short"
            )

    def test_intro_outro_passes_when_short(self):
        from agents.demo_pipeline.critique import _check_intro_outro_length

        script = _make_script()  # intro/outro are ~4 words each
        result = _check_intro_outro_length(script)
        assert result is None

    def test_intro_fails_when_too_long(self):
        from agents.demo_pipeline.critique import _check_intro_outro_length

        long_intro = " ".join(["word"] * 50)
        script = DemoScript(
            title="Long Intro",
            audience="family",
            intro_narration=long_intro,
            outro_narration="Short outro.",
            scenes=[
                DemoScene(
                    title="Scene 1",
                    narration="Narration 1",
                    duration_hint=10.0,
                    screenshot=ScreenshotSpec(url="http://localhost:5173/"),
                )
            ],
        )
        result = _check_intro_outro_length(script)
        assert result is not None
        assert result.severity == "critical"
        assert "Intro" in result.issues[0]

    def test_outro_fails_when_too_long(self):
        from agents.demo_pipeline.critique import _check_intro_outro_length

        long_outro = " ".join(["word"] * 50)
        script = DemoScript(
            title="Long Outro",
            audience="family",
            intro_narration="Short intro.",
            outro_narration=long_outro,
            scenes=[
                DemoScene(
                    title="Scene 1",
                    narration="Narration 1",
                    duration_hint=10.0,
                    screenshot=ScreenshotSpec(url="http://localhost:5173/"),
                )
            ],
        )
        result = _check_intro_outro_length(script)
        assert result is not None
        assert "Outro" in result.issues[0]

    def test_both_intro_outro_fail(self):
        from agents.demo_pipeline.critique import _check_intro_outro_length

        long_text = " ".join(["word"] * 50)
        script = DemoScript(
            title="Both Long",
            audience="family",
            intro_narration=long_text,
            outro_narration=long_text,
            scenes=[
                DemoScene(
                    title="Scene 1",
                    narration="Narration 1",
                    duration_hint=10.0,
                    screenshot=ScreenshotSpec(url="http://localhost:5173/"),
                )
            ],
        )
        result = _check_intro_outro_length(script)
        assert result is not None
        assert len(result.issues) == 2

    def test_visual_variety_fails_with_too_many_screenshots(self):
        from agents.demo_pipeline.critique import _check_visual_variety

        script = DemoScript(
            title="Many Screenshots",
            audience="family",
            intro_narration="Welcome.",
            outro_narration="Bye.",
            scenes=[
                DemoScene(
                    title=f"Scene {i}",
                    narration=f"Narration {i}",
                    duration_hint=10.0,
                    screenshot=ScreenshotSpec(url=f"http://localhost:5173/page{i}"),
                )
                for i in range(1, 5)
            ],
        )
        result = _check_visual_variety(script)
        assert result is not None
        assert "consecutive" in result.issues[0]

    def test_visual_variety_fails_with_too_many_screencasts(self):
        from agents.demo_models import InteractionSpec, InteractionStep
        from agents.demo_pipeline.critique import _check_visual_variety

        script = DemoScript(
            title="Many Screencasts",
            audience="family",
            intro_narration="Welcome.",
            outro_narration="Bye.",
            scenes=[
                DemoScene(
                    title=f"Screencast {i}",
                    narration=f"Narration {i}",
                    duration_hint=10.0,
                    visual_type="screencast",
                    interaction=InteractionSpec(
                        url="http://localhost:5173/chat",
                        steps=[InteractionStep(action="wait", value="1000")],
                    ),
                )
                for i in range(1, 4)
            ],
        )
        result = _check_visual_variety(script)
        assert result is not None
        assert any("3 screencast" in issue for issue in result.issues)

    def test_visual_variety_fails_screencast_without_interaction(self):
        from agents.demo_pipeline.critique import _check_visual_variety

        script = DemoScript(
            title="Missing Interaction",
            audience="family",
            intro_narration="Welcome.",
            outro_narration="Bye.",
            scenes=[
                DemoScene(
                    title="Bad Screencast",
                    narration="Narration",
                    duration_hint=10.0,
                    visual_type="screencast",
                ),
            ],
        )
        result = _check_visual_variety(script)
        assert result is not None
        assert any("no interaction spec" in issue for issue in result.issues)

    def test_visual_variety_allows_many_screenshots(self):
        """Multiple screenshots with diagram breaks are OK."""
        from agents.demo_pipeline.critique import _check_visual_variety

        script = DemoScript(
            title="Many Screenshots",
            audience="family",
            intro_narration="Welcome.",
            outro_narration="Bye.",
            scenes=[
                DemoScene(
                    title="Dashboard 1",
                    narration="Narration 1",
                    duration_hint=10.0,
                    visual_type="screenshot",
                    screenshot=ScreenshotSpec(url="http://localhost:5173/"),
                ),
                DemoScene(
                    title="Dashboard 2",
                    narration="Narration 2",
                    duration_hint=10.0,
                    visual_type="screenshot",
                    screenshot=ScreenshotSpec(url="http://localhost:5173/"),
                ),
                DemoScene(
                    title="Diagram",
                    narration="Break",
                    duration_hint=10.0,
                    visual_type="diagram",
                    diagram_spec="A -> B",
                ),
                DemoScene(
                    title="Dashboard 3",
                    narration="Narration 3",
                    duration_hint=10.0,
                    visual_type="screenshot",
                    screenshot=ScreenshotSpec(url="http://localhost:5173/chat"),
                ),
            ],
        )
        result = _check_visual_variety(script)
        assert result is None  # No issues — screenshots with breaks are fine

    def test_visual_variety_fails_route_concentration(self):
        """Too many screenshots of the same route produces identical images."""
        from agents.demo_pipeline.critique import _check_visual_variety

        # 6 scenes (triggers route concentration check), 5 on same route
        scenes = []
        for i in range(5):
            scenes.append(
                DemoScene(
                    title=f"Dashboard {i + 1}",
                    narration=f"Narration {i + 1}",
                    duration_hint=10.0,
                    visual_type="screenshot",
                    screenshot=ScreenshotSpec(url="http://localhost:5173/"),
                )
            )
        # Add a diagram break to avoid consecutive-type trigger dominating
        scenes.insert(
            2,
            DemoScene(
                title="Diagram",
                narration="Break",
                duration_hint=10.0,
                visual_type="diagram",
                diagram_spec="A -> B",
            ),
        )
        script = DemoScript(
            title="Route Concentration",
            audience="family",
            intro_narration="Welcome.",
            outro_narration="Bye.",
            scenes=scenes,
        )
        result = _check_visual_variety(script)
        assert result is not None
        assert any("screenshots of route" in issue for issue in result.issues)

    def test_visual_variety_allows_distributed_routes(self):
        """Screenshots distributed across routes are fine."""
        from agents.demo_pipeline.critique import _check_visual_variety

        scenes = [
            DemoScene(
                title="Dash 1",
                narration="N1",
                duration_hint=10.0,
                visual_type="screenshot",
                screenshot=ScreenshotSpec(url="http://localhost:5173/"),
            ),
            DemoScene(
                title="Diagram 1",
                narration="D1",
                duration_hint=10.0,
                visual_type="diagram",
                diagram_spec="A -> B",
            ),
            DemoScene(
                title="Chat 1",
                narration="N2",
                duration_hint=10.0,
                visual_type="screenshot",
                screenshot=ScreenshotSpec(url="http://localhost:5173/chat"),
            ),
            DemoScene(
                title="Dash 2",
                narration="N3",
                duration_hint=10.0,
                visual_type="screenshot",
                screenshot=ScreenshotSpec(url="http://localhost:5173/"),
            ),
            DemoScene(
                title="Diagram 2",
                narration="D2",
                duration_hint=10.0,
                visual_type="diagram",
                diagram_spec="C -> D",
            ),
            DemoScene(
                title="Demos 1",
                narration="N4",
                duration_hint=10.0,
                visual_type="screenshot",
                screenshot=ScreenshotSpec(url="http://localhost:5173/demos"),
            ),
            DemoScene(
                title="Chat 2",
                narration="N5",
                duration_hint=10.0,
                visual_type="screenshot",
                screenshot=ScreenshotSpec(url="http://localhost:5173/chat"),
            ),
        ]
        script = DemoScript(
            title="Distributed Routes",
            audience="family",
            intro_narration="Welcome.",
            outro_narration="Bye.",
            scenes=scenes,
        )
        result = _check_visual_variety(script)
        assert result is None


class TestDeterministicFixes:
    def test_route_redistribution(self):
        from agents.demo_pipeline.critique import _fix_route_concentration

        # 5 screenshots on /, 0 on /chat, 0 on /demos — should redistribute
        scenes = [
            DemoScene(
                title=f"Dash {i + 1}",
                narration=f"N{i + 1}",
                duration_hint=10.0,
                visual_type="screenshot",
                screenshot=ScreenshotSpec(url="http://localhost:5173/"),
            )
            for i in range(5)
        ]
        # Interleave diagrams
        scenes.insert(
            1,
            DemoScene(
                title="D1",
                narration="D",
                duration_hint=10.0,
                visual_type="diagram",
                diagram_spec="A -> B",
            ),
        )
        scenes.insert(
            3,
            DemoScene(
                title="D2",
                narration="D",
                duration_hint=10.0,
                visual_type="diagram",
                diagram_spec="C -> D",
            ),
        )
        script = DemoScript(
            title="Test",
            audience="family",
            intro_narration="Hi.",
            outro_narration="Bye.",
            scenes=scenes,
        )
        fixed = _fix_route_concentration(script)
        route_counts: dict[str, int] = {}
        for s in fixed.scenes:
            if s.visual_type == "screenshot" and s.screenshot:
                url = s.screenshot.url.rstrip("/")
                if url.endswith(":5173"):
                    route_counts["/"] = route_counts.get("/", 0) + 1
                elif "/chat" in url:
                    route_counts["/chat"] = route_counts.get("/chat", 0) + 1
                elif "/demos" in url:
                    route_counts["/demos"] = route_counts.get("/demos", 0) + 1
        assert route_counts.get("/", 0) <= 2  # Static pages limited to 2
        assert len(route_counts) > 1

    def test_intro_outro_trim(self):
        from agents.demo_pipeline.critique import _fix_intro_outro

        long_intro = " ".join(["word"] * 50)
        long_outro = " ".join(["word"] * 50)
        script = DemoScript(
            title="Test",
            audience="family",
            intro_narration=long_intro,
            outro_narration=long_outro,
            scenes=[
                DemoScene(
                    title="S1",
                    narration="N",
                    duration_hint=10.0,
                    screenshot=ScreenshotSpec(url="http://localhost:5173/"),
                )
            ],
        )
        fixed = _fix_intro_outro(script)
        assert len(fixed.intro_narration.split()) <= 35
        assert len(fixed.outro_narration.split()) <= 35

    def test_no_redistribution_when_balanced(self):
        from agents.demo_pipeline.critique import _fix_route_concentration

        scenes = [
            DemoScene(
                title="Dash",
                narration="N",
                duration_hint=10.0,
                visual_type="screenshot",
                screenshot=ScreenshotSpec(url="http://localhost:5173/"),
            ),
            DemoScene(
                title="Chat",
                narration="N",
                duration_hint=10.0,
                visual_type="screenshot",
                screenshot=ScreenshotSpec(url="http://localhost:5173/chat"),
            ),
            DemoScene(
                title="Demos",
                narration="N",
                duration_hint=10.0,
                visual_type="screenshot",
                screenshot=ScreenshotSpec(url="http://localhost:5173/demos"),
            ),
        ]
        script = DemoScript(
            title="Test",
            audience="family",
            intro_narration="Hi.",
            outro_narration="Bye.",
            scenes=scenes,
        )
        fixed = _fix_route_concentration(script)
        for old, new in zip(script.scenes, fixed.scenes, strict=False):
            if old.screenshot and new.screenshot:
                assert old.screenshot.url == new.screenshot.url


class TestIllustrationCritique:
    def test_max_three_illustrations_enforced(self):
        """More than 3 illustration scenes are flagged."""
        from agents.demo_pipeline.critique import _check_visual_variety

        illus_spec = IllustrationSpec(
            prompt="A conceptual illustration",
            style="warm minimal illustration",
        )
        scenes = [
            DemoScene(
                title=f"Illustration {i}",
                narration=f"Narration {i}",
                duration_hint=10.0,
                visual_type="illustration",
                illustration=illus_spec,
            )
            for i in range(1, 5)  # 4 illustration scenes
        ]
        # Add enough screenshots to satisfy ratio
        for i in range(1, 5):
            scenes.append(
                DemoScene(
                    title=f"Screenshot {i}",
                    narration=f"Screenshot narration {i}",
                    duration_hint=10.0,
                    visual_type="screenshot",
                    screenshot=ScreenshotSpec(url=f"http://localhost:5173/page{i}"),
                )
            )
        script = DemoScript(
            title="Too Many Illustrations",
            audience="family",
            intro_narration="Welcome.",
            outro_narration="Bye.",
            scenes=scenes,
        )
        result = _check_visual_variety(script)
        assert result is not None
        assert any("illustration" in issue.lower() and "max 3" in issue for issue in result.issues)

    def test_illustration_without_spec_flagged(self):
        """Illustration scene without illustration spec is flagged."""
        from agents.demo_pipeline.critique import _check_visual_variety

        script = DemoScript(
            title="Missing Spec",
            audience="family",
            intro_narration="Welcome.",
            outro_narration="Bye.",
            scenes=[
                DemoScene(
                    title="Bad Illustration",
                    narration="Narration",
                    duration_hint=10.0,
                    visual_type="illustration",
                    # illustration=None (default)
                ),
            ],
        )
        result = _check_visual_variety(script)
        assert result is not None
        assert any("illustration spec" in issue for issue in result.issues)

    def test_illustrations_dont_count_toward_screenshot_ratio(self):
        """Illustrations don't satisfy the 50% screenshot requirement."""
        from agents.demo_pipeline.critique import _check_visual_variety

        illus_spec = IllustrationSpec(
            prompt="A conceptual illustration",
            style="warm minimal illustration",
        )
        # 3 illustrations + 1 screenshot = 4 scenes, need 2 screenshots but only have 1
        scenes = [
            DemoScene(
                title=f"Illustration {i}",
                narration=f"Narration {i}",
                duration_hint=10.0,
                visual_type="illustration",
                illustration=illus_spec,
            )
            for i in range(1, 4)  # 3 illustrations
        ]
        scenes.append(
            DemoScene(
                title="Screenshot 1",
                narration="Screenshot narration",
                duration_hint=10.0,
                visual_type="screenshot",
                screenshot=ScreenshotSpec(url="http://localhost:5173/"),
            )
        )
        script = DemoScript(
            title="Mostly Illustrations",
            audience="family",
            intro_narration="Welcome.",
            outro_narration="Bye.",
            scenes=scenes,
        )
        result = _check_visual_variety(script)
        assert result is not None
        assert any("screenshots/screencasts" in issue for issue in result.issues)
