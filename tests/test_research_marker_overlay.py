"""Tests for ResearchMarkerOverlay — LRR Phase 2 item 4.

Covers the visibility window logic (fresh vs stale marker, missing file,
corrupted JSON) plus the state() snapshot so concurrent render() calls
don't race against the marker file.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agents.studio_compositor.research_marker_overlay import (
    MARKER_VISIBILITY_SECONDS,
    ResearchMarkerOverlay,
    _parse_iso_utc,
)


def _write_marker(path: Path, *, condition_id: str, written_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "condition_id": condition_id,
                "written_at": written_at.isoformat().replace("+00:00", "Z"),
            }
        )
    )


class TestVisibilityWindow:
    def test_fresh_marker_is_visible(self, tmp_path: Path) -> None:
        marker = tmp_path / "research-marker.json"
        now = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
        _write_marker(marker, condition_id="cond-phase-a-baseline-qwen-001", written_at=now)

        overlay = ResearchMarkerOverlay(marker_path=marker, now_fn=lambda: now)
        state = overlay.state()
        assert state["visible"] is True
        assert state["condition_id"] == "cond-phase-a-baseline-qwen-001"

    def test_marker_at_exact_boundary_is_visible(self, tmp_path: Path) -> None:
        marker = tmp_path / "research-marker.json"
        written = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
        now = written + timedelta(seconds=MARKER_VISIBILITY_SECONDS)
        _write_marker(marker, condition_id="cond-x", written_at=written)

        overlay = ResearchMarkerOverlay(marker_path=marker, now_fn=lambda: now)
        state = overlay.state()
        assert state["visible"] is True

    def test_stale_marker_is_not_visible(self, tmp_path: Path) -> None:
        marker = tmp_path / "research-marker.json"
        written = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
        now = written + timedelta(seconds=MARKER_VISIBILITY_SECONDS + 1)
        _write_marker(marker, condition_id="cond-x", written_at=written)

        overlay = ResearchMarkerOverlay(marker_path=marker, now_fn=lambda: now)
        state = overlay.state()
        assert state["visible"] is False

    def test_future_marker_not_visible(self, tmp_path: Path) -> None:
        """If the clock skew makes the marker 'future' we treat it as not visible."""
        marker = tmp_path / "research-marker.json"
        now = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
        future = now + timedelta(seconds=10)
        _write_marker(marker, condition_id="cond-x", written_at=future)

        overlay = ResearchMarkerOverlay(marker_path=marker, now_fn=lambda: now)
        state = overlay.state()
        assert state["visible"] is False


class TestFailureModes:
    def test_missing_marker_file(self, tmp_path: Path) -> None:
        overlay = ResearchMarkerOverlay(marker_path=tmp_path / "nope.json")
        state = overlay.state()
        assert state == {"visible": False, "reason": "marker file absent"}

    def test_corrupt_json(self, tmp_path: Path) -> None:
        marker = tmp_path / "research-marker.json"
        marker.write_text("not json {{{")
        overlay = ResearchMarkerOverlay(marker_path=marker)
        state = overlay.state()
        assert state["visible"] is False
        assert "invalid json" in state["reason"]

    def test_unexpected_payload_type(self, tmp_path: Path) -> None:
        marker = tmp_path / "research-marker.json"
        marker.write_text(json.dumps(["not", "a", "dict"]))
        overlay = ResearchMarkerOverlay(marker_path=marker)
        state = overlay.state()
        assert state["visible"] is False

    def test_missing_fields(self, tmp_path: Path) -> None:
        marker = tmp_path / "research-marker.json"
        marker.write_text(json.dumps({"condition_id": "cond-x"}))  # missing written_at
        overlay = ResearchMarkerOverlay(marker_path=marker)
        state = overlay.state()
        assert state["visible"] is False
        assert "missing required fields" in state["reason"]

    def test_unparseable_written_at(self, tmp_path: Path) -> None:
        marker = tmp_path / "research-marker.json"
        marker.write_text(
            json.dumps({"condition_id": "cond-x", "written_at": "definitely not iso"})
        )
        overlay = ResearchMarkerOverlay(marker_path=marker)
        state = overlay.state()
        assert state["visible"] is False


class TestRenderCalls:
    def test_visible_state_triggers_draw(self, tmp_path: Path) -> None:
        marker = tmp_path / "research-marker.json"
        now = datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)
        _write_marker(marker, condition_id="cond-phase-a-baseline-qwen-001", written_at=now)

        overlay = ResearchMarkerOverlay(marker_path=marker, now_fn=lambda: now)
        cr = MagicMock()
        # cairo text_extents returns a 6-tuple (x_bearing, y_bearing, width, height, x_advance, y_advance).
        cr.text_extents.return_value = (0.0, 0.0, 420.0, 24.0, 430.0, 0.0)
        overlay.render(cr, canvas_w=1920, canvas_h=1080, t=0.0, state=overlay.state())
        # At least one fill call for the banner background
        assert cr.fill.call_count >= 1
        # Text shown
        cr.show_text.assert_called_once()
        args, _ = cr.show_text.call_args
        assert "cond-phase-a-baseline-qwen-001" in args[0]

    def test_invisible_state_only_clears(self, tmp_path: Path) -> None:
        overlay = ResearchMarkerOverlay(marker_path=tmp_path / "nope.json")
        cr = MagicMock()
        overlay.render(cr, canvas_w=1920, canvas_h=1080, t=0.0, state=overlay.state())
        # Clear-to-transparent always runs
        cr.paint.assert_called_once()
        # No banner drawn
        cr.show_text.assert_not_called()


class TestValidation:
    def test_zero_visibility_rejected(self) -> None:
        with pytest.raises(ValueError, match="visibility_seconds"):
            ResearchMarkerOverlay(visibility_seconds=0)

    def test_negative_visibility_rejected(self) -> None:
        with pytest.raises(ValueError, match="visibility_seconds"):
            ResearchMarkerOverlay(visibility_seconds=-1.0)


class TestIsoParse:
    def test_parse_z_suffix(self) -> None:
        parsed = _parse_iso_utc("2026-04-14T12:00:00Z")
        assert parsed is not None
        assert parsed == datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)

    def test_parse_offset_suffix(self) -> None:
        parsed = _parse_iso_utc("2026-04-14T12:00:00+00:00")
        assert parsed is not None
        assert parsed == datetime(2026, 4, 14, 12, 0, 0, tzinfo=UTC)

    def test_parse_with_microseconds(self) -> None:
        parsed = _parse_iso_utc("2026-04-14T12:00:00.123456Z")
        assert parsed is not None

    def test_reject_non_string(self) -> None:
        assert _parse_iso_utc(None) is None  # type: ignore[arg-type]
        assert _parse_iso_utc(12345) is None  # type: ignore[arg-type]

    def test_reject_garbage(self) -> None:
        assert _parse_iso_utc("total garbage") is None
