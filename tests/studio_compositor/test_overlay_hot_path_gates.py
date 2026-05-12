from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from agents.studio_compositor import overlay


def test_overlay_zone_manager_draw_defaults_enabled(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_OVERLAY_ZONE_MANAGER_DRAW_ENABLED", raising=False)

    assert overlay.overlay_zone_manager_draw_enabled() is True


def test_overlay_zone_manager_draw_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_OVERLAY_ZONE_MANAGER_DRAW_ENABLED", "0")

    assert overlay.overlay_zone_manager_draw_enabled() is False


def test_pre_fx_layout_draw_defaults_enabled(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_PRE_FX_LAYOUT_DRAW_ENABLED", raising=False)

    assert overlay.pre_fx_layout_draw_enabled() is True


def test_pre_fx_layout_draw_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_PRE_FX_LAYOUT_DRAW_ENABLED", "disabled")

    assert overlay.pre_fx_layout_draw_enabled() is False


def test_sierpinski_base_overlay_defaults_enabled(monkeypatch) -> None:
    monkeypatch.delenv("HAPAX_SIERPINSKI_BASE_OVERLAY_ENABLED", raising=False)

    assert overlay.sierpinski_base_overlay_enabled() is True


def test_sierpinski_base_overlay_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_SIERPINSKI_BASE_OVERLAY_ENABLED", "0")

    assert overlay.sierpinski_base_overlay_enabled() is False


def test_on_draw_skips_sierpinski_and_geal_when_base_overlay_disabled(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_SIERPINSKI_BASE_OVERLAY_ENABLED", "0")
    monkeypatch.setenv("HAPAX_PRE_FX_LAYOUT_DRAW_ENABLED", "0")
    monkeypatch.setattr(overlay, "_paint_face_obscure_rects", lambda *_args: None)
    renderer = MagicMock()
    geal = MagicMock()
    compositor = SimpleNamespace(
        config=SimpleNamespace(overlay_enabled=True),
        _overlay_canvas_size=(640, 360),
        _sierpinski_renderer=renderer,
        _sierpinski_loader=SimpleNamespace(_active_slot=2),
        _geal_source=geal,
        _cached_audio={"mixer_energy": 0.75},
    )

    overlay.on_draw(compositor, None, MagicMock(), 0, 0)

    renderer.set_audio_energy.assert_not_called()
    renderer.set_active_slot.assert_not_called()
    renderer.draw.assert_not_called()
    geal.render.assert_not_called()


def test_on_draw_runs_sierpinski_and_geal_when_base_overlay_enabled(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_SIERPINSKI_BASE_OVERLAY_ENABLED", "1")
    monkeypatch.setenv("HAPAX_PRE_FX_LAYOUT_DRAW_ENABLED", "0")
    monkeypatch.setattr(overlay, "_paint_face_obscure_rects", lambda *_args: None)
    renderer = MagicMock()
    geal = MagicMock()
    compositor = SimpleNamespace(
        config=SimpleNamespace(overlay_enabled=True),
        _overlay_canvas_size=(640, 360),
        _sierpinski_renderer=renderer,
        _sierpinski_loader=SimpleNamespace(_active_slot=2),
        _geal_source=geal,
        _cached_audio={"mixer_energy": 0.75, "tts_active": True},
    )

    overlay.on_draw(compositor, None, MagicMock(), 0, 0)

    renderer.set_audio_energy.assert_called_once_with(0.75)
    renderer.set_active_slot.assert_called_once_with(2)
    renderer.draw.assert_called_once()
    geal.render.assert_called_once()
