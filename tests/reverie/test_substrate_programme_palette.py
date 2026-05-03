"""Tests for programme-aware Reverie substrate palette (Phase 8).

Verifies the soft-prior mechanism in
``agents.reverie.substrate_palette`` and its wiring through
``agents.reverie._uniforms.write_uniforms``:

  - programme target alone (no modulation) lands at the centre
  - stimmung-stance modulates around the centre
  - transition_energy briefly lifts saturation above the centre
    (grounding-expansion property — programme target is not a ceiling)
  - composed value clamps to ``[0.0, 1.0]``
  - missing programme / missing target falls through to package damping
  - programme target overrides BitchX saturation but preserves
    BitchX hue + brightness damping (programme governs saturation only)
  - per-role default targets (LISTENING quiet, HOTHOUSE_PRESSURE bright)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from agents.reverie import _uniforms
from agents.reverie.substrate_palette import (
    _STIMMUNG_STANCE_DELTA,
    _TRANSITION_ENERGY_GAIN,
    compute_substrate_saturation,
    stimmung_delta,
)
from shared.programme import (
    Programme,
    ProgrammeConstraintEnvelope,
    ProgrammeRole,
)

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_plan_cache():
    _uniforms._plan_defaults_cache = None
    _uniforms._plan_defaults_mtime = 0.0
    yield
    _uniforms._plan_defaults_cache = None
    _uniforms._plan_defaults_mtime = 0.0


def _programme(
    role: ProgrammeRole = ProgrammeRole.LISTENING,
    *,
    saturation_target: float | None = 0.30,
) -> Programme:
    constraints_kwargs: dict = {}
    if saturation_target is not None:
        constraints_kwargs["reverie_saturation_target"] = saturation_target
    return Programme(
        programme_id=f"prog-{role.value}",
        role=role,
        planned_duration_s=300.0,
        constraints=ProgrammeConstraintEnvelope(**constraints_kwargs),
        parent_show_id="test-show",
    )


class _FakeVisualChain:
    def __init__(self, deltas: dict[str, float] | None = None) -> None:
        self._deltas = dict(deltas or {})

    def compute_param_deltas(self) -> dict[str, float]:
        return dict(self._deltas)


def _write_plan(tmp_path: Path) -> Path:
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
    path = tmp_path / "homage-substrate-package.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ── compute_substrate_saturation — pure function unit tests ─────────────


class TestComposeBasics:
    def test_no_programme_returns_none(self) -> None:
        assert compute_substrate_saturation(None) is None

    def test_programme_without_target_returns_none(self) -> None:
        prog = _programme(saturation_target=None)
        assert compute_substrate_saturation(prog) is None

    def test_programme_target_alone_lands_at_centre(self) -> None:
        prog = _programme(saturation_target=0.30)
        assert compute_substrate_saturation(prog) == pytest.approx(0.30)

    def test_programme_target_with_quiet_stimmung_unchanged(self) -> None:
        prog = _programme(saturation_target=0.50)
        assert compute_substrate_saturation(prog, {"overall_stance": "nominal"}) == pytest.approx(
            0.50
        )


class TestStimmungModulation:
    def test_critical_stimmung_lowers_target(self) -> None:
        prog = _programme(saturation_target=0.50)
        composed = compute_substrate_saturation(prog, {"overall_stance": "critical"})
        # 0.50 + (-0.15) = 0.35
        assert composed == pytest.approx(0.50 + _STIMMUNG_STANCE_DELTA["critical"])
        assert composed < 0.50

    def test_seeking_stimmung_lifts_target(self) -> None:
        prog = _programme(saturation_target=0.30)
        composed = compute_substrate_saturation(prog, {"overall_stance": "seeking"})
        assert composed == pytest.approx(0.30 + _STIMMUNG_STANCE_DELTA["seeking"])
        assert composed > 0.30

    def test_unknown_stance_treated_as_zero_delta(self) -> None:
        prog = _programme(saturation_target=0.42)
        assert compute_substrate_saturation(
            prog, {"overall_stance": "totally-made-up"}
        ) == pytest.approx(0.42)

    def test_stimmung_delta_helper_returns_zero_for_none(self) -> None:
        assert stimmung_delta(None) == 0.0
        assert stimmung_delta({}) == 0.0


class TestTransitionEnergyLift:
    """Phase 8 success criterion (plan §line 873-875): listening programme
    + high transition-energy briefly lifts saturation above the centre.
    Programme target is not a ceiling.
    """

    def test_max_transition_energy_lifts_target(self) -> None:
        prog = _programme(role=ProgrammeRole.LISTENING, saturation_target=0.30)
        composed = compute_substrate_saturation(prog, transition_energy=1.0)
        assert composed == pytest.approx(0.30 + _TRANSITION_ENERGY_GAIN)
        assert composed > 0.30  # Programme target NOT a ceiling

    def test_partial_transition_energy_partially_lifts(self) -> None:
        prog = _programme(saturation_target=0.40)
        composed = compute_substrate_saturation(prog, transition_energy=0.5)
        assert composed == pytest.approx(0.40 + 0.05)

    def test_negative_transition_energy_clamped_to_zero(self) -> None:
        prog = _programme(saturation_target=0.40)
        composed = compute_substrate_saturation(prog, transition_energy=-0.5)
        # Clamp at 0 → no lift
        assert composed == pytest.approx(0.40)

    def test_excess_transition_energy_clamped_to_one(self) -> None:
        prog = _programme(saturation_target=0.40)
        composed = compute_substrate_saturation(prog, transition_energy=99.0)
        # energy clamps to 1.0 → 0.40 + 0.10 = 0.50
        assert composed == pytest.approx(0.50)


class TestClamping:
    def test_high_target_plus_lift_clamps_at_one(self) -> None:
        prog = _programme(saturation_target=0.95)
        # 0.95 + 0.05 (seeking) + 0.10 (full energy) = 1.10 → clamp to 1.0
        composed = compute_substrate_saturation(
            prog, {"overall_stance": "seeking"}, transition_energy=1.0
        )
        assert composed == pytest.approx(1.0)

    def test_low_target_plus_critical_clamps_at_zero(self) -> None:
        prog = _programme(saturation_target=0.10)
        # 0.10 + (-0.15) = -0.05 → clamp to 0.0
        composed = compute_substrate_saturation(prog, {"overall_stance": "critical"})
        assert composed == pytest.approx(0.0)


class TestGroundingExpansion:
    """Architectural axiom: programme target EXPANDS grounding, never replaces.

    A LISTENING programme with target 0.30 must still allow saturation to
    visibly shift when transition energy or seeking stance arrives.
    """

    def test_listening_plus_seeking_lifts_above_quiet_target(self) -> None:
        prog = _programme(role=ProgrammeRole.LISTENING, saturation_target=0.30)
        composed = compute_substrate_saturation(
            prog, {"overall_stance": "seeking"}, transition_energy=0.6
        )
        # 0.30 + 0.05 + 0.06 = 0.41 — visibly above the quiet 0.30 centre
        assert composed > 0.30
        assert composed == pytest.approx(0.41)

    def test_quiet_programme_target_does_not_silence_substrate(self) -> None:
        """Even with the lowest realistic centre, substrate stays visible."""
        prog = _programme(saturation_target=0.10)
        composed = compute_substrate_saturation(prog, transition_energy=1.0)
        assert composed > 0.0


# ── write_uniforms — integration tests with programme_provider ───────────


class TestWriteUniformsProgrammeIntegration:
    def test_no_provider_falls_through_to_package_damping(self, tmp_path: Path) -> None:
        """When no programme_provider passed, BitchX damping rules (existing)."""
        plan_file = _write_plan(tmp_path)
        uniforms_file = tmp_path / "uniforms.json"
        substrate_file = _write_substrate_package(
            tmp_path, {"package": "bitchx", "palette_accent_hue_deg": 180.0}
        )
        with (
            mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
            mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
            mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", substrate_file),
            mock.patch.object(_uniforms.time, "time", return_value=1776041528.0),
        ):
            _uniforms.write_uniforms(
                {"salience": 0.5, "material": "fire", "timestamp": 1776041528.0},
                None,
                _FakeVisualChain(),
                trace_strength=0.0,
                trace_center=(0.5, 0.5),
                trace_radius=0.0,
            )
        result = json.loads(uniforms_file.read_text())
        assert result["color.saturation"] == pytest.approx(0.40)  # BitchX wins

    def test_provider_with_target_overrides_bitchx_saturation(self, tmp_path: Path) -> None:
        """Programme target 0.30 overrides BitchX 0.40, preserves hue+brightness."""
        plan_file = _write_plan(tmp_path)
        uniforms_file = tmp_path / "uniforms.json"
        substrate_file = _write_substrate_package(
            tmp_path, {"package": "bitchx", "palette_accent_hue_deg": 180.0}
        )
        prog = _programme(saturation_target=0.30)

        with (
            mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
            mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
            mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", substrate_file),
            mock.patch.object(_uniforms.time, "time", return_value=1776041528.0),
        ):
            _uniforms.write_uniforms(
                {"salience": 0.5, "material": "fire", "timestamp": 1776041528.0},
                None,
                _FakeVisualChain(),
                trace_strength=0.0,
                trace_center=(0.5, 0.5),
                trace_radius=0.0,
                programme_provider=lambda: prog,
            )
        result = json.loads(uniforms_file.read_text())
        # Programme governs saturation
        assert result["color.saturation"] == pytest.approx(0.30)
        # BitchX still governs hue + brightness (package-scoped, not programme)
        assert result["color.hue_rotate"] == pytest.approx(180.0)
        assert result["color.brightness"] == pytest.approx(0.85)

    def test_provider_returning_none_falls_through(self, tmp_path: Path) -> None:
        """Programme provider returning None defers to package damping."""
        plan_file = _write_plan(tmp_path)
        uniforms_file = tmp_path / "uniforms.json"
        substrate_file = _write_substrate_package(
            tmp_path, {"package": "bitchx", "palette_accent_hue_deg": 180.0}
        )
        with (
            mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
            mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
            mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", substrate_file),
            mock.patch.object(_uniforms.time, "time", return_value=1776041528.0),
        ):
            _uniforms.write_uniforms(
                {"salience": 0.5, "material": "fire", "timestamp": 1776041528.0},
                None,
                _FakeVisualChain(),
                trace_strength=0.0,
                trace_center=(0.5, 0.5),
                trace_radius=0.0,
                programme_provider=lambda: None,
            )
        result = json.loads(uniforms_file.read_text())
        assert result["color.saturation"] == pytest.approx(0.40)  # BitchX wins

    def test_programme_target_with_no_package_overrides_plan_default(self, tmp_path: Path) -> None:
        """No homage package — programme target still wins over plan default 1.0."""
        plan_file = _write_plan(tmp_path)
        uniforms_file = tmp_path / "uniforms.json"
        missing_substrate = tmp_path / "missing-package.json"
        prog = _programme(saturation_target=0.55)

        with (
            mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
            mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
            mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", missing_substrate),
            # U8 mode tint is orthogonal to programme saturation ownership;
            # isolate it so this pin keeps asserting programme-vs-plan scope.
            mock.patch.object(_uniforms, "_apply_mode_palette_tint", lambda u, **kw: None),
            mock.patch.object(_uniforms.time, "time", return_value=1776041528.0),
        ):
            _uniforms.write_uniforms(
                {"salience": 0.5, "material": "water", "timestamp": 1776041528.0},
                None,
                _FakeVisualChain(),
                trace_strength=0.0,
                trace_center=(0.5, 0.5),
                trace_radius=0.0,
                programme_provider=lambda: prog,
            )
        result = json.loads(uniforms_file.read_text())
        assert result["color.saturation"] == pytest.approx(0.55)
        # Hue still at plan default (no package, no programme override)
        assert result["color.hue_rotate"] == pytest.approx(0.0)

    def test_transition_energy_threaded_into_compose(self, tmp_path: Path) -> None:
        """transition_energy kwarg flows into compose; lifts saturation."""
        plan_file = _write_plan(tmp_path)
        uniforms_file = tmp_path / "uniforms.json"
        missing_substrate = tmp_path / "missing-package.json"
        prog = _programme(saturation_target=0.30)

        with (
            mock.patch.object(_uniforms, "PLAN_FILE", plan_file),
            mock.patch.object(_uniforms, "UNIFORMS_FILE", uniforms_file),
            mock.patch.object(_uniforms, "HOMAGE_SUBSTRATE_PACKAGE_FILE", missing_substrate),
            mock.patch.object(_uniforms.time, "time", return_value=1776041528.0),
        ):
            _uniforms.write_uniforms(
                {"salience": 0.5, "material": "water", "timestamp": 1776041528.0},
                None,
                _FakeVisualChain(),
                trace_strength=0.0,
                trace_center=(0.5, 0.5),
                trace_radius=0.0,
                programme_provider=lambda: prog,
                transition_energy=1.0,
            )
        result = json.loads(uniforms_file.read_text())
        # 0.30 + 0.10 = 0.40
        assert result["color.saturation"] == pytest.approx(0.40)


class TestPerRoleDefaults:
    """Per-role saturation hints from plan §lines 851-857.

    These targets are LLM planner suggestions, not hardcoded constants —
    the Programme carries the chosen value. These tests pin the
    semantics of compose_target across role-typical centres so the
    planner has predictable behaviour to design against.
    """

    @pytest.mark.parametrize(
        "role,centre",
        [
            (ProgrammeRole.LISTENING, 0.30),
            (ProgrammeRole.HOTHOUSE_PRESSURE, 0.70),
            (ProgrammeRole.WIND_DOWN, 0.25),
            (ProgrammeRole.WORK_BLOCK, 0.50),
        ],
    )
    def test_role_centre_lands_at_value(self, role: ProgrammeRole, centre: float) -> None:
        prog = _programme(role=role, saturation_target=centre)
        assert compute_substrate_saturation(prog) == pytest.approx(centre)

    def test_hothouse_above_listening_at_same_modulation(self) -> None:
        """Bright role still reads brighter than quiet role under same stimmung."""
        loud = _programme(role=ProgrammeRole.HOTHOUSE_PRESSURE, saturation_target=0.70)
        quiet = _programme(role=ProgrammeRole.LISTENING, saturation_target=0.30)
        stim = {"overall_stance": "cautious"}
        assert compute_substrate_saturation(loud, stim) > compute_substrate_saturation(quiet, stim)
