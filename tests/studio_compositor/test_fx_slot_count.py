from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import cairo

from agents.studio_compositor import fx_chain


def test_fx_slot_count_defaults_to_operational_headroom(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_COMPOSITOR_FX_SLOTS", raising=False)

    assert fx_chain._fx_slot_count_from_env() == fx_chain.DEFAULT_FX_SLOT_COUNT


def test_fx_slot_count_honors_incident_reduction(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_COMPOSITOR_FX_SLOTS", "1")

    assert fx_chain._fx_slot_count_from_env() == 1


def test_fx_slot_count_rejects_invalid_value(monkeypatch, caplog) -> None:
    monkeypatch.setenv("HAPAX_COMPOSITOR_FX_SLOTS", "many")

    with caplog.at_level(logging.WARNING):
        assert fx_chain._fx_slot_count_from_env() == fx_chain.DEFAULT_FX_SLOT_COUNT

    assert "Invalid HAPAX_COMPOSITOR_FX_SLOTS" in caplog.text


def test_fx_slot_count_clamps_to_runtime_bounds(monkeypatch, caplog) -> None:
    monkeypatch.setenv("HAPAX_COMPOSITOR_FX_SLOTS", "999")

    with caplog.at_level(logging.WARNING):
        assert fx_chain._fx_slot_count_from_env() == fx_chain.MAX_FX_SLOT_COUNT

    assert "Clamped HAPAX_COMPOSITOR_FX_SLOTS" in caplog.text


def test_cache_clear_helpers_are_callable() -> None:
    fx_chain.clear_scaled_blit_cache()
    fx_chain.clear_layout_composite_cache()


def test_shader_fx_disabled_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_COMPOSITOR_DISABLE_SHADER_FX", raising=False)

    assert fx_chain._shader_fx_disabled() is False


def test_shader_fx_disabled_honors_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_COMPOSITOR_DISABLE_SHADER_FX", "1")

    assert fx_chain._shader_fx_disabled() is True


def test_overlay_only_output_convert_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_OVERLAY_ONLY_OUTPUT_CONVERT", raising=False)

    assert fx_chain._overlay_only_output_convert_enabled() is False


def test_overlay_only_output_convert_honors_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_OVERLAY_ONLY_OUTPUT_CONVERT", "1")

    assert fx_chain._overlay_only_output_convert_enabled() is True


def test_post_fx_overlay_canary_defaults_off(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_COMPOSITOR_DISABLE_POST_FX_OVERLAY", raising=False)

    assert fx_chain._post_fx_overlay_disabled() is False


def test_post_fx_overlay_canary_honors_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_COMPOSITOR_DISABLE_POST_FX_OVERLAY", "1")

    assert fx_chain._post_fx_overlay_disabled() is True


def test_hero_small_overlay_defaults_enabled(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_HERO_SMALL_OVERLAY_ENABLED", raising=False)

    assert fx_chain._hero_small_overlay_enabled() is True


def test_hero_small_overlay_canary_honors_disable(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_HERO_SMALL_OVERLAY_ENABLED", "0")

    assert fx_chain._hero_small_overlay_enabled() is False


def test_hero_small_stage_defaults_post_fx(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_HERO_SMALL_OVERLAY_ENABLED", raising=False)
    monkeypatch.delenv("HAPAX_HERO_SMALL_RENDER_STAGE", raising=False)

    assert fx_chain._hero_small_overlay_stage() == "post_fx"


def test_hero_small_stage_can_move_to_pre_fx(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_HERO_SMALL_RENDER_STAGE", "pre_fx")

    assert fx_chain._hero_small_overlay_stage() == "pre_fx"


def test_post_fx_overlay_not_required_without_work_when_hero_small_is_pre_fx(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_HERO_SMALL_RENDER_STAGE", "pre_fx")
    compositor = SimpleNamespace(
        layout_state=SimpleNamespace(get=lambda: SimpleNamespace(assignments=[]))
    )

    assert fx_chain._post_fx_overlay_required(compositor) is False


def test_post_fx_overlay_required_for_post_fx_assignment(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_HERO_SMALL_RENDER_STAGE", "pre_fx")
    assignment = SimpleNamespace(render_stage="post_fx")
    compositor = SimpleNamespace(
        layout_state=SimpleNamespace(get=lambda: SimpleNamespace(assignments=[assignment]))
    )

    assert fx_chain._post_fx_overlay_required(compositor) is True


def test_hero_small_draws_only_on_configured_stage(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_HERO_SMALL_RENDER_STAGE", "pre_fx")
    hero_small = MagicMock()
    compositor = SimpleNamespace(_hero_small=hero_small)

    fx_chain.draw_hero_small_overlay(compositor, MagicMock(), stage="post_fx")
    hero_small.draw.assert_not_called()

    fx_chain.draw_hero_small_overlay(compositor, MagicMock(), stage="pre_fx")
    hero_small.draw.assert_called_once()


def test_pre_fx_background_disabled_bypasses_full_canvas_composite_cache(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_PRE_FX_LAYOUT_BACKGROUND_COMPOSITE_ENABLED", "0")
    calls: list[dict[str, object]] = []

    def fake_pip_draw_from_layout(
        cr,
        layout_state,
        source_registry,
        *,
        stage=None,
        use_composite_cache=True,
    ) -> None:
        calls.append(
            {
                "stage": stage,
                "use_composite_cache": use_composite_cache,
                "layout_state": layout_state,
                "source_registry": source_registry,
            }
        )

    monkeypatch.setattr(fx_chain, "pip_draw_from_layout", fake_pip_draw_from_layout)
    layout_state = object()
    source_registry = object()
    compositor = SimpleNamespace(layout_state=layout_state, source_registry=source_registry)

    fx_chain.draw_pre_fx_layout_from_composite(compositor, MagicMock(), 1920, 1080)

    assert calls == [
        {
            "stage": "pre_fx",
            "use_composite_cache": False,
            "layout_state": layout_state,
            "source_registry": source_registry,
        }
    ]


def test_post_fx_background_composite_defaults_enabled(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_POST_FX_LAYOUT_BACKGROUND_COMPOSITE_ENABLED", raising=False)

    assert fx_chain._post_fx_background_composite_enabled() is True


def test_post_fx_background_disabled_bypasses_full_canvas_composite_cache(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_POST_FX_LAYOUT_BACKGROUND_COMPOSITE_ENABLED", "0")
    calls: list[dict[str, object]] = []

    def fake_pip_draw_from_layout(
        cr,
        layout_state,
        source_registry,
        *,
        stage=None,
        use_composite_cache=True,
    ) -> None:
        calls.append(
            {
                "stage": stage,
                "use_composite_cache": use_composite_cache,
                "layout_state": layout_state,
                "source_registry": source_registry,
            }
        )

    monkeypatch.setattr(fx_chain, "pip_draw_from_layout", fake_pip_draw_from_layout)
    layout_state = object()
    source_registry = object()
    compositor = SimpleNamespace(layout_state=layout_state, source_registry=source_registry)

    fx_chain.draw_post_fx_layout_from_composite(compositor, MagicMock(), 1920, 1080)

    assert calls == [
        {
            "stage": "post_fx",
            "use_composite_cache": False,
            "layout_state": layout_state,
            "source_registry": source_registry,
        }
    ]


def test_pip_draw_uses_post_fx_background_composite(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_draw_post_fx_layout_from_composite(compositor, cr, canvas_w, canvas_h) -> None:
        calls.append({"compositor": compositor, "canvas_w": canvas_w, "canvas_h": canvas_h})

    monkeypatch.setattr(
        fx_chain,
        "draw_post_fx_layout_from_composite",
        fake_draw_post_fx_layout_from_composite,
    )
    monkeypatch.setattr(fx_chain, "draw_hero_small_overlay", lambda *args, **kwargs: None)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1280, 720)
    cr = cairo.Context(surface)
    compositor = SimpleNamespace(layout_state=object(), source_registry=object())

    fx_chain._pip_draw(compositor, cr)

    assert calls == [{"compositor": compositor, "canvas_w": 1280, "canvas_h": 720}]
