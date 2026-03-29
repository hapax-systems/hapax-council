"""Tests for the reverberation mechanism — imagination self-surprise detection."""

from __future__ import annotations

from pathlib import Path

from agents.imagination import (
    ContentReference,
    ImaginationFragment,
    ImaginationLoop,
    reverberation_check,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_fragment(**overrides) -> ImaginationFragment:
    defaults = {
        "content_references": [
            ContentReference(kind="text", source="test", salience=0.5),
        ],
        "dimensions": {"intensity": 0.4},
        "salience": 0.5,
        "continuation": False,
        "narrative": "a warm sunset over distant hills",
    }
    defaults.update(overrides)
    return ImaginationFragment(**defaults)


# ---------------------------------------------------------------------------
# reverberation_check unit tests
# ---------------------------------------------------------------------------


class TestReverberationCheck:
    def test_identical_texts_zero_reverberation(self) -> None:
        assert reverberation_check("hello world", "hello world") == 0.0

    def test_completely_different_texts_high_reverberation(self) -> None:
        result = reverberation_check("warm sunset hills", "cold machinery noise")
        assert result > 0.8

    def test_partial_overlap_moderate_reverberation(self) -> None:
        result = reverberation_check(
            "warm sunset over distant hills",
            "warm light fading over dark mountains",
        )
        assert 0.3 < result < 0.9

    def test_empty_narrative_returns_zero(self) -> None:
        assert reverberation_check("", "something observed") == 0.0

    def test_empty_observation_returns_zero(self) -> None:
        assert reverberation_check("something imagined", "") == 0.0

    def test_both_empty_returns_zero(self) -> None:
        assert reverberation_check("", "") == 0.0

    def test_case_insensitive(self) -> None:
        r1 = reverberation_check("Hello World", "hello world")
        assert r1 == 0.0

    def test_single_word_overlap(self) -> None:
        result = reverberation_check("cat", "cat")
        assert result == 0.0

    def test_single_word_no_overlap(self) -> None:
        result = reverberation_check("cat", "dog")
        assert result == 1.0


# ---------------------------------------------------------------------------
# ImaginationLoop reverberation integration
# ---------------------------------------------------------------------------


class TestImaginationLoopReverberation:
    def test_check_reverberation_no_fragments(self) -> None:
        loop = ImaginationLoop()
        assert loop._check_reverberation() == 0.0

    def test_check_reverberation_no_observation_file(self, tmp_path: Path) -> None:
        loop = ImaginationLoop(
            visual_observation_path=tmp_path / "nonexistent.txt",
        )
        loop._record_fragment(_make_fragment())
        assert loop._check_reverberation() == 0.0

    def test_check_reverberation_with_observation(self, tmp_path: Path) -> None:
        obs_path = tmp_path / "visual-observation.txt"
        obs_path.write_text("cold dark angular geometry pulsing")

        loop = ImaginationLoop(
            visual_observation_path=obs_path,
        )
        loop._record_fragment(_make_fragment(narrative="warm sunset over distant hills"))

        reverb = loop._check_reverberation()
        assert reverb > 0.5  # very different = high reverberation
        assert loop._last_reverberation == reverb

    def test_check_reverberation_similar_observation(self, tmp_path: Path) -> None:
        obs_path = tmp_path / "visual-observation.txt"
        obs_path.write_text("a warm sunset fading over hills")

        loop = ImaginationLoop(
            visual_observation_path=obs_path,
        )
        loop._record_fragment(_make_fragment(narrative="a warm sunset over distant hills"))

        reverb = loop._check_reverberation()
        assert reverb < 0.5  # similar = low reverberation

    def test_reverberation_updates_last_value(self, tmp_path: Path) -> None:
        obs_path = tmp_path / "visual-observation.txt"
        obs_path.write_text("completely unrelated machine noise static")

        loop = ImaginationLoop(
            visual_observation_path=obs_path,
        )
        assert loop._last_reverberation == 0.0

        loop._record_fragment(_make_fragment())
        loop._check_reverberation()
        assert loop._last_reverberation > 0.0


# ---------------------------------------------------------------------------
# Reverberation semantics — visual description vs health text
# ---------------------------------------------------------------------------


class TestReverberationSemantics:
    def test_similar_visual_descriptions_low_reverberation(self, tmp_path: Path) -> None:
        obs_path = tmp_path / "visual-observation.txt"
        obs_path.write_text("warm orange gradient with faint text fragments drifting upward")
        loop = ImaginationLoop(visual_observation_path=obs_path)
        loop._record_fragment(
            _make_fragment(narrative="warm sunset tones with text floating upward in the field")
        )
        reverb = loop._check_reverberation()
        assert reverb < 0.8

    def test_health_text_always_high_reverberation(self, tmp_path: Path) -> None:
        obs_path = tmp_path / "visual-observation.txt"
        obs_path.write_text("Trajectory: stable. Concern: none")
        loop = ImaginationLoop(visual_observation_path=obs_path)
        loop._record_fragment(_make_fragment(narrative="warm sunset over distant hills"))
        reverb = loop._check_reverberation()
        assert reverb > 0.7
