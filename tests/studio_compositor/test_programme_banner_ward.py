"""Tests for agents.studio_compositor.programme_banner_ward (cc-task programme-banner-ward).

Pin the residual-time math, the narrative-beat truncation, the state-
snapshot path with mocked store, and render-no-crash on edge cases.
Cairo render is exercised against an in-memory ImageSurface so no
display server / GStreamer is needed.
"""

from __future__ import annotations

from unittest.mock import patch

import cairo
import pytest

from agents.studio_compositor.programme_banner_ward import (
    NARRATIVE_BEAT_MAX_CHARS,
    ProgrammeBannerWard,
    compute_residual_s,
    format_residual,
    truncate_beat,
)


class TestFormatResidual:
    def test_zero_seconds(self) -> None:
        assert format_residual(0.0) == "0m 0s"

    def test_negative_clamps_to_zero(self) -> None:
        """Programme overrun must NOT render negative time; planner /
        manager owns transition, ward stays neutral."""
        assert format_residual(-30.0) == "0m 0s"

    def test_one_minute_five_seconds(self) -> None:
        assert format_residual(65.0) == "1m 5s"

    def test_under_one_minute(self) -> None:
        assert format_residual(45.0) == "0m 45s"

    def test_one_hour_exact(self) -> None:
        assert format_residual(3600.0) == "60m 0s"

    def test_long_programme(self) -> None:
        """90-minute programme: 5400 seconds → 90m 0s (no HH:MM)."""
        assert format_residual(5400.0) == "90m 0s"

    def test_fractional_seconds_truncate(self) -> None:
        """Sub-second residual rounds DOWN to the integer second."""
        assert format_residual(65.7) == "1m 5s"


class TestTruncateBeat:
    def test_none_returns_empty(self) -> None:
        assert truncate_beat(None) == ""

    def test_empty_string_returns_empty(self) -> None:
        assert truncate_beat("") == ""

    def test_whitespace_only_returns_empty(self) -> None:
        assert truncate_beat("   \n\t") == ""

    def test_short_beat_passes_through(self) -> None:
        assert truncate_beat("brief direction") == "brief direction"

    def test_strips_surrounding_whitespace(self) -> None:
        assert truncate_beat("  trim me  ") == "trim me"

    def test_at_max_passes_through(self) -> None:
        text = "x" * NARRATIVE_BEAT_MAX_CHARS
        assert truncate_beat(text) == text

    def test_above_max_truncates_with_ellipsis(self) -> None:
        text = "x" * (NARRATIVE_BEAT_MAX_CHARS + 20)
        result = truncate_beat(text)
        assert len(result) == NARRATIVE_BEAT_MAX_CHARS
        assert result.endswith("…")

    def test_custom_max_chars(self) -> None:
        result = truncate_beat("the quick brown fox jumps", max_chars=10)
        assert len(result) == 10
        assert result.endswith("…")


class TestComputeResidualS:
    def test_no_start_returns_full_duration(self) -> None:
        """A planned-but-not-started programme renders the full window."""
        assert compute_residual_s(None, 600.0) == 600.0

    def test_just_started(self) -> None:
        residual = compute_residual_s(1000.0, 600.0, now=1001.0)
        assert residual == pytest.approx(599.0)

    def test_halfway(self) -> None:
        residual = compute_residual_s(1000.0, 600.0, now=1300.0)
        assert residual == pytest.approx(300.0)

    def test_completed(self) -> None:
        residual = compute_residual_s(1000.0, 600.0, now=1600.0)
        assert residual == pytest.approx(0.0)

    def test_overrun_negative(self) -> None:
        """Past planned end → negative residual; format_residual clamps."""
        residual = compute_residual_s(1000.0, 600.0, now=1700.0)
        assert residual == pytest.approx(-100.0)


class TestStateSnapshot:
    """state() reads default_store().active_programme() with import + run guards."""

    def test_max_beat_chars_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_beat_chars must be"):
            ProgrammeBannerWard(max_beat_chars=0)

    def test_no_active_programme_yields_active_none(self) -> None:
        ward = ProgrammeBannerWard()
        with patch(
            "shared.programme_store.default_store",
        ) as mock_store_factory:
            mock_store_factory.return_value.active_programme.return_value = None
            state = ward.state()
        assert state == {"active": None}

    def test_active_programme_snapshot_shape(self) -> None:
        from types import SimpleNamespace

        ward = ProgrammeBannerWard()
        fake_programme = SimpleNamespace(
            role="experiment",
            content=SimpleNamespace(narrative_beat="follow the spectral mutation"),
            actual_started_at=1000.0,
            planned_duration_s=600.0,
        )
        with patch("shared.programme_store.default_store") as mock_factory:
            mock_factory.return_value.active_programme.return_value = fake_programme
            state = ward.state()
        assert state == {
            "active": {
                "role": "experiment",
                "narrative_beat": "follow the spectral mutation",
                "actual_started_at": 1000.0,
                "planned_duration_s": 600.0,
            }
        }

    def test_store_load_failure_yields_active_none(self) -> None:
        """A broken store must NOT crash the compositor render thread."""
        ward = ProgrammeBannerWard()
        with patch("shared.programme_store.default_store") as mock_factory:
            mock_factory.side_effect = OSError("disk failure")
            state = ward.state()
        assert state == {"active": None}

    def test_active_programme_call_failure_yields_active_none(self) -> None:
        ward = ProgrammeBannerWard()
        with patch("shared.programme_store.default_store") as mock_factory:
            mock_factory.return_value.active_programme.side_effect = RuntimeError("boom")
            state = ward.state()
        assert state == {"active": None}


class TestRenderEdgeCases:
    """Render must complete without exceptions on every edge case
    (compositor render thread can't tolerate a Cairo crash)."""

    def _new_context(self) -> tuple[cairo.ImageSurface, cairo.Context]:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 1080)
        return surface, cairo.Context(surface)

    def test_render_no_active_programme_does_not_crash(self) -> None:
        ward = ProgrammeBannerWard()
        _surface, cr = self._new_context()
        ward.render(cr, 1920, 1080, 0.0, {"active": None})
        # Should produce a fully-cleared transparent surface (no banner).

    def test_render_full_programme(self) -> None:
        ward = ProgrammeBannerWard()
        _surface, cr = self._new_context()
        ward.render(
            cr,
            1920,
            1080,
            0.0,
            {
                "active": {
                    "role": "experiment",
                    "narrative_beat": "follow the spectral mutation",
                    "actual_started_at": 1000.0,
                    "planned_duration_s": 600.0,
                }
            },
        )

    def test_render_missing_role_yields_no_banner(self) -> None:
        """Missing role would produce a blank box; ward must short-circuit."""
        ward = ProgrammeBannerWard()
        _surface, cr = self._new_context()
        ward.render(
            cr,
            1920,
            1080,
            0.0,
            {
                "active": {
                    "role": "",
                    "narrative_beat": "x",
                    "actual_started_at": 1000.0,
                    "planned_duration_s": 600.0,
                }
            },
        )

    def test_render_none_narrative_beat(self) -> None:
        ward = ProgrammeBannerWard()
        _surface, cr = self._new_context()
        ward.render(
            cr,
            1920,
            1080,
            0.0,
            {
                "active": {
                    "role": "ritual",
                    "narrative_beat": None,
                    "actual_started_at": 1000.0,
                    "planned_duration_s": 600.0,
                }
            },
        )

    def test_render_at_smaller_canvas(self) -> None:
        """Preview / mobile canvas must not collapse the banner."""
        ward = ProgrammeBannerWard()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 640, 360)
        cr = cairo.Context(surface)
        ward.render(
            cr,
            640,
            360,
            0.0,
            {
                "active": {
                    "role": "wind_down",
                    "narrative_beat": "let the room go quiet",
                    "actual_started_at": 1000.0,
                    "planned_duration_s": 300.0,
                }
            },
        )

    def test_render_very_long_narrative_beat(self) -> None:
        """200-char narrative_beat must truncate, not wrap forever."""
        ward = ProgrammeBannerWard()
        _surface, cr = self._new_context()
        long_beat = "the spectral mutation continues to refract through " * 5
        ward.render(
            cr,
            1920,
            1080,
            0.0,
            {
                "active": {
                    "role": "experiment",
                    "narrative_beat": long_beat,
                    "actual_started_at": 1000.0,
                    "planned_duration_s": 600.0,
                }
            },
        )


class TestShowDontTellInvariant:
    """Per cc-task spec + memory feedback_show_dont_tell_director: the
    ward announces programme STATE — it does NOT script narration or
    announce director moves. Pin via negative assertions."""

    def test_render_writes_no_director_move_strings(self) -> None:
        """The Cairo text path must not emit any string referencing
        director moves or scripted narration."""
        from unittest.mock import MagicMock

        ward = ProgrammeBannerWard()
        cr = MagicMock(spec=cairo.Context)
        ward.render(
            cr,
            1920,
            1080,
            0.0,
            {
                "active": {
                    "role": "experiment",
                    "narrative_beat": "follow the spectral mutation",
                    "actual_started_at": 1000.0,
                    "planned_duration_s": 600.0,
                }
            },
        )
        # Collect every string passed to show_text.
        shown = [c.args[0] for c in cr.show_text.call_args_list if c.args]
        forbidden_substrings = (
            "and now",
            "next up",
            "Hapax says",
            "Hapax thinks",
            "let me",
            "I will",
        )
        for s in shown:
            for forbidden in forbidden_substrings:
                assert forbidden.lower() not in s.lower(), (
                    f"banner emitted scripted-narration phrase {forbidden!r} in {s!r}"
                )

    def test_state_does_not_carry_intent_or_script(self) -> None:
        """state() must not surface director-loop fields (intent, last
        move, scripted lines) — only programme STATE."""
        from types import SimpleNamespace

        ward = ProgrammeBannerWard()
        fake_programme = SimpleNamespace(
            role="experiment",
            content=SimpleNamespace(narrative_beat="x"),
            actual_started_at=1000.0,
            planned_duration_s=600.0,
        )
        with patch("shared.programme_store.default_store") as mock_factory:
            mock_factory.return_value.active_programme.return_value = fake_programme
            state = ward.state()
        active = state["active"]
        # Only these 4 keys; nothing leaking from director-loop adjacent code.
        assert set(active.keys()) == {
            "role",
            "narrative_beat",
            "actual_started_at",
            "planned_duration_s",
        }
