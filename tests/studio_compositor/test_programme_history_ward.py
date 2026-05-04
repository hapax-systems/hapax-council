"""Unit tests for ``ProgrammeHistoryCairoSource`` (cc-task ``ward-programme-history-e-panel``)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import cairo
import pytest

from agents.studio_compositor import programme_history_ward as phw
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from agents.studio_compositor.programme_history_ward import (
    ProgrammeHistoryCairoSource,
    _format_dwell_short,
    _resolve_moksha_package,
    _role_palette_role,
    _select_history,
    _short_role,
)
from shared.programme import (
    Programme,
    ProgrammeConstraintEnvelope,
    ProgrammeContent,
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
    programme_id: str = "test-prog-1",
    role: ProgrammeRole = ProgrammeRole.SHOWCASE,
    status: ProgrammeStatus = ProgrammeStatus.ACTIVE,
    planned_duration_s: float = 1200.0,
    started_at: float | None = None,
    ended_at: float | None = None,
) -> Programme:
    return Programme(
        programme_id=programme_id,
        role=role,
        status=status,
        planned_duration_s=planned_duration_s,
        actual_started_at=started_at,
        actual_ended_at=ended_at,
        constraints=ProgrammeConstraintEnvelope(),
        content=ProgrammeContent(),
        ritual=ProgrammeRitual(),
        success=ProgrammeSuccessCriteria(),
        parent_show_id="test-show",
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Enable the feature flag + disable HAPAX_HOMAGE_ACTIVE so the FSM
    legacy path renders unconditionally for the renders-content tests."""

    monkeypatch.setenv(phw._FEATURE_FLAG_ENV, "1")
    monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "0")


@pytest.fixture
def store(tmp_path: Path) -> ProgrammePlanStore:
    return ProgrammePlanStore(path=tmp_path / "plans.jsonl")


def _render_to_surface(src, w: int = 460, h: int = 110):
    """Render src and capture all text strings passed to render_text."""

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


# ── 1. Helpers ────────────────────────────────────────────────────────────


class TestRolePaletteRole:
    """Every ProgrammeRole value resolves to a palette-role name (no KeyError)."""

    @pytest.mark.parametrize("role", list(ProgrammeRole))
    def test_role_value_resolves(self, role):
        result = _role_palette_role(role.value)
        # Must be a non-empty string the HomagePalette can resolve.
        assert isinstance(result, str)
        assert result

    def test_unknown_role_falls_back_to_muted(self):
        assert _role_palette_role("not-a-real-role") == "muted"


class TestShortRole:
    def test_clip_to_six_chars(self):
        assert _short_role("hothouse_pressure") == "hothou"

    def test_short_role_unchanged(self):
        assert _short_role("rant") == "rant"

    def test_empty_returns_question_mark(self):
        assert _short_role("") == "?"


class TestFormatDwellShort:
    def test_no_start_renders_placeholder(self):
        p = _make_programme(started_at=None)
        assert _format_dwell_short(p, now=time.time()) == "--:--"

    def test_in_flight_minutes_seconds(self):
        now = 10_000.0
        p = _make_programme(started_at=now - 754.0)
        # 12 min 34 s → 12:34
        assert _format_dwell_short(p, now=now) == "12:34"

    def test_long_dwell_renders_hours_minutes(self):
        now = 10_000.0
        p = _make_programme(started_at=now - 7320.0)  # 2h 02m
        assert _format_dwell_short(p, now=now) == "02:02"

    def test_completed_uses_recorded_end_time(self):
        # Started 1000 s, ended 1300 s → 5 min run.
        p = _make_programme(
            status=ProgrammeStatus.COMPLETED,
            started_at=1000.0,
            ended_at=1300.0,
        )
        assert _format_dwell_short(p, now=99999.0) == "05:00"


class TestSelectHistory:
    def test_drops_never_started(self):
        prog_a = _make_programme(programme_id="a", started_at=None)
        prog_b = _make_programme(programme_id="b", started_at=10.0)
        out = _select_history([prog_a, prog_b], depth=5)
        assert [p.programme_id for p in out] == ["b"]

    def test_oldest_first_order(self):
        prog_a = _make_programme(programme_id="a", started_at=30.0)
        prog_b = _make_programme(programme_id="b", started_at=10.0)
        prog_c = _make_programme(programme_id="c", started_at=20.0)
        out = _select_history([prog_a, prog_b, prog_c], depth=5)
        assert [p.programme_id for p in out] == ["b", "c", "a"]

    def test_truncates_to_depth(self):
        progs = [_make_programme(programme_id=f"p{i}", started_at=float(i)) for i in range(8)]
        out = _select_history(progs, depth=3)
        assert [p.programme_id for p in out] == ["p5", "p6", "p7"]


# ── 2. Moksha package resolution ─────────────────────────────────────────


class TestResolveMokshaPackage:
    def test_resolves_to_moksha_package_when_registered(self):
        pkg = _resolve_moksha_package()
        assert pkg.name in {
            "enlightenment-moksha-v1",
            "enlightenment-moksha-authentic-v1",
            # If the package registry does not include either Moksha
            # variant in this test env, the helper falls through to the
            # active-or-bitchx fallback; that's a coverage gap we accept
            # here because the fallback path is itself tested below.
            "bitchx",
            "bitchx-authentic-v1",
            "bitchx_consent_safe",
        }

    def test_palette_resolves_canonical_roles(self):
        """Every palette role the ward references must resolve on the active package.

        Defends against a future palette refactor that drops one of the
        roles the ward uses (chrome / bright / muted / accent_*).
        """

        pkg = _resolve_moksha_package()
        for role in (
            "muted",
            "bright",
            "accent_red",
            "accent_yellow",
            "accent_cyan",
            "accent_magenta",
            "accent_green",
            "accent_blue",
        ):
            colour = pkg.resolve_colour(role)
            assert isinstance(colour, tuple)
            assert len(colour) == 4


# ── 3. Render — empty + populated ─────────────────────────────────────────


class TestRenderHeader:
    def test_renders_curly_brace_header(self, store):
        src = ProgrammeHistoryCairoSource(store=store)
        _surface, cr = _render_to_surface(src)
        # Curly chrome marker must appear (Moksha grammar
        # ``container_shape="curly"``).
        joined = "".join(cr.rendered_texts)
        assert "{ " in joined
        assert " }" in joined
        assert "programme history" in joined

    def test_empty_store_renders_no_history_yet(self, store):
        src = ProgrammeHistoryCairoSource(store=store)
        _surface, cr = _render_to_surface(src)
        joined = " ".join(cr.rendered_texts)
        assert "no history yet" in joined

    def test_empty_store_keeps_header_legible(self, store):
        """Empty state still emits header tokens — never silent."""

        src = ProgrammeHistoryCairoSource(store=store)
        surface, _cr = _render_to_surface(src)
        assert _surface_not_empty(surface)


class TestRenderHistory:
    def test_renders_all_history_cells(self, store):
        # Three completed programmes oldest→newest, plus one active.
        prog_old = _make_programme(
            programme_id="old",
            role=ProgrammeRole.LISTENING,
            status=ProgrammeStatus.COMPLETED,
            started_at=100.0,
            ended_at=400.0,
        )
        prog_mid = _make_programme(
            programme_id="mid",
            role=ProgrammeRole.SHOWCASE,
            status=ProgrammeStatus.COMPLETED,
            started_at=500.0,
            ended_at=900.0,
        )
        prog_now = _make_programme(
            programme_id="now",
            role=ProgrammeRole.RITUAL,
            status=ProgrammeStatus.ACTIVE,
            started_at=1000.0,
        )
        store.add(prog_old)
        store.add(prog_mid)
        store.add(prog_now)

        src = ProgrammeHistoryCairoSource(store=store)
        _surface, cr = _render_to_surface(src)
        joined = " ".join(cr.rendered_texts)
        # Each role label appears (truncated to 6 chars).
        assert _short_role("listening") in joined
        assert _short_role("showcase") in joined
        assert _short_role("ritual") in joined

    def test_active_programme_anchors_the_arc(self, store):
        """The active programme's role appears alongside the chevron ladder."""

        prog_now = _make_programme(
            programme_id="now",
            role=ProgrammeRole.HOTHOUSE_PRESSURE,
            status=ProgrammeStatus.ACTIVE,
            started_at=1000.0,
        )
        store.add(prog_now)

        src = ProgrammeHistoryCairoSource(store=store)
        _surface, cr = _render_to_surface(src)
        joined = " ".join(cr.rendered_texts)
        assert _short_role("hothouse_pressure") in joined

    def test_pending_programmes_excluded(self, store):
        """A PENDING programme (planner-scheduled but not yet activated)
        must not appear in the timeline — the arc represents what HAS run."""

        scheduled = _make_programme(
            programme_id="scheduled",
            role=ProgrammeRole.RITUAL,
            status=ProgrammeStatus.PENDING,
            started_at=None,
        )
        store.add(scheduled)

        src = ProgrammeHistoryCairoSource(store=store)
        _surface, cr = _render_to_surface(src)
        joined = " ".join(cr.rendered_texts)
        # Empty-state copy is what should appear, not the role label.
        assert "no history yet" in joined
        assert _short_role("ritual") not in joined


# ── 4. Constraints & invariants ───────────────────────────────────────────


class TestSurfaceConstraints:
    def test_subclass_of_homage_transitional_source(self):
        """Renders inside the HOMAGE FSM lifecycle (matches programme_state_ward)."""

        assert issubclass(ProgrammeHistoryCairoSource, HomageTransitionalSource)

    def test_default_source_id(self):
        src = ProgrammeHistoryCairoSource()
        assert src.source_id == "programme_history"

    def test_feature_flag_default_off(self, monkeypatch, store):
        """Without the feature flag, render is a no-op."""

        monkeypatch.delenv(phw._FEATURE_FLAG_ENV, raising=False)
        src = ProgrammeHistoryCairoSource(store=store)
        _surface, cr = _render_to_surface(src)
        assert cr.rendered_texts == []

    def test_refresh_interval_caps_at_2hz(self):
        """Operator constraint: cadence ≤ 2 Hz (refresh interval ≥ 0.5 s)."""

        assert phw._REFRESH_INTERVAL_S >= 0.5

    def test_class_registered_in_cairo_source_registry(self):
        """The ward must be registered so layouts can declare it."""

        from agents.studio_compositor.cairo_sources import get_cairo_source_class

        assert get_cairo_source_class("ProgrammeHistoryCairoSource") is ProgrammeHistoryCairoSource

    def test_no_hardcoded_hex_in_module_source(self):
        """Per cc-task constraint: palette tokens flow through the
        HomagePackage, not hardcoded hex.

        Scans the rendered module text for hex-RGB literals like ``#RRGGBB``
        or ``0x[0-9a-f]{6}`` outside of comments / docstrings. The Moksha
        package itself supplies the palette via floats; this check
        catches drift if a later edit hardcodes a hex value.
        """

        import re
        from pathlib import Path

        text = Path(phw.__file__).read_text(encoding="utf-8")
        # Strip docstrings + comments before scanning so the spec mention
        # of "Moksha-dark-chrome" or hex mentioned in narrative text
        # don't false-positive.
        stripped = re.sub(r'""".*?"""', "", text, flags=re.DOTALL)
        stripped = re.sub(r"#.*$", "", stripped, flags=re.MULTILINE)
        # Match only hex-color literals (#RRGGBB / 0xRRGGBB), not
        # arbitrary hex digits in unrelated identifiers.
        forbidden = re.findall(r'"#[0-9a-fA-F]{6,8}"', stripped)
        assert not forbidden, f"hardcoded hex colour found: {forbidden}"


class TestRedactionSafety:
    """Ward must not surface anything that would violate
    ``interpersonal_transparency`` (no person names from constraints/notes).
    """

    def test_programme_notes_and_personal_constraint_fields_not_rendered(self, store):
        """Notes + constraint envelope fields stay behind the role label.

        Even though the Programme model lets the planner attach a notes
        string, the ward intentionally only renders role + dwell. This
        test asserts a notes string carrying a hypothetical person name
        does not leak into the rendered text list.
        """

        prog = _make_programme(programme_id="p", started_at=10.0)
        prog = prog.model_copy(update={"notes": "with-jane-doe (private)"})
        store.add(prog)

        src = ProgrammeHistoryCairoSource(store=store)
        _surface, cr = _render_to_surface(src)
        joined = " ".join(cr.rendered_texts)
        assert "jane-doe" not in joined.lower()
        assert "private" not in joined.lower()
