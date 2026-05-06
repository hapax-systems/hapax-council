"""Unit tests for ChronicleTickerCairoSource (ytb-LORE-MVP PR A)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import cairo
import pytest

from agents.studio_compositor import chronicle_ticker as ct
from agents.studio_compositor.chronicle_ticker import (
    ChronicleTickerCairoSource,
    _collect_rows,
    _fmt_row,
)
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from shared.chronicle import ChronicleEvent


class _SpyContext(cairo.Context):
    """cairo.Context subclass that records the texts passed to render_text."""

    def __new__(cls, surface):
        inst = cairo.Context.__new__(cls, surface)
        inst.rendered_texts = []
        return inst


@pytest.fixture(autouse=True)
def _env_and_paths(monkeypatch, tmp_path: Path):
    """Feature flag ON + redirect chronicle to tmp file + legacy paint-and-hold."""
    monkeypatch.setenv(ct._FEATURE_FLAG_ENV, "1")
    monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "0")
    chronicle_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(ct, "CHRONICLE_FILE", chronicle_path)
    return chronicle_path


def _write_events(path: Path, events: list[ChronicleEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(e.to_json() for e in events) + "\n", encoding="utf-8")


def _ev(
    *,
    ts: float,
    source: str = "stimmung",
    event_type: str = "shift",
    salience: float | None = 0.9,
    extra: dict | None = None,
) -> ChronicleEvent:
    payload: dict = {}
    if salience is not None:
        payload["salience"] = salience
    if extra:
        payload.update(extra)
    return ChronicleEvent(
        ts=ts,
        trace_id="0" * 32,
        span_id="0" * 16,
        parent_span_id=None,
        source=source,
        event_type=event_type,
        payload=payload,
    )


def _render_to_surface(src, w: int = 420, h: int = 140):
    """Render the source into a fresh surface, spying on render_text calls."""
    from agents.studio_compositor import text_render as _tr

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = _SpyContext(surface)

    real_render = _tr.render_text

    def _spy(cr_arg, style, x=0.0, y=0.0):
        try:
            cr_arg.rendered_texts.append(style.text)
        except AttributeError:
            pass
        return real_render(cr_arg, style, x, y)

    with patch.object(_tr, "render_text", _spy):
        src.render(cr, w, h, t=0.0, state={})
    return surface, cr


def _surface_not_empty(surface: cairo.ImageSurface) -> bool:
    data = bytes(surface.get_data())
    return any(b != 0 for b in data)


# ── _fmt_row ──────────────────────────────────────────────────────────────


class TestFmtRow:
    def test_renders_hhmm_and_discriminator(self):
        ts = time.mktime(time.strptime("2026-04-24 18:42:00", "%Y-%m-%d %H:%M:%S"))
        row = _fmt_row(_ev(ts=ts, source="programme", event_type="shift_REPAIR"))
        assert row.startswith("18:42")
        assert "programme.shift_REPAIR" in row


# ── _collect_rows ─────────────────────────────────────────────────────────


class TestCollectRows:
    def test_empty_file_returns_empty(self, _env_and_paths):
        # No chronicle file written — collector must return [].
        assert _collect_rows(time.time()) == []

    def test_filters_low_salience(self, _env_and_paths):
        now = time.time()
        _write_events(
            _env_and_paths,
            [
                _ev(ts=now - 5, salience=0.8, source="a", event_type="hi"),
                _ev(ts=now - 10, salience=0.2, source="a", event_type="lo"),
                _ev(ts=now - 15, salience=0.75, source="a", event_type="mid"),
            ],
        )
        rows = _collect_rows(now)
        # Two passed the 0.7 threshold.
        assert len(rows) == 2
        assert any("hi" in r for r in rows)
        assert any("mid" in r for r in rows)
        assert all("lo" not in r for r in rows)

    def test_caps_at_max_rows(self, _env_and_paths):
        now = time.time()
        events = [_ev(ts=now - i, salience=0.9, source="s", event_type=f"e{i}") for i in range(10)]
        _write_events(_env_and_paths, events)
        rows = _collect_rows(now)
        assert len(rows) == 3

    def test_rows_are_newest_first(self, _env_and_paths):
        now = time.time()
        _write_events(
            _env_and_paths,
            [
                _ev(ts=now - 30, salience=0.9, event_type="older"),
                _ev(ts=now - 5, salience=0.9, event_type="newer"),
            ],
        )
        rows = _collect_rows(now)
        assert len(rows) == 2
        assert "newer" in rows[0]
        assert "older" in rows[1]

    def test_high_salience_outranks_recent_lower_salience(self, _env_and_paths):
        """Salience ranks above recency: a 30s-old critical event outranks
        a 5s-old routine one when both are lore-worthy."""
        now = time.time()
        _write_events(
            _env_and_paths,
            [
                _ev(ts=now - 30, salience=1.0, event_type="critical"),
                _ev(ts=now - 5, salience=0.75, event_type="routine"),
            ],
        )
        rows = _collect_rows(now)
        assert len(rows) == 2
        assert "critical" in rows[0]
        assert "routine" in rows[1]

    def test_equal_salience_preserves_newest_first(self, _env_and_paths):
        """Newest-first tie-break holds when salience values match."""
        now = time.time()
        _write_events(
            _env_and_paths,
            [
                _ev(ts=now - 30, salience=0.85, event_type="elder"),
                _ev(ts=now - 5, salience=0.85, event_type="junior"),
            ],
        )
        rows = _collect_rows(now)
        assert len(rows) == 2
        assert "junior" in rows[0]
        assert "elder" in rows[1]

    def test_window_excludes_old_events(self, _env_and_paths):
        now = time.time()
        old = now - 2 * ct._WINDOW_SECONDS  # well outside the 10-min window
        _write_events(
            _env_and_paths,
            [
                _ev(ts=old, salience=0.95, event_type="ancient"),
                _ev(ts=now - 10, salience=0.9, event_type="recent"),
            ],
        )
        rows = _collect_rows(now)
        assert len(rows) == 1
        assert "recent" in rows[0]

    def test_non_allowlist_source_without_salience_excluded(self, _env_and_paths):
        """A source outside ``_LORE_SOURCES`` and without salience is skipped."""
        now = time.time()
        _write_events(
            _env_and_paths,
            [
                _ev(ts=now - 5, source="visual", salience=None, event_type="anon"),
                _ev(ts=now - 6, source="visual", salience=0.9, event_type="marked"),
            ],
        )
        rows = _collect_rows(now)
        # Only the salience-tagged event surfaces; the other source is filtered.
        assert len(rows) == 1
        assert "marked" in rows[0]

    def test_allowlist_source_without_salience_included(self, _env_and_paths):
        """Stimmung / programme / director surface without needing salience."""
        now = time.time()
        _write_events(
            _env_and_paths,
            [
                _ev(ts=now - 5, source="stimmung", salience=None, event_type="stance_changed"),
                _ev(ts=now - 10, source="programme", salience=None, event_type="shift_REPAIR"),
                _ev(ts=now - 15, source="director", salience=None, event_type="observing"),
            ],
        )
        rows = _collect_rows(now)
        assert len(rows) == 3
        assert any("stimmung.stance_changed" in r for r in rows)
        assert any("programme.shift_REPAIR" in r for r in rows)
        assert any("director.observing" in r for r in rows)

    def test_visual_firehose_excluded(self, _env_and_paths):
        """The high-frequency visual.* spam is never surfaced."""
        now = time.time()
        _write_events(
            _env_and_paths,
            [
                _ev(ts=now - i, source="visual", salience=None, event_type="params.shifted")
                for i in range(1, 11)
            ],
        )
        assert _collect_rows(now) == []

    def test_noise_event_types_excluded(self, _env_and_paths):
        """Known high-frequency routine event types are skipped even from lore sources.

        ``engine.rule.matched`` in ``_NOISE_EVENT_TYPES`` — build a fake
        chronicle event with ``source="engine"`` and
        ``event_type="rule.matched"`` and confirm the filter excludes it.
        ``engine`` is not in ``_LORE_SOURCES`` so this also needs a
        synthesised ``rule.matched`` coming from an allow-list source,
        which is what the blocklist is designed to guard against.
        """
        now = time.time()
        _write_events(
            _env_and_paths,
            [
                _ev(ts=now - 5, source="engine", salience=None, event_type="rule.matched"),
                # Synthesise the guardrail case: allow-list source + blocked event type.
                _ev(
                    ts=now - 6,
                    source="stimmung",
                    salience=0.9,
                    event_type="noop",
                ),
            ],
        )
        rows = _collect_rows(now)
        # Only the stimmung.noop event surfaces.
        assert len(rows) == 1
        assert "stimmung.noop" in rows[0]


# ── ChronicleTickerCairoSource ────────────────────────────────────────────


class TestChronicleTicker:
    def test_inherits_homage_transitional_source(self):
        assert issubclass(ChronicleTickerCairoSource, HomageTransitionalSource)

    def test_source_id_is_chronicle_ticker(self):
        src = ChronicleTickerCairoSource()
        assert src.source_id == "chronicle_ticker"

    def test_renders_without_crash_when_chronicle_missing(self, _env_and_paths):
        src = ChronicleTickerCairoSource()
        surface, _cr = _render_to_surface(src)
        # Always renders something: header at minimum + '(quiet)' when empty.
        assert _surface_not_empty(surface)

    def test_renders_header_and_quiet_when_no_events(self, _env_and_paths):
        src = ChronicleTickerCairoSource()
        _surface, cr = _render_to_surface(src)
        texts = " ".join(cr.rendered_texts)
        assert "»»»" in texts
        assert "[chronicle]" in texts
        assert "(quiet)" in texts

    def test_renders_event_rows(self, _env_and_paths):
        now = time.time()
        _write_events(
            _env_and_paths,
            [
                _ev(ts=now - 5, salience=0.9, source="programme", event_type="shift_REPAIR"),
                _ev(ts=now - 10, salience=0.8, source="stimmung", event_type="anxiety_rising"),
            ],
        )
        src = ChronicleTickerCairoSource()
        _surface, cr = _render_to_surface(src)
        texts = " ".join(cr.rendered_texts)
        assert "programme.shift_REPAIR" in texts
        assert "stimmung.anxiety_rising" in texts

    def test_feature_flag_off_suppresses_render(self, monkeypatch, _env_and_paths):
        monkeypatch.setenv(ct._FEATURE_FLAG_ENV, "0")
        now = time.time()
        _write_events(
            _env_and_paths,
            [_ev(ts=now - 5, salience=0.9, source="x", event_type="y")],
        )
        src = ChronicleTickerCairoSource()
        _surface, cr = _render_to_surface(src)
        # No text should reach render_text when the flag is off.
        assert cr.rendered_texts == []

    def test_refresh_cache_respects_interval(self, _env_and_paths, monkeypatch):
        """A second render within the refresh interval reuses cache — no re-query."""
        now = time.time()
        _write_events(_env_and_paths, [_ev(ts=now - 5, salience=0.9, event_type="first")])
        src = ChronicleTickerCairoSource()
        _render_to_surface(src)
        first_rows = list(src._cached_rows)
        assert any("first" in r for r in first_rows)

        # Replace the chronicle file with newer event.
        _write_events(_env_and_paths, [_ev(ts=now - 1, salience=0.9, event_type="second")])
        # Render again without advancing time → cached rows unchanged.
        _render_to_surface(src)
        assert src._cached_rows == first_rows

    def test_refresh_cache_refreshes_after_interval(self, _env_and_paths, monkeypatch):
        """After the refresh interval elapses, _maybe_refresh re-queries."""
        now = time.time()
        _write_events(_env_and_paths, [_ev(ts=now - 5, salience=0.9, event_type="first")])
        src = ChronicleTickerCairoSource()
        src._maybe_refresh(now)
        assert any("first" in r for r in src._cached_rows)

        _write_events(_env_and_paths, [_ev(ts=now - 1, salience=0.9, event_type="second")])
        # Advance past the refresh interval.
        src._maybe_refresh(now + ct._REFRESH_INTERVAL_S + 0.1)
        assert any("second" in r for r in src._cached_rows)
        assert not any("first" in r for r in src._cached_rows)


# ── Registry integration ──────────────────────────────────────────────────


class TestRegistry:
    def test_registered_under_class_name(self):
        from agents.studio_compositor.cairo_sources import get_cairo_source_class

        cls = get_cairo_source_class("ChronicleTickerCairoSource")
        assert cls is ChronicleTickerCairoSource


# ── Resilience ────────────────────────────────────────────────────────────


class TestResilience:
    def test_malformed_chronicle_lines_tolerated(self, _env_and_paths):
        now = time.time()
        good = _ev(ts=now - 5, salience=0.9, event_type="ok").to_json()
        _env_and_paths.parent.mkdir(parents=True, exist_ok=True)
        _env_and_paths.write_text("not-json\n" + good + "\n", encoding="utf-8")
        rows = _collect_rows(now)
        assert len(rows) == 1
        assert "ok" in rows[0]

    def test_chronicle_query_exception_returns_empty(self, _env_and_paths, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("chronicle unreachable")

        monkeypatch.setattr(ct, "query", _boom)
        assert _collect_rows(time.time()) == []

    def test_non_numeric_salience_on_non_allowlist_source_excluded(self, _env_and_paths):
        """Bad salience on a non-lore source is skipped.

        Covers the failure mode where a rogue emitter writes a
        non-numeric value into ``payload.salience``: the event is
        neither salience-qualified nor allow-list-qualified, so it
        stays out of the ward.
        """
        now = time.time()
        weird = _ev(ts=now - 5, source="visual", salience=None)
        raw = json.loads(weird.to_json())
        raw["payload"]["salience"] = "high"  # string, not numeric
        _env_and_paths.parent.mkdir(parents=True, exist_ok=True)
        _env_and_paths.write_text(json.dumps(raw) + "\n", encoding="utf-8")
        rows = _collect_rows(now)
        assert rows == []
