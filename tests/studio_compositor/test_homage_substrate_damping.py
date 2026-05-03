"""Phase A6 regression pin — Reverie substrate damping under BitchX.

HOMAGE reckoning §3.7 and the reverie-substrate-invariant governance doc
§3 mandate that when BitchX is the active homage package the Reverie
``colorgrade`` pass damps saturation to ~0.40 (range 0.35-0.55), rotates
hue toward the package accent (180° cyan), and damps brightness so the
substrate reads as a tinted-cyan ground rather than a kaleidoscopic
competitor for visual attention.

Before Phase A6 the broadcast-to-uniforms path was incomplete:
``Choreographer.broadcast_package_to_substrates`` wrote the palette hint
to ``/dev/shm/hapax-compositor/homage-substrate-package.json`` but no
consumer read the hint and wrote damped ``color.saturation`` /
``color.hue_rotate`` / ``color.brightness`` into
``/dev/shm/hapax-imagination/uniforms.json``. The Reverie mixer's
``write_uniforms`` call now reads the broadcast and applies the damping
in-place after plan defaults + chain deltas so no chain amplification
can re-boost saturation above the substrate-invariant ceiling.

The governance regression test
``tests/studio_compositor/test_reverie_substrate_invariant.py`` pins
the clauses in the governance doc §1 at the choreographer surface;
this file pins the broadcast→uniforms write at the mixer surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from agents.reverie import _uniforms


@pytest.fixture(autouse=True)
def _reset_plan_cache():
    """Clear the module-level plan-defaults cache between tests."""
    _uniforms._plan_defaults_cache = None
    _uniforms._plan_defaults_mtime = 0.0
    yield
    _uniforms._plan_defaults_cache = None
    _uniforms._plan_defaults_mtime = 0.0


class _FakeVisualChain:
    """Minimal VisualChainCapability stand-in matching the protocol used by
    ``write_uniforms``. Tests control the chain deltas explicitly so the
    damping assertions are independent of the active dimensions mapping.
    """

    def __init__(self, deltas: dict[str, float] | None = None) -> None:
        self._deltas = dict(deltas or {})

    def compute_param_deltas(self) -> dict[str, float]:
        return dict(self._deltas)


def _write_plan(tmp_path: Path) -> Path:
    """Write a minimal vocabulary plan that includes the colorgrade node."""
    plan = {
        "version": 2,
        "targets": {
            "main": {
                "passes": [
                    {"node_id": "noise", "uniforms": {"amplitude": 0.7}},
                    {
                        "node_id": "color",
                        "uniforms": {
                            "saturation": 1.0,
                            "brightness": 1.0,
                            "contrast": 0.8,
                            "sepia": 0.0,
                            "hue_rotate": 0.0,
                        },
                    },
                ]
            }
        },
    }
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan))
    return plan_file


def _write_substrate_package(tmp_path: Path, payload: dict) -> Path:
    """Mirror the choreographer's substrate-package broadcast to tmp."""
    path = tmp_path / "homage-substrate-package.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ── _read_homage_substrate_package -----------------------------------------


def test_read_homage_substrate_package_parses_valid_payload(tmp_path: Path) -> None:
    path = _write_substrate_package(
        tmp_path,
        {
            "package": "bitchx",
            "palette_accent_hue_deg": 180.0,
            "custom_slot_index": 4,
            "substrate_source_ids": ["reverie", "reverie_external_rgba"],
        },
    )
    result = _uniforms._read_homage_substrate_package(path)
    assert result is not None
    assert result["package"] == "bitchx"
    assert result["palette_accent_hue_deg"] == pytest.approx(180.0)


def test_read_homage_substrate_package_missing_returns_none(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.json"
    assert _uniforms._read_homage_substrate_package(missing) is None


def test_read_homage_substrate_package_malformed_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert _uniforms._read_homage_substrate_package(path) is None


def test_read_homage_substrate_package_non_dict_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert _uniforms._read_homage_substrate_package(path) is None


# ── _apply_homage_package_damping -----------------------------------------


def test_apply_damping_bitchx_overrides_colorgrade_keys() -> None:
    """BitchX payload writes all three colorgrade damping keys in place."""
    uniforms = {
        "color.saturation": 1.2,  # amplified by some chain delta
        "color.brightness": 1.0,
        "color.hue_rotate": 0.0,
        "noise.amplitude": 0.7,
    }
    _uniforms._apply_homage_package_damping(
        uniforms,
        {"package": "bitchx", "palette_accent_hue_deg": 180.0},
    )
    # Invariant: saturation must be within the spec-mandated [0.35, 0.55] band.
    assert 0.35 <= uniforms["color.saturation"] <= 0.55
    assert uniforms["color.saturation"] == pytest.approx(0.40)
    assert uniforms["color.hue_rotate"] == pytest.approx(180.0)
    assert uniforms["color.brightness"] == pytest.approx(0.85)
    # Non-colorgrade uniforms untouched.
    assert uniforms["noise.amplitude"] == pytest.approx(0.7)


def test_apply_damping_non_bitchx_package_is_no_op() -> None:
    """Consent-safe / other packages don't receive the BitchX-specific damping."""
    uniforms = {
        "color.saturation": 1.0,
        "color.brightness": 1.0,
        "color.hue_rotate": 0.0,
    }
    _uniforms._apply_homage_package_damping(
        uniforms,
        {"package": "bitchx_consent_safe", "palette_accent_hue_deg": 0.0},
    )
    # No BitchX → values unchanged.
    assert uniforms["color.saturation"] == pytest.approx(1.0)
    assert uniforms["color.brightness"] == pytest.approx(1.0)
    assert uniforms["color.hue_rotate"] == pytest.approx(0.0)


def test_apply_damping_missing_payload_is_no_op() -> None:
    uniforms = {"color.saturation": 1.0}
    _uniforms._apply_homage_package_damping(uniforms, None)
    assert uniforms["color.saturation"] == pytest.approx(1.0)


def test_apply_damping_empty_payload_is_no_op() -> None:
    uniforms = {"color.saturation": 1.0}
    _uniforms._apply_homage_package_damping(uniforms, {})
    assert uniforms["color.saturation"] == pytest.approx(1.0)


# ── End-to-end write_uniforms with BitchX broadcast ------------------------


def test_write_uniforms_damps_saturation_when_bitchx_active(tmp_path: Path) -> None:
    """End-to-end: write_uniforms with a BitchX substrate-package broadcast
    must produce ``color.saturation`` inside the spec band [0.35, 0.55].

    This is the Phase A6 success criterion: even when chain deltas would
    otherwise amplify saturation above 1.0, the substrate invariant
    damping wins because it's applied after the merge.
    """
    plan_file = _write_plan(tmp_path)
    uniforms_file = tmp_path / "uniforms.json"
    substrate_file = _write_substrate_package(
        tmp_path,
        {
            "package": "bitchx",
            "palette_accent_hue_deg": 180.0,
            "custom_slot_index": 4,
            "substrate_source_ids": ["reverie", "reverie_external_rgba"],
        },
    )

    # Chain deltas attempt to amplify saturation — damping must override.
    aggressive_chain = _FakeVisualChain(
        {
            "color.saturation": 0.8,
            "color.brightness": 0.3,
        }
    )

    FAKE_NOW = 1776041528.0
    fake_imagination = {
        "salience": 0.9,
        "material": "fire",
        "timestamp": FAKE_NOW,
    }

    with (
        mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
        mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
        mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", substrate_file),
        mock.patch.object(_uniforms.time, "time", return_value=FAKE_NOW),
    ):
        _uniforms.write_uniforms(
            fake_imagination,
            None,
            aggressive_chain,
            trace_strength=0.0,
            trace_center=(0.5, 0.5),
            trace_radius=0.0,
        )

    result = json.loads(uniforms_file.read_text())

    # Phase A6 success criterion: saturation in the spec band.
    assert 0.35 <= result["color.saturation"] <= 0.55
    assert result["color.saturation"] == pytest.approx(0.40)
    assert result["color.hue_rotate"] == pytest.approx(180.0)
    assert result["color.brightness"] == pytest.approx(0.85)


def test_write_uniforms_no_damping_without_bitchx_broadcast(tmp_path: Path) -> None:
    """When the substrate-package file is missing the damping is a no-op.

    Baseline write path (plan defaults + chain deltas) must still produce
    sensible values so a pre-HOMAGE-bootstrap state does not render black.
    """
    plan_file = _write_plan(tmp_path)
    uniforms_file = tmp_path / "uniforms.json"
    # Intentionally not writing the substrate package file.
    missing_substrate = tmp_path / "never-written-homage-substrate-package.json"

    chain = _FakeVisualChain({"color.saturation": 0.1})

    FAKE_NOW = 1776041528.0
    fake_imagination = {
        "salience": 0.5,
        "material": "water",
        "timestamp": FAKE_NOW,
    }

    with (
        mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
        mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
        mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", missing_substrate),
        mock.patch.object(_uniforms.time, "time", return_value=FAKE_NOW),
        # u8-imagination-mode-tint added a per-tick mode-palette write to
        # color.hue_rotate via _apply_mode_palette_tint. This pin tests
        # the no-bitchx homage pathway only — short-circuit mode tint so
        # the pin stays focused on homage damping.
        mock.patch.object(_uniforms, "_apply_mode_palette_tint", lambda u, **kw: None),
    ):
        _uniforms.write_uniforms(
            fake_imagination,
            None,
            chain,
            trace_strength=0.0,
            trace_center=(0.5, 0.5),
            trace_radius=0.0,
        )

    result = json.loads(uniforms_file.read_text())
    # Plan default 1.0 + chain delta 0.1 = 1.1; silence=1.0 since imagination fresh.
    assert result["color.saturation"] == pytest.approx(1.1)
    # Hue rotate stays at plan default (0.0) — mode tint mocked above.
    assert result["color.hue_rotate"] == pytest.approx(0.0)


def test_write_uniforms_consent_safe_variant_leaves_saturation_undamped(
    tmp_path: Path,
) -> None:
    """Consent-safe variant has palette_accent_hue_deg=0.0 and no BitchX
    damping — Reverie keeps its baseline rendering in that mode.
    """
    plan_file = _write_plan(tmp_path)
    uniforms_file = tmp_path / "uniforms.json"
    substrate_file = _write_substrate_package(
        tmp_path,
        {
            "package": "bitchx_consent_safe",
            "palette_accent_hue_deg": 0.0,
            "custom_slot_index": 4,
            "substrate_source_ids": ["reverie", "reverie_external_rgba"],
        },
    )

    chain = _FakeVisualChain({"color.saturation": 0.0})

    FAKE_NOW = 1776041528.0
    fake_imagination = {
        "salience": 0.4,
        "material": "air",
        "timestamp": FAKE_NOW,
    }

    with (
        mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
        mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
        mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", substrate_file),
        mock.patch.object(_uniforms.time, "time", return_value=FAKE_NOW),
        # u8-imagination-mode-tint added a per-tick mode-palette write to
        # color.hue_rotate. This pin tests the consent-safe homage pathway
        # only — short-circuit mode tint to keep the pin focused.
        mock.patch.object(_uniforms, "_apply_mode_palette_tint", lambda u, **kw: None),
    ):
        _uniforms.write_uniforms(
            fake_imagination,
            None,
            chain,
            trace_strength=0.0,
            trace_center=(0.5, 0.5),
            trace_radius=0.0,
        )

    result = json.loads(uniforms_file.read_text())
    # Consent-safe variant leaves plan default 1.0 intact (no BitchX damping).
    assert result["color.saturation"] == pytest.approx(1.0)
    assert result["color.hue_rotate"] == pytest.approx(0.0)
