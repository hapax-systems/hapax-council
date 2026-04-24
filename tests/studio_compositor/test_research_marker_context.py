"""Tests for ytb-LORE-MVP PR C — research-marker sprint-context subtext.

Pins behavior of the ``HAPAX_LORE_RESEARCH_MARKER_CONTEXT_ENABLED``
feature flag + sprint-state read path on
:class:`ResearchMarkerOverlay._draw_banner`.

Feature-flag-OFF path is validated by the shipped
``test_research_marker_emissive`` suite (byte-level golden image
unchanged). These tests cover:

* flag-parser recognizes truthy values
* sprint-line / next-block formatters handle partial / empty state
* read path degrades silently when sprint file is absent / malformed
* ``_draw_banner`` runs cleanly with flag ON (ward stays non-blank)
* ``_draw_banner`` under flag ON tolerates a missing sprint file
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest

from agents.studio_compositor import research_marker_overlay


def _cairo_available() -> bool:
    try:
        import cairo  # noqa: F401
    except ImportError:
        return False
    return True


_HAS_CAIRO = _cairo_available()
requires_cairo = pytest.mark.skipif(not _HAS_CAIRO, reason="pycairo not installed")

_FROZEN_NOW = datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC)


# ── feature-flag parser ───────────────────────────────────────────────


class TestContextEnabledParser:
    @pytest.mark.parametrize("truthy", ["1", "true", "TRUE", "yes", "on", " 1 "])
    def test_truthy_values_enable(self, truthy: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(research_marker_overlay.CONTEXT_FEATURE_FLAG_ENV, truthy)
        assert research_marker_overlay._context_enabled()

    @pytest.mark.parametrize("falsy", ["", "0", "false", "FALSE", "no", "off"])
    def test_falsy_values_disable(self, falsy: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(research_marker_overlay.CONTEXT_FEATURE_FLAG_ENV, falsy)
        assert not research_marker_overlay._context_enabled()

    def test_absent_env_disables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(research_marker_overlay.CONTEXT_FEATURE_FLAG_ENV, raising=False)
        assert not research_marker_overlay._context_enabled()


# ── sprint-state reader ───────────────────────────────────────────────


class TestReadSprintState:
    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        assert research_marker_overlay._read_sprint_state(tmp_path / "nope.json") is None

    def test_returns_dict_on_valid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "sprint.json"
        path.write_text(json.dumps({"current_sprint": 0, "current_day": 26}))
        state = research_marker_overlay._read_sprint_state(path)
        assert state == {"current_sprint": 0, "current_day": 26}

    def test_returns_none_on_malformed_json(self, tmp_path: Path) -> None:
        path = tmp_path / "sprint.json"
        path.write_text("{not json")
        assert research_marker_overlay._read_sprint_state(path) is None

    def test_returns_none_on_non_dict_payload(self, tmp_path: Path) -> None:
        path = tmp_path / "sprint.json"
        path.write_text("[1, 2, 3]")
        assert research_marker_overlay._read_sprint_state(path) is None


# ── line formatters ───────────────────────────────────────────────────


class TestFormatSprintLine:
    def test_renders_canonical_line(self) -> None:
        state = {
            "current_sprint": 0,
            "current_day": 26,
            "measures_completed": 14,
            "measures_total": 28,
        }
        assert (
            research_marker_overlay._format_sprint_line(state)
            == "sprint 0 · day 26  14/28 measures"
        )

    def test_missing_field_returns_none(self) -> None:
        partial = {"current_sprint": 0, "current_day": 26}
        assert research_marker_overlay._format_sprint_line(partial) is None


class TestFormatNextBlockLine:
    def test_renders_measure_and_title(self) -> None:
        state = {"next_block": {"measure": "7.2", "title": "Claim 5 correlation analysis"}}
        assert (
            research_marker_overlay._format_next_block_line(state)
            == "next: [7.2] Claim 5 correlation analysis"
        )

    def test_renders_title_only_when_measure_missing(self) -> None:
        state = {"next_block": {"title": "free block"}}
        assert research_marker_overlay._format_next_block_line(state) == "next: free block"

    def test_returns_none_when_next_block_absent(self) -> None:
        assert research_marker_overlay._format_next_block_line({}) is None

    def test_returns_none_when_title_empty(self) -> None:
        assert (
            research_marker_overlay._format_next_block_line({"next_block": {"measure": "1.1"}})
            is None
        )

    def test_returns_none_when_next_block_not_dict(self) -> None:
        assert research_marker_overlay._format_next_block_line({"next_block": "x"}) is None


# ── draw_banner behavior under the flag ──────────────────────────────


@requires_cairo
class TestDrawBannerContextFlag:
    @staticmethod
    def _make_surface():
        import cairo

        return cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 120)

    def test_flag_off_does_not_read_sprint_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import cairo

        monkeypatch.delenv(research_marker_overlay.CONTEXT_FEATURE_FLAG_ENV, raising=False)
        surface = self._make_surface()
        cr = cairo.Context(surface)
        overlay = research_marker_overlay.ResearchMarkerOverlay(
            now_fn=lambda: _FROZEN_NOW,
            sprint_state_path=tmp_path / "sprint.json",
        )
        with mock.patch.object(
            research_marker_overlay,
            "_read_sprint_state",
            wraps=research_marker_overlay._read_sprint_state,
        ) as spy:
            overlay._draw_banner(cr, 1920, 120, "cond-test-001")
        spy.assert_not_called()

    def test_flag_on_reads_sprint_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import cairo

        monkeypatch.setenv(research_marker_overlay.CONTEXT_FEATURE_FLAG_ENV, "1")
        sprint_path = tmp_path / "sprint.json"
        sprint_path.write_text(
            json.dumps(
                {
                    "current_sprint": 0,
                    "current_day": 26,
                    "measures_completed": 14,
                    "measures_total": 28,
                    "next_block": {"measure": "7.2", "title": "correlation"},
                }
            )
        )
        surface = self._make_surface()
        cr = cairo.Context(surface)
        overlay = research_marker_overlay.ResearchMarkerOverlay(
            now_fn=lambda: _FROZEN_NOW,
            sprint_state_path=sprint_path,
        )
        with mock.patch.object(
            research_marker_overlay,
            "_read_sprint_state",
            wraps=research_marker_overlay._read_sprint_state,
        ) as spy:
            overlay._draw_banner(cr, 1920, 120, "cond-test-001")
        spy.assert_called_once_with(sprint_path)
        surface.flush()
        data = bytes(surface.get_data())
        # Banner paints a 96-px ground when flag ON — confirm at least
        # one byte in the subtext band (rows 64–95) is non-transparent.
        stride = surface.get_stride()
        subtext_start = 64 * stride
        subtext_end = 96 * stride
        assert any(b != 0 for b in data[subtext_start:subtext_end])

    def test_flag_on_sprint_file_missing_renders_core_band_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import cairo

        monkeypatch.setenv(research_marker_overlay.CONTEXT_FEATURE_FLAG_ENV, "1")
        surface = self._make_surface()
        cr = cairo.Context(surface)
        overlay = research_marker_overlay.ResearchMarkerOverlay(
            now_fn=lambda: _FROZEN_NOW,
            sprint_state_path=tmp_path / "does-not-exist.json",
        )
        # Must not raise, and the core (top 64-px) band still renders.
        overlay._draw_banner(cr, 1920, 120, "cond-test-001")
        surface.flush()
        data = bytes(surface.get_data())
        stride = surface.get_stride()
        core_start = 0
        core_end = 64 * stride
        assert any(b != 0 for b in data[core_start:core_end])

    def test_flag_on_malformed_sprint_json_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import cairo

        monkeypatch.setenv(research_marker_overlay.CONTEXT_FEATURE_FLAG_ENV, "1")
        sprint_path = tmp_path / "sprint.json"
        sprint_path.write_text("{broken")
        surface = self._make_surface()
        cr = cairo.Context(surface)
        overlay = research_marker_overlay.ResearchMarkerOverlay(
            now_fn=lambda: _FROZEN_NOW,
            sprint_state_path=sprint_path,
        )
        overlay._draw_banner(cr, 1920, 120, "cond-test-001")  # must not raise
