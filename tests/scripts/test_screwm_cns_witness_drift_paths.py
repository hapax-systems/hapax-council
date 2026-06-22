"""Pin: screwm-cns-witness drift taps point at the LIVE quake-live-<slot> surface.

The retired ``quake-drift-field.bgra`` (producer ``hapax-quake-drift-field.service``
is inactive+disabled) and ``quake-drift-currency.bgra`` (no producer) left the
witness blind to drift liveness — every drift verdict was ABSENT. This test pins
the repoint to the live ``quake-live-reverie.bgra`` surface so a regression to the
dead paths is caught.

cc-task: avsdlc-drift-reconcile-witness-and-mounts. Self-contained per workspace convention.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "screwm-cns-witness.py"


def _witness():
    spec = importlib.util.spec_from_file_location("screwm_cns_witness", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_drift_taps_point_at_the_live_surface() -> None:
    mod = _witness()
    for name in ("drift_field", "drift_currency"):
        path, shape = mod.ARTIFACTS[name]
        assert "quake-live-" in path.name, (
            f"{name} must tap a live quake-live-* surface, got {path}"
        )
        assert "quake-drift-" not in path.name, (
            f"{name} must not tap the retired quake-drift-* path"
        )
        assert shape == (540, 960, 4), (
            f"{name} shape must match the live BGRA (540x960x4), got {shape}"
        )


def test_no_retired_drift_paths_remain() -> None:
    mod = _witness()
    retired = {"quake-drift-field.bgra", "quake-drift-currency.bgra"}
    for _name, (path, _shape) in mod.ARTIFACTS.items():
        assert path.name not in retired, f"retired drift path still tapped: {path}"


def test_drift_edges_still_bind_reverie_to_drift() -> None:
    # The reverie→drift causality edges must still reference the (now-live) drift taps.
    mod = _witness()
    edge_names = {e for pair in mod.EDGES for e in pair}
    assert "drift_field" in edge_names and "drift_currency" in edge_names
    assert "reverie" in edge_names
