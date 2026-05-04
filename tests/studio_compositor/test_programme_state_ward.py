"""Unit tests for ProgrammeStateCairoSource (ytb-LORE-MVP PR B)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import cairo
import pytest

from agents.studio_compositor import programme_state_ward as psw
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from agents.studio_compositor.programme_state_ward import (
    ProgrammeStateCairoSource,
    _fmt_dwell,
    _fmt_hms,
    _role_palette_role,
    _summarise_constraint,
)
from shared.programme import (
    Programme,
    ProgrammeConstraintEnvelope,
    ProgrammeContent,
    ProgrammeDisplayDensity,
    ProgrammeRitual,
    ProgrammeRole,
    ProgrammeStatus,
    ProgrammeSuccessCriteria,
)
from shared.programme_store import ProgrammePlanStore


class _SpyContext(cairo.Context):
    """cairo.Context subclass that records texts passed to render_text."""

    def __new__(cls, surface):
        inst = cairo.Context.__new__(cls, surface)
        inst.rendered_texts = []
        return inst


def _make_programme(
    *,
    role: ProgrammeRole = ProgrammeRole.SHOWCASE,
    status: ProgrammeStatus = ProgrammeStatus.ACTIVE,
    planned_duration_s: float = 1200.0,
    started_at: float | None = None,
    display_density: ProgrammeDisplayDensity | None = ProgrammeDisplayDensity.DENSE,
    homage_package: str | None = None,
    monetization_opt_ins: set[str] | None = None,
    programme_id: str = "test-prog-1",
) -> Programme:
    envelope = ProgrammeConstraintEnvelope(
        display_density=display_density,
        homage_package=homage_package,
        monetization_opt_ins=monetization_opt_ins or set(),
    )
    return Programme(
        programme_id=programme_id,
        role=role,
        status=status,
        planned_duration_s=planned_duration_s,
        actual_started_at=started_at,
        constraints=envelope,
        content=ProgrammeContent(),
        ritual=ProgrammeRitual(),
        success=ProgrammeSuccessCriteria(),
        parent_show_id="test-show",
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv(psw._FEATURE_FLAG_ENV, "1")
    monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "0")


@pytest.fixture
def store(tmp_path: Path) -> ProgrammePlanStore:
    return ProgrammePlanStore(path=tmp_path / "plans.jsonl")


def _render_to_surface(src, w: int = 360, h: int = 120):
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


# ── _fmt_hms / _fmt_dwell ─────────────────────────────────────────────────


class TestFmtHms:
    def test_zero(self):
        assert _fmt_hms(0) == "00:00:00"

    def test_hour_minute_second(self):
        assert _fmt_hms(3754) == "01:02:34"

    def test_negative_clamped(self):
        assert _fmt_hms(-5) == "00:00:00"


class TestFmtDwell:
    def test_programme_without_start_renders_zero_dwell(self):
        p = _make_programme(started_at=None, planned_duration_s=600.0)
        assert _fmt_dwell(p, now=time.time()) == "00:00:00 / 00:10:00"

    def test_in_flight_programme(self):
        now = 10_000.0
        p = _make_programme(started_at=now - 754.0, planned_duration_s=1200.0)
        assert _fmt_dwell(p, now=now) == "00:12:34 / 00:20:00"


# ── _summarise_constraint ────────────────────────────────────────────────


class TestSummariseConstraint:
    def test_empty_envelope_is_unconstrained(self):
        env = ProgrammeConstraintEnvelope()
        assert _summarise_constraint(env) == "(unconstrained)"

    def test_homage_package_only(self):
        env = ProgrammeConstraintEnvelope(homage_package="bitchx-authentic-v1")
        assert _summarise_constraint(env) == "bitchx-authentic-v1"

    def test_opt_ins_only(self):
        env = ProgrammeConstraintEnvelope(monetization_opt_ins={"chat", "music"})
        out = _summarise_constraint(env)
        assert "+chat" in out
        assert "+music" in out

    def test_package_and_opt_ins(self):
        env = ProgrammeConstraintEnvelope(
            homage_package="bitchx-authentic-v1",
            monetization_opt_ins={"chat"},
        )
        out = _summarise_constraint(env)
        assert "bitchx-authentic-v1" in out
        assert "+chat" in out

    def test_opt_ins_truncated_to_three(self):
        env = ProgrammeConstraintEnvelope(
            monetization_opt_ins={"a", "b", "c", "d", "e"},
        )
        out = _summarise_constraint(env)
        # Sorted + sliced to 3; {"a","b","c"} → "+a +b +c"
        assert out.count("+") == 3


# ── _role_palette_role ────────────────────────────────────────────────────


class TestRolePaletteRole:
    def test_mapped_operator_context_roles(self):
        assert _role_palette_role(ProgrammeRole.REPAIR.value) == "accent_red"
        assert _role_palette_role(ProgrammeRole.SHOWCASE.value) == "accent_yellow"
        assert _role_palette_role(ProgrammeRole.LISTENING.value) == "accent_cyan"
        assert _role_palette_role(ProgrammeRole.RITUAL.value) == "accent_magenta"
        assert _role_palette_role(ProgrammeRole.WIND_DOWN.value) == "accent_blue"

    def test_mapped_segmented_content_roles(self):
        assert _role_palette_role(ProgrammeRole.TIER_LIST.value) == "accent_blue"
        assert _role_palette_role(ProgrammeRole.TOP_10.value) == "accent_yellow"
        assert _role_palette_role(ProgrammeRole.RANT.value) == "accent_red"
        assert _role_palette_role(ProgrammeRole.REACT.value) == "accent_green"
        assert _role_palette_role(ProgrammeRole.ICEBERG.value) == "accent_cyan"
        assert _role_palette_role(ProgrammeRole.INTERVIEW.value) == "accent_magenta"
        assert _role_palette_role(ProgrammeRole.LECTURE.value) == "bright"

    def test_all_segmented_content_roles_mapped(self):
        """No segmented-content role should fall through to muted.

        Acceptance criterion from cc-task
        ``programme-state-ward-palette-accents-segmented-types``.
        """
        segmented_content_roles = (
            ProgrammeRole.TIER_LIST,
            ProgrammeRole.TOP_10,
            ProgrammeRole.RANT,
            ProgrammeRole.REACT,
            ProgrammeRole.ICEBERG,
            ProgrammeRole.INTERVIEW,
            ProgrammeRole.LECTURE,
        )
        for role in segmented_content_roles:
            resolved = _role_palette_role(role.value)
            assert resolved != "muted", (
                f"{role.name} maps to muted — segmented-content roles must have a distinct accent"
            )

    def test_segmented_content_accents_are_canonical_palette_roles(self):
        """Every accent must be a HomagePalette ColourRoleName.

        Anything outside the canonical set would silently fall back to
        muted at render time via ``_resolve()``.
        """
        canonical_role_names = {
            "muted",
            "bright",
            "accent_cyan",
            "accent_magenta",
            "accent_green",
            "accent_yellow",
            "accent_red",
            "accent_blue",
            "terminal_default",
            "background",
        }
        new_roles = (
            ProgrammeRole.TIER_LIST,
            ProgrammeRole.TOP_10,
            ProgrammeRole.RANT,
            ProgrammeRole.REACT,
            ProgrammeRole.ICEBERG,
            ProgrammeRole.INTERVIEW,
            ProgrammeRole.LECTURE,
        )
        for role in new_roles:
            assert _role_palette_role(role.value) in canonical_role_names

    def test_unknown_role_falls_to_muted(self):
        assert _role_palette_role("not_a_role") == "muted"


# ── ProgrammeStateCairoSource ────────────────────────────────────────────


class TestProgrammeStateWard:
    def test_inherits_homage_transitional_source(self):
        assert issubclass(ProgrammeStateCairoSource, HomageTransitionalSource)

    def test_source_id_is_programme_state(self, store: ProgrammePlanStore):
        src = ProgrammeStateCairoSource(store=store)
        assert src.source_id == "programme_state"

    def test_renders_header_and_idle_when_no_programme(self, store: ProgrammePlanStore):
        src = ProgrammeStateCairoSource(store=store)
        surface, cr = _render_to_surface(src)
        assert _surface_not_empty(surface)
        texts = " ".join(cr.rendered_texts)
        assert "»»»" in texts
        assert "[programme]" in texts
        assert "[IDLE]" in texts

    def test_renders_active_programme(self, store: ProgrammePlanStore):
        p = _make_programme(
            role=ProgrammeRole.SHOWCASE,
            started_at=time.time() - 120.0,
            display_density=ProgrammeDisplayDensity.DENSE,
            homage_package="bitchx-authentic-v1",
        )
        store.add(p)
        src = ProgrammeStateCairoSource(store=store)
        _surface, cr = _render_to_surface(src)
        texts = " ".join(cr.rendered_texts)
        assert "[programme]" in texts
        # Role/density render as StrEnum.value (lowercase).
        assert ProgrammeRole.SHOWCASE.value in texts
        assert ProgrammeDisplayDensity.DENSE.value in texts
        assert "bitchx-authentic-v1" in texts
        assert "dwell:" in texts

    def test_density_unknown_renders_question_mark(self, store: ProgrammePlanStore):
        p = _make_programme(
            role=ProgrammeRole.LISTENING,
            started_at=time.time(),
            display_density=None,
        )
        store.add(p)
        src = ProgrammeStateCairoSource(store=store)
        _surface, cr = _render_to_surface(src)
        texts = " ".join(cr.rendered_texts)
        assert ProgrammeRole.LISTENING.value in texts
        assert "?" in texts

    def test_feature_flag_off_suppresses_render(self, store: ProgrammePlanStore, monkeypatch):
        monkeypatch.setenv(psw._FEATURE_FLAG_ENV, "0")
        p = _make_programme(started_at=time.time())
        store.add(p)
        src = ProgrammeStateCairoSource(store=store)
        _surface, cr = _render_to_surface(src)
        assert cr.rendered_texts == []

    def test_refresh_cache_respects_interval(self, store: ProgrammePlanStore):
        """Second render within 2 s reuses cached programme."""
        p1 = _make_programme(
            programme_id="p1",
            role=ProgrammeRole.SHOWCASE,
            started_at=time.time(),
        )
        store.add(p1)
        src = ProgrammeStateCairoSource(store=store)
        _render_to_surface(src)
        assert src._cached_programme is not None
        assert src._cached_programme.programme_id == "p1"

        # Replace store state. Since _maybe_refresh was called <2 s ago,
        # the ward must keep serving p1.
        store.deactivate(p1.programme_id)
        p2 = _make_programme(
            programme_id="p2",
            role=ProgrammeRole.REPAIR,
            started_at=time.time(),
        )
        store.add(p2)
        _render_to_surface(src)
        assert src._cached_programme.programme_id == "p1"

    def test_refresh_cache_refreshes_after_interval(self, store: ProgrammePlanStore, monkeypatch):
        p1 = _make_programme(programme_id="p1", started_at=time.time())
        store.add(p1)
        src = ProgrammeStateCairoSource(store=store)
        src._maybe_refresh(now=0.0)
        assert src._cached_programme.programme_id == "p1"

        store.deactivate(p1.programme_id)
        p2 = _make_programme(
            programme_id="p2",
            role=ProgrammeRole.REPAIR,
            started_at=time.time(),
        )
        store.add(p2)
        # Advance past the refresh interval.
        src._maybe_refresh(now=psw._REFRESH_INTERVAL_S + 0.1)
        assert src._cached_programme.programme_id == "p2"

    def test_store_exception_renders_idle(self, store: ProgrammePlanStore, monkeypatch):
        def _boom(self):
            raise RuntimeError("store unreachable")

        monkeypatch.setattr(ProgrammePlanStore, "active_programme", _boom)
        src = ProgrammeStateCairoSource(store=store)
        _surface, cr = _render_to_surface(src)
        texts = " ".join(cr.rendered_texts)
        assert "[IDLE]" in texts


# ── Registry integration ──────────────────────────────────────────────────


class TestRegistry:
    def test_registered_under_class_name(self):
        from agents.studio_compositor.cairo_sources import get_cairo_source_class

        cls = get_cairo_source_class("ProgrammeStateCairoSource")
        assert cls is ProgrammeStateCairoSource
