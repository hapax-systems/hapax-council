"""Unit tests for PrecedentTickerCairoSource."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import cairo
import pytest

from agents.studio_compositor import precedent_ticker_ward as pt
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from agents.studio_compositor.precedent_ticker_ward import (
    PrecedentTickerCairoSource,
    _collect_rows,
    _decision_glyph,
    _load_all_precedents,
    _row_for,
    _short_date,
)
from shared.axiom_registry import Precedent

# ── pure helpers ──────────────────────────────────────────────────────


class TestShortDate:
    def test_iso_date_truncates_to_mm_dd(self):
        assert _short_date("2026-05-04") == "05-04"

    def test_iso_with_trailing_time_still_works(self):
        assert _short_date("2026-05-04T03:30:00Z") == "05-04"

    def test_short_input_passes_through_truncated(self):
        # Empty string yields empty; partial yields up to 5 chars.
        assert _short_date("") == ""
        assert _short_date("abc") == "abc"

    def test_unexpected_format_does_not_crash(self):
        # No hyphens at expected positions → fall through truncated.
        assert _short_date("20260504") == "20260"


class TestDecisionGlyph:
    def test_compliant_maps_to_check(self):
        assert _decision_glyph("compliant") == "✓"

    def test_violation_maps_to_x(self):
        assert _decision_glyph("violation") == "✗"

    def test_non_compliant_maps_to_x(self):
        assert _decision_glyph("non-compliant") == "✗"

    def test_compliant_with_conditions_maps_to_approx(self):
        assert _decision_glyph("compliant-with-conditions") == "≈"

    def test_unknown_decision_maps_to_neutral_glyph(self):
        assert _decision_glyph("nonsense") == "·"

    def test_case_and_whitespace_tolerant(self):
        assert _decision_glyph("  COMPLIANT  ") == "✓"


class TestRowFor:
    def test_full_row(self):
        prec = Precedent(
            id="sp-su-001",
            axiom_id="single_user",
            decision="compliant",
            tier="T1",
            created="2026-05-04",
        )
        row = _row_for(prec)
        assert row.precedent_id == "sp-su-001"
        assert row.created == "05-04"
        assert row.tier == "T1"
        assert row.decision == "compliant"
        assert row.glyph == "✓"

    def test_missing_tier_renders_em_dash(self):
        prec = Precedent(id="x", axiom_id="single_user", decision="compliant", tier="")
        assert _row_for(prec).tier == "—"


# ── _load_all_precedents ──────────────────────────────────────────────


def _write_yaml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class TestLoadAllPrecedents:
    def test_reads_seed_list_schema(self, tmp_path: Path):
        _write_yaml(
            tmp_path / "seed" / "x.yaml",
            "axiom_id: single_user\n"
            "precedents:\n"
            "  - id: sp-1\n"
            "    decision: compliant\n"
            "    tier: T1\n"
            "    created: '2026-05-04'\n",
        )
        precedents = _load_all_precedents(tmp_path)
        assert len(precedents) == 1
        assert precedents[0].id == "sp-1"
        assert precedents[0].axiom_id == "single_user"

    def test_reads_standalone_schema(self, tmp_path: Path):
        _write_yaml(
            tmp_path / "sp-2.yaml",
            "precedent_id: sp-2\n"
            "axiom_id: executive_function\n"
            "decision: violation\n"
            "tier: T0\n"
            "created: '2026-04-30'\n",
        )
        precedents = _load_all_precedents(tmp_path)
        assert len(precedents) == 1
        assert precedents[0].id == "sp-2"
        assert precedents[0].axiom_id == "executive_function"

    def test_missing_precedents_dir_returns_empty(self, tmp_path: Path):
        assert _load_all_precedents(tmp_path / "does-not-exist") == []

    def test_malformed_yaml_skipped_silently(self, tmp_path: Path):
        good = tmp_path / "seed" / "good.yaml"
        bad = tmp_path / "seed" / "bad.yaml"
        good.parent.mkdir(parents=True)
        good.write_text(
            "axiom_id: x\n"
            "precedents:\n"
            "  - id: ok\n"
            "    decision: compliant\n"
            "    tier: T1\n"
            "    created: '2026-05-04'\n"
        )
        bad.write_text(":\n  - {[malformed")
        precedents = _load_all_precedents(tmp_path)
        assert [p.id for p in precedents] == ["ok"]

    def test_row_without_id_skipped(self, tmp_path: Path):
        _write_yaml(
            tmp_path / "seed" / "x.yaml",
            "axiom_id: x\n"
            "precedents:\n"
            "  - decision: compliant\n"  # no id → skip
            "  - id: ok\n"
            "    decision: compliant\n"
            "    tier: T1\n"
            "    created: '2026-05-04'\n",
        )
        precedents = _load_all_precedents(tmp_path)
        assert [p.id for p in precedents] == ["ok"]

    def test_seed_row_without_axiom_id_skipped(self, tmp_path: Path):
        # Multi-axiom seeds (no parent axiom_id) require row-level axiom_id.
        _write_yaml(
            tmp_path / "seed" / "multi.yaml",
            "precedents:\n"
            "  - id: orphan\n"
            "    decision: compliant\n"
            "    tier: T1\n"  # no axiom_id at row or parent
            "  - id: anchored\n"
            "    axiom_id: single_user\n"
            "    decision: compliant\n"
            "    tier: T1\n"
            "    created: '2026-05-04'\n",
        )
        precedents = _load_all_precedents(tmp_path)
        assert [p.id for p in precedents] == ["anchored"]


# ── _collect_rows ─────────────────────────────────────────────────────


class TestCollectRows:
    def test_returns_empty_when_no_precedents(self, tmp_path: Path):
        assert _collect_rows(tmp_path) == []

    def test_caps_at_max_rows(self, tmp_path: Path):
        body = "axiom_id: x\nprecedents:\n"
        for i in range(10):
            body += (
                f"  - id: sp-{i}\n"
                f"    decision: compliant\n"
                f"    tier: T1\n"
                f"    created: '2026-05-{i:02d}'\n"
            )
        _write_yaml(tmp_path / "seed" / "x.yaml", body)
        rows = _collect_rows(tmp_path)
        assert len(rows) == 3

    def test_orders_newest_first(self, tmp_path: Path):
        _write_yaml(
            tmp_path / "seed" / "x.yaml",
            "axiom_id: x\n"
            "precedents:\n"
            "  - id: old\n"
            "    decision: compliant\n"
            "    tier: T1\n"
            "    created: '2026-01-01'\n"
            "  - id: new\n"
            "    decision: compliant\n"
            "    tier: T1\n"
            "    created: '2026-05-04'\n",
        )
        rows = _collect_rows(tmp_path)
        assert rows[0].precedent_id == "new"
        assert rows[1].precedent_id == "old"

    def test_stable_secondary_sort_on_id(self, tmp_path: Path):
        # Same date — id (descending) breaks the tie deterministically.
        _write_yaml(
            tmp_path / "seed" / "x.yaml",
            "axiom_id: x\n"
            "precedents:\n"
            "  - id: sp-a\n"
            "    decision: compliant\n"
            "    tier: T1\n"
            "    created: '2026-05-04'\n"
            "  - id: sp-z\n"
            "    decision: compliant\n"
            "    tier: T1\n"
            "    created: '2026-05-04'\n",
        )
        first_call = _collect_rows(tmp_path)
        second_call = _collect_rows(tmp_path)
        assert [r.precedent_id for r in first_call] == [r.precedent_id for r in second_call]


# ── render path ───────────────────────────────────────────────────────


class _SpyContext(cairo.Context):
    def __new__(cls, surface):
        inst = cairo.Context.__new__(cls, surface)
        inst.rendered_texts = []
        return inst


@pytest.fixture
def env(monkeypatch, tmp_path: Path):
    """Feature flag ON + redirect AXIOMS_PATH to tmp + paint-and-hold."""
    monkeypatch.setenv(pt._FEATURE_FLAG_ENV, "1")
    monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "0")
    return tmp_path


def _render(src, w: int = 460, h: int = 140):
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
    return any(b != 0 for b in bytes(surface.get_data()))


class TestPrecedentTickerCairoSource:
    def test_inherits_homage_transitional_source(self):
        assert issubclass(PrecedentTickerCairoSource, HomageTransitionalSource)

    def test_source_id(self):
        assert PrecedentTickerCairoSource().source_id == "precedent_ticker"

    def test_renders_without_crash_when_no_precedents(self, env):
        # Empty AXIOMS_PATH dir → empty state.
        with patch.object(pt, "_collect_rows", return_value=[]):
            src = PrecedentTickerCairoSource()
            surface, cr = _render(src)
        assert _surface_not_empty(surface)
        texts = " ".join(cr.rendered_texts)
        assert "»»»" in texts
        assert "[precedent]" in texts
        assert "(no precedents)" in texts

    def test_renders_precedent_rows(self, env):
        rows = [
            pt._PrecedentRow(
                precedent_id="sp-su-001",
                created="05-04",
                tier="T1",
                decision="compliant",
                glyph="✓",
            ),
            pt._PrecedentRow(
                precedent_id="sp-su-004",
                created="05-03",
                tier="T0",
                decision="violation",
                glyph="✗",
            ),
        ]
        with patch.object(pt, "_collect_rows", return_value=rows):
            src = PrecedentTickerCairoSource()
            _surface, cr = _render(src)
        texts = " ".join(cr.rendered_texts)
        assert "sp-su-001" in texts
        assert "✓" in texts and "compliant" in texts
        assert "sp-su-004" in texts
        assert "✗" in texts and "violation" in texts

    def test_feature_flag_off_suppresses_render(self, monkeypatch, env):
        monkeypatch.setenv(pt._FEATURE_FLAG_ENV, "0")
        with patch.object(pt, "_collect_rows") as mock_collect:
            mock_collect.return_value = [
                pt._PrecedentRow("sp-1", "05-04", "T1", "compliant", "✓"),
            ]
            src = PrecedentTickerCairoSource()
            _surface, cr = _render(src)
        assert cr.rendered_texts == []

    def test_refresh_cache_respects_interval(self, env):
        """A second render within the refresh interval reuses the cache."""
        rows_a = [pt._PrecedentRow("sp-A", "05-04", "T1", "compliant", "✓")]
        rows_b = [pt._PrecedentRow("sp-B", "05-04", "T1", "compliant", "✓")]
        src = PrecedentTickerCairoSource()
        with patch.object(pt, "_collect_rows", return_value=rows_a):
            src._maybe_refresh(time.time())
        first = list(src._cached_rows)
        assert first == rows_a
        # Second call with new data inside the cache window — must NOT
        # re-query (cached_rows still rows_a).
        with patch.object(pt, "_collect_rows", return_value=rows_b):
            src._maybe_refresh(time.time())
        assert src._cached_rows == first

    def test_refresh_cache_advances_after_interval(self, env):
        rows_a = [pt._PrecedentRow("sp-A", "05-04", "T1", "compliant", "✓")]
        rows_b = [pt._PrecedentRow("sp-B", "05-04", "T1", "violation", "✗")]
        src = PrecedentTickerCairoSource()
        with patch.object(pt, "_collect_rows", return_value=rows_a):
            now = time.time()
            src._maybe_refresh(now)
        with patch.object(pt, "_collect_rows", return_value=rows_b):
            src._maybe_refresh(now + pt._REFRESH_INTERVAL_S + 0.1)
        assert src._cached_rows == rows_b


# ── registry ──────────────────────────────────────────────────────────


class TestRegistry:
    def test_registered_under_class_name(self):
        from agents.studio_compositor.cairo_sources import get_cairo_source_class

        cls = get_cairo_source_class("PrecedentTickerCairoSource")
        assert cls is PrecedentTickerCairoSource


# ── consent / redaction safety ────────────────────────────────────────


class TestRedactionSafety:
    """Ward must surface only operator-ratified case-law fields.

    The cc-task spec calls out: "redaction-safe (no operator PII, no raw
    chat author IDs)". Precedents carry operator-ratified text only; the
    ward must never surface anything outside the schema's fields, and
    must especially never pick up free-form ``reasoning`` (which can
    quote operator deliberation in detail).
    """

    def test_reasoning_field_never_rendered(self, env):
        prec = Precedent(
            id="sp-x",
            axiom_id="x",
            situation="situation that should not surface",
            decision="compliant",
            reasoning="REASONING TEXT WITH OPERATOR PERSONAL DETAILS",
            tier="T1",
            created="2026-05-04",
        )
        rows = [_row_for(prec)]
        with patch.object(pt, "_collect_rows", return_value=rows):
            src = PrecedentTickerCairoSource()
            _surface, cr = _render(src)
        joined = " ".join(cr.rendered_texts)
        assert "REASONING TEXT WITH OPERATOR PERSONAL DETAILS" not in joined
        assert "situation that should not surface" not in joined
