from __future__ import annotations

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
