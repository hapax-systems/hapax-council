"""Tests for HeroSmallOverlay."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.studio_compositor.hero_small_overlay import HeroSmallOverlay


def test_constructs_without_error() -> None:
    overlay = HeroSmallOverlay("brio-operator", 100, 200, 320, 180)
    assert overlay._hero_role == "brio-operator"
    assert overlay._tile_x == 100
    assert overlay._tile_y == 200
    assert overlay._tile_w == 320
    assert overlay._tile_h == 180
    assert overlay._projection.grants_layout_success is False
    assert overlay._projection.grants_face_obscuring is False


def test_draw_no_surface_is_no_op() -> None:
    overlay = HeroSmallOverlay("brio-operator", 0, 0, 100, 100)
    cr = MagicMock()
    with patch("agents.studio_compositor.hero_small_overlay.Path.exists", return_value=False):
        overlay.draw(cr)
    cr.set_source_surface.assert_not_called()
    cr.fill.assert_not_called()


def test_ttl_rate_limits_load() -> None:
    overlay = HeroSmallOverlay("brio-operator", 0, 0, 100, 100)
    with (
        patch(
            "agents.studio_compositor.hero_small_overlay.time.monotonic",
            side_effect=[0.0, 0.1, 0.2],
        ),
        patch("agents.studio_compositor.hero_small_overlay.Path.exists", return_value=False),
    ):
        overlay._try_load()  # tick 1: now=0.0, load attempted
        overlay._try_load()  # tick 2: now=0.1, < 0.5s TTL → skipped
        overlay._try_load()  # tick 3: now=0.2, < 0.5s TTL → skipped
    # No assertion on internal state; the rate-limit logic is a guard
    # against re-decoding faster than the snapshot refresh rate.
    assert overlay._last_load == 0.0


def test_draw_swallows_cairo_exception() -> None:
    overlay = HeroSmallOverlay("brio-operator", 0, 0, 100, 100)
    cr = MagicMock()
    cr.save.side_effect = RuntimeError("cairo broke")
    overlay._surface = MagicMock()
    # Must not raise.
    overlay.draw(cr)


def test_init_logs_position() -> None:
    with patch("agents.studio_compositor.hero_small_overlay.log") as mock_log:
        HeroSmallOverlay("brio-room", 50, 60, 200, 113)
    mock_log.info.assert_called_once()
    call_args = mock_log.info.call_args
    assert "brio-room" in str(call_args)


def test_draw_uses_constant_alpha_projection() -> None:
    overlay = HeroSmallOverlay("brio-operator", 0, 0, 100, 100)
    overlay._surface = MagicMock()
    cr = MagicMock()

    overlay.draw(cr)

    cr.paint_with_alpha.assert_called_once_with(overlay._projection.alpha)
    assert cr.set_source_rgba.call_args_list[0].args[-1] == overlay._projection.backdrop_alpha
    assert cr.set_source_rgba.call_args_list[-1].args[-1] == overlay._projection.border_alpha
