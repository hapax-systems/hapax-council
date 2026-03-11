"""Tests for agents.demo_pipeline.lessons — cross-run lesson accumulation."""
from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

import pytest
import yaml

from agents.demo_pipeline.lessons import (
    MAX_LESSONS_PER_ARCHETYPE,
    Lesson,
    accumulate_lessons,
    extract_lessons,
    format_lessons_block,
    load_lessons,
    load_lessons_for_archetype,
    save_lessons,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lesson(text: str, count: int = 1, added: str = "2026-01-01") -> Lesson:
    return {"text": text, "success_count": count, "added": added}


def _make_eval_result(
    passed: bool = True,
    iterations: int = 2,
    adjustments: list[str] | None = None,
) -> "DemoEvalResult":
    from agents.demo_models import DemoEvalDimension, DemoEvalReport, DemoEvalResult

    dim = DemoEvalDimension(
        name="tone",
        category="text",
        passed=True,
        score=0.9,
    )
    report = DemoEvalReport(
        dimensions=[dim],
        overall_pass=passed,
        overall_score=0.9,
        iteration=iterations,
        adjustments_applied=adjustments or [],
    )
    return DemoEvalResult(
        scenario="family",
        passed=passed,
        iterations=iterations,
        final_report=report,
        history=[],
        demo_dir="/tmp/demo",
    )


# ---------------------------------------------------------------------------
# TestLoadLessons
# ---------------------------------------------------------------------------


class TestLoadLessons:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_lessons(tmp_path / "nonexistent.yaml") == {}

    def test_malformed_yaml_returns_empty(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("{{{{not valid yaml: [", encoding="utf-8")
        assert load_lessons(bad) == {}

    def test_loads_existing_lessons(self, tmp_path: Path) -> None:
        store = {
            "family": [_make_lesson("Use simpler words")],
        }
        f = tmp_path / "lessons.yaml"
        f.write_text(yaml.dump(store), encoding="utf-8")
        loaded = load_lessons(f)
        assert "family" in loaded
        assert loaded["family"][0]["text"] == "Use simpler words"
        assert loaded["family"][0]["success_count"] == 1

    def test_preserves_extra_archetypes(self, tmp_path: Path) -> None:
        store = {
            "family": [_make_lesson("A")],
            "custom-audience": [_make_lesson("B")],
        }
        f = tmp_path / "lessons.yaml"
        f.write_text(yaml.dump(store), encoding="utf-8")
        loaded = load_lessons(f)
        assert "custom-audience" in loaded
        assert loaded["custom-audience"][0]["text"] == "B"

    def test_drops_malformed_entries(self, tmp_path: Path) -> None:
        raw = {
            "family": [
                {"text": "good", "success_count": 1, "added": "2026-01-01"},
                {"text": "missing count"},  # invalid
                "just a string",  # invalid
                {"text": "also good", "success_count": 2, "added": "2026-02-01"},
            ],
        }
        f = tmp_path / "lessons.yaml"
        f.write_text(yaml.dump(raw), encoding="utf-8")
        loaded = load_lessons(f)
        assert len(loaded["family"]) == 2
        assert loaded["family"][0]["text"] == "good"
        assert loaded["family"][1]["text"] == "also good"


# ---------------------------------------------------------------------------
# TestSaveLessons
# ---------------------------------------------------------------------------


class TestSaveLessons:
    def test_roundtrip(self, tmp_path: Path) -> None:
        store = {
            "family": [_make_lesson("Simplify jargon", 3, "2026-01-15")],
            "leadership": [_make_lesson("Lead with ROI", 1, "2026-02-01")],
        }
        f = tmp_path / "lessons.yaml"
        save_lessons(store, f)
        loaded = load_lessons(f)
        assert loaded == store

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c" / "lessons.yaml"
        store = {"family": [_make_lesson("test")]}
        save_lessons(store, deep)
        assert deep.exists()
        loaded = load_lessons(deep)
        assert loaded == store


# ---------------------------------------------------------------------------
# TestExtractLessons
# ---------------------------------------------------------------------------


class TestExtractLessons:
    def test_passing_multi_iteration_returns_adjustments(self) -> None:
        result = _make_eval_result(
            passed=True,
            iterations=2,
            adjustments=["Simplified jargon", "Added analogies"],
        )
        lessons = extract_lessons(result)
        assert lessons == ["Simplified jargon", "Added analogies"]

    def test_failing_returns_empty(self) -> None:
        result = _make_eval_result(passed=False, iterations=2, adjustments=["Fix tone"])
        assert extract_lessons(result) == []

    def test_first_iteration_pass_returns_empty(self) -> None:
        result = _make_eval_result(passed=True, iterations=1, adjustments=["Something"])
        assert extract_lessons(result) == []

    def test_filters_blank_lines(self) -> None:
        result = _make_eval_result(
            passed=True,
            iterations=2,
            adjustments=["Good lesson", "", "  ", "Another lesson"],
        )
        lessons = extract_lessons(result)
        assert lessons == ["Good lesson", "Another lesson"]


# ---------------------------------------------------------------------------
# TestAccumulateLessons
# ---------------------------------------------------------------------------


class TestAccumulateLessons:
    def test_adds_new_lessons(self) -> None:
        store: dict[str, list[Lesson]] = {}
        result = accumulate_lessons(store, "family", ["Use analogies", "Shorter sentences"])
        assert len(result["family"]) == 2
        assert result["family"][0]["text"] == "Use analogies"
        assert result["family"][0]["success_count"] == 1
        assert result["family"][0]["added"] == date.today().isoformat()

    def test_dedup_increments_count(self) -> None:
        store = {"family": [_make_lesson("Use analogies", 2, "2026-01-01")]}
        result = accumulate_lessons(store, "family", ["Use analogies"])
        assert len(result["family"]) == 1
        assert result["family"][0]["success_count"] == 3

    def test_prunes_oldest_at_max(self) -> None:
        # Fill with MAX lessons dated in the past
        existing = [
            _make_lesson(f"old-{i}", 1, f"2025-01-{i + 1:02d}")
            for i in range(MAX_LESSONS_PER_ARCHETYPE)
        ]
        store = {"family": existing}
        # Add one more — should push total to MAX+1, then prune oldest
        result = accumulate_lessons(store, "family", ["brand new lesson"])
        assert len(result["family"]) == MAX_LESSONS_PER_ARCHETYPE
        # The oldest entry (2025-01-01) should have been dropped
        texts = [l["text"] for l in result["family"]]
        assert "old-0" not in texts
        assert "brand new lesson" in texts

    def test_creates_archetype_if_missing(self) -> None:
        store = {"family": [_make_lesson("existing")]}
        result = accumulate_lessons(store, "leadership", ["New insight"])
        assert "leadership" in result
        assert result["leadership"][0]["text"] == "New insight"
        # Original archetype untouched
        assert "family" in result

    def test_empty_noop(self) -> None:
        store = {"family": [_make_lesson("existing")]}
        result = accumulate_lessons(store, "family", [])
        assert result == store

    def test_does_not_mutate_input(self) -> None:
        original_lesson = _make_lesson("Keep it simple", 1, "2026-01-01")
        store = {"family": [original_lesson]}
        store_copy = copy.deepcopy(store)
        accumulate_lessons(store, "family", ["New lesson"])
        assert store == store_copy


# ---------------------------------------------------------------------------
# TestFormatLessonsBlock
# ---------------------------------------------------------------------------


class TestFormatLessonsBlock:
    def test_empty_returns_empty_string(self) -> None:
        assert format_lessons_block([]) == ""

    def test_formats_single_lesson(self) -> None:
        result = format_lessons_block([_make_lesson("Use analogies", 1)])
        assert "- Use analogies" in result
        assert "(confirmed" not in result

    def test_shows_confirmation_count(self) -> None:
        result = format_lessons_block([_make_lesson("Use analogies", 5)])
        assert "(confirmed 5x)" in result

    def test_header_present(self) -> None:
        result = format_lessons_block([_make_lesson("test")])
        assert result.startswith("## LESSONS FROM PRIOR RUNS")
