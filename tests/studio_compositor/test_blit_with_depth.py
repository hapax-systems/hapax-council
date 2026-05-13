"""``blit_with_depth`` — z-plane depth attenuation on blit opacity.

Phase 1 of the ward stimmung modulator + z-axis spec
(``docs/superpowers/specs/2026-04-21-ward-stimmung-modulator-design.md``).
The function combines a semantic ``z_plane`` with a sub-plane
``z_index_float`` to scale the blit opacity. These tests pin the
behaviour-neutrality of the default plane and the attenuation curve of
the deeper planes so the schema change cannot silently dim every ward
on the stream.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.studio_compositor import fx_chain
from agents.studio_compositor.ward_properties import WardProperties
from agents.studio_compositor.z_plane_constants import (
    _Z_INDEX_BASE,
    DEFAULT_Z_INDEX_FLOAT,
    DEFAULT_Z_PLANE,
)
from shared.compositor_model import SurfaceGeometry


def _capture_blit_opacity(z_plane: str, z_index_float: float = 0.5) -> float:
    """Call ``blit_with_depth`` with stubs and return the opacity passed to ``blit_scaled``."""
    cr = MagicMock()
    src = MagicMock()
    geom = SurfaceGeometry(kind="rect", x=0, y=0, w=100, h=100)
    with patch.object(fx_chain, "blit_scaled") as blit_scaled_mock:
        fx_chain.blit_with_depth(
            cr,
            src,
            geom,
            opacity=1.0,
            blend_mode="over",
            z_plane=z_plane,
            z_index_float=z_index_float,
        )
        assert blit_scaled_mock.call_count == 1
        return (
            blit_scaled_mock.call_args.kwargs.get("opacity") or blit_scaled_mock.call_args.args[3]
        )


def test_default_plane_is_behavior_neutral() -> None:
    """Default ``on-scrim`` + sub-plane 0.5 yields ~0.96 opacity multiplier.

    Existing wards land on the default plane so the Phase 1 schema change
    must not visibly dim anything on the stream.
    """
    opacity = _capture_blit_opacity(DEFAULT_Z_PLANE, DEFAULT_Z_INDEX_FLOAT)
    assert 0.95 <= opacity <= 0.97


def test_beyond_scrim_attenuates() -> None:
    """``beyond-scrim`` significantly reduces opacity (~0.68 at sub-plane 0.5)."""
    opacity = _capture_blit_opacity("beyond-scrim", 0.5)
    assert 0.65 <= opacity <= 0.71
    # Always strictly less than the default so the depth is perceivable.
    default_opacity = _capture_blit_opacity(DEFAULT_Z_PLANE, DEFAULT_Z_INDEX_FLOAT)
    assert opacity < default_opacity


def test_surface_scrim_passes_through() -> None:
    """``surface-scrim`` is the foreground plane — opacity ≈ 1.0 input × ~1.0 multiplier."""
    opacity = _capture_blit_opacity("surface-scrim", 0.5)
    assert 0.99 <= opacity <= 1.001


def test_unknown_plane_falls_back_to_default() -> None:
    """An unrecognized ``z_plane`` falls back to default so a typo doesn't blank a ward."""
    unknown = _capture_blit_opacity("totally-not-a-plane", 0.5)
    default = _capture_blit_opacity(DEFAULT_Z_PLANE, 0.5)
    assert abs(unknown - default) < 1e-6


def test_z_index_float_modulates_within_plane() -> None:
    """Higher ``z_index_float`` brings a ward forward (more opaque) within its plane."""
    far = _capture_blit_opacity("mid-scrim", 0.0)
    near = _capture_blit_opacity("mid-scrim", 1.0)
    assert near > far


def test_no_pumping_disables_depth_opacity(monkeypatch) -> None:
    """No-pumping mode makes stale z-plane fields visually inert."""
    monkeypatch.setenv("HAPAX_VISUAL_PUMPING_ENABLED", "0")
    monkeypatch.delenv("HAPAX_WARD_MODULATOR_DEPTH_OPACITY_ENABLED", raising=False)

    opacity = _capture_blit_opacity("beyond-scrim", 0.0)

    assert opacity == 1.0


def test_depth_opacity_can_be_explicitly_restored(monkeypatch) -> None:
    """Depth opacity stays available for a later dedicated restoration canary."""
    monkeypatch.setenv("HAPAX_VISUAL_PUMPING_ENABLED", "0")
    monkeypatch.setenv("HAPAX_WARD_MODULATOR_DEPTH_OPACITY_ENABLED", "1")

    opacity = _capture_blit_opacity("beyond-scrim", 0.0)

    assert opacity < 1.0


def test_depth_opacity_override_requires_explicit_truthy_value(monkeypatch) -> None:
    """FX blits use the same conservative truth table as the ward modulator."""
    monkeypatch.setenv("HAPAX_VISUAL_PUMPING_ENABLED", "0")
    monkeypatch.setenv("HAPAX_WARD_MODULATOR_DEPTH_OPACITY_ENABLED", "enabled")

    opacity = _capture_blit_opacity("beyond-scrim", 0.0)

    assert opacity == 1.0


def test_ward_properties_defaults_match_constants() -> None:
    """Schema additions match the constant defaults so no other code path desyncs."""
    props = WardProperties()
    assert props.z_plane == DEFAULT_Z_PLANE
    assert props.z_index_float == DEFAULT_Z_INDEX_FLOAT
    # Constants module exposes the per-plane depth bases for the modulator.
    assert set(_Z_INDEX_BASE.keys()) == {
        "beyond-scrim",
        "mid-scrim",
        "on-scrim",
        "surface-scrim",
    }
