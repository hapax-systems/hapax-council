"""HOMAGE Phase 6 — ward↔shader bidirectional coupling tests.

Spec: ``docs/superpowers/specs/2026-04-18-homage-framework-design.md`` §4.6.
Task: #112. Closes the reverse-path loop — the HOMAGE choreographer
reads a small shader-feedback payload and modulates ward hold pacing
accordingly.

The Reverie-side publisher is out of scope for this commit; these
tests exercise the consumer (choreographer + `shared.homage_coupling`
parsing) against hand-written payloads.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.studio_compositor.homage.choreographer import Choreographer
from shared.homage_coupling import (
    HIGH_DRIFT_THRESHOLD,
    HIGH_ENERGY_THRESHOLD,
    HOLD_EXTEND_MULTIPLIER,
    HOLD_SHORTEN_MULTIPLIER,
    ShaderCouplingReading,
    hold_multiplier,
    parse_shader_reading,
    read_shader_reading,
)


def _write_reading(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def choreographer(tmp_path: Path) -> Choreographer:
    return Choreographer(
        pending_file=tmp_path / "homage-pending.json",
        uniforms_file=tmp_path / "uniforms.json",
        shader_reading_file=tmp_path / "homage-shader-reading.json",
    )


class TestPayloadParseRoundTrip:
    def test_valid_payload_round_trips(self) -> None:
        original = ShaderCouplingReading(
            timestamp=123.5,
            shader_energy=0.6,
            shader_drift=0.4,
            substrate_fresh=True,
        )
        parsed = parse_shader_reading(original.to_dict())
        assert parsed == original

    def test_clamps_out_of_range_scalars(self) -> None:
        parsed = parse_shader_reading(
            {
                "timestamp": 0.0,
                "shader_energy": 1.7,
                "shader_drift": -0.5,
                "substrate_fresh": True,
            }
        )
        assert parsed is not None
        assert parsed.shader_energy == 1.0
        assert parsed.shader_drift == 0.0

    def test_missing_fields_returns_none(self) -> None:
        assert parse_shader_reading({"timestamp": 0.0, "shader_energy": 0.5}) is None

    def test_non_bool_substrate_fresh_returns_none(self) -> None:
        assert (
            parse_shader_reading(
                {
                    "timestamp": 0.0,
                    "shader_energy": 0.5,
                    "shader_drift": 0.5,
                    "substrate_fresh": "yes",
                }
            )
            is None
        )

    def test_non_dict_returns_none(self) -> None:
        assert parse_shader_reading(["not", "a", "dict"]) is None

    def test_read_shader_reading_missing_file(self, tmp_path: Path) -> None:
        assert read_shader_reading(tmp_path / "does-not-exist.json") is None

    def test_read_shader_reading_malformed_file(self, tmp_path: Path) -> None:
        p = tmp_path / "homage-shader-reading.json"
        p.write_text("not json", encoding="utf-8")
        assert read_shader_reading(p) is None


class TestHoldMultiplier:
    def test_none_reading_defaults_to_one(self) -> None:
        assert hold_multiplier(None, now=0.0) == 1.0

    def test_high_energy_extends_hold(self) -> None:
        reading = ShaderCouplingReading(
            timestamp=10.0,
            shader_energy=HIGH_ENERGY_THRESHOLD + 0.05,
            shader_drift=0.1,
            substrate_fresh=True,
        )
        assert hold_multiplier(reading, now=10.5) == HOLD_EXTEND_MULTIPLIER

    def test_high_drift_shortens_hold(self) -> None:
        reading = ShaderCouplingReading(
            timestamp=10.0,
            shader_energy=0.1,
            shader_drift=HIGH_DRIFT_THRESHOLD + 0.05,
            substrate_fresh=True,
        )
        assert hold_multiplier(reading, now=10.5) == HOLD_SHORTEN_MULTIPLIER

    def test_drift_beats_energy_when_both_high(self) -> None:
        reading = ShaderCouplingReading(
            timestamp=10.0,
            shader_energy=0.9,
            shader_drift=0.9,
            substrate_fresh=True,
        )
        # Drift takes precedence — break feedback lock-in first.
        assert hold_multiplier(reading, now=10.5) == HOLD_SHORTEN_MULTIPLIER

    def test_substrate_not_fresh_flag_defaults_to_one(self) -> None:
        reading = ShaderCouplingReading(
            timestamp=10.0,
            shader_energy=0.9,
            shader_drift=0.9,
            substrate_fresh=False,
        )
        assert hold_multiplier(reading, now=10.5) == 1.0

    def test_stale_reading_defaults_to_one(self) -> None:
        reading = ShaderCouplingReading(
            timestamp=10.0,
            shader_energy=0.9,
            shader_drift=0.9,
            substrate_fresh=True,
        )
        # >2 s old — substrate window has closed regardless of flag.
        assert hold_multiplier(reading, now=15.0) == 1.0


class TestChoreographerReadShaderCoupling:
    def test_missing_file_returns_none(self, choreographer: Choreographer) -> None:
        assert choreographer.read_shader_coupling() is None

    def test_valid_payload_parses(self, choreographer: Choreographer, tmp_path: Path) -> None:
        _write_reading(
            tmp_path / "homage-shader-reading.json",
            {
                "timestamp": 100.0,
                "shader_energy": 0.5,
                "shader_drift": 0.25,
                "substrate_fresh": True,
            },
        )
        reading = choreographer.read_shader_coupling()
        assert reading is not None
        assert reading.shader_energy == 0.5
        assert reading.shader_drift == 0.25
        assert reading.substrate_fresh is True


class TestChoreographerPacing:
    def test_missing_file_yields_neutral_pacing(self, choreographer: Choreographer) -> None:
        assert choreographer.hold_pacing_multiplier(now=0.0) == 1.0

    def test_high_energy_extends_pacing(self, choreographer: Choreographer, tmp_path: Path) -> None:
        _write_reading(
            tmp_path / "homage-shader-reading.json",
            {
                "timestamp": 100.0,
                "shader_energy": 0.9,
                "shader_drift": 0.1,
                "substrate_fresh": True,
            },
        )
        assert choreographer.hold_pacing_multiplier(now=100.5) == HOLD_EXTEND_MULTIPLIER

    def test_high_drift_shortens_pacing(self, choreographer: Choreographer, tmp_path: Path) -> None:
        _write_reading(
            tmp_path / "homage-shader-reading.json",
            {
                "timestamp": 100.0,
                "shader_energy": 0.1,
                "shader_drift": 0.95,
                "substrate_fresh": True,
            },
        )
        assert choreographer.hold_pacing_multiplier(now=100.5) == HOLD_SHORTEN_MULTIPLIER

    def test_stale_reading_yields_neutral_pacing(
        self, choreographer: Choreographer, tmp_path: Path
    ) -> None:
        _write_reading(
            tmp_path / "homage-shader-reading.json",
            {
                "timestamp": 100.0,
                "shader_energy": 0.9,
                "shader_drift": 0.95,
                "substrate_fresh": True,
            },
        )
        # >2 s old — stale, fall back to timer pacing.
        assert choreographer.hold_pacing_multiplier(now=105.0) == 1.0

    def test_malformed_reading_yields_neutral_pacing(
        self, choreographer: Choreographer, tmp_path: Path
    ) -> None:
        (tmp_path / "homage-shader-reading.json").write_text("garbage", encoding="utf-8")
        assert choreographer.hold_pacing_multiplier(now=0.0) == 1.0
