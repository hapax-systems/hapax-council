"""Tests for the ward_render_scope context manager + per-Cairo-source wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.studio_compositor import ward_properties as wp


@pytest.fixture(autouse=True)
def _redirect_path(monkeypatch, tmp_path):
    monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", tmp_path / "ward-properties.json")
    wp.clear_ward_properties_cache()
    yield
    wp.clear_ward_properties_cache()


class TestWardRenderScope:
    def test_visible_yields_props(self):
        cr = MagicMock()
        with wp.ward_render_scope(cr, "anything") as props:
            assert props is not None
            assert props.visible is True
        # No group push when alpha=1.0
        cr.push_group.assert_not_called()
        cr.pop_group_to_source.assert_not_called()

    def test_invisible_yields_none(self):
        wp.set_ward_properties("hidden", wp.WardProperties(visible=False), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        cr = MagicMock()
        with wp.ward_render_scope(cr, "hidden") as props:
            assert props is None
        cr.push_group.assert_not_called()
        cr.pop_group_to_source.assert_not_called()

    def test_low_alpha_pushes_and_pops_group(self):
        wp.set_ward_properties("dim", wp.WardProperties(alpha=0.3), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        cr = MagicMock()
        with wp.ward_render_scope(cr, "dim") as props:
            assert props is not None
            assert props.alpha == 0.3
        cr.push_group.assert_called_once()
        cr.pop_group_to_source.assert_called_once()
        cr.paint_with_alpha.assert_called_once_with(0.3)

    def test_alpha_clamped_to_unit_interval(self):
        wp.set_ward_properties("over", wp.WardProperties(alpha=1.5), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        cr = MagicMock()
        # alpha > 0.999 path — no group, no paint_with_alpha
        with wp.ward_render_scope(cr, "over"):
            pass
        cr.push_group.assert_not_called()

    def test_negative_alpha_clamped(self):
        wp.set_ward_properties("neg", wp.WardProperties(alpha=-0.5), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        cr = MagicMock()
        with wp.ward_render_scope(cr, "neg"):
            pass
        # Negative alpha < 0.999 → group path; paint_with_alpha clamped to 0.0
        cr.paint_with_alpha.assert_called_once_with(0.0)

    def test_exception_in_block_still_pops_group(self):
        wp.set_ward_properties("err", wp.WardProperties(alpha=0.5), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        cr = MagicMock()
        with pytest.raises(RuntimeError):
            with wp.ward_render_scope(cr, "err"):
                raise RuntimeError("boom")
        # The group must still be popped even when the body raises.
        cr.push_group.assert_called_once()
        cr.pop_group_to_source.assert_called_once()
