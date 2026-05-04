"""Tests for the hybrid Moksha+BitchX research-instrument-dashboard ward.

Pinned by tests:

* Default-OFF feature flag: an unset / "0" env produces a no-op render
  (transparent canvas) so the ward never surprises a viewer mid-broadcast
  on first deploy.
* Empty-state silence: no marker AND no claims ⇒ no-op render. The
  ward squats no pixels in the steady state where research is not
  configured.
* Empty-state header: marker present but no claims ⇒ frame + header +
  active-condition line render. Tests that ``render_content`` paints
  *something* in this case (line-count > 0 in the cairo recording
  surface).
* Status palette routing: a passing claim resolves to ``accent_green``,
  a failing to ``accent_red``, an unverified to ``accent_yellow``.
  Pinned via ``ClaimRow`` properties so a future palette swap is
  visible in the diff.
* No hardcoded hex: the ward never calls ``set_source_rgba`` with
  values not derived from a HomagePackage ``resolve_colour`` call.
* Claims YAML loader: missing file → []; malformed → []; valid
  schema → ClaimRow list with the right fields.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

# ── Module loader ───────────────────────────────────────────────────────


@pytest.fixture()
def ward_module():
    """Import the ward module fresh per test (env-flag tests need this)."""
    import importlib

    import agents.studio_compositor.research_instrument_dashboard_ward as mod

    importlib.reload(mod)
    return mod


# ── Claims YAML loader ──────────────────────────────────────────────────


class TestLoadClaims:
    def test_missing_file_returns_empty(self, ward_module, tmp_path: Path):
        result = ward_module.load_claims(tmp_path / "no.yaml")
        assert result == []

    def test_malformed_yaml_returns_empty(self, ward_module, tmp_path: Path):
        bad = tmp_path / "claims.yaml"
        bad.write_text(":::not yaml at all{{{", encoding="utf-8")
        assert ward_module.load_claims(bad) == []

    def test_top_level_not_dict_returns_empty(self, ward_module, tmp_path: Path):
        bad = tmp_path / "claims.yaml"
        bad.write_text("- just a list\n", encoding="utf-8")
        assert ward_module.load_claims(bad) == []

    def test_valid_schema_yields_claim_rows(self, ward_module, tmp_path: Path):
        good = tmp_path / "claims.yaml"
        good.write_text(
            """
claims:
  - condition_id: cond-A
    metric: latency_p50_ms
    status: passing
  - condition_id: cond-B
    metric: uptime_min
    status: failing
""",
            encoding="utf-8",
        )
        rows = ward_module.load_claims(good)
        assert len(rows) == 2
        assert rows[0].condition_id == "cond-A"
        assert rows[0].metric == "latency_p50_ms"
        assert rows[0].status == "passing"
        assert rows[1].status == "failing"

    def test_target_condition_alias_works(self, ward_module, tmp_path: Path):
        good = tmp_path / "claims.yaml"
        good.write_text(
            """
claims:
  - target_condition: cond-X
    metric: throughput
    status: unverified
""",
            encoding="utf-8",
        )
        rows = ward_module.load_claims(good)
        assert len(rows) == 1
        assert rows[0].condition_id == "cond-X"

    def test_partial_schema_rows_skipped(self, ward_module, tmp_path: Path):
        good = tmp_path / "claims.yaml"
        good.write_text(
            """
claims:
  - condition_id: cond-A
    metric: m
    status: passing
  - metric: orphan      # no condition
    status: passing
  - condition_id: cond-B
    status: failing     # no metric
  - condition_id: cond-C
    metric: m
                         # no status
""",
            encoding="utf-8",
        )
        rows = ward_module.load_claims(good)
        # Only the first row is fully populated.
        assert len(rows) == 1
        assert rows[0].condition_id == "cond-A"

    def test_status_normalized_to_lowercase(self, ward_module, tmp_path: Path):
        good = tmp_path / "claims.yaml"
        good.write_text(
            """
claims:
  - condition_id: cond-A
    metric: m
    status: PASSING
""",
            encoding="utf-8",
        )
        rows = ward_module.load_claims(good)
        assert rows[0].status == "passing"


# ── ClaimRow status routing ─────────────────────────────────────────────


class TestClaimRowStatusRouting:
    def test_passing_routes_to_green(self, ward_module):
        row = ward_module.ClaimRow(condition_id="cond", metric="m", status="passing")
        assert row.status_palette_role == "accent_green"
        assert "pass" in row.status_glyph

    def test_failing_routes_to_red(self, ward_module):
        row = ward_module.ClaimRow(condition_id="cond", metric="m", status="failing")
        assert row.status_palette_role == "accent_red"
        assert "fail" in row.status_glyph

    def test_unverified_routes_to_yellow(self, ward_module):
        row = ward_module.ClaimRow(condition_id="cond", metric="m", status="unverified")
        assert row.status_palette_role == "accent_yellow"
        assert "unver" in row.status_glyph

    def test_unknown_status_falls_through_to_muted(self, ward_module):
        row = ward_module.ClaimRow(condition_id="cond", metric="m", status="weird")
        assert row.status_palette_role == "muted"
        assert row.status_glyph == "- ?"


# ── Feature flag ────────────────────────────────────────────────────────


class TestFeatureFlag:
    def test_unset_is_off(self, ward_module, monkeypatch):
        monkeypatch.delenv("HAPAX_LORE_RESEARCH_INSTRUMENT_DASHBOARD_ENABLED", raising=False)
        assert ward_module._feature_flag_enabled() is False

    def test_zero_is_off(self, ward_module, monkeypatch):
        monkeypatch.setenv("HAPAX_LORE_RESEARCH_INSTRUMENT_DASHBOARD_ENABLED", "0")
        assert ward_module._feature_flag_enabled() is False

    def test_one_is_on(self, ward_module, monkeypatch):
        monkeypatch.setenv("HAPAX_LORE_RESEARCH_INSTRUMENT_DASHBOARD_ENABLED", "1")
        assert ward_module._feature_flag_enabled() is True

    def test_truthy_words_on(self, ward_module, monkeypatch):
        for v in ("true", "yes", "on", "TRUE"):
            monkeypatch.setenv("HAPAX_LORE_RESEARCH_INSTRUMENT_DASHBOARD_ENABLED", v)
            assert ward_module._feature_flag_enabled() is True


# ── render_content gating ───────────────────────────────────────────────


class _FakeContext:
    """Minimal cairo.Context double — counts draw operations."""

    def __init__(self) -> None:
        self.fill_count = 0
        self.stroke_count = 0
        self.rgba_calls: list[tuple[float, float, float, float]] = []

    def set_source_rgba(self, r, g, b, a):
        self.rgba_calls.append((r, g, b, a))

    def set_line_width(self, w):
        pass

    def rectangle(self, *args):
        pass

    def fill(self):
        self.fill_count += 1

    def stroke(self):
        self.stroke_count += 1


class TestRenderContentGating:
    def test_flag_off_renders_nothing(self, ward_module, monkeypatch):
        monkeypatch.delenv("HAPAX_LORE_RESEARCH_INSTRUMENT_DASHBOARD_ENABLED", raising=False)
        ward = ward_module.ResearchInstrumentDashboardCairoSource()
        ctx = _FakeContext()
        ward.render_content(ctx, 540, 220, t=0.0, state={})
        assert ctx.fill_count == 0
        assert ctx.stroke_count == 0

    def test_empty_state_renders_nothing(self, ward_module, monkeypatch):
        """Flag on, but no marker AND no claims ⇒ no-op render."""
        monkeypatch.setenv("HAPAX_LORE_RESEARCH_INSTRUMENT_DASHBOARD_ENABLED", "1")
        ward = ward_module.ResearchInstrumentDashboardCairoSource()
        with (
            mock.patch.object(ward_module, "read_marker", return_value=None),
            mock.patch.object(ward_module, "load_claims", return_value=[]),
        ):
            ctx = _FakeContext()
            ward.render_content(ctx, 540, 220, t=0.0, state={})
        assert ctx.fill_count == 0
        assert ctx.stroke_count == 0

    def test_marker_only_renders_frame(self, ward_module, monkeypatch):
        """Flag on, marker but zero claims ⇒ frame + header paint."""
        monkeypatch.setenv("HAPAX_LORE_RESEARCH_INSTRUMENT_DASHBOARD_ENABLED", "1")
        from datetime import UTC, datetime

        from shared.research_marker import MarkerState

        marker = MarkerState(
            condition_id="cond-test",
            set_at=datetime.now(UTC),
            set_by="test",
            epoch=1,
        )
        ward = ward_module.ResearchInstrumentDashboardCairoSource()
        with (
            mock.patch.object(ward_module, "read_marker", return_value=marker),
            mock.patch.object(ward_module, "load_claims", return_value=[]),
            mock.patch(
                "agents.studio_compositor.text_render.render_text",
                return_value=None,
            ),
            mock.patch(
                "agents.studio_compositor.text_render.measure_text",
                return_value=(120, 14),
            ),
        ):
            ctx = _FakeContext()
            ward.render_content(ctx, 540, 220, t=0.0, state={})
        # Frame paints background + bracket border.
        assert ctx.fill_count >= 1
        assert ctx.stroke_count >= 1


# ── Color sourcing — no hardcoded hex ───────────────────────────────────


class TestPaletteSourcing:
    def test_no_hardcoded_hex_in_module_source(self, ward_module):
        """The ward must not bind an RGBA tuple at module level except
        the documented constants. Smoke check: search the source for
        bare ``set_source_rgba(0.`` calls — none should exist *in code*
        outside ``_render_frame`` (which only ever passes ``bg`` /
        ``chrome`` resolved from the package)."""
        import inspect

        source = inspect.getsource(ward_module)
        # Allowed: any ``set_source_rgba(*var)`` form (palette resolution).
        # Disallowed: ``set_source_rgba(0.`` literal — that's hardcoded
        # hex in disguise.
        assert "set_source_rgba(0." not in source
        assert "set_source_rgba(1." not in source
