"""Regression tests for the ward stimmung modulator (Phase 2)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.studio_compositor import ward_stimmung_modulator as _wsm
from agents.studio_compositor.ward_properties import WardProperties
from agents.studio_compositor.ward_stimmung_modulator import WardStimmungModulator


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_wsm.ENABLE_ENV, "1")
    monkeypatch.delenv(_wsm.MAX_ALPHA_STEP_ENV, raising=False)
    monkeypatch.delenv(_wsm.MAX_Z_INDEX_STEP_ENV, raising=False)


@pytest.fixture
def current_path(tmp_path: pytest.TempPathFactory) -> Path:
    return Path(tmp_path) / "current.json"  # type: ignore[arg-type]


def _write_current(path: Path, dims: dict[str, float], ts_offset: float = 0.0) -> None:
    payload = {"dimensions": dims, "timestamp": time.time() + ts_offset}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_disabled_by_default(monkeypatch: pytest.MonkeyPatch, current_path: Path) -> None:
    """No ``HAPAX_WARD_MODULATOR_ACTIVE`` → ``maybe_tick`` is a no-op."""
    monkeypatch.delenv(_wsm.ENABLE_ENV, raising=False)
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    with patch.object(_wsm, "set_ward_properties") as setter:
        for _ in range(10):
            mod.maybe_tick()
    setter.assert_not_called()


def test_dims_read_fail_returns_none(enabled: None, current_path: Path) -> None:
    """Missing ``current.json`` → no writes, stale counter increments."""
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    with (
        patch.object(_wsm, "set_ward_properties") as setter,
        patch.object(_wsm, "_emit_modulator_stale") as stale_emit,
    ):
        mod.maybe_tick()
    setter.assert_not_called()
    stale_emit.assert_called_once()


def test_stale_dims_skipped(enabled: None, current_path: Path) -> None:
    """``timestamp`` past STALENESS_S → modulator treats as stale."""
    _write_current(
        current_path, {"depth": 1.0, "coherence": 0.5}, ts_offset=-(_wsm.STALENESS_S + 5.0)
    )
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    with (
        patch.object(_wsm, "set_ward_properties") as setter,
        patch.object(_wsm, "_emit_modulator_stale") as stale_emit,
    ):
        mod.maybe_tick()
    setter.assert_not_called()
    stale_emit.assert_called_once()


def test_staleness_env_override_extends_cutoff(
    enabled: None, current_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``HAPAX_WARD_MODULATOR_STALENESS_S`` env extends the cutoff."""
    monkeypatch.setenv(_wsm.STALENESS_ENV, "300")
    # Default 120s would treat -180s as stale; with override 300s it is fresh.
    _write_current(current_path, {"depth": 0.5, "coherence": 0.5}, ts_offset=-180.0)
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    with (
        patch.object(_wsm, "set_ward_properties") as setter,
        patch.object(_wsm, "_emit_modulator_stale") as stale_emit,
    ):
        mod.maybe_tick()
    stale_emit.assert_not_called()
    assert setter.called


def test_staleness_env_invalid_falls_back_to_default(
    enabled: None, current_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Garbage env value falls back to ``STALENESS_S`` rather than raising."""
    monkeypatch.setenv(_wsm.STALENESS_ENV, "not-a-number")
    _write_current(
        current_path, {"depth": 0.5, "coherence": 0.5}, ts_offset=-(_wsm.STALENESS_S + 5.0)
    )
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    with (
        patch.object(_wsm, "set_ward_properties") as setter,
        patch.object(_wsm, "_emit_modulator_stale") as stale_emit,
    ):
        mod.maybe_tick()
    stale_emit.assert_called_once()
    setter.assert_not_called()


def test_default_plane_wards_untouched(enabled: None, current_path: Path) -> None:
    """``on-scrim`` wards NOT in the WARD_Z_PLANE_DEFAULTS map keep their values —
    modulator never overrides the default plane for non-mapped wards."""
    from agents.studio_compositor.z_plane_constants import WARD_Z_PLANE_DEFAULTS

    _write_current(current_path, {"depth": 1.0, "coherence": 0.0})
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    base = WardProperties(z_plane="on-scrim", alpha=1.0)
    captured_writes: list[str] = []

    def _capture(ward_id: str, props: WardProperties, ttl_s: float) -> None:
        captured_writes.append(ward_id)

    with (
        patch.object(_wsm, "get_specific_ward_properties", return_value=base),
        patch.object(_wsm, "set_ward_properties", side_effect=_capture),
    ):
        mod.maybe_tick()
    # Wards NOT in the defaults map must not be touched.
    for ward_id in captured_writes:
        assert ward_id in WARD_Z_PLANE_DEFAULTS, (
            f"modulator wrote to {ward_id} which has no default plane assignment"
        )


def test_beyond_scrim_attenuates_alpha_with_depth(enabled: None, current_path: Path) -> None:
    """High ``depth`` dim drives ``beyond-scrim`` ``alpha`` down with a bounded step."""
    _write_current(current_path, {"depth": 1.0, "coherence": 0.5})
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    base = WardProperties(z_plane="beyond-scrim", alpha=1.0, z_index_float=0.5)
    captured: dict[str, WardProperties] = {}

    def _capture(ward_id: str, props: WardProperties, ttl_s: float) -> None:
        captured[ward_id] = props

    with (
        patch.object(_wsm, "get_specific_ward_properties", return_value=base),
        patch.object(_wsm, "set_ward_properties", side_effect=_capture),
    ):
        mod.maybe_tick()
    assert captured, "modulator should write at least one beyond-scrim ward"
    sample = next(iter(captured.values()))
    assert sample.z_plane == "beyond-scrim"
    assert sample.alpha < 1.0
    # depth=1.0 targets 0.5, but the live surface takes an enveloped
    # step per tick rather than popping instantly.
    assert sample.alpha == pytest.approx(1.0 - _wsm.MAX_ALPHA_STEP)


def test_alpha_step_env_bounds_depth_transition(
    enabled: None, current_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The alpha envelope is env-tunable for live no-blink calibration."""
    monkeypatch.setenv(_wsm.MAX_ALPHA_STEP_ENV, "0.05")
    _write_current(current_path, {"depth": 1.0, "coherence": 0.5})
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    base = WardProperties(z_plane="beyond-scrim", alpha=1.0, z_index_float=0.2)
    captured: dict[str, WardProperties] = {}

    def _capture(ward_id: str, props: WardProperties, ttl_s: float) -> None:
        captured[ward_id] = props

    with (
        patch.object(_wsm, "get_specific_ward_properties", return_value=base),
        patch.object(_wsm, "set_ward_properties", side_effect=_capture),
    ):
        mod.maybe_tick()
    sample = next(iter(captured.values()))
    assert sample.alpha == pytest.approx(0.95)
    assert sample.z_index_float == pytest.approx(0.2)


def test_z_index_step_env_bounds_depth_transition(
    enabled: None, current_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The z-index envelope is bounded separately from alpha."""
    monkeypatch.setenv(_wsm.MAX_Z_INDEX_STEP_ENV, "0.05")
    _write_current(current_path, {"depth": 0.0, "coherence": 1.0})
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    # beyond-scrim target at coherence=1.0 is 0.1; from 0.8, only one
    # 0.05 step is allowed in this tick.
    base = WardProperties(z_plane="beyond-scrim", alpha=1.0, z_index_float=0.8)
    captured: dict[str, WardProperties] = {}

    def _capture(ward_id: str, props: WardProperties, ttl_s: float) -> None:
        captured[ward_id] = props

    with (
        patch.object(_wsm, "get_specific_ward_properties", return_value=base),
        patch.object(_wsm, "set_ward_properties", side_effect=_capture),
    ):
        mod.maybe_tick()
    sample = next(iter(captured.values()))
    assert sample.alpha == pytest.approx(1.0)
    assert sample.z_index_float == pytest.approx(0.75)


def test_does_not_override_z_plane(enabled: None, current_path: Path) -> None:
    """Modulator must never write a different ``z_plane`` than the input ward had."""
    _write_current(current_path, {"depth": 0.5, "coherence": 0.5})
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    base = WardProperties(z_plane="mid-scrim", alpha=0.8)
    captured: list[WardProperties] = []

    def _capture(ward_id: str, props: WardProperties, ttl_s: float) -> None:
        captured.append(props)

    with (
        patch.object(_wsm, "get_specific_ward_properties", return_value=base),
        patch.object(_wsm, "set_ward_properties", side_effect=_capture),
    ):
        mod.maybe_tick()
    assert captured
    for props in captured:
        assert props.z_plane == "mid-scrim"


def test_tick_divisor_runs_every_nth_call(enabled: None, current_path: Path) -> None:
    """``maybe_tick`` only calls ``_run`` every ``tick_every_n`` invocations."""
    _write_current(current_path, {"depth": 0.5, "coherence": 0.5})
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=6)
    with patch.object(mod, "_run") as run_spy:
        for _ in range(5):
            mod.maybe_tick()
        assert run_spy.call_count == 0
        mod.maybe_tick()
        assert run_spy.call_count == 1
        for _ in range(6):
            mod.maybe_tick()
        assert run_spy.call_count == 2


def test_modulator_swallows_internal_exceptions(enabled: None, current_path: Path) -> None:
    """Any exception inside ``_run`` is logged but does not propagate."""
    _write_current(current_path, {"depth": 0.5, "coherence": 0.5})
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    with patch.object(mod, "_run", side_effect=RuntimeError("kaboom")):
        # Must not raise.
        mod.maybe_tick()


def test_default_z_plane_applied_when_ward_has_no_override(
    enabled: None, current_path: Path
) -> None:
    """Spec §4 default plane assignment fires for wards in WARD_Z_PLANE_DEFAULTS
    when no explicit override exists. Modulator only iterates WARD_DOMAIN, so
    defaults mapped for wards not in that registry are not exercised here."""
    from agents.studio_compositor.ward_fx_mapping import WARD_DOMAIN
    from agents.studio_compositor.z_plane_constants import WARD_Z_PLANE_DEFAULTS

    _write_current(current_path, {"depth": 1.0, "coherence": 0.5})
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    captured: dict[str, WardProperties] = {}

    def _capture(ward_id: str, props: WardProperties, ttl_s: float) -> None:
        captured[ward_id] = props

    with (
        patch.object(_wsm, "get_specific_ward_properties", return_value=None),
        patch.object(_wsm, "set_ward_properties", side_effect=_capture),
    ):
        mod.maybe_tick()
    in_scope = {ward: plane for ward, plane in WARD_Z_PLANE_DEFAULTS.items() if ward in WARD_DOMAIN}
    assert in_scope, "expected at least one defaults-mapped ward in WARD_DOMAIN"
    for ward_id, expected_plane in in_scope.items():
        assert ward_id in captured, f"{ward_id} missing from modulator writes"
        assert captured[ward_id].z_plane == expected_plane


def test_default_plane_does_not_override_existing_assignment(
    enabled: None, current_path: Path
) -> None:
    """Director-set z_plane is preserved — defaults only fire on on-scrim."""
    _write_current(current_path, {"depth": 0.5, "coherence": 0.5})
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    # chat_ambient is in defaults (mid-scrim), but director already set it
    # to beyond-scrim — the modulator must NOT downgrade to mid-scrim.
    director_set = WardProperties(z_plane="beyond-scrim", alpha=0.9)
    captured: list[WardProperties] = []

    def _capture(ward_id: str, props: WardProperties, ttl_s: float) -> None:
        if ward_id == "chat_ambient":
            captured.append(props)

    with (
        patch.object(
            _wsm,
            "get_specific_ward_properties",
            side_effect=lambda w: director_set if w == "chat_ambient" else None,
        ),
        patch.object(_wsm, "set_ward_properties", side_effect=_capture),
    ):
        mod.maybe_tick()
    assert captured, "chat_ambient should still get a write"
    assert captured[0].z_plane == "beyond-scrim"


def test_blit_with_depth_and_modulator_round_trip(enabled: None, current_path: Path) -> None:
    """Modulator-written ``z_index_float`` is the value ``blit_with_depth`` reads."""
    from agents.studio_compositor import fx_chain
    from shared.compositor_model import SurfaceGeometry

    _write_current(current_path, {"depth": 1.0, "coherence": 1.0})
    mod = WardStimmungModulator(current_path=current_path, tick_every_n=1)
    base = WardProperties(z_plane="beyond-scrim", alpha=1.0, z_index_float=0.5)
    captured_props: list[WardProperties] = []

    def _capture(ward_id: str, props: WardProperties, ttl_s: float) -> None:
        captured_props.append(props)

    with (
        patch.object(_wsm, "get_specific_ward_properties", return_value=base),
        patch.object(_wsm, "set_ward_properties", side_effect=_capture),
    ):
        mod.maybe_tick()
    assert captured_props
    # coherence=1.0 → convergence=+0.1 → z_idx = 0.2 - 0.1 = 0.1
    sample = captured_props[0]
    assert sample.z_index_float < base.z_index_float
    # Now feed those values into blit_with_depth and confirm it produces
    # a real attenuation (< default-plane multiplier).
    cr = MagicMock()
    src = MagicMock()
    geom = SurfaceGeometry(kind="rect", x=0, y=0, w=10, h=10)
    with patch.object(fx_chain, "blit_scaled") as blit_scaled:
        fx_chain.blit_with_depth(
            cr,
            src,
            geom,
            opacity=1.0,
            blend_mode="over",
            z_plane=sample.z_plane,
            z_index_float=sample.z_index_float,
        )
        opacity = blit_scaled.call_args.args[3]
    assert opacity < 0.7  # beyond-scrim, well below the on-scrim ~0.96


@pytest.mark.parametrize(
    "payload,kind",
    [
        ("null", "null"),
        ('"a string"', "string"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
    ],
)
def test_read_dims_rejects_non_dict_root(tmp_path, payload, kind):
    """Schema drift: current.json with valid JSON whose root is not a
    mapping previously raised AttributeError out of ``raw.get(...)`` —
    the modulator runs in the compositor tick loop, so a corrupt
    writer would cascade through every ward's modulation pass. Pin
    malformed → None for each non-dict shape."""
    current_path = tmp_path / "current.json"
    current_path.write_text(payload)
    mod = _wsm.WardStimmungModulator(
        current_path=current_path,
        ward_properties_ttl_s=10.0,
    )
    assert mod._read_dims() is None, f"root={kind} must yield None"
